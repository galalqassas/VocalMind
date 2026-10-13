"""
VocalMind evaluators (judging layer).

Layer responsibility:
  - RAG retrieval (services/rag/query_engine.py): fetches grounded chunks only.
  - Evaluators in this module: consume retrieved context + business input and
    generate transcript/question-level judgment reports.

Evaluators:
  1) PolicyComplianceEvaluator
     Transcript-level compliance report generator.
  2) AnswerCorrectnessEvaluator
     Question/answer-level factual correctness report generator.
"""

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field
try:
    from app.core.llm_circuit_breaker import get_breaker, is_transient_llm_error
except ImportError:  # pragma: no cover - standalone rag test/runtime fallback
    from llm_circuit_breaker import get_breaker, is_transient_llm_error

try:
    from .config import settings, build_rag_llm_client, rag_judge_model
    from .prompt_safety import sanitize_prompt_text
    from .query_engine import RAGQueryEngine
except ImportError:  # pragma: no cover - allows direct script/test imports
    from config import settings, build_rag_llm_client, rag_judge_model
    from prompt_safety import sanitize_prompt_text
    from query_engine import RAGQueryEngine


logger = logging.getLogger(__name__)


# ── Result Models ─────────────────────────────────────────────────────────────


class ComplianceResult(BaseModel):
    """Result of a policy compliance check."""

    transcript: str
    compliance_score: float = Field(ge=0.0, le=1.0, description="0 = non-compliant, 1 = fully compliant")
    degraded: bool = False
    violations: list[str] = Field(default_factory=list)
    policy_references: list[str] = Field(default_factory=list)
    reasoning: str = ""
    retrieved_policies: list[dict] = Field(default_factory=list)
    retrieval_seconds: float = 0.0
    evaluation_seconds: float = 0.0


class CorrectnessResult(BaseModel):
    """Result of an answer correctness check."""

    question: str
    agent_answer: str
    correctness_score: float = Field(ge=0.0, le=1.0, description="0 = incorrect, 1 = correct")
    is_correct: bool = False
    reasoning: str = ""
    source_references: list[str] = Field(default_factory=list)
    retrieved_snippets: list[dict] = Field(default_factory=list)
    retrieval_seconds: float = 0.0
    evaluation_seconds: float = 0.0


class EvaluationReport(BaseModel):
    """Aggregated report for a batch of evaluations."""

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    eval_type: str  # "compliance" or "correctness"
    model: str = ""
    total_samples: int = 0
    avg_score: float = 0.0
    results: list[ComplianceResult | CorrectnessResult] = Field(default_factory=list)


# ── Compliance Evaluator ──────────────────────────────────────────────────────

COMPLIANCE_PROMPT = """\
You are a compliance auditor for a customer-service organization.

You are given:
1. A transcript of an agent's interaction with a customer.
2. Relevant company policy sections retrieved from the policy database.

Evaluate whether the agent's actions and statements comply with the company policies.

--- COMPANY POLICIES ---
{policies}

--- AGENT TRANSCRIPT ---
{transcript}

--- INSTRUCTIONS ---
Analyze the transcript against each relevant policy section.  Identify any
violations (specific actions or statements that break policy rules).  Also
note any commendable compliance.

Respond with ONLY valid JSON — no markdown, no explanation outside JSON:
{{
    "compliance_score": <float 0.0 to 1.0>,
    "violations": ["violation 1", "violation 2", ...],
    "policy_references": ["Policy Section X: Title", ...],
    "reasoning": "Brief explanation of your assessment"
}}
"""


