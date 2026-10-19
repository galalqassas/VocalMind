# Manager Assistant (Text-to-SQL)

Natural-language analytics for managers. Implementation: `backend/app/api/routes/assistant.py`; UI: `frontend/src/app/components/manager/ManagerAssistant.tsx`.

## Endpoints (manager role only; others get 403)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/assistant/query` | Ask a question; creates an `assistant_sessions` row when `session_id` is omitted |
| GET | `/api/v1/assistant/history` | Last 30 non-deleted sessions with their messages |
| PATCH | `/api/v1/assistant/session/{id}` | Rename a session |
| DELETE | `/api/v1/assistant/session/{id}` | Soft delete (`is_deleted=true`) |

Each turn, including failures, is stored in `assistant_queries` (question, generated SQL, answer, timing, and `result_rows` JSON when that column exists — `infra/db/03_assistant_result_rows.sql`).

## Request flow (`POST /query`)

1. `help` / `?` and similar return a static help text.
2. Context: the last 6 user questions in the session (`_fetch_conversation_block`).
3. Ordinal follow-ups (question contains "first"…"fifth" or "1st"…"5th") reuse the user's most recent generated SQL as `WITH prev AS (…) SELECT id FROM prev LIMIT 1 OFFSET n`.
4. Otherwise `IntentResolver.resolve_sql` prompts the LLM with the allowed schema and examples. If parsing fails it retries without conversation context, then once with a repair prompt.
5. `_is_org_scoped_sql` requires a literal `organization_id = '<caller org id>'`.
6. `_validate_sql_structure` (below).
7. Execute on `assistant_sql_engine` (`ASSISTANT_DATABASE_URL`).
8. Answer: deterministic text for ordinal and "top/highest/best/lowest/worst" questions; otherwise an LLM summary of up to 20 rows (falls back to "I found N result(s).").

Failures at steps 4–7 return HTTP 200 with `success: false, degraded: true` and a user-facing message.

## Providers (`ASSISTANT_LLM_PROVIDER`)

| Value | Behaviour |
|---|---|
| `auto` (Settings default) | Groq (`GROQ_API_KEY`, `LLM_MODEL`) → Ollama Cloud |
| `ollama_cloud` (compose default) | Ollama Cloud only. SQL uses `get_model_for_stage("text_to_sql")` (when `LLM_PROVIDER=ollama_cloud`: `OLLAMA_MODEL_TEXT_TO_SQL`, else the heavy model); answers use `OLLAMA_CLOUD_FAST_MODEL` |
| `groq` | Groq only |
| `ollama` | Local Ollama only (compose profile `local-ml`): `ASSISTANT_OLLAMA_MODEL` (default `qwen2.5:7b`) at `OLLAMA_BASE_URL`, then `http://host.docker.internal:11434` |

Named providers do not fall back. Local Ollama is never part of `auto`. Groq, Ollama Cloud, and local Ollama calls go through circuit breakers (`backend/app/core/llm_circuit_breaker.py`) with 2 attempts on transient errors.

## Read-only enforcement

Three layers:

1. **SQL validation** (`_validate_sql_structure`): exactly one statement; `SELECT` or `WITH … SELECT` only; tables limited to `users`, `organizations`, `interactions`, `interaction_scores`, `policy_compliance`, `company_policies`, `utterances` with a per-table column allowlist (`_ASSISTANT_TABLE_COLUMNS`); no `SELECT *` or `table.*`; explicit `LIMIT` ≤ 200.
2. **Org scoping** (`_is_org_scoped_sql`), above.
3. **Database role**: `ASSISTANT_DATABASE_URL` connects as `vocalmind_readonly`, created by `infra/db/04_assistant_readonly_role.sql` with column-level `SELECT` grants on the same columns and no other privileges.

Scores are stored on a 0–1 scale; the SQL prompt tells the model to multiply by 10 or 100 for display.

## Known issues

- With `ASSISTANT_LLM_PROVIDER=ollama_cloud` but `LLM_PROVIDER=groq`, the SQL stage sends the Groq `LLM_MODEL` name to Ollama Cloud (stage model resolution follows `LLM_PROVIDER`).
- Ordinal detection is a substring match, so any question containing e.g. "first" or "second" is treated as a follow-up to the previous SQL.
- The ordinal follow-up reads the latest SQL across all of the user's sessions, not the current one.
