import json
import uuid
import asyncio
import time
import logging
import random
import re
from decimal import Decimal
from typing import Optional
from collections.abc import Iterable

import httpx
import sqlparse
from openai import AsyncOpenAI
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from sqlmodel import text
from sqlalchemy.ext.asyncio import create_async_engine
from uuid import UUID

from app.core.config import settings
from app.core.llm_circuit_breaker import CircuitOpenError, get_breaker, is_transient_llm_error
from app.llm_trigger.chains import get_model_for_stage

from app.api.deps import CurrentUser, SessionDep
from app.core.database import engine
from app.models.enums import QueryMode, UserRole
from app.schemas.assistant import AssistantQueryRequest, AssistantQueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


assistant_sql_engine = create_async_engine(
    settings.ASSISTANT_DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={
        "prepared_statement_cache_size": 0,
        "statement_cache_size": 0,
    },
)

async def _with_retry_async(
    call,
    *,
    max_retries: int,
    base_delay: float,
    retry_label: str,
) -> Optional[str]:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await call()
        except Exception as exc:
            last_exc = exc
            if not is_transient_llm_error(exc) or attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.3)
            logger.warning(
                "%s attempt %d/%d failed (transient), retrying in %.1fs: %s",
                retry_label,
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


_SQL_LIMIT_CAP = 200
_ASSISTANT_TABLE_COLUMNS: dict[str, set[str]] = {
    "users": {"id", "organization_id", "name", "email", "role", "agent_type", "is_active"},
    "organizations": {"id", "name"},
    "interactions": {
        "id",
        "organization_id",
        "agent_id",
        "duration_seconds",
        "interaction_date",
        "processing_status",
        "language_detected",
        "has_overlap",
    },
    "interaction_scores": {
        "id",
        "interaction_id",
        "overall_score",
        "empathy_score",
        "policy_score",
        "resolution_score",
        "was_resolved",
        "total_silence_seconds",
        "avg_response_time_seconds",
    },
    "policy_compliance": {
        "id",
        "interaction_id",
        "policy_id",
        "is_compliant",
        "compliance_score",
        "llm_reasoning",
    },
    "company_policies": {"id", "organization_id", "policy_category", "policy_title", "policy_text", "is_active"},
    "utterances": {"id", "interaction_id", "speaker_role", "emotion", "start_time_seconds", "end_time_seconds"},
}
_ASSISTANT_ALLOWED_TABLES = set(_ASSISTANT_TABLE_COLUMNS)
_ASSISTANT_ALLOWED_COLUMNS_UNQUALIFIED = {
    col for cols in _ASSISTANT_TABLE_COLUMNS.values() for col in cols
}
_SQL_KEYWORDS = {
    "and", "or", "not", "as", "on", "in", "is", "null", "true", "false", "case", "when", "then", "else", "end",
    "distinct", "order", "by", "group", "having", "desc", "asc", "where", "from", "join", "left", "right", "inner",
    "outer", "cross", "full", "union", "all", "limit", "offset", "with", "select", "like", "ilike", "between", "exists",
    "count", "sum", "avg", "min", "max", "round", "date_trunc", "now", "current_date", "current_timestamp", "interval",
    "cast", "coalesce", "json_build_object", "jsonb_build_object", "row_number", "over", "partition",
    "numeric", "text", "varchar", "integer", "int", "float", "boolean", "timestamp", "date", "extract", "month", "year", "day"
}


# ---------------------------------------------------------------------------
# Help response
# ---------------------------------------------------------------------------
_HELP_RESPONSE = """Here is what you can ask me about your call center:\n\n**Agents & Performance**\n- "Who are the top 5 agents by overall score?"\n- "Which agent has the lowest resolution rate?"\n- "Show agents ranked by empathy score"\n\n**Interactions & Calls**\n- "How many calls were not resolved?"\n- "Show interactions in the last 30 days"\n- "Which calls had the highest empathy score?"\n\n**Policy Violations**\n- "List all policy violations"\n- "Which agents violated the Escalation Protocol?"\n\n**Customer Emotions**\n- "What are the most common customer emotions?"\n- "Show calls where the customer was frustrated"\n\n**Available score columns:**\noverall_score, empathy_score, policy_score, resolution_score (all 0-10 scale)\n\nTip: you can add time filters like "last 30 days", "last 3 months", or "all time"."""

_HELP_TRIGGERS = {"help", "?", "what can i ask", "what can you do", "commands", "guide"}

# ---------------------------------------------------------------------------
# SQL extraction (model output can include fences, chatter, or multiple blocks)
# ---------------------------------------------------------------------------
def _strip_model_artifacts(text: str) -> str:
    t = text.strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<thinking>.*?</thinking>", "", t, flags=re.DOTALL | re.IGNORECASE)
    return t.strip()


def _extract_fenced_block(text: str) -> Optional[str]:
    """If text contains a ``` fenced block, return its inner content (first match)."""
    start = text.find("```")
    if start == -1:
        return None
    i = start + 3
    nl = text.find("\n", i)
    if nl != -1:
        lang_or_sql = text[i:nl].strip()
        # Language tag (sql, postgres, …) or empty line after opening fence
        if not lang_or_sql or (
            lang_or_sql.isalpha() and not lang_or_sql.lower().startswith("select")
        ):
            i = nl + 1
    end = text.find("```", i)
    if end == -1:
        return None
    return text[i:end].strip()


def _parse_sql_from_model_output(raw: Optional[str]) -> Optional[str]:
    """Return a single SELECT statement from LLM output, or None."""
    if not raw:
        return None
    text = _strip_model_artifacts(raw)

    fenced = _extract_fenced_block(text)
    if fenced:
        text = fenced

    tail = text.strip()
    # Prefer a top-level WITH ... SELECT so we do not clip the CTE at an inner SELECT.
    m_with = re.search(r"\b(with\s+[\s\S]+)$", tail, re.IGNORECASE | re.DOTALL)
    if m_with:
        sql = m_with.group(1).strip().rstrip(";").strip()
        if sql:
            return sql

    m = re.search(r"\b(select[\s\S]+)$", tail, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    sql = m.group(1).strip()
    pieces = [s for s in sqlparse.split(sql) if s.strip()]
    if len(pieces) == 1:
        sql = pieces[0].strip().rstrip(";").strip()
    return sql or None


def _iter_select_clauses(sql: str) -> Iterable[str]:
    for match in re.finditer(r"\bselect\b([\s\S]*?)\bfrom\b", sql, re.IGNORECASE):
        yield (match.group(1) or "").strip()


def _extract_cte_names(sql: str) -> set[str]:
    cte_names: set[str] = set()
    for match in re.finditer(r"\bwith\s+([a-z_][a-z0-9_]*)\s+as\s*\(", sql, re.IGNORECASE):
        cte_names.add(match.group(1).lower())
    for match in re.finditer(r",\s*([a-z_][a-z0-9_]*)\s+as\s*\(", sql, re.IGNORECASE):
        cte_names.add(match.group(1).lower())
    return cte_names


def _extract_table_aliases(sql: str) -> dict[str, str]:
    sql = _neutralize_func_from(sql)
    aliases: dict[str, str] = {}
    pattern = re.compile(
        r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)(?:\s+(?:as\s+)?([a-z_][a-z0-9_]*))?",
        re.IGNORECASE,
    )
    cte_names = _extract_cte_names(sql)
    for table, alias in pattern.findall(sql):
        table_l = table.lower()
        if table_l in cte_names:
            continue
        if table_l in _ASSISTANT_ALLOWED_TABLES:
            aliases[table_l] = table_l
            if alias:
                aliases[alias.lower()] = table_l
    return aliases


# Functions that use the `EXPR FROM source` SQL syntax. Their inner `FROM` must
# not be mistaken for a table source by the table/alias extractors below.
_FUNC_FROM_PATTERN = re.compile(
    r"(\b(?:extract|substring|trim|overlay)\s*\([^()]*?)\bfrom\b",
    re.IGNORECASE,
)


def _neutralize_func_from(sql: str) -> str:
    """Replace the `FROM` keyword inside EXTRACT/SUBSTRING/TRIM/OVERLAY calls.

    `EXTRACT(MONTH FROM i.interaction_date)` would otherwise make the table
    extractor read `i` as a real table and reject the query.
    """
    prev = None
    out = sql
    # Re-apply until stable so multiple such calls in one statement are handled.
    while prev != out:
        prev = out
        out = _FUNC_FROM_PATTERN.sub(r"\1,", out)
    return out


def _extract_referenced_tables(sql: str) -> set[str]:
    sql = _neutralize_func_from(sql)
    cte_names = _extract_cte_names(sql)
    refs: set[str] = set()
    for table in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", sql, flags=re.IGNORECASE):
        t = table.lower()
        if t not in cte_names:
            refs.add(t)
    return refs


def _validate_column_reference(token: str, aliases: dict[str, str]) -> None:
    token_l = token.lower()
    if "." in token_l:
        alias, col = token_l.split(".", 1)
        table = aliases.get(alias)
        if table is None:
            raise ValueError(f"SQL references unknown table alias '{alias}'.")
        if col not in _ASSISTANT_TABLE_COLUMNS[table]:
            raise ValueError(f"Column '{col}' is not allowed on table '{table}'.")
        return
    if token_l in _ASSISTANT_ALLOWED_COLUMNS_UNQUALIFIED:
        return
    if token_l in _SQL_KEYWORDS:
        return
    if token_l.isdigit():
        return
    raise ValueError(f"Column '{token}' is not in the assistant allowlist.")


def _validate_sql_structure(sql: str) -> None:
    sql_clean = (sql or "").strip().rstrip(";")
    if not sql_clean:
        raise ValueError("Generated SQL is empty.")
    if ";" in sql_clean:
        raise ValueError("Assistant SQL must be exactly one statement.")

    split_statements = [s.strip() for s in sqlparse.split(sql_clean) if s.strip()]
    if len(split_statements) != 1:
        raise ValueError("Assistant SQL must be exactly one statement.")

    parsed = sqlparse.parse(sql_clean)
    if len(parsed) != 1:
        raise ValueError("Assistant SQL must parse as a single statement.")

    statement = parsed[0]
    stype = (statement.get_type() or "").upper()
    lead = sql_clean.lstrip().lower()
    if stype != "SELECT" and not lead.startswith("with "):
        raise ValueError("Only SELECT or WITH...SELECT statements are allowed.")

    tables = _extract_referenced_tables(sql_clean)
    disallowed_tables = sorted(t for t in tables if t not in _ASSISTANT_ALLOWED_TABLES)
    if disallowed_tables:
        raise ValueError(f"SQL references disallowed tables: {', '.join(disallowed_tables)}.")

    aliases = _extract_table_aliases(sql_clean)
    
    # Extract AS aliases to allow them as columns (e.g. AS avg_score)
    defined_aliases = set()
    for match in re.finditer(r"\bas\s+([a-z_][a-z0-9_]*)\b", sql_clean, flags=re.IGNORECASE):
        defined_aliases.add(match.group(1).lower())
        
    # Strip string literals so we don't validate inside them
    sql_no_strings = re.sub(r"'[^']*'", "''", sql_clean)
    
    # Strip comments
    sql_no_strings = re.sub(r"/\*.*?\*/", " ", sql_no_strings, flags=re.DOTALL)
    sql_no_strings = re.sub(r"--.*?\n", " ", sql_no_strings)

    # COUNT(*) is the most common aggregate. Collapse it to COUNT(1) so the
    # wildcard-projection guard below does not see the `*`, and so the inner
    # token is a bare digit (ignored) rather than a fake column.
    normalized = re.sub(r"\bcount\s*\(\s*\*\s*\)", "count(1)", sql_no_strings, flags=re.IGNORECASE)
    # `table.*` is never legitimate here (COUNT(*) was already collapsed above),
    # so reject any qualified-wildcard regardless of what follows it. The earlier
    # anchored form let `SELECT i.* FROM ...` slip through and exfiltrate columns.
    if re.search(r"[a-z_][a-z0-9_]*\s*\.\s*\*", normalized, re.IGNORECASE):
        raise ValueError("Wildcard projection (table.*) is not allowed.")
    if re.search(r"(^|select|,)\s*\*\s*(,|$|from)", normalized, re.IGNORECASE):
        raise ValueError("Wildcard projection (SELECT *) is not allowed.")

    for alias_ref, col_ref in re.findall(
        r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        _validate_column_reference(f"{alias_ref}.{col_ref}", aliases)

    # Any identifier immediately followed by '(' is a function call, not a
    # column. Function names never leak sensitive columns (the read-only DB
    # role is the real execution guard), so allow them generically instead of
    # maintaining a brittle allowlist of every Postgres function.
    called_functions = {
        m.lower()
        for m in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", normalized, flags=re.IGNORECASE)
    }

    bare_words = re.findall(r"\b([a-z_][a-z0-9_]*)\b", normalized, flags=re.IGNORECASE)
    for word in bare_words:
        w_lower = word.lower()
        if w_lower in aliases:
            continue
        if w_lower in defined_aliases:
            continue
        if w_lower in called_functions:
            continue
        if re.search(rf"\b[a-z_][a-z0-9_]*\.{word}\b", normalized, flags=re.IGNORECASE):
            continue
        _validate_column_reference(word, aliases)

    limit_matches = list(re.finditer(r"\blimit\s+(\d+)\b", sql_clean, re.IGNORECASE))
    if not limit_matches:
        raise ValueError(f"SQL must include an explicit LIMIT <= {_SQL_LIMIT_CAP}.")
    limit_value = int(limit_matches[-1].group(1))
    if limit_value > _SQL_LIMIT_CAP:
        raise ValueError(f"LIMIT {limit_value} exceeds maximum allowed {_SQL_LIMIT_CAP}.")


def _is_org_scoped_sql(sql: str, org_id: UUID) -> bool:
    """
    Verify generated SQL explicitly scopes to the caller organization.
    """
    s = sql or ""
    # Strip multi-line and single-line comments
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"--.*?\n", " ", s)

    normalized = re.sub(r"\s+", " ", s.lower()).strip()
    org_str = str(org_id).lower()
    if not normalized:
        return False

    # Require an explicit binding of `organization_id` to the CALLER's own org id,
    # e.g. `organization_id = '<caller-org>'` (any alias prefix). Checking only that
    # both tokens appear somewhere let the org id hide in an unrelated string literal
    # while `organization_id` was actually filtered to a different tenant.
    binding = re.compile(
        r"organization_id\s*=\s*'" + re.escape(org_str) + r"'",
        re.IGNORECASE,
    )
    return bool(binding.search(normalized))


def _ordinal_followup_offset(question: str) -> Optional[int]:
    """Return 0-based offset for follow-ups like 'second one', else None."""
    q = (question or "").strip().lower()
    if not q:
        return None
    mapping = {
        "first": 0,
        "1st": 0,
        "second": 1,
        "2nd": 1,
        "third": 2,
        "3rd": 2,
        "fourth": 3,
        "4th": 3,
        "fifth": 4,
        "5th": 4,
    }
    for token, offset in mapping.items():
        if token in q:
            return offset
    return None


def _strip_trailing_limit_offset(sql: str) -> str:
    """Best-effort remove trailing LIMIT/OFFSET from SQL text."""
    s = (sql or "").strip().rstrip(";")
    s = re.sub(r"\s+offset\s+\d+\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+limit\s+\d+\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _build_ordinal_followup_sql(previous_sql: str, offset: int) -> Optional[str]:
    base = _strip_trailing_limit_offset(previous_sql)
    if not base:
        return None
    return f"WITH prev AS ({base}) SELECT id FROM prev LIMIT 1 OFFSET {max(0, offset)}"


def _ordinal_word(offset: int) -> str:
    words = ["first", "second", "third", "fourth", "fifth"]
    if 0 <= offset < len(words):
        return words[offset]
    return f"#{offset + 1}"


def _deterministic_ordinal_answer(offset: int, rows: list[dict]) -> str:
    ow = _ordinal_word(offset)
    if not rows:
        return f"I couldn't find a {ow} ranked result for that request."

    row = rows[0]
    name = row.get("name") or row.get("agent_name") or row.get("agent") or row.get("user_name")
    score = row.get("avg_score") or row.get("score") or row.get("overall_score")
    if name is not None and score is not None:
        return f"The {ow} ranked agent is {name} with a score of {score}."
    if name is not None:
        return f"The {ow} ranked result is {name}."
    return f"I found the {ow} ranked result: {row}."


def _is_rank_query(question: str) -> bool:
    q = (question or "").lower()
    return any(token in q for token in ("top", "highest", "best", "lowest", "worst"))


def _deterministic_rank_answer(rows: list[dict]) -> str:
    if not rows:
        return "I couldn't find ranked results for that request."
    row = rows[0]
    name = row.get("name") or row.get("agent_name") or row.get("agent") or row.get("user_name")
    score = row.get("avg_score") or row.get("score") or row.get("overall_score")
    if name is not None and score is not None:
        return f"The top result is {name} with a score of {score}."
    if name is not None:
        return f"The top result is {name}."
    return f"The top result is: {row}."


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
_SCHEMA = """
Tables and columns:
- users: id(UUID), organization_id(UUID), name, email, role('manager'/'agent'), agent_type('human'/'ai'), is_active(BOOL)
- organizations: id(UUID), name
- interactions: id(UUID), organization_id(UUID), agent_id(UUID->users.id), duration_seconds, interaction_date(TIMESTAMP), processing_status('completed'/'pending'/'failed'), language_detected, has_overlap(BOOL)
- interaction_scores: id(UUID), interaction_id(UUID->interactions.id), overall_score(FLOAT 0-1), empathy_score(FLOAT 0-1), policy_score(FLOAT 0-1), resolution_score(FLOAT 0-1), was_resolved(BOOL), total_silence_seconds(FLOAT), avg_response_time_seconds(FLOAT)
- policy_compliance: id(UUID), interaction_id(UUID), policy_id(UUID->company_policies.id), is_compliant(BOOL), compliance_score(FLOAT 0-1), llm_reasoning(TEXT)
- company_policies: id(UUID), organization_id(UUID), policy_category, policy_title, policy_text, is_active(BOOL)
- utterances: id(UUID), interaction_id(UUID), speaker_role('agent'/'customer'), emotion('neutral'/'happy'/'frustrated'/'angry'/'sad'/'empathetic'/'fearful'), start_time_seconds(FLOAT), end_time_seconds(FLOAT)
"""


def _build_sql_prompt(org_id: UUID, question: str, conversation_block: str = "") -> str:
    org = str(org_id)
    conv = ""
    if conversation_block.strip():
        conv = f"""Prior conversation (oldest first; use only to resolve follow-ups like "same period", "those agents", "what about last week?"):
{conversation_block.strip()}

"""
    return f"""You are a PostgreSQL expert for a call-center analytics platform.
Convert the manager's question into a single valid PostgreSQL SELECT query.

Schema:
{_SCHEMA}

{conv}Rules:
1. Always restrict to the organization: use organization_id = '{org}' on `users` OR `interactions` tables.
2. Return ONLY raw SQL - no markdown, no explanation.
3. Read-only: a single SELECT or WITH ... SELECT — never DELETE/UPDATE/DROP/INSERT/ALTER/CREATE/TRUNCATE.
4. Add LIMIT 50 unless the user asks for more or uses aggregates (COUNT/SUM/AVG).
5. Float casting: PostgreSQL ROUND() requires NUMERIC type. Always write ROUND(expr::NUMERIC, 1).
6. Scores in db are 0.0-1.0. To show as 0-10: multiply by 10. To show as percent: multiply by 100.
7. For ambiguous "top/best" keywords, use `overall_score` as the primary metric.
8. Time shortcuts: "this week" -> interaction_date >= date_trunc('week', now()), "last 30 days" -> interaction_date >= NOW() - INTERVAL '30 days'. If no time is specified, query all data.
9. Match names using ILIKE. Cast UUID output with ::text.
10. Join interaction_scores on: interaction_scores.interaction_id = interactions.id
11. Output format: respond with ONLY the SQL statement — no markdown, no labels, no commentary before or after.
12. For ranked lists (top/best/highest/lowest), add deterministic tie-breaking with a stable secondary key (e.g., ORDER BY metric DESC, name ASC).

Examples:
Q: Who are the top 5 agents by overall score?
A: SELECT u.name, ROUND(AVG(s.overall_score)::NUMERIC * 10, 1) AS avg_score FROM users u JOIN interactions i ON i.agent_id = u.id AND i.organization_id = '{org}' JOIN interaction_scores s ON s.interaction_id = i.id WHERE u.role = 'agent' GROUP BY u.id, u.name ORDER BY avg_score DESC LIMIT 5

Q: Show top performing agents
A: SELECT u.name, ROUND(AVG(s.overall_score)::NUMERIC * 10, 1) AS avg_score, ROUND(AVG(s.empathy_score)::NUMERIC * 10, 1) AS empathy FROM users u JOIN interactions i ON i.agent_id = u.id AND i.organization_id = '{org}' JOIN interaction_scores s ON s.interaction_id = i.id WHERE u.role = 'agent' GROUP BY u.id, u.name ORDER BY avg_score DESC LIMIT 10

Q: Which agent has the highest empathy score?
A: SELECT u.name, ROUND(AVG(s.empathy_score)::NUMERIC * 10, 1) AS avg_empathy FROM users u JOIN interactions i ON i.agent_id = u.id AND i.organization_id = '{org}' JOIN interaction_scores s ON s.interaction_id = i.id WHERE u.role = 'agent' GROUP BY u.id, u.name ORDER BY avg_empathy DESC LIMIT 1

Q: Show top performing agents this week
A: SELECT u.name, ROUND(AVG(s.overall_score)::NUMERIC * 10, 1) AS avg_score FROM users u JOIN interactions i ON i.agent_id = u.id AND i.organization_id = '{org}' JOIN interaction_scores s ON s.interaction_id = i.id WHERE u.role = 'agent' AND i.interaction_date >= date_trunc('week', now()) GROUP BY u.id, u.name ORDER BY avg_score DESC LIMIT 10

Q: agent with lowest resolution rate
A: SELECT u.name, ROUND(AVG(s.resolution_score)::NUMERIC * 100, 1) AS resolution_pct FROM users u JOIN interactions i ON i.agent_id = u.id AND i.organization_id = '{org}' JOIN interaction_scores s ON s.interaction_id = i.id WHERE u.role = 'agent' GROUP BY u.id, u.name ORDER BY resolution_pct ASC LIMIT 1

Q: list policy violations
A: SELECT i.id::text AS interaction_id, cp.policy_title, ROUND(pc.compliance_score::NUMERIC * 10, 1) AS compliance_score, pc.llm_reasoning FROM policy_compliance pc JOIN company_policies cp ON pc.policy_id = cp.id JOIN interactions i ON pc.interaction_id = i.id WHERE pc.is_compliant = false AND i.organization_id = '{org}' LIMIT 50

Q: most common customer emotions
A: SELECT emotion, COUNT(*) AS count FROM utterances u JOIN interactions i ON u.interaction_id = i.id WHERE u.speaker_role = 'customer' AND i.organization_id = '{org}' GROUP BY emotion ORDER BY count DESC LIMIT 10

Question: {question}
SQL:"""


def _build_synthesis_prompt(question: str, sql: str, rows: list) -> str:
    return f"""You are a concise data analyst for a call-center manager.
The manager asked: "{question}"

The following SQL was executed and returned {len(rows)} rows (showing up to 20):
{rows[:20]}

Write 2-4 sentences of plain text answering the question using the actual data.
- Mention specific names and numbers from the results.
- Scores in the data are already scaled: if a value looks like 8.5 it is out of 10; if it looks like 85 it is a percentage.
- If a raw 0-1 float appears (like 0.8), present it as 80%.
- If results are empty, say no data was found for that time period and suggest trying "last 30 days" or "all time".
- No markdown, no bullet points, no SQL repetition."""


def _build_sql_repair_prompt(org_id: UUID, question: str, bad_output: str) -> str:
    org = str(org_id)
    return f"""Your previous attempt did not produce executable SQL.
You MUST return exactly one valid PostgreSQL SELECT statement for this schema and organization.

organization_id must be constrained to '{org}' on users or interactions.
Return only SQL. No markdown, no prose, no code fences.

Question: {question}
Previous invalid output:
{bad_output[:1000]}

SQL:"""


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


async def _ollama_chat_complete(prompt: str, temperature: float) -> Optional[str]:
    """Non-streaming chat completion against a local Ollama server."""
    configured_base = (settings.OLLAMA_BASE_URL or "").rstrip("/")
    bases = [b for b in [configured_base, "http://host.docker.internal:11434"] if b]
    # remove duplicates while preserving order
    uniq_bases = list(dict.fromkeys(bases))
    model = (settings.ASSISTANT_OLLAMA_MODEL or "qwen2.5:7b").strip()
    models_to_try = [model, "qwen2.5:7b"]
    uniq_models = list(dict.fromkeys([m for m in models_to_try if m]))

    timeout = httpx.Timeout(settings.ASSISTANT_OLLAMA_TIMEOUT_SECONDS)
    for base in uniq_bases:
        url = f"{base}/api/chat"
        async with httpx.AsyncClient(timeout=timeout) as client:
            for model_name in uniq_models:
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                breaker = get_breaker("ollama_local")
                try:
                    async def _request_once() -> Optional[str]:
                        r = await client.post(url, json=payload)
                        r.raise_for_status()
                        data = r.json()
                        msg = data.get("message") or {}
                        content = (msg.get("content") or "").strip()
                        return content or None

                    async def _breaker_wrapped_once() -> Optional[str]:
                        return await breaker.call(_request_once)

                    content = await _with_retry_async(
                        _breaker_wrapped_once,
                        max_retries=2,
                        base_delay=0.5,
                        retry_label=f"Ollama local ({base}/{model_name})",
                    )
                    if content:
                        return content
                except CircuitOpenError:
                    logger.warning(
                        "Ollama local circuit open; skipping provider attempt (base=%s model=%s)",
                        base,
                        model_name,
                    )
                    continue
                except Exception as exc:
                    logger.warning("Ollama assistant request failed (base=%s model=%s): %s", base, model_name, exc)
                    continue
    logger.error(
        "Assistant provider exhaustion: all Ollama local attempts failed (bases=%s models=%s)",
        uniq_bases,
        uniq_models,
    )
    return None


async def _ollama_cloud_chat_complete(
    prompt: str,
    temperature: float,
    *,
    stage: str | None = None,
) -> Optional[str]:
    """Chat completion via Ollama Cloud OpenAI-compatible API."""
    key = (settings.OLLAMA_CLOUD_API_KEY or "").strip()
    if not key:
        return None
    if stage:
        model = (get_model_for_stage(stage) or "").strip()
    else:
        model = (settings.OLLAMA_CLOUD_FAST_MODEL or "").strip()
    if not model:
        return None
    breaker = get_breaker("ollama_cloud")
    try:
        client = AsyncOpenAI(
            api_key=key,
            base_url=settings.OLLAMA_CLOUD_BASE_URL,
            timeout=settings.ASSISTANT_OLLAMA_TIMEOUT_SECONDS,
        )

        async def _request_once() -> Optional[str]:
            resp = await client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            content = (resp.choices[0].message.content or "").strip() if resp.choices else ""
            return content or None

        async def _breaker_wrapped_once() -> Optional[str]:
            return await breaker.call(_request_once)

        return await _with_retry_async(
            _breaker_wrapped_once,
            max_retries=2,
            base_delay=0.5,
            retry_label=f"Ollama Cloud ({model})",
        )
    except CircuitOpenError:
        logger.warning("Ollama Cloud circuit open; skipping provider attempt (%s)", model)
        return None
    except Exception as exc:
        logger.warning("Ollama Cloud assistant request failed (%s): %s", model, exc)
        logger.error("Assistant provider exhaustion: Ollama Cloud request failed with no fallback result (%s)", model)
        return None


async def _groq_chat_complete(prompt: str, temperature: float) -> Optional[str]:
    """Use Groq OpenAI-compatible API when GROQ_API_KEY is configured."""
    key = (settings.GROQ_API_KEY or "").strip()
    if not key:
        return None
    model = (settings.LLM_MODEL or "llama-3.3-70b-versatile").strip()
    breaker = get_breaker("groq")
    try:
        client = AsyncOpenAI(
            api_key=key,
            base_url="https://api.groq.com/openai/v1",
            timeout=settings.ASSISTANT_OLLAMA_TIMEOUT_SECONDS,
        )

        async def _request_once() -> Optional[str]:
            resp = await client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            content = (resp.choices[0].message.content or "").strip() if resp.choices else ""
            return content or None

        async def _breaker_wrapped_once() -> Optional[str]:
            return await breaker.call(_request_once)

        return await _with_retry_async(
            _breaker_wrapped_once,
            max_retries=2,
            base_delay=0.5,
            retry_label=f"Groq ({model})",
        )
    except CircuitOpenError:
        logger.warning("Groq circuit open; skipping provider attempt (%s)", model)
        return None
    except Exception as exc:
        logger.warning("Groq assistant request failed (%s): %s", model, exc)
        logger.error("Assistant provider exhaustion: Groq request failed with no fallback result (%s)", model)
        return None


class IntentResolver:
    def __init__(self):
        self.last_llm_backend: str = ""

    async def _generate_content_with_fallback(
        self,
        prompt: str,
        temperature: float,
        *,
        stage: str | None = None,
    ) -> Optional[str]:
        """Call the provider set by ASSISTANT_LLM_PROVIDER; auto = Groq, then Ollama Cloud."""
        self.last_llm_backend = ""
        provider = (settings.ASSISTANT_LLM_PROVIDER or "auto").strip().lower()

        if provider == "ollama":
            t = await _ollama_chat_complete(prompt, temperature)
            if t:
                self.last_llm_backend = "Ollama"
            return t

        if provider == "groq":
            t = await _groq_chat_complete(prompt, temperature)
            if t:
                self.last_llm_backend = "Groq"
            return t

        if provider == "ollama_cloud":
            t = await _ollama_cloud_chat_complete(prompt, temperature, stage=stage)
            if t:
                self.last_llm_backend = "Ollama Cloud"
            return t

        t = await _groq_chat_complete(prompt, temperature)
        if t:
            self.last_llm_backend = "Groq"
            return t

        t = await _ollama_cloud_chat_complete(prompt, temperature, stage=stage)
        if t:
            self.last_llm_backend = "Ollama Cloud"
        return t

    async def resolve_sql(
        self,
        question: str,
        org_id: UUID,
        conversation_block: str = "",
        *,
        _retried_without_context: bool = False,
    ) -> Optional[str]:
        prompt = _build_sql_prompt(org_id, question, conversation_block)
        try:
            response_text = await self._generate_content_with_fallback(
                prompt,
                0.0,
                stage="text_to_sql",
            )
            sql = _parse_sql_from_model_output(response_text)

            if (not sql or "UNKNOWN" in (sql or "").upper()) and conversation_block.strip() and not _retried_without_context:
                logger.info("Assistant SQL parse failed with conversation context; retrying without prior turns")
                return await self.resolve_sql(
                    question, org_id, "", _retried_without_context=True
                )

            if not sql or "UNKNOWN" in (sql or "").upper():
                if response_text:
                    repair_prompt = _build_sql_repair_prompt(org_id, question, response_text)
                    repaired = await self._generate_content_with_fallback(
                        repair_prompt,
                        0.0,
                        stage="text_to_sql",
                    )
                    repaired_sql = _parse_sql_from_model_output(repaired)
                    if repaired_sql and "UNKNOWN" not in repaired_sql.upper():
                        sql = repaired_sql

            if not sql or "UNKNOWN" in (sql or "").upper():
                if response_text:
                    logger.debug(
                        "Assistant SQL parse produced nothing; preview=%r",
                        (response_text[:100] + "…") if len(response_text) > 100 else response_text,
                    )
                return None

            return sql
        except Exception as exc:
            logger.error(f"Assistant SQL generation failed: {exc}")
            return None

    async def synthesize_answer(self, question: str, sql: str, rows: list) -> str:
        prompt = _build_synthesis_prompt(question, sql, rows)
        try:
            response_text = await self._generate_content_with_fallback(prompt, 0.3)
            out = (response_text or "").strip()
            if not out:
                return f"I found {len(rows)} result(s)." if rows else "No results found for that query."
            return out
        except Exception as exc:
            logger.warning(f"Synthesis failed: {exc}")
            return f"I found {len(rows)} result(s)." if rows else "No results found for that query."

async def _fetch_conversation_block(conn, user_id: UUID, session_id: Optional[str] = None, max_pairs: int = 6, max_chars: int = 1800) -> str:
    """Recent user prompts only (helps follow-up context without noisy answer text)."""
    where_clause = "user_id = :uid AND query_text IS NOT NULL AND trim(query_text) != ''"
    params = {"uid": str(user_id), "lim": max_pairs}
    if session_id:
        where_clause += " AND CAST(session_id AS TEXT) = :sid"
        params["sid"] = session_id
        
    hist_r = await conn.execute(
        text(
            f"""
            SELECT query_text
            FROM assistant_queries
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        params,
    )
    rows = list(hist_r.all())
    rows.reverse()
    parts: list[str] = []
    for (q,) in rows:
        qs = (q or "").replace("\n", " ").strip()[:420]
        parts.append(f"User: {qs}")
    block = "\n\n".join(parts)
    if len(block) > max_chars:
        block = block[-max_chars:]
    return block


@router.get("/history", responses={401: {"description": "Not authenticated"}, 403: {"description": "Access denied - manager role required"}})
async def get_assistant_history(current_user: CurrentUser):
    """Recent assistant sessions for the signed-in manager."""
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Assistant is only available to managers")

    async with engine.connect() as conn:
        sessions_r = await conn.execute(
            text("""
                SELECT id, title, is_deleted, created_at
                FROM assistant_sessions
                WHERE user_id = :uid AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT 30
            """),
            {"uid": str(current_user.id)},
        )
        sessions_db = sessions_r.all()
        if not sessions_db:
            return []
        session_ids = [str(s.id) for s in sessions_db]

        sids_placeholders = ", ".join([f":sid_{i}" for i in range(len(session_ids))])
        params = {f"sid_{i}": session_ids[i] for i in range(len(session_ids))}
        try:
            queries_r = await conn.execute(
                text(f"""
                    SELECT id, session_id, query_text, response_text, generated_sql, execution_time_ms, ai_understanding,
                           result_rows, created_at
                    FROM assistant_queries
                    WHERE CAST(session_id AS TEXT) IN ({sids_placeholders})
                    ORDER BY created_at ASC
                """),
                params,
            )
            has_rows_column = True
        except Exception:
            await conn.rollback()
            queries_r = await conn.execute(
                text(f"""
                    SELECT id, session_id, query_text, response_text, generated_sql, execution_time_ms, ai_understanding,
                           created_at
                    FROM assistant_queries
                    WHERE CAST(session_id AS TEXT) IN ({sids_placeholders})
                    ORDER BY created_at ASC
                """),
                params,
            )
            has_rows_column = False
            
        queries_db = list(queries_r.all())

        def _coerce_result_rows(raw) -> Optional[list]:
            if raw is None:
                return None
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, list) else None
                except json.JSONDecodeError:
                    return None
            return None

        def _ts_label(created_at) -> Optional[str]:
            if created_at is None:
                return None
            try:
                return created_at.isoformat()
            except Exception:
                return str(created_at)

        def _ai_turn_success(response_text: Optional[str], gen_sql: Optional[str], ai_u: Optional[str]) -> bool:
            if ai_u and str(ai_u).lower() == "help":
                return True
            if not gen_sql:
                return False
            low = (response_text or "").lower()
            if any(p in low for p in ("database error", "hit a database error", "rate limits", "not sure how to answer", "having trouble connecting")):
                return False
            return True

        session_map = {}
        for s in sessions_db:
            session_map[str(s.id)] = {
                "id": str(s.id),
                "title": s.title,
                "deleted": s.is_deleted,
                "messages": []
            }

        for row in queries_db:
            if has_rows_column:
                idx, sid, q, r_text, gen_sql, exec_ms, ai_u, result_rows_raw, created_at = row
            else:
                idx, sid, q, r_text, gen_sql, exec_ms, ai_u, created_at = row
                result_rows_raw = None
            if not r_text:
                continue
            ts = _ts_label(created_at)
            stored_data = _coerce_result_rows(result_rows_raw)
            sid_str = str(sid)
            
            if sid_str in session_map:
                session_map[sid_str]["messages"].append({
                    "id": f"q_{idx}", "type": "user", "content": q, "mode": "chat", "created_at": ts,
                })
                success = _ai_turn_success(r_text, gen_sql, ai_u)
                exec_label = f"{exec_ms}ms" if exec_ms is not None else None
                ai_payload: dict = {
                    "id": f"a_{idx}", "type": "ai", "content": r_text, "mode": "chat", "success": success,
                    "sql": gen_sql or None, "executionTime": exec_label, "execution_time": exec_label, "created_at": ts,
                }
                if stored_data is not None:
                    ai_payload["data"] = stored_data
                session_map[sid_str]["messages"].append(ai_payload)

        return list(session_map.values())


@router.post("/query", response_model=AssistantQueryResponse, responses={401: {"description": "Not authenticated"}, 403: {"description": "Access denied - manager role required"}, 422: {"description": "Invalid input query parameters"}})
async def process_assistant_query(
    request: AssistantQueryRequest,
    current_user: CurrentUser,
) -> AssistantQueryResponse:
    """
    Submit a natural language query or chat message to the AI Manager Assistant.
    """
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Assistant is only available to managers")

    query_text = request.query_text.strip()
    mode = request.mode or QueryMode.chat
    manager_id = current_user.id
    org_id = current_user.organization_id
    start_time = time.time()

    session_id_val = request.session_id
    async with engine.connect() as conn:
        if not session_id_val:
            title = query_text.strip()[:42] + ("..." if len(query_text) > 42 else "")
            if not title:
                title = "New Chat"
            new_session_id = str(uuid.uuid4())
            ins_session = await conn.execute(
                text("INSERT INTO assistant_sessions (id, user_id, organization_id, title, is_deleted, created_at) VALUES (:sid, :uid, :oid, :title, false, timezone('utc', now())) RETURNING id"),
                {"sid": new_session_id, "uid": str(manager_id), "oid": str(org_id), "title": title}
            )
            session_id_val = str(ins_session.scalar())
            await conn.commit()

        # Help / schema discovery (persist so it appears in history)
        if query_text.lower() in _HELP_TRIGGERS or query_text in ("?", ""):
            help_ms = int((time.time() - start_time) * 1000)
            ins = await conn.execute(
                text(
                    """
                    INSERT INTO assistant_queries
                    (session_id, user_id, organization_id, query_mode, query_text, ai_understanding, response_text, execution_time_ms)
                    VALUES (:sid, :u, :o, :m, :q, :ai, :r, :e)
                    RETURNING id
                    """
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text or "help",
                    "ai": "help",
                    "r": _HELP_RESPONSE,
                    "e": help_ms,
                },
            )
            await conn.commit()
            qid = ins.scalar()
            exec_label = f"{help_ms}ms"
            return {
                "id": str(qid) if qid else "",
                "session_id": session_id_val,
                "type": "ai",
                "content": _HELP_RESPONSE,
                "mode": mode.value,
                "success": True,
                "degraded": False,
                "executionTime": exec_label,
                "execution_time": exec_label,
            }

        resolver = IntentResolver()
        conversation_block = await _fetch_conversation_block(conn, manager_id, session_id_val)

        sql = None
        ordinal_offset = _ordinal_followup_offset(query_text)
        if ordinal_offset is not None:
            prev_sql_r = await conn.execute(
                text(
                    """
                    SELECT generated_sql
                    FROM assistant_queries
                    WHERE user_id = :uid AND generated_sql IS NOT NULL AND trim(generated_sql) != ''
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"uid": str(manager_id)},
            )
            prev_sql = prev_sql_r.scalar()
            if prev_sql:
                sql = _build_ordinal_followup_sql(str(prev_sql), ordinal_offset)

        if not sql:
            sql = await resolver.resolve_sql(query_text, org_id, conversation_block)

        if not sql:
            msg = (
                "I'm not sure how to answer that from the available data. "
                "Try asking about agents, scores, violations, or emotions -- or type 'help'."
            )
            await conn.execute(
                text(
                    "INSERT INTO assistant_queries (session_id, user_id, organization_id, query_mode, query_text, response_text, execution_time_ms) VALUES (:sid, :u, :o, :m, :q, :r, :e)"
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text,
                    "r": msg,
                    "e": int((time.time() - start_time) * 1000),
                },
            )
            await conn.commit()
            return {
                "session_id": session_id_val,
                "type": "ai",
                "content": msg,
                "mode": mode.value,
                "success": False,
                "degraded": True,
                "executionTime": f"{int((time.time() - start_time) * 1000)}ms",
                "execution_time": f"{int((time.time() - start_time) * 1000)}ms",
            }

        if not _is_org_scoped_sql(sql, org_id):
            err_msg = (
                "I can only run organization-scoped analytics queries. "
                "Please rephrase your request."
            )
            await conn.execute(
                text(
                    "INSERT INTO assistant_queries (session_id, user_id, organization_id, query_mode, query_text, generated_sql, response_text, execution_time_ms) VALUES (:sid, :u, :o, :m, :q, :s, :r, :e)"
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text,
                    "s": sql,
                    "r": err_msg,
                    "e": int((time.time() - start_time) * 1000),
                },
            )
            await conn.commit()
            return {
                "session_id": session_id_val,
                "type": "ai",
                "content": err_msg,
                "mode": mode.value,
                "sql": sql,
                "success": False,
                "degraded": True,
                "executionTime": f"{int((time.time() - start_time) * 1000)}ms",
                "execution_time": f"{int((time.time() - start_time) * 1000)}ms",
            }

        try:
            _validate_sql_structure(sql)
        except ValueError as exc:
            err_msg = (
                "I can only run safe analytics queries. "
                f"{exc}"
            )
            await conn.execute(
                text(
                    "INSERT INTO assistant_queries (session_id, user_id, organization_id, query_mode, query_text, generated_sql, response_text, execution_time_ms) VALUES (:sid, :u, :o, :m, :q, :s, :r, :e)"
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text,
                    "s": sql,
                    "r": err_msg,
                    "e": int((time.time() - start_time) * 1000),
                },
            )
            await conn.commit()
            return {
                "session_id": session_id_val,
                "type": "ai",
                "content": err_msg,
                "mode": mode.value,
                "sql": sql,
                "success": False,
                "degraded": True,
                "executionTime": f"{int((time.time() - start_time) * 1000)}ms",
                "execution_time": f"{int((time.time() - start_time) * 1000)}ms",
            }

        try:
            t0 = time.time()
            async with assistant_sql_engine.connect() as assistant_conn:
                res = await assistant_conn.execute(text(sql))
            rows = [dict(r._mapping) for r in res]
            exec_ms = int((time.time() - t0) * 1000)
        except Exception as exc:
            await conn.rollback()
            sql_preview = (sql[:100] + "…") if len(sql) > 100 else sql
            logger.debug("SQL exec error: %s | SQL preview: %s", exc, sql_preview, exc_info=True)
            err_msg = "I understood your request but hit a database error. Try rephrasing or type 'help' for example queries."
            await conn.execute(
                text(
                    "INSERT INTO assistant_queries (session_id, user_id, organization_id, query_mode, query_text, generated_sql, response_text, execution_time_ms) VALUES (:sid, :u, :o, :m, :q, :s, :r, :e)"
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text,
                    "s": sql,
                    "r": err_msg,
                    "e": int((time.time() - start_time) * 1000),
                },
            )
            await conn.commit()
            return {
                "session_id": session_id_val,
                "type": "ai",
                "content": err_msg,
                "mode": mode.value,
                "sql": sql,
                "success": False,
                "degraded": True,
                "executionTime": f"{int((time.time() - start_time) * 1000)}ms",
                "execution_time": f"{int((time.time() - start_time) * 1000)}ms",
            }

        if ordinal_offset is not None:
            answer = _deterministic_ordinal_answer(ordinal_offset, rows)
        elif _is_rank_query(query_text):
            answer = _deterministic_rank_answer(rows)
        else:
            answer = await resolver.synthesize_answer(query_text, sql, rows)

        backend = (resolver.last_llm_backend or "LLM").strip()
        ai_label = f"{backend} text-to-SQL" if backend else "text-to-SQL"
        rows_json = json.dumps(rows, default=_json_safe) if rows else None

        try:
            ins = await conn.execute(
                text(
                    """
                    INSERT INTO assistant_queries
                    (session_id, user_id, organization_id, query_mode, query_text, ai_understanding, generated_sql, response_text, execution_time_ms, result_rows)
                    VALUES (:sid, :u, :o, :m, :q, :ai, :s, :r, :e, CAST(:data AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text,
                    "ai": ai_label,
                    "s": sql,
                    "r": answer,
                    "e": exec_ms,
                    "data": rows_json,
                },
            )
        except Exception:
            await conn.rollback()
            # Backward compatibility for DBs without result_rows column.
            ins = await conn.execute(
                text(
                    """
                    INSERT INTO assistant_queries
                    (session_id, user_id, organization_id, query_mode, query_text, ai_understanding, generated_sql, response_text, execution_time_ms)
                    VALUES (:sid, :u, :o, :m, :q, :ai, :s, :r, :e)
                    RETURNING id
                    """
                ),
                {
                    "sid": session_id_val,
                    "u": str(manager_id),
                    "o": str(org_id),
                    "m": mode.value,
                    "q": query_text,
                    "ai": ai_label,
                    "s": sql,
                    "r": answer,
                    "e": exec_ms,
                },
            )
        await conn.commit()
        qid = ins.scalar()
        exec_label = f"{exec_ms}ms"

        return {
            "id": str(qid) if qid else "",
            "session_id": session_id_val,
                "type": "ai",
            "content": answer,
            "mode": mode.value,
            "sql": sql,
            "executionTime": exec_label,
            "execution_time": exec_label,
            "data": rows,
            "rowCount": len(rows),
            "success": True,
            "degraded": False,
        }


class AssistantSessionRenameRequest(BaseModel):
    title: str

@router.patch("/session/{session_id}")
async def rename_assistant_session(
    session_id: str,
    request: AssistantSessionRenameRequest,
    current_user: CurrentUser,
    session: SessionDep,
):
    """Rename an assistant session."""
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    res = await session.exec(
        text("UPDATE assistant_sessions SET title = :t WHERE CAST(id AS TEXT) = :sid AND CAST(user_id AS TEXT) = :uid RETURNING id"),
        params={"t": request.title[:255], "sid": session_id, "uid": str(current_user.id)},
    )
    if not res.scalar():
        raise HTTPException(status_code=404, detail="Session not found")
    await session.commit()
    return {"success": True}

@router.delete("/session/{session_id}")
async def delete_assistant_session(
    session_id: str,
    current_user: CurrentUser,
    session: SessionDep,
):
    """Soft delete an assistant session."""
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    res = await session.exec(
        text("UPDATE assistant_sessions SET is_deleted = true WHERE CAST(id AS TEXT) = :sid AND CAST(user_id AS TEXT) = :uid RETURNING id"),
        params={"sid": session_id, "uid": str(current_user.id)},
    )
    if not res.scalar():
        raise HTTPException(status_code=404, detail="Session not found")
    await session.commit()
    return {"success": True}