class PolicyComplianceEvaluator:
    """
    Transcript-level policy compliance judge/report generator.

    This class does not own retrieval indexing logic. It consumes context
    returned by the RAG retrieval layer and produces a compliance report.
    """

    def __init__(self, engine: RAGQueryEngine | None = None) -> None:
        self.engine = engine or RAGQueryEngine()
        self._judge_client = build_rag_llm_client()

    def check(
        self,
        transcript: str,
        org_filter: str | None = None,
        verbose: bool = False,
    ) -> ComplianceResult:
        """
        Run a policy-compliance check on a transcript.

        Args:
            transcript:  The agent's call transcript text.
            org_filter:  Filter retrieval to a specific organization.
            verbose:     Print intermediate results.
        """
        # 1. Retrieve relevant policy sections (parents) via retrieval-only API.
        result = self.engine.retrieve_policy_context(
            transcript,
            org_filter=org_filter,
            verbose=verbose,
        )
        retrieval_time = result["timing"]["retrieval"]

        safe_transcript = sanitize_prompt_text(transcript, max_length=8000)
        policies_text = "\n\n---\n\n".join(
            f"[{c['metadata'].get('doc_id', 'N/A')} | "
            f"{c['metadata'].get('Header 1', '')} > {c['metadata'].get('Header 2', '')}]\n"
            f"{sanitize_prompt_text(c['text'], max_length=2500)}"
            for c in result["chunks"]
        )
        safe_policies = sanitize_prompt_text(policies_text, max_length=12000)

        if not safe_policies.strip():
            return ComplianceResult(
                transcript=safe_transcript,
                compliance_score=0.5,
                degraded=True,
                reasoning="No relevant policies found for this transcript.",
                retrieval_seconds=retrieval_time,
            )

        # 2. LLM-as-Judge
        prompt = COMPLIANCE_PROMPT.format(policies=safe_policies, transcript=safe_transcript)
        groq_breaker = get_breaker("groq")

        t0 = time.perf_counter()
        try:
            content = _invoke_judge_with_retry(
                lambda: groq_breaker.call_sync(
                    lambda: _run_judge_client(self._judge_client, prompt, 2048)
                )
            )
        except Exception as llm_exc:
            eval_time = time.perf_counter() - t0
            return ComplianceResult(
                transcript=safe_transcript,
                compliance_score=0.5,
                degraded=True,
                reasoning=f"LLM judge request failed after retries: {llm_exc}",
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )
        eval_time = time.perf_counter() - t0

        # 3. Parse response
        content = content.strip()
        try:
            parsed = _parse_json_response(content)
            if "error" in parsed:
                raise ValueError(parsed["error"])
        except ValueError as parse_exc:
            return ComplianceResult(
                transcript=safe_transcript,
                compliance_score=0.5,
                degraded=True,
                reasoning=f"Failed to parse LLM evaluation response: {parse_exc}",
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )

        try:
            return ComplianceResult(
                transcript=safe_transcript,
                compliance_score=_validated_score(parsed, "compliance_score"),
                violations=_validated_string_list(parsed, "violations"),
                policy_references=_validated_string_list(parsed, "policy_references"),
                reasoning=_validated_string(parsed, "reasoning"),
                retrieved_policies=[
                    {"text": c["text"][:200], "metadata": c["metadata"]}
                    for c in result["chunks"]
                ],
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )
        except ValueError as validation_exc:
            return ComplianceResult(
                transcript=safe_transcript,
                compliance_score=0.5,
                degraded=True,
                reasoning=f"Invalid LLM evaluation shape: {validation_exc}",
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )


# ── Answer Correctness Evaluator ──────────────────────────────────────────────

CORRECTNESS_PROMPT = """\
You are an impartial quality auditor for a customer-service call center.

You are given:
1. A customer's question.
2. The agent's answer during the call.
3. Relevant knowledge base snippets retrieved from the company's documents.

Determine whether the agent's answer is **factually correct** based on the
company's official knowledge base.

--- KNOWLEDGE BASE SNIPPETS ---
{snippets}

--- CUSTOMER QUESTION ---
{question}

--- AGENT ANSWER ---
{answer}

--- INSTRUCTIONS ---
Compare the agent's answer against the knowledge base snippets.
- If the answer is accurate and consistent with the knowledge base → high score.
- If the answer contains factual errors or contradicts the knowledge base → low score.
- If the knowledge base doesn't cover the topic → note it and give a middle score.

Respond with ONLY valid JSON — no markdown, no explanation outside JSON:
{{
    "correctness_score": <float 0.0 to 1.0>,
    "is_correct": <boolean>,
    "reasoning": "Brief explanation",
    "source_references": ["Reference 1", "Reference 2", ...]
}}
"""


class AnswerCorrectnessEvaluator:
    """
    Answer correctness judge/report generator.

    This class consumes retrieval context from the RAG retrieval layer and
    evaluates factual alignment for a single question/answer pair.
    """

    def __init__(self, engine: RAGQueryEngine | None = None) -> None:
        self.engine = engine or RAGQueryEngine()
        self._judge_client = build_rag_llm_client()

    def check(
        self,
        question: str,
        agent_answer: str,
        org_filter: str | None = None,
        verbose: bool = False,
    ) -> CorrectnessResult:
        """
        Check if an agent's answer is factually correct.

        Args:
            question:     The customer's question.
            agent_answer: The agent's response.
            org_filter:   Filter retrieval to a specific organization.
            verbose:      Print intermediate results.
        """
        # 1. Retrieve relevant snippets (children) via retrieval-only API.
        result = self.engine.retrieve_answer_context(
            question,
            org_filter=org_filter,
            verbose=verbose,
        )
        retrieval_time = result["timing"]["retrieval"]

        safe_question = sanitize_prompt_text(question, max_length=3000)
        safe_answer = sanitize_prompt_text(agent_answer, max_length=3000)
        snippets_text = "\n\n---\n\n".join(
            f"[{c['metadata'].get('doc_id', 'N/A')} | "
            f"{c['metadata'].get('source_file', '')}]\n"
            f"{sanitize_prompt_text(c['text'], max_length=2500)}"
            for c in result["chunks"]
        )
        safe_snippets = sanitize_prompt_text(snippets_text, max_length=12000)

        if not safe_snippets.strip():
            return CorrectnessResult(
                question=safe_question,
                agent_answer=safe_answer,
                correctness_score=0.5,
                reasoning="No relevant knowledge base entries found for this question.",
                retrieval_seconds=retrieval_time,
            )

        # 2. LLM-as-Judge
        prompt = CORRECTNESS_PROMPT.format(
            snippets=safe_snippets, question=safe_question, answer=safe_answer
        )
        groq_breaker = get_breaker("groq")

        t0 = time.perf_counter()
        try:
            content = _invoke_judge_with_retry(
                lambda: groq_breaker.call_sync(
                    lambda: _run_judge_client(self._judge_client, prompt, 2048)
                )
            )
        except Exception as llm_exc:
            eval_time = time.perf_counter() - t0
            return CorrectnessResult(
                question=safe_question,
                agent_answer=safe_answer,
                correctness_score=0.5,
                reasoning=f"LLM judge request failed after retries: {llm_exc}",
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )
        eval_time = time.perf_counter() - t0

        # 3. Parse response
        content = content.strip()
        try:
            parsed = _parse_json_response(content)
            if "error" in parsed:
                raise ValueError(parsed["error"])
        except ValueError as parse_exc:
            return CorrectnessResult(
                question=safe_question,
                agent_answer=safe_answer,
                correctness_score=0.5,
                reasoning=f"Failed to parse LLM evaluation response: {parse_exc}",
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )

        try:
            return CorrectnessResult(
                question=safe_question,
                agent_answer=safe_answer,
                correctness_score=_validated_score(parsed, "correctness_score"),
                is_correct=_validated_bool(parsed, "is_correct"),
                reasoning=_validated_string(parsed, "reasoning"),
                source_references=_validated_string_list(parsed, "source_references"),
                retrieved_snippets=[
                    {"text": c["text"][:200], "metadata": c["metadata"]}
                    for c in result["chunks"]
                ],
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )
        except ValueError as validation_exc:
            return CorrectnessResult(
                question=safe_question,
                agent_answer=safe_answer,
                correctness_score=0.5,
                reasoning=f"Invalid LLM evaluation shape: {validation_exc}",
                retrieval_seconds=retrieval_time,
                evaluation_seconds=round(eval_time, 4),
            )


# ── Batch Evaluation ──────────────────────────────────────────────────────────


def run_compliance_batch(
    transcripts: list[str],
    org_filter: str | None = None,
    verbose: bool = False,
) -> EvaluationReport:
    """Evaluate a batch of transcripts for policy compliance."""
    evaluator = PolicyComplianceEvaluator()
    results: list[ComplianceResult] = []

    for i, transcript in enumerate(transcripts, 1):
        print(f"\n[{i}/{len(transcripts)}] Checking compliance...")
        result = evaluator.check(transcript, org_filter=org_filter, verbose=verbose)
        results.append(result)
        status = "PASS" if result.compliance_score >= 0.7 else "FAIL"
        print(f"  Score: {result.compliance_score:.2f} [{status}]")
        if result.violations:
            for v in result.violations:
                print(f"  Violation: {v}")

    avg_score = sum(r.compliance_score for r in results) / len(results) if results else 0
    report = EvaluationReport(
        eval_type="compliance",
        model=rag_judge_model(),
        total_samples=len(results),
        avg_score=round(avg_score, 4),
        results=results,
    )
    _save_report(report, "compliance")
    return report


def run_correctness_batch(
    qa_pairs: list[dict[str, str]],
    org_filter: str | None = None,
    verbose: bool = False,
) -> EvaluationReport:
    """
    Evaluate a batch of Q&A pairs for answer correctness.

    Args:
        qa_pairs: List of dicts with 'question' and 'answer' keys.
    """
    evaluator = AnswerCorrectnessEvaluator()
    results: list[CorrectnessResult] = []

    for i, qa in enumerate(qa_pairs, 1):
        print(f"\n[{i}/{len(qa_pairs)}] Checking answer: {qa['question'][:60]}...")
        result = evaluator.check(
            qa["question"], qa["answer"], org_filter=org_filter, verbose=verbose
        )
        results.append(result)
        icon = "correct" if result.is_correct else "incorrect"
        print(f"  Score: {result.correctness_score:.2f} [{icon}]  {result.reasoning[:80]}")

    avg_score = sum(r.correctness_score for r in results) / len(results) if results else 0
    report = EvaluationReport(
        eval_type="correctness",
        model=rag_judge_model(),
        total_samples=len(results),
        avg_score=round(avg_score, 4),
        results=results,
    )
    _save_report(report, "correctness")
    return report


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_transient_llm_error(exc: Exception) -> bool:
    return is_transient_llm_error(exc)

def _run_judge_client(client, prompt: str, max_tokens: int) -> str:
    if hasattr(client, "invoke"):
        # LangChain ChatModel (e.g. ChatVertexAI)
        from langchain_core.messages import HumanMessage
        response = client.invoke([HumanMessage(content=prompt)])
        return response.content
    else:
        # OpenAI or Groq client
        response = client.chat.completions.create(
            model=rag_judge_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


def _invoke_judge_with_retry(call, max_retries: int = 3) -> object:
    base_delay = 0.5
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return call()
        except Exception as exc:
            last_exc = exc
            if not _is_transient_llm_error(exc) or attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.3)
            logger.warning(
                "RAG judge attempt %d/%d failed (transient), retrying in %.1fs: %s",
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _parse_json_response(content: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    if "```" in content:
        parts = content.split("```")
        for part in parts:
            clean = part.replace("json", "", 1).strip() if part.strip().startswith("json") else part.strip()
            if clean.startswith("{"):
                content = clean
                break

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
        return {"error": f"Failed to parse LLM response as JSON: {content[:200]}"}


def _validated_score(parsed: dict, key: str) -> float:
    if key not in parsed:
        raise ValueError(f"Missing required key: {key}")
    try:
        raw = float(parsed[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {key}") from exc
    return max(0.0, min(1.0, raw))


def _validated_string_list(parsed: dict, key: str) -> list[str]:
    if key not in parsed:
        raise ValueError(f"Missing required key: {key}")
    value = parsed[key]
    if not isinstance(value, list):
        raise ValueError(f"Invalid list value for {key}")
    return [str(item).strip() for item in value if str(item).strip()]


def _validated_string(parsed: dict, key: str) -> str:
    if key not in parsed:
        raise ValueError(f"Missing required key: {key}")
    value = parsed[key]
    if value is None:
        return ""
    return str(value).strip()


def _validated_bool(parsed: dict, key: str) -> bool:
    if key not in parsed:
        raise ValueError(f"Missing required key: {key}")
    value = parsed[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"Invalid bool value for {key}")


def _save_report(report: EvaluationReport, prefix: str) -> Path:
    """Save evaluation report to JSON."""
    reports_dir = settings.BASE_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"{prefix}_report_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    print(f"\n  Report saved → {path}")
    return path
