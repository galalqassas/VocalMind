from __future__ import annotations

import asyncio
import logging
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.emotion_fusion import EMOTION_NORMALIZATION, fuse_emotion_signals, infer_text_emotion_with_provider
from app.llm_trigger.chains import (
    _invoke_chain_with_retry,
    build_emotion_shift_chain,
    build_nli_policy_chain,
    build_process_adherence_chain,
    build_topic_classification_chain,
)
from app.llm_trigger.prompt_constants import RESOLUTION_GRAPHS, STEP_KEY_TO_LABEL, UNKNOWN_TOPIC, _step_key
from app.llm_trigger.retrieval import RetrievedChunk, resolve_retrieved_sop_context, retrieve_policy_chunks
from app.llm_trigger.schemas import (
    ClaimProvenance,
    EvidenceAnchoredExplainability,
    EvidenceCitation,
    EvidenceSpan,
    EmotionShiftAnalysis,
    InteractionLLMTriggerReport,
    NLIEvaluation,
    PolicyReference,
    ProcessAdherenceReport,
    TriggerAttribution,
)
from app.models.interaction import Interaction
from app.models.llm_trigger_cache import InteractionLLMTriggerCache
from app.models.policy import CompanyPolicy, OrganizationPolicy
from app.models.transcript import Transcript
from app.models.utterance import Utterance
from app.models.user import User


logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 5
_evaluator_lock = threading.Lock()
_policy_compliance_evaluator = None


class LLMUnavailableError(RuntimeError):
    """A model the reasoning engine depends on (LLM or text-emotion) failed.

    There is no heuristic fallback: the stage fails and can be reprocessed later.
    """


async def _run_chain(stage: str, build_chain, inputs: dict) -> Any:
    try:
        return await _invoke_chain_with_retry(build_chain(), inputs)
    except Exception as exc:
        raise LLMUnavailableError(f"LLM stage '{stage}' is unavailable: {exc}") from exc


def _model_call(stage: str, fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise LLMUnavailableError(f"Model stage '{stage}' is unavailable: {exc}") from exc


ROLLING_WINDOW_TURNS = 8
ROLLING_WINDOW_STRIDE = 4
MAX_PROCESS_WINDOWS = 3
INSUFFICIENT_EVIDENCE_LABEL = "insufficient evidence"
POLICY_PRIORITY_BUCKETS: tuple[str, ...] = ("regulatory", "legal")

BULLET_PREFIXES = ("•", "-", "–", "▪", "\uf0b7", "*", "·")


def _filter_bullet_steps(steps: list[str]) -> list[str]:
    return [s for s in steps if s.strip() and s.strip()[0] not in BULLET_PREFIXES]


MAX_STEP_WORDS = 12  # procedural step names are short; prose is long


def _filter_prose_steps(steps: list[str]) -> list[str]:
    """Remove prose sentences masquerading as SOP step names."""
    filtered = []
    for s in steps:
        stripped = s.strip()
        if not stripped:
            continue
        word_count = len(stripped.split())
        is_prose = (
            word_count > MAX_STEP_WORDS
            or bool(re.search(r"[A-Z]{2,}-[A-Z]+-(?:RULE|REG|LAW)-\d+", stripped))
            or (
                stripped.endswith(".")
                and word_count >= 4
                and any(
                    w in stripped.lower()
                    for w in [
                        "filed",
                        "loaded",
                        "complete",
                        "confirm",
                        "airplane",
                        "disclosure",
                        "operations",
                        "business days",
                        "expedited",
                        "must be",
                        "prior to",
                        "in order to",
                        "before sending",
                        "identity verification",
                        "ctr is",
                        "sar is",
                        "mode is",
                        "sim card",
                        "restart the",
                        "reboot the",
                        "toggle ",
                        "power cycle",
                        "unplug the",
                    ]
                )
            )
        )
        if not is_prose:
            filtered.append(s)
    return filtered


def _normalize_step_identity(step: str) -> str:
    """Canonical key for cross-topic step comparison (handles -, _, /, spacing)."""
    normalized = re.sub(r"[^a-z0-9 ]", " ", step.lower().strip())
    return re.sub(r"\s+", " ", normalized).strip().replace(" ", "_")


def _filter_cross_topic_steps(steps: list[str], topic_hint: str) -> list[str]:
    """Remove steps that belong to a different topic's RESOLUTION_GRAPH."""
    if not topic_hint or topic_hint not in RESOLUTION_GRAPHS:
        return steps
    other_topic_steps: set[str] = set()
    for topic, topic_steps in RESOLUTION_GRAPHS.items():
        if topic != topic_hint:
            for step in topic_steps:
                other_topic_steps.add(_normalize_step_identity(step))
    filtered: list[str] = []
    for s in steps:
        if _normalize_step_identity(s) in other_topic_steps:
            continue
        filtered.append(s)
    return filtered



_FRICTION_TITLES = {
    "interruption": "Agent Interruption",
    "dismissive_tone": "Dismissive Agent Tone",
    "missing_acknowledgment": "Missing Acknowledgment",
    "none": "No Agent Friction",
}


def _friction_title(dissonance_type: str | None) -> str:
    key = (dissonance_type or "none").strip().lower().replace("-", "_").replace(" ", "_")
    return _FRICTION_TITLES.get(key, "Agent Friction")


# A diagnosed friction must be anchored to something the AGENT actually said.
# This guards against the friction LLM over-detecting on clean calls (e.g.
# inferring "interruption" from a frustrated-but-well-handled customer).
_FRICTION_GROUNDING_MIN_OVERLAP = 0.5


def _agent_turn_texts(conversation_text: str) -> list[str]:
    texts: list[str] = []
    for line in (conversation_text or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("agent:"):
            texts.append(stripped.split(":", 1)[1].strip())
    return texts


_POLICY_QUOTE_MIN_OVERLAP = 0.5


def _quote_anchored_in_policy(quote: str, policy_text: str) -> bool:
    """True if a quote is verbatim-contained in, or strongly overlaps, the policy."""
    normalized = _normalize_for_match(quote)
    if len(normalized.split()) < 3:
        return False
    if normalized in _normalize_for_match(policy_text):
        return True
    return any(
        _token_overlap_ratio(quote, segment) >= _POLICY_QUOTE_MIN_OVERLAP
        for segment in _split_sentences(policy_text)
    )


def _customer_turn_texts(conversation_text: str) -> list[str]:
    texts: list[str] = []
    for line in (conversation_text or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("customer:"):
            texts.append(stripped.split(":", 1)[1].strip())
    return texts


def _friction_grounded_in_agent_turns(
    result: EmotionShiftAnalysis,
    conversation_text: str,
) -> bool:
    """Recall-safe grounding check for a diagnosed friction.

    Only returns False (suppress) when the model DID supply evidence and that
    evidence aligns to a CUSTOMER turn rather than any agent turn — the specific
    false-positive mode where the LLM cites the customer's own emotional line as
    "agent friction". When the model omits evidence entirely (a frequent Gemini
    habit) we do NOT suppress: absence of a quote is not proof of innocence, and
    over-suppressing there was wiping out real interruption/dismissive verdicts.
    """
    agent_turns = _agent_turn_texts(conversation_text)
    if not agent_turns:
        return True  # cannot verify without labelled turns; do not suppress

    # An explicit agent-speaker citation with text is sufficient grounding.
    if any(c.speaker == "agent" and (c.quote or "").strip() for c in (result.citations or [])):
        return True

    quotes = [q for q in (result.evidence_quotes or []) if len(_normalize_for_match(q).split()) >= 3]
    if not quotes:
        return True  # nothing to verify; keep the model's verdict

    agent_blob_norm = _normalize_for_match(" \n ".join(agent_turns))
    customer_turns = _customer_turn_texts(conversation_text)
    for quote in quotes:
        normalized = _normalize_for_match(quote)
        agent_overlap = (
            1.0 if normalized in agent_blob_norm
            else max((_token_overlap_ratio(quote, turn) for turn in agent_turns), default=0.0)
        )
        if agent_overlap >= _FRICTION_GROUNDING_MIN_OVERLAP:
            return True
        customer_overlap = max((_token_overlap_ratio(quote, turn) for turn in customer_turns), default=0.0)
        # Only this quote is customer-aligned; keep scanning the rest.
        if agent_overlap >= customer_overlap:
            # Ambiguous (not clearly customer-sourced) — don't suppress on it.
            return True
    # Every usable quote aligned better to the customer than to any agent turn.
    return False


def _log_step(interaction_id: UUID | str, step: str, **kwargs) -> None:
    extra = {"interaction_id": str(interaction_id), "pipeline_step": step, **kwargs}
    logger.info("LLM trigger pipeline step: %s", step, extra=extra)


def _candidate_rag_roots() -> list[Path]:
    """
    Return possible parents that contain the ``rag`` package, ordered by preference.

    1) ``/app`` in the Docker container (services/rag is bind-mounted at /app/rag).
    2) Repo-relative ``services/`` from this source file (local dev / pytest).
    """
    here = Path(__file__).resolve()
    return [
        Path("/app"),
        here.parents[3] / "services",
    ]


def _ensure_rag_on_path() -> None:
    """Append the first parent that actually contains ``rag/evaluator.py`` to sys.path."""
    for root in _candidate_rag_roots():
        if (root / "rag" / "evaluator.py").exists():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.append(root_str)
            return


def _get_policy_compliance_evaluator():
    """
    Lazily load the transcript-level PolicyComplianceEvaluator from services/rag.

    This keeps the trigger pipeline explicit about layer boundaries:
      - retrieval/context + transcript-level compliance report are handled by
        the dedicated evaluator module,
      - claim-level checks stay in the local NLI checker.
    """
    global _policy_compliance_evaluator
    if _policy_compliance_evaluator is not None:
        return _policy_compliance_evaluator
    with _evaluator_lock:
        if _policy_compliance_evaluator is not None:
            return _policy_compliance_evaluator
        try:
            _ensure_rag_on_path()
            from rag.evaluator import PolicyComplianceEvaluator
            _policy_compliance_evaluator = PolicyComplianceEvaluator()
        except Exception as exc:
            logger.warning("Unable to initialize PolicyComplianceEvaluator: %s", exc)
            _policy_compliance_evaluator = None
        return _policy_compliance_evaluator


@dataclass
class TranscriptWindow:
    window_id: str
    start_index: int
    end_index: int
    start_seconds: float
    end_seconds: float
    text: str


@dataclass
class ResolvedPolicyContext:
    text: str
    version: str | None = None
    effective_at: str | None = None
    category: str | None = None
    conflict_resolution_applied: bool = False
    retrieval_failed: bool = False


def _join_retrieved_chunk_text(chunks: list[RetrievedChunk]) -> str:
    return "\n\n---\n\n".join(chunk.text.strip() for chunk in chunks if chunk.text.strip())


def _policy_chunk_reference(chunk: RetrievedChunk) -> str:
    header_path = " > ".join(
        str(chunk.metadata.get(key)).strip()
        for key in ("Header 1", "Header 2", "Header 3")
        if chunk.metadata.get(key)
    )
    return header_path or str(chunk.metadata.get("source_file") or chunk.metadata.get("doc_id") or "retrieved-policy")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _sanitize_for_prompt(text: str, max_length: int = 4000) -> str:
    sanitized = (text or "").strip()
    sanitized = re.sub(r"(?i)^system\s*:", "[system]:", sanitized, flags=re.MULTILINE)
    sanitized = re.sub(r"(?i)^assistant\s*:", "[assistant]:", sanitized, flags=re.MULTILINE)
    sanitized = re.sub(r"(?i)^human\s*:", "[human]:", sanitized, flags=re.MULTILINE)
    sanitized = re.sub(r"(?i)^user\s*:", "[user]:", sanitized, flags=re.MULTILINE)
    sanitized = re.sub(r"```", "` ", sanitized)
    return _truncate_text(sanitized, max_length)


def _normalize_acoustic_label(label: str) -> str:
    base = (label or "neutral").strip().lower()
    return EMOTION_NORMALIZATION.get(base, base or "neutral")


def _emotion_polarity(label: str) -> str:
    normalized = _normalize_acoustic_label(label)
    if normalized in {"happy", "grateful"}:
        return "positive"
    if normalized in {"neutral", "unknown"}:
        return "neutral"
    if normalized in {"angry", "frustrated", "sad"}:
        return "negative"
    return "neutral"



def _detect_topic_from_sop_chunks(chunks: list[RetrievedChunk]) -> str | None:
    if not chunks:
        return None

    source_text = " ".join(
        str(value)
        for chunk in chunks
        for value in (
            chunk.metadata.get("source_file"),
            chunk.metadata.get("doc_id"),
            chunk.metadata.get("Header 1"),
            chunk.metadata.get("Header 2"),
            chunk.metadata.get("Header 3"),
            chunk.reference,
            chunk.provenance,
        )
        if value
    ).lower()

    # Hints derived from the actual SOP source_file names ingested for nexalink + meridian.
    # Order matters: more-specific patterns first so e.g. fraud_investigation outranks billing.
    # Accept both '_' and '-' separators so legacy filenames (e.g. "01-refund-request-processing")
    # and the canonical ingestion names ("SOP_01_refund_request_processing") both match.
    hint_map = (
        ("fraud_dispute", ("sop_03_fraud_investigation", "fraud-investigation", "card fraud", "reg e dispute", "card_fraud", "reg_e_dispute", "reg-e-dispute")),
        ("aml_review", ("sop_05_aml_bsa_reporting", "aml-bsa-reporting", "aml", "bsa", "money laundering")),
        ("account_opening", ("sop_01_account_opening_kyc", "account-opening-kyc", "kyc", "account opening", "account_opening")),
        ("wire_transfer", ("wire_transfer", "wire transfer", "wire-transfer", "wire_transfer_verification", "enhanced verification wire")),
        ("account_signers", ("account_signers", "authorized signer", "signer change", "business_account_signers")),
        ("fee_adjustment", ("fee waiver", "fee_waiver", "fee-waiver", "overdraft", "bnk-sop-04")),
        ("retention", ("sop_05_customer_retention_cancellation", "customer-retention-cancellation", "account_closure_retention", "account-closure-retention", "retention", "cancellation")),
        ("account_access", ("sop_04_account_access_recovery", "account-access-recovery", "account access", "account_access", "2fa", "pin reset")),
        ("technical_support", ("sop_03_technical_support_troubleshooting", "technical-support-troubleshooting", "technical support", "technical_support")),
        ("refund_request", ("sop_01_refund_request_processing", "refund-request-processing", "refund request", "refund_request", "01-refund", "01_refund")),
        ("billing_issue", ("sop_02_billing_issue_resolution", "billing-issue-resolution", "billing issue", "billing_issue", "02-billing", "02_billing")),
    )
    for topic, hints in hint_map:
        if any(hint in source_text for hint in hints):
            return topic
    return None


# Topic → SOP source_file fragments to prefer. Each value is a list of substring
# tokens; a chunk is "on-topic" if any token appears in the chunk's source_file
# (lowercased). When at least one chunk matches the topic, off-topic chunks are
# dropped from the SOP context fed to the LLM — this fixes the "wrong SOP cited"
# class of failures where the dense retriever ranks the retention SOP above the
# refund SOP because the customer used the word "credit".
_TOPIC_TO_SOP_FILE_TOKENS: dict[str, tuple[str, ...]] = {
    "refund_request": ("refund_request_processing",),
    "billing_issue": ("billing_issue_resolution",),
    "technical_support": ("technical_support_troubleshooting",),
    "account_access": ("account_access_recovery",),
    "retention": ("customer_retention_cancellation", "account_closure_retention"),
    "account_opening": ("account_opening_kyc",),
    "fraud_dispute": ("fraud_investigation", "reg_e_dispute_resolution"),
    "fee_adjustment": ("account_closure_retention", "billing_issue_resolution"),
    "aml_review": ("aml_bsa_reporting",),
    "wire_transfer": ("wire_transfer", "wire transfer"),
    "account_signers": ("authorized signer", "signer change"),
}


def _filter_chunks_by_topic(
    chunks: list[RetrievedChunk], topic: str | None
) -> list[RetrievedChunk]:
    """Return only chunks whose source_file matches the topic. If none match, return original list."""
    if not chunks or not topic:
        return chunks
    tokens = _TOPIC_TO_SOP_FILE_TOKENS.get(topic) or ()
    if not tokens:
        return chunks
    on_topic = [
        chunk
        for chunk in chunks
        if any(tok in str(chunk.metadata.get("source_file") or "").lower() for tok in tokens)
    ]
    return on_topic or chunks


def _extract_sop_steps(retrieved_sop: str) -> list[str]:
    steps: list[str] = []
    for line in retrieved_sop.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if raw.startswith("#") or raw.startswith("<!--"):
            continue
        if "|" in raw:
            continue

        if not re.match(r"^(?:[-*]|\d+[.)])\s+", raw):
            if not raw.lower().startswith("step "):
                continue

        cleaned = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", raw).strip()
        if not cleaned:
            continue
        if len(cleaned.split()) >= 3 and len(cleaned) <= 120:
            steps.append(cleaned)
    return steps[:5]



def _split_sentences(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]



def _truncate_text(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    trimmed = normalized[:max_chars].rsplit(" ", 1)[0].strip()
    return trimmed or normalized[:max_chars].strip()



def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


def _policy_priority(category: str | None) -> int:
    normalized = (category or "").strip().lower()
    for idx, prefix in enumerate(POLICY_PRIORITY_BUCKETS):
        if normalized.startswith(prefix):
            return idx
    return len(POLICY_PRIORITY_BUCKETS)


def _iso_or_none(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.isoformat()



def _has_mapped_transcript_citation(citations: list[EvidenceCitation]) -> bool:
    return any(
        c.source == "transcript"
        and c.utterance_index is not None
        and bool((c.quote or "").strip())
        for c in citations
    )


def _backfill_transcript_citation_indices(
    citations: list[EvidenceCitation],
    utterances: list[Utterance],
) -> None:
    normalized_utterances: list[tuple[int, str, str]] = []
    for utterance in utterances:
        text = (utterance.text or "").strip()
        if not text:
            continue
        normalized = _normalize_for_match(text)
        if not normalized:
            continue
        role = utterance.speaker_role.value if utterance.speaker_role else "unknown"
        normalized_utterances.append((utterance.sequence_index, normalized, role))

    for citation in citations:
        if citation.source != "transcript" or citation.utterance_index is not None:
            continue
        quote_norm = _normalize_for_match(citation.quote)
        if not quote_norm:
            continue
        for sequence_index, utterance_norm, speaker in normalized_utterances:
            if quote_norm in utterance_norm or utterance_norm in quote_norm:
                citation.utterance_index = sequence_index
                if citation.speaker == "unknown":
                    citation.speaker = speaker  # type: ignore[assignment]
                break


async def _resolve_active_policy_context(
    session: AsyncSession,
    organization_id: UUID,
    ground_truth_policy: str,
    fallback_sop: str,
    query_text: str,
    org_filter: str | None,
) -> ResolvedPolicyContext:
    """
    Resolve the single policy context used by the claim-level NLI check.

    Retrieval happens here, but judgment does not: the returned text is later
    passed to ``run_single_claim_nli_policy_check`` for entailment-style
    classification.
    """
    if ground_truth_policy.strip():
        return ResolvedPolicyContext(
            text=ground_truth_policy.strip(),
            version="manual-override",
            category="override",
            conflict_resolution_applied=False,
        )

    retrieval_query = query_text.strip() or fallback_sop.strip()
    retrieval_failed = False
    if retrieval_query:
        try:
            retrieved_policy_chunks = retrieve_policy_chunks(
                query_text=retrieval_query,
                org_filter=org_filter,
                top_k=2,
            )
        except Exception:
            retrieval_failed = True
            logger.warning(
                "Policy retrieval failed [org=%s query_len=%d]",
                org_filter or "<none>",
                len(retrieval_query),
                exc_info=True,
            )
            retrieved_policy_chunks = []

        if retrieved_policy_chunks:
            primary_chunk = retrieved_policy_chunks[0]
            primary_source = str(
                primary_chunk.metadata.get("source_file")
                or primary_chunk.metadata.get("doc_id")
                or ""
            ).strip()
            contextual_chunks = [
                chunk
                for chunk in retrieved_policy_chunks
                if not primary_source
                or str(chunk.metadata.get("source_file") or chunk.metadata.get("doc_id") or "").strip() == primary_source
            ] or [primary_chunk]
            primary_reference = _policy_chunk_reference(primary_chunk)
            reference_basis = str(primary_chunk.metadata.get("source_file") or primary_chunk.metadata.get("doc_id") or primary_reference)
            unique_references = {_policy_chunk_reference(chunk) for chunk in contextual_chunks}
            return ResolvedPolicyContext(
                text=_join_retrieved_chunk_text(contextual_chunks),
                version=f"retrieved:{reference_basis}",
                category=str(primary_chunk.metadata.get("doc_type") or primary_chunk.metadata.get("category") or "retrieved"),
                conflict_resolution_applied=len(unique_references) > 1,
                retrieval_failed=False,
            )

    stmt = (
        select(
            CompanyPolicy.id,
            CompanyPolicy.policy_category,
            CompanyPolicy.policy_text,
            CompanyPolicy.updated_at,
            CompanyPolicy.created_at,
        )
        .join(OrganizationPolicy, OrganizationPolicy.policy_id == CompanyPolicy.id)
        .where(
            OrganizationPolicy.organization_id == organization_id,
            OrganizationPolicy.is_active == True,  # noqa: E712
            CompanyPolicy.is_active == True,  # noqa: E712
        )
    )
    rows = list((await session.exec(stmt)).all())

    if not rows:
        text = fallback_sop.strip() or "No ground truth policy context provided."
        return ResolvedPolicyContext(
            text=text,
            version="fallback",
            category="fallback",
            retrieval_failed=retrieval_failed,
        )

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            _policy_priority(row.policy_category),
            -(row.updated_at or row.created_at).timestamp(),
        ),
    )
    selected = sorted_rows[0]
    categories = {str(row.policy_category or "").lower() for row in rows}
    conflict_applied = len(rows) > 1 and len(categories) > 1
    version_basis = selected.updated_at or selected.created_at
    version_token = f"{selected.id}:{version_basis.date().isoformat()}" if version_basis else str(selected.id)

    return ResolvedPolicyContext(
        text=(selected.policy_text or "").strip() or (fallback_sop.strip() or "No ground truth policy context provided."),
        version=version_token,
        effective_at=_iso_or_none(version_basis),
        category=selected.policy_category,
        conflict_resolution_applied=conflict_applied,
        retrieval_failed=retrieval_failed,
    )


def _format_timestamp(seconds: float) -> str:
    seconds_int = max(0, int(seconds))
    return f"{seconds_int // 60:02d}:{seconds_int % 60:02d}"


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _utterance_speaker(utterance: Utterance | None) -> str:
    if not utterance or not utterance.speaker_role:
        return "unknown"
    return utterance.speaker_role.value


def _find_utterance_by_index(
    utterances: list[Utterance],
    utterance_index: int | None,
) -> Utterance | None:
    if utterance_index is None:
        return None
    for utterance in utterances:
        if utterance.sequence_index == utterance_index:
            return utterance
    return None


def _extract_reference_label(text: str, fallback: str) -> str:
    for raw_line in text.splitlines():
        line = _clean_display_text(raw_line)
        if not line:
            continue
        bracket_match = re.match(r"^\[(.+?)\]$", line)
        if bracket_match:
            return bracket_match.group(1).strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
        return line[:120]
    return fallback


def _clean_display_text(text: str | None) -> str:
    cleaned = (text or "").replace("\r", "")
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("â€¢", " / ").replace("Ã¢â‚¬Â¢", " / ")
    cleaned = re.sub(r"\b(image|table)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[_]{2,}", "_", cleaned)
    cleaned = re.sub(r"[-|]{4,}", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _extract_display_clause(text: str, max_chars: int = 260) -> str:
    preferred_lines: list[str] = []
    fallback_lines: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_display_text(raw_line)
        if not line:
            continue
        if re.match(r"^\[.+\]$", line):
            continue
        lowered = line.lower()
        if lowered.endswith(".pdf") or lowered in {
            "overview",
            "organization:",
            "version:",
            "effective date:",
            "step-by-step procedure",
            "related policies",
            "key considerations",
            "eligibility criteria",
        }:
            continue
        fallback_lines.append(line)
        if line.lower().startswith(("step ", "compliance:", "note:", "forbidden", "quote the correct timeline", "offer ", "provide ", "verify ", "apply ", "escalate ")):
            preferred_lines.append(line)

    candidate_lines = preferred_lines or fallback_lines
    if not candidate_lines:
        return _truncate_text(_clean_display_text(text), max_chars) or "No clause available."

    snippet = " ".join(candidate_lines[:2])
    return _truncate_text(snippet, max_chars) or "No clause available."


def _span_from_citation(
    citation: EvidenceCitation | None,
    utterances: list[Utterance],
) -> EvidenceSpan | None:
    if not citation or not (citation.quote or "").strip():
        return None

    utterance = _find_utterance_by_index(utterances, citation.utterance_index)
    speaker = citation.speaker
    if speaker == "unknown" and utterance:
        speaker = _utterance_speaker(utterance)  # type: ignore[assignment]

    start_seconds = utterance.start_time_seconds if utterance else None
    end_seconds = utterance.end_time_seconds if utterance else None

    return EvidenceSpan(
        utterance_index=citation.utterance_index,
        speaker=speaker,
        quote=citation.quote.strip(),
        timestamp=_format_timestamp(start_seconds) if start_seconds is not None else None,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )


def _best_citation(
    citations: list[EvidenceCitation],
    source: str,
    speaker: str | None = None,
) -> EvidenceCitation | None:
    for citation in citations:
        if citation.source != source:
            continue
        if speaker and citation.speaker != speaker:
            continue
        if (citation.quote or "").strip():
            return citation
    return None


def _supporting_quotes(citations: list[EvidenceCitation], limit: int = 3) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        quote = (citation.quote or "").strip()
        if not quote or quote in seen:
            continue
        seen.add(quote)
        quotes.append(quote)
        if len(quotes) >= limit:
            break
    return quotes


def _best_retrieved_chunk(chunks: list[RetrievedChunk], query_text: str) -> RetrievedChunk | None:
    if not chunks:
        return None
    return max(
        chunks,
        key=lambda chunk: (
            float(chunk.score) if chunk.score is not None else -1.0,
            _token_overlap_ratio(query_text, chunk.text),
            len(chunk.text),
        ),
    )


def _chunk_source_key(chunk: RetrievedChunk | None) -> str:
    if not chunk:
        return ""
    return str(chunk.metadata.get("source_file") or chunk.metadata.get("doc_id") or "").strip().lower()


def _filter_chunks_by_policy_context(
    chunks: list[RetrievedChunk],
    policy_context: ResolvedPolicyContext,
) -> list[RetrievedChunk]:
    version = (policy_context.version or "").strip()
    if not version.startswith("retrieved:"):
        return chunks
    expected_key = version.split("retrieved:", 1)[1].strip().lower()
    if not expected_key:
        return chunks
    filtered = [chunk for chunk in chunks if expected_key in _chunk_source_key(chunk)]
    return filtered or chunks


def _build_policy_reference(
    citation: EvidenceCitation | None,
    *,
    source_kind: str,
    source_text: str,
    fallback_reference: str,
    doc_type: str | None = None,
    doc_id: str | None = None,
    rule_id: str | None = None,
    step_number: str | None = None,
    severity: str | None = None,
    policy_ref: list[str] | None = None,
    version: str | None = None,
    category: str | None = None,
    provenance: str | None = None,
) -> PolicyReference | None:
    clause = ""
    if citation and (citation.quote or "").strip():
        clause = _clean_display_text(citation.quote)
    if not clause:
        clause = _extract_display_clause(source_text)
    if not clause:
        return None

    return PolicyReference(
        source=source_kind,  # type: ignore[arg-type]
        reference=_clean_display_text(_extract_reference_label(source_text, fallback_reference)),
        clause=clause,
        doc_type=doc_type if doc_type in {"policy", "sop", "kb"} else source_kind,  # type: ignore[arg-type]
        doc_id=doc_id,
        rule_id=rule_id,
        step_number=step_number,
        severity=severity,
        policy_ref=policy_ref or [],
        version=version,
        category=category,
        provenance=_clean_display_text(provenance),
    )


def _build_policy_reference_from_chunk(
    chunk: RetrievedChunk | None,
    *,
    source_kind: str,
    fallback_text: str,
    fallback_reference: str,
    version: str | None = None,
    category: str | None = None,
) -> PolicyReference | None:
    if chunk and chunk.text.strip():
        clause = _extract_display_clause(chunk.text)
        chunk_doc_type = chunk.metadata.get("doc_type")
        policy_ref = chunk.metadata.get("policy_ref") or []
        if isinstance(policy_ref, str):
            policy_ref = [item.strip() for item in policy_ref.split(",") if item.strip()]
        # Prefer the SOP/policy file name + section header for the human-readable
        # reference label. The previous _extract_reference_label fallback used
        # the chunk's first non-blank line, which for table-heavy SOPs returned
        # raw markdown like '| Field | Value |' and made the citation unusable.
        source_file = (chunk.metadata.get("source_file") or "").strip()
        section_header = ""
        for hkey in ("Header 1", "Header 2", "Header 3"):
            val = chunk.metadata.get(hkey)
            if val:
                section_header = str(val).strip()
                break
        if source_file and section_header:
            reference_label = f"{source_file} — {section_header}"
        elif source_file:
            reference_label = source_file
        else:
            reference_label = _clean_display_text(
                _extract_reference_label(chunk.text, chunk.reference or fallback_reference)
            )
        return PolicyReference(
            source=source_kind,  # type: ignore[arg-type]
            reference=reference_label,
            clause=clause or _truncate_text(_clean_display_text(chunk.text), 220),
            doc_type=chunk_doc_type if chunk_doc_type in {"policy", "sop", "kb"} else source_kind,  # type: ignore[arg-type]
            doc_id=chunk.metadata.get("doc_id"),
            rule_id=chunk.metadata.get("rule_id"),
            step_number=chunk.metadata.get("step_number"),
            severity=chunk.metadata.get("severity"),
            policy_ref=policy_ref if isinstance(policy_ref, list) else [],
            version=version,
            category=category,
            provenance=_clean_display_text(chunk.provenance or chunk.collection or chunk.source),
        )
    return _build_policy_reference(
        None,
        source_kind=source_kind,
        source_text=fallback_text,
        fallback_reference=fallback_reference,
        doc_type=source_kind,
        policy_ref=[],
        version=version,
        category=category,
        provenance=None,
    )


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens.intersection(right_tokens)) / len(left_tokens.union(right_tokens))


def _emotion_signal_confidence(
    span: EvidenceSpan | None,
    utterances: list[Utterance],
) -> float | None:
    acoustic_confidence: float | None = None
    if span and span.utterance_index is not None:
        utterance = _find_utterance_by_index(utterances, span.utterance_index)
        if utterance and utterance.emotion_confidence is not None:
            acoustic_confidence = float(utterance.emotion_confidence)

    text_confidence: float | None = None
    if span and span.quote.strip():
        _label, text_confidence = _model_call("text_emotion", infer_text_emotion_with_provider, span.quote)

    available = [score for score in [acoustic_confidence, text_confidence] if score is not None]
    if not available:
        return None
    return _clamp_unit(sum(available) / len(available))


def _select_step_citation(
    citations: list[EvidenceCitation],
    step: str,
) -> EvidenceCitation | None:
    transcript_citations = [citation for citation in citations if citation.source == "transcript"]
    if not transcript_citations:
        return None
    best = max(
        transcript_citations,
        key=lambda citation: _token_overlap_ratio(step, citation.quote),
    )
    if _token_overlap_ratio(step, best.quote) < 0.08:
        return None
    return best


def _map_nli_verdict(category: str, insufficient_evidence: bool = False) -> str:
    if insufficient_evidence:
        return "Insufficient Evidence"
    normalized = (category or "").strip().lower()
    if normalized == "entailment":
        return "Supported"
    if normalized == "contradiction":
        return "Contradiction"
    if normalized == "policy hallucination":
        return "Contradiction"
    if normalized == "benign deviation":
        return "Neutral"
    return "Neutral"


def _build_emotion_trigger_attribution(
    emotion_shift: EmotionShiftAnalysis,
    utterances: list[Utterance],
    acoustic_emotion: str,
) -> TriggerAttribution:
    transcript_citation = _best_citation(emotion_shift.citations, "transcript", speaker="customer") or _best_citation(
        emotion_shift.citations,
        "transcript",
    )
    span = _span_from_citation(transcript_citation, utterances)
    verdict = (
        "Insufficient Evidence"
        if emotion_shift.insufficient_evidence
        else "Cross-Modal Mismatch"
        if emotion_shift.is_dissonance_detected
        else "No Trigger"
    )
    evidence_chain = [
        f"Acoustic emotion signal resolved to {acoustic_emotion}.",
        f"Transcript span used for review: {(span.quote if span else 'No mapped transcript span was available.')}",
        emotion_shift.root_cause,
    ]

    return TriggerAttribution(
        attribution_id="emotion-dissonance",
        family="emotion",
        trigger_type="Acoustic-Transcript Dissonance",
        title=_friction_title(emotion_shift.dissonance_type),
        verdict=verdict,  # type: ignore[arg-type]
        confidence=emotion_shift.confidence_score or _emotion_signal_confidence(span, utterances),
        evidence_span=span,
        reasoning=emotion_shift.root_cause,
        evidence_chain=evidence_chain,
        supporting_quotes=emotion_shift.evidence_quotes or _supporting_quotes(emotion_shift.citations),
    )


EMOTION_TRANSITION_MIN_CONFIDENCE = 0.55
EMOTION_TRANSITION_MAX_CARDS = 3


def _build_emotion_transition_attributions(
    utterances: list[Utterance],
) -> list[TriggerAttribution]:
    """
    Emit only polarity-crossing emotion transitions per speaker.

    Rationale: emitting one card for every consecutive emotion label change
    floods the explainability deck with "No Trigger" / "Neutral" entries that
    carry no review value. We surface only meaningful arc shifts
    (positive↔negative) above a confidence threshold, capped at a small number
    so the deck stays scannable.
    """
    candidates: list[tuple[float, Utterance, Utterance, str, str, str]] = []
    previous_by_speaker: dict[str, Utterance] = {}

    for utterance in utterances:
        if not (utterance.text or "").strip():
            continue
        speaker = _utterance_speaker(utterance)
        previous = previous_by_speaker.get(speaker)
        previous_by_speaker[speaker] = utterance
        if previous is None:
            continue

        before = _normalize_acoustic_label(previous.emotion or "neutral")
        after = _normalize_acoustic_label(utterance.emotion or "neutral")
        if before == after:
            continue

        before_polarity = _emotion_polarity(before)
        after_polarity = _emotion_polarity(after)
        if before_polarity == after_polarity:
            continue
        if "neutral" in (before_polarity, after_polarity):
            continue

        confidence = _clamp_unit(float(utterance.emotion_confidence or 0.0))
        if confidence < EMOTION_TRANSITION_MIN_CONFIDENCE:
            continue

        candidates.append((confidence, previous, utterance, speaker, before, after))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[:EMOTION_TRANSITION_MAX_CARDS]
    selected.sort(key=lambda item: item[2].sequence_index)

    attributions: list[TriggerAttribution] = []
    for confidence, previous, utterance, speaker, before, after in selected:
        span = EvidenceSpan(
            utterance_index=utterance.sequence_index,
            speaker=speaker,  # type: ignore[arg-type]
            quote=(utterance.text or "").strip(),
            timestamp=_format_timestamp(utterance.start_time_seconds or 0.0),
            start_seconds=utterance.start_time_seconds,
            end_seconds=utterance.end_time_seconds,
        )
        direction = "improved" if _emotion_polarity(after) == "positive" else "deteriorated"
        evidence_chain = [
            f"{speaker.title()} emotion {direction}: {before} → {after}.",
            f"Previous span: {(previous.text or '').strip() or 'No prior span available.'}",
            f"Current span: {(utterance.text or '').strip()}",
        ]
        reasoning = (
            f"{speaker.title()} emotion {direction} from {before} to {after} at {span.timestamp}, "
            "crossing emotional polarity above the noise threshold."
        )
        verdict = "Cross-Modal Mismatch" if direction == "deteriorated" else "Neutral"
        attributions.append(
            TriggerAttribution(
                attribution_id=f"emotion-change-{speaker}-{utterance.sequence_index}",
                family="emotion",
                trigger_type="Emotion Polarity Shift",
                title=f"{speaker.title()} emotion: {before} → {after}",
                verdict=verdict,  # type: ignore[arg-type]
                confidence=confidence,
                evidence_span=span,
                reasoning=reasoning,
                evidence_chain=evidence_chain,
                supporting_quotes=[
                    quote
                    for quote in [
                        (previous.text or "").strip(),
                        (utterance.text or "").strip(),
                    ]
                    if quote
                ],
            )
        )

    return attributions


def _build_process_trigger_attributions(
    process_adherence: ProcessAdherenceReport,
    utterances: list[Utterance],
    sop_context: str,
    sop_chunks: list[RetrievedChunk],
) -> list[TriggerAttribution]:
    if not process_adherence.missing_sop_steps:
        return []

    attributions: list[TriggerAttribution] = []
    for index, step in enumerate(process_adherence.missing_sop_steps, start=1):
        transcript_citation = _select_step_citation(process_adherence.citations, step)
        span = _span_from_citation(transcript_citation, utterances)
        overlap = _token_overlap_ratio(step, transcript_citation.quote if transcript_citation else "")
        sop_citation = _best_citation(process_adherence.citations, "sop")
        best_sop_chunk = _best_retrieved_chunk(sop_chunks, step)
        policy_reference = _build_policy_reference_from_chunk(
            best_sop_chunk,
            source_kind="sop",
            fallback_text=sop_citation.quote if sop_citation else sop_context,
            fallback_reference="Retrieved SOP",
        )
        verdict = "Partial Attempt" if overlap >= 0.18 else "Contradiction"
        evidence_chain = [
            f"Expected SOP step: {step}.",
            f"Closest transcript evidence: {(span.quote if span else 'No matching utterance span was recovered.')}",
            process_adherence.justification,
        ]
        reasoning = (
            f"The review looked for explicit execution of the SOP step '{step}'. "
            f"{('A nearby transcript span was found but did not fully satisfy the step. ' if span else 'No reliable transcript span matched this step. ')}"
            f"{process_adherence.justification}"
        )

        attributions.append(
            TriggerAttribution(
                attribution_id=f"sop-step-{index}",
                family="sop",
                trigger_type="SOP Violation",
                title=step,
                verdict=verdict,  # type: ignore[arg-type]
                confidence=process_adherence.confidence_score or (best_sop_chunk.score if best_sop_chunk else None),
                evidence_span=span,
                policy_reference=PolicyReference.model_validate(policy_reference.model_dump()) if policy_reference else None,
                reasoning=reasoning,
                evidence_chain=evidence_chain,
                supporting_quotes=[quote for quote in [span.quote if span else None, step] if quote],
            )
        )

    return attributions



def _build_claim_provenance_cards(
    nli_policy: NLIEvaluation,
    utterances: list[Utterance],
    policy_context: ResolvedPolicyContext,
    agent_statement: str,
    policy_chunks: list[RetrievedChunk],
    org_filter: str | None,
) -> list[ClaimProvenance]:
    """
    Build claim provenance cards.

    Always emits at least one card when an agent statement and any policy
    context exist, so the UI's "Retrieval Provenance Scoring" deck does not
    silently render empty.
    """
    claim_citations = [
        citation
        for citation in nli_policy.citations
        if citation.source == "transcript" and citation.speaker in {"agent", "unknown"}
    ]
    if not claim_citations and (agent_statement or "").strip():
        claim_citations = [
            EvidenceCitation(
                source="transcript",
                speaker="agent",
                quote=_truncate_text(agent_statement, 220),
            )
        ]

    cards: list[ClaimProvenance] = []
    verdict = _map_nli_verdict(nli_policy.nli_category, nli_policy.insufficient_evidence)
    policy_citation = _best_citation(nli_policy.citations, "policy")
    fallback_policy_text = (
        (policy_citation.quote if policy_citation else None)
        or policy_context.text
        or ""
    )
    for index, citation in enumerate(claim_citations[:2], start=1):
        span = _span_from_citation(citation, utterances)
        claim_text = (citation.quote or "").strip()
        per_claim_chunks: list[RetrievedChunk] = []
        if claim_text:
            try:
                per_claim_chunks = retrieve_policy_chunks(
                    query_text=claim_text,
                    org_filter=org_filter,
                    top_k=2,
                )
            except Exception:
                logger.warning(
                    "Per-claim policy retrieval failed [org=%s claim_len=%d claim_index=%d]",
                    org_filter or "<none>",
                    len(claim_text),
                    index,
                    exc_info=True,
                )
                per_claim_chunks = []
        candidate_chunks = _filter_chunks_by_policy_context(
            per_claim_chunks or policy_chunks,
            policy_context,
        )
        best_policy_chunk = _best_retrieved_chunk(candidate_chunks, claim_text)
        similarity = (
            _clamp_unit(best_policy_chunk.score)
            if best_policy_chunk and best_policy_chunk.score is not None
            else None
        )
        policy_reference = _build_policy_reference_from_chunk(
            best_policy_chunk,
            source_kind="policy",
            fallback_text=fallback_policy_text,
            fallback_reference=f"{policy_context.category or 'Policy'} reference",
            version=policy_context.version,
            category=policy_context.category,
        )
        if not policy_reference:
            # Always anchor the claim to *some* policy reference so the
            # "Retrieval Provenance Scoring" deck is never empty — even when
            # vector retrieval is degraded (e.g. embedding service offline) and
            # only the NLI justification is available.
            clause = (
                _clean_display_text(fallback_policy_text)
                or _clean_display_text(nli_policy.justification)
                or "No policy context could be retrieved for this claim (retrieval degraded)."
            )
            policy_reference = PolicyReference(
                source="policy",  # type: ignore[arg-type]
                reference=f"{policy_context.category or 'Policy'} reference",
                clause=_truncate_text(clause, 260) or "Active policy context",
                doc_type="policy",  # type: ignore[arg-type]
                policy_ref=[],
                version=policy_context.version,
                category=policy_context.category,
            )

        provenance = " | ".join(
            part
            for part in [
                policy_reference.reference,
                policy_reference.provenance,
            ]
            if part
        )

        cards.append(
            ClaimProvenance(
                claim_id=f"claim-{index}",
                claim_text=claim_text,
                claim_span=span,
                retrieved_policy=PolicyReference.model_validate(policy_reference.model_dump()),
                semantic_similarity=similarity,
                nli_verdict=verdict,  # type: ignore[arg-type]
                confidence=nli_policy.confidence_score,
                reasoning=nli_policy.justification,
                provenance=provenance or "Active policy context",
                supporting_quotes=[quote for quote in [claim_text, policy_reference.clause] if quote],
            )
        )

    return cards


def _build_explainability_layer(
    emotion_shift: EmotionShiftAnalysis,
    process_adherence: ProcessAdherenceReport,
    nli_policy: NLIEvaluation,
    utterances: list[Utterance],
    acoustic_emotion: str,
    sop_context: str,
    sop_chunks: list[RetrievedChunk],
    policy_context: ResolvedPolicyContext,
    policy_chunks: list[RetrievedChunk],
    agent_statement: str,
    org_filter: str | None,
) -> EvidenceAnchoredExplainability:
    trigger_attributions: list[TriggerAttribution] = [
        _build_emotion_trigger_attribution(
            emotion_shift=emotion_shift,
            utterances=utterances,
            acoustic_emotion=acoustic_emotion,
        )
    ]
    trigger_attributions.extend(_build_emotion_transition_attributions(utterances))
    trigger_attributions.extend(
        _build_process_trigger_attributions(
            process_adherence=process_adherence,
            utterances=utterances,
            sop_context=sop_context,
            sop_chunks=sop_chunks,
        )
    )

    return EvidenceAnchoredExplainability(
        trigger_attributions=trigger_attributions,
        claim_provenance=_build_claim_provenance_cards(
            nli_policy=nli_policy,
            utterances=utterances,
            policy_context=policy_context,
            policy_chunks=policy_chunks,
            agent_statement=agent_statement,
            org_filter=org_filter,
        ),
    )


def _reconstruct_transcript(utterances: list[Utterance]) -> str:
    lines: list[str] = []
    for utterance in utterances:
        if not utterance.text:
            continue
        role = utterance.speaker_role.value if utterance.speaker_role else "unknown"
        lines.append(f"{role}: {utterance.text}")
    return "\n".join(lines)


def _build_rolling_windows(
    utterances: list[Utterance],
    window_turns: int = ROLLING_WINDOW_TURNS,
    stride: int = ROLLING_WINDOW_STRIDE,
) -> list[TranscriptWindow]:
    if not utterances:
        return []

    window_turns = max(1, window_turns)
    stride = max(1, stride)
    windows: list[TranscriptWindow] = []
    index = 0

    for start in range(0, len(utterances), stride):
        end = min(start + window_turns, len(utterances))
        chunk = utterances[start:end]
        text = _reconstruct_transcript(chunk)
        if not text.strip():
            if end == len(utterances):
                break
            continue

        first = chunk[0]
        last = chunk[-1]
        windows.append(
            TranscriptWindow(
                window_id=f"W{index}",
                start_index=start,
                end_index=end - 1,
                start_seconds=first.start_time_seconds or 0.0,
                end_seconds=last.end_time_seconds or last.start_time_seconds or 0.0,
                text=text,
            )
        )
        index += 1

        if end >= len(utterances):
            break

    return windows


def _emotion_window_score(window: TranscriptWindow, utterances: list[Utterance]) -> tuple[float, int]:
    """Rank windows by the pipeline's (acoustic/fused) negative customer emotion signal."""
    negative_signal = sum(
        float(u.emotion_confidence or 0.0)
        for u in utterances[window.start_index : window.end_index + 1]
        if _utterance_speaker(u) == "customer" and _emotion_polarity(u.emotion or "neutral") == "negative"
    )
    return negative_signal, window.end_index


def _select_emotion_window(windows: list[TranscriptWindow], utterances: list[Utterance]) -> TranscriptWindow | None:
    if not windows:
        return None
    return max(windows, key=lambda window: _emotion_window_score(window, utterances))


def _select_process_windows(windows: list[TranscriptWindow], max_windows: int = MAX_PROCESS_WINDOWS) -> list[TranscriptWindow]:
    if len(windows) <= max_windows:
        return windows

    selected_indices: list[int] = [0, len(windows) - 1]
    if max_windows >= 3:
        selected_indices.insert(1, len(windows) // 2)

    selected = sorted(set(selected_indices))[:max_windows]
    return [windows[idx] for idx in selected]


def _render_window_bundle(windows: list[TranscriptWindow]) -> str:
    if not windows:
        return ""

    blocks: list[str] = []
    for window in windows:
        blocks.append(
            f"[{window.window_id}] turns {window.start_index}-{window.end_index} "
            f"({_format_timestamp(window.start_seconds)}-{_format_timestamp(window.end_seconds)})\n"
            f"{window.text}"
        )
    return "\n\n".join(blocks)



async def analyze_emotion_shift(
    agent_context: str,
    customer_text: str,
    acoustic_emotion: str,
    conversation_text: str = "",
) -> EmotionShiftAnalysis:
    """Diagnose agent friction with the emotion-shift LLM chain; LLM failures propagate."""
    inferred_emotion = _normalize_acoustic_label(acoustic_emotion)

    # Agent-behaviour friction is independent of the customer's emotion, so the
    # chain always runs on a real, speaker-labelled conversation.
    conversation = (conversation_text or "").strip()
    if len(conversation.split()) < 8:
        return EmotionShiftAnalysis(
            is_dissonance_detected=False,
            dissonance_type="None",
            root_cause="Conversation too short to assess agent friction.",
            counterfactual_correction="If the agent had continued the same supportive approach, the interaction likely would have remained stable.",
            current_customer_emotion=inferred_emotion,
            current_emotion_reasoning=INSUFFICIENT_EVIDENCE_LABEL,
            insufficient_evidence=True,
        )

    friction_agent_context = (
        f"{agent_context}\n\n"
        "Full conversation (speaker-labelled — analyze the AGENT turns for "
        "interruption, dismissive tone, or missing acknowledgment):\n"
        f"{conversation}"
    )
    result = await _run_chain(
        "emotion_shift",
        build_emotion_shift_chain,
        {
            "detected_emotion": acoustic_emotion,
            "agent_context": _sanitize_for_prompt(friction_agent_context, max_length=7000),
            "customer_text": _sanitize_for_prompt(customer_text),
            "acoustic_emotion": acoustic_emotion,
        },
    )
    result.is_dissonance_detected = result.dissonance_type.strip().lower() != "none"
    # Suppress ungrounded friction: if the model claims agent friction but cannot
    # back it with an agent-spoken quote, treat the call as friction-free so a
    # well-handled call is not penalized on the empathy axis.
    if result.is_dissonance_detected and not _friction_grounded_in_agent_turns(result, conversation):
        result.dissonance_type = "none"
        result.is_dissonance_detected = False
        result.root_cause = "No agent-grounded friction evidence; treated as no friction."
    if (
        not result.root_cause.strip()
        or not result.evidence_quotes
        or INSUFFICIENT_EVIDENCE_LABEL in result.root_cause.lower()
    ):
        result.root_cause = INSUFFICIENT_EVIDENCE_LABEL
    if not result.citations:
        result.citations = [
            EvidenceCitation(source="transcript", speaker="customer", quote=quote)
            for quote in result.evidence_quotes
        ]
    result.current_customer_emotion = inferred_emotion
    return result


async def classify_topic(transcript_text: str) -> str:
    """Classify the call into one RESOLUTION_GRAPHS topic (or UNKNOWN_TOPIC) with the fast LLM stage."""
    result = await _run_chain(
        "topic_classification",
        build_topic_classification_chain,
        {"transcript_text": _sanitize_for_prompt(transcript_text, max_length=6000)},
    )
    return result.topic


def _resolve_step_labels(step_keys: list[str], expected_steps: list[str]) -> list[str]:
    """Map LLM step_key outputs back to human-readable step labels."""
    labels = {**STEP_KEY_TO_LABEL, **{_step_key(step): step for step in expected_steps}}
    resolved: list[str] = []
    for key in step_keys:
        label = labels.get(_step_key(key), key)
        if label not in resolved:
            resolved.append(label)
    return resolved


def _reference_sop_citation(chunks: list[RetrievedChunk]) -> EvidenceCitation:
    primary = chunks[0]
    source_file = (primary.metadata.get("source_file") or "").strip()
    header_parts = " > ".join(
        str(primary.metadata.get(k)).strip()
        for k in ("Header 1", "Header 2", "Header 3")
        if primary.metadata.get(k)
    )
    label = f"{source_file} — {header_parts}" if source_file and header_parts else (source_file or "Retrieved SOP")
    return EvidenceCitation(source="sop", speaker="system", quote=f"[Reference SOP] {label}")


async def evaluate_process_adherence(
    transcript_text: str,
    retrieved_sop_from_pinecone: str,
    org_filter: str | None = None,
    retrieved_sop_chunks: list[RetrievedChunk] | None = None,
    full_transcript_text: str | None = None,
    topic: str | None = None,
) -> ProcessAdherenceReport:
    """SOP adherence judged by the LLM; topic comes from ``classify_topic`` when not supplied."""
    if retrieved_sop_chunks is not None:
        retrieved_sop = "\n\n---\n\n".join(chunk.text for chunk in retrieved_sop_chunks if chunk.text)
    else:
        try:
            retrieved_sop_context = resolve_retrieved_sop_context(
                transcript_text=transcript_text,
                retrieved_sop_from_pinecone=retrieved_sop_from_pinecone,
                org_filter=org_filter,
            )
            retrieved_sop = retrieved_sop_context.text
            retrieved_sop_chunks = retrieved_sop_context.chunks
            if retrieved_sop_context.retrieval_failed:
                logger.warning(
                    "Process adherence SOP retrieval degraded [org=%s transcript_len=%d]",
                    org_filter or "<none>",
                    len(transcript_text or ""),
                )
        except Exception:
            logger.warning(
                "Process adherence SOP retrieval threw [org=%s transcript_len=%d]",
                org_filter or "<none>",
                len(transcript_text or ""),
                exc_info=True,
            )
            retrieved_sop = ""
            retrieved_sop_chunks = []

    if topic is None:
        topic = await classify_topic(full_transcript_text or transcript_text)
    # When the classifier abstains, fall back to the retrieved SOP document's own metadata.
    topic_hint = topic if topic != UNKNOWN_TOPIC else (_detect_topic_from_sop_chunks(retrieved_sop_chunks or []) or "")

    # Topic-aware SOP filter: drop chunks whose source_file doesn't match the topic,
    # so the LLM doesn't see retention SOP text when the call is about a refund.
    if retrieved_sop_chunks:
        filtered_chunks = _filter_chunks_by_topic(retrieved_sop_chunks, topic_hint)
        if len(filtered_chunks) != len(retrieved_sop_chunks):
            retrieved_sop_chunks = filtered_chunks
            retrieved_sop = "\n\n---\n\n".join(chunk.text for chunk in filtered_chunks if chunk.text)

    expected_steps = _extract_sop_steps(retrieved_sop)[:8] or RESOLUTION_GRAPHS.get(topic_hint, [])[:8]
    expected_steps = _filter_cross_topic_steps(
        _filter_prose_steps(_filter_bullet_steps(expected_steps)),
        topic_hint,
    )

    result = await _run_chain(
        "process_adherence",
        build_process_adherence_chain,
        {
            "topic_hint": topic_hint or UNKNOWN_TOPIC,
            "transcript_text": _sanitize_for_prompt(transcript_text),
            "retrieved_sop": _sanitize_for_prompt(retrieved_sop or "No SOP context found.", max_length=6000),
            "expected_resolution_graph": "\n".join(f"- {step}" for step in expected_steps)
            or "- No explicit graph available.",
        },
    )

    result.detected_topic = topic_hint or (result.detected_topic or "").strip()
    result.missing_sop_steps = _filter_cross_topic_steps(
        _filter_prose_steps(_filter_bullet_steps(_resolve_step_labels(result.missing_sop_steps, expected_steps))),
        topic_hint,
    )
    if not result.citations:
        result.citations = [
            EvidenceCitation(source="transcript", speaker="unknown", quote=quote)
            for quote in result.evidence_quotes
        ]

    # Always name WHICH retrieved SOP grounded the verdict (file name + section
    # header) so the explainability panel can show the retrieval source.
    if retrieved_sop_chunks and not any(
        (c.source or "").lower() == "sop"
        and any(tok in (c.quote or "").lower() for tok in ("sop_", "policy_", ".pdf"))
        for c in result.citations
    ):
        result.citations.append(_reference_sop_citation(retrieved_sop_chunks))
    return result


async def run_single_claim_nli_policy_check(
    agent_statement: str,
    ground_truth_policy: str,
) -> NLIEvaluation:
    """
    Single-claim NLI policy alignment check.

    This function validates one agent statement against one policy context and
    returns entailment-style categories. It is intentionally separate from
    transcript-level compliance reporting.
    """
    result = await _run_chain(
        "nli_policy",
        build_nli_policy_chain,
        {
            "agent_statement": _sanitize_for_prompt(agent_statement),
            "ground_truth_policy": _sanitize_for_prompt(ground_truth_policy, max_length=6000),
        },
    )
    model_policy_quotes = [
        c.quote for c in result.citations
        if (c.source or "").lower() == "policy" and (c.quote or "").strip()
    ] + list(result.evidence_quotes)

    # Contradiction grounding gate: a genuine contradiction must quote a clause
    # that actually exists in the retrieved policy. When the model cannot anchor
    # one, the alleged violation is likely spurious (the false-positive mode seen
    # on PASS calls where the agent correctly enforced/denied), so soften to
    # Benign Deviation instead of flooring the policy score. NOT applied to Policy
    # Hallucination, whose defining trait is citing a clause ABSENT from policy.
    if result.nli_category == "Contradiction" and (ground_truth_policy or "").strip():
        if not any(_quote_anchored_in_policy(q, ground_truth_policy) for q in model_policy_quotes):
            result.nli_category = "Benign Deviation"
            result.severity = "none"
            result.policy_alignment_score = max(result.policy_alignment_score or 0.0, 0.45)
            result.justification = (
                "Downgraded from Contradiction: no retrieved-policy clause was quoted to anchor "
                "the alleged violation. " + (result.justification or "")
            ).strip()
    return result


async def run_nli_policy_check(
    agent_statement: str,
    ground_truth_policy: str,
) -> NLIEvaluation:
    """Backward-compatible alias for single-claim NLI policy alignment checks."""
    return await run_single_claim_nli_policy_check(
        agent_statement=agent_statement,
        ground_truth_policy=ground_truth_policy,
    )


def _derive_llm_inputs(
    utterances: list[Utterance],
    transcript_text: str,
    agent_name: str | None,
) -> tuple[str, str, str, str, str]:
    customer_fragments: list[str] = []
    agent_fragments: list[str] = []
    customer_emotion_weights: dict[str, float] = {}
    acoustic_emotion = "neutral"
    acoustic_confidence: float | None = None

    for index, utterance in enumerate(utterances):
        if not utterance.text:
            continue
        role = utterance.speaker_role.value if utterance.speaker_role else ""

        if role == "customer":
            customer_fragments.append(utterance.text)
            if utterance.emotion:
                normalized_emotion = _normalize_acoustic_label(utterance.emotion)
                confidence = float(utterance.emotion_confidence) if utterance.emotion_confidence is not None else 0.5
                recency_weight = 1.0 + (((index + 1) / max(1, len(utterances))) * 0.08)
                customer_emotion_weights[normalized_emotion] = customer_emotion_weights.get(normalized_emotion, 0.0) + (confidence * recency_weight)

        if role == "agent":
            agent_fragments.append(utterance.text)

    if customer_emotion_weights:
        def _emotion_rank(item: tuple[str, float]) -> tuple[float, int]:
            label, weight = item
            polarity_rank = {
                "negative": 2,
                "neutral": 1,
                "positive": 0,
            }.get(_emotion_polarity(label), 0)
            return (weight, polarity_rank)

        acoustic_emotion = max(customer_emotion_weights.items(), key=_emotion_rank)[0]
        total_weight = sum(customer_emotion_weights.values())
        acoustic_confidence = customer_emotion_weights[acoustic_emotion] / total_weight if total_weight > 0 else 0.5

    # Speaker-attributed text only. Empty when diarization could not separate a
    # speaker — the caller decides how to fall back, keeping the LLM-input and
    # the manager-facing display values distinct.
    customer_text = _truncate_text("\n".join(customer_fragments), 2400)
    agent_statement = _truncate_text("\n".join(agent_fragments), 2400)

    agent_label = agent_name or "Unknown Agent"
    agent_context = (
        f"Agent name: {agent_label}. "
        "Analyze full-call behavior in a customer-service quality assurance setting."
    )
    # Text-emotion fusion still needs content even when customer turns were not
    # separable; fall back locally without polluting the returned display text.
    fusion_text = customer_text or (_truncate_text(transcript_text, 900) if transcript_text else "")
    fused = _model_call(
        "emotion_fusion",
        fuse_emotion_signals,
        text=fusion_text,
        acoustic_emotion=acoustic_emotion,
        acoustic_confidence=acoustic_confidence,
    )
    return agent_context, customer_text, acoustic_emotion, fused.emotion, agent_statement


async def _evaluate_emotion_pipeline(
    agent_context: str,
    customer_text: str,
    fused_emotion: str,
    conversation_text: str = "",
) -> EmotionShiftAnalysis:
    return await analyze_emotion_shift(
        agent_context=agent_context,
        customer_text=customer_text,
        acoustic_emotion=fused_emotion,
        conversation_text=conversation_text,
    )


async def _evaluate_policy_and_sop_trigger_checks(
    process_context_text: str,
    sop_context: str,
    sop_chunks: list[RetrievedChunk],
    org_filter: str | None,
    agent_statement: str,
    policy_context: str,
    full_transcript_text: str | None = None,
    topic: str | None = None,
) -> tuple[ProcessAdherenceReport, NLIEvaluation]:
    """
    Run trigger checks that consume retrieved SOP/policy context.

    RAG has already retrieved the context before this function is called. This
    helper only performs judgment:
      - SOP process adherence for a transcript window.
      - NLI policy alignment for one agent statement.
    """
    process_task = evaluate_process_adherence(
        transcript_text=process_context_text,
        retrieved_sop_from_pinecone=sop_context,
        org_filter=org_filter,
        retrieved_sop_chunks=sop_chunks,
        full_transcript_text=full_transcript_text,
        topic=topic,
    )
    nli_task = run_single_claim_nli_policy_check(
        agent_statement=agent_statement,
        ground_truth_policy=policy_context,
    )
    return await asyncio.gather(process_task, nli_task)


async def _evaluate_transcript_policy_pipeline(
    transcript_text: str,
    org_filter: str | None,
) -> Any | None:
    """
    Run transcript-level compliance evaluation using the dedicated evaluator.

    This call is supplemental for trigger orchestration clarity and does not
    change the public trigger response schema.
    """
    evaluator = _get_policy_compliance_evaluator()
    if evaluator is None:
        return None
    try:
        return await asyncio.to_thread(
            evaluator.check,
            transcript_text,
            org_filter,
            False,
        )
    except Exception as exc:
        logger.warning("PolicyComplianceEvaluator failed in trigger pipeline: %s", exc)
        return None


async def load_cached_interaction_trigger_report(
    session: AsyncSession,
    interaction_id: UUID,
    org_filter: str | None,
) -> InteractionLLMTriggerReport | None:
    """Public read helper for cached trigger payloads (no pipeline execution)."""
    return await _load_cached_trigger_report(session, interaction_id, org_filter)


async def _load_cached_trigger_report(
    session: AsyncSession,
    interaction_id: UUID,
    org_filter: str | None,
) -> InteractionLLMTriggerReport | None:
    if org_filter is not None:
        org_filter = str(org_filter)
    cached_result = await session.exec(
        select(InteractionLLMTriggerCache).where(InteractionLLMTriggerCache.interaction_id == interaction_id)
    )
    cached = cached_result.first()
    if not cached or not cached.report_payload:
        return None
    if org_filter and cached.org_filter and cached.org_filter != org_filter:
        return None
    payload_version = cached.report_payload.get("_schema_version", 1) if isinstance(cached.report_payload, dict) else 1
    if payload_version < CACHE_SCHEMA_VERSION:
        logger.info(
            "Cached LLM trigger payload for interaction %s has schema version %d (current: %d), invalidating.",
            interaction_id,
            payload_version,
            CACHE_SCHEMA_VERSION,
        )
        return None
    try:
        return InteractionLLMTriggerReport.model_validate(cached.report_payload)
    except Exception:
        logger.warning("Ignoring invalid cached LLM trigger payload for interaction %s", interaction_id, exc_info=True)
        return None


async def _resolve_active_knowledge_version(session: AsyncSession, interaction_id) -> int | None:
    """Active knowledge version number for an interaction's org (seeds a baseline)."""
    from app.core.knowledge_versioning import get_active_version_number

    org_id = (await session.exec(
        select(Interaction.organization_id).where(Interaction.id == interaction_id)
    )).first()
    if org_id is None:
        return None
    return await get_active_version_number(session, org_id)


async def _persist_trigger_report(
    session: AsyncSession,
    report: InteractionLLMTriggerReport,
    org_filter: str | None,
    *,
    commit: bool,
    knowledge_version_override: int | None = None,
) -> None:
    if org_filter is not None:
        org_filter = str(org_filter)
    cached_result = await session.exec(
        select(InteractionLLMTriggerCache).where(InteractionLLMTriggerCache.interaction_id == report.interaction_id)
    )
    cached = cached_result.first() or InteractionLLMTriggerCache(interaction_id=report.interaction_id)
    cached.org_filter = org_filter
    knowledge_version = (
        knowledge_version_override
        if knowledge_version_override is not None
        else await _resolve_active_knowledge_version(session, report.interaction_id)
    )
    cached.knowledge_version = knowledge_version
    cached.report_payload = {
        **report.model_dump(mode="json"),
        "_schema_version": CACHE_SCHEMA_VERSION,
        "knowledge_version": knowledge_version,
    }
    cached.computed_at = datetime.now(timezone.utc)
    session.add(cached)
    if commit:
        await session.commit()
    else:
        await session.flush()


async def invalidate_llm_trigger_cache(
    session: AsyncSession,
    org_filter: str | None = None,
) -> int:
    if org_filter is not None:
        org_filter = str(org_filter)
    from sqlalchemy import delete
    stmt = delete(InteractionLLMTriggerCache)
    if org_filter:
        stmt = stmt.where(InteractionLLMTriggerCache.org_filter == org_filter)
    result = await session.exec(stmt)
    await session.commit()
    count = result.rowcount if hasattr(result, 'rowcount') else 0
    logger.info("Invalidated %d LLM trigger cache entries (org_filter=%s)", count, org_filter)
    return count


def _ensure_on_topic_sop_chunks(
    sop_chunks: list[RetrievedChunk],
    topic: str,
    transcript_text: str,
    org_filter: str | None,
) -> list[RetrievedChunk]:
    """Keep the SOP context on the classified topic, re-retrieving when the dense
    retriever returned only off-topic documents (e.g. retention SOP for a refund call)."""
    wanted_tokens = _TOPIC_TO_SOP_FILE_TOKENS.get(topic, ())
    if not wanted_tokens:
        return sop_chunks

    def _on_topic(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return [
            c for c in chunks
            if any(tok in str(c.metadata.get("source_file") or "").lower() for tok in wanted_tokens)
        ]

    on_topic = _on_topic(sop_chunks)
    if not on_topic:
        from app.core.config import settings as _settings
        from app.llm_trigger.retrieval import SOPRetriever

        try:
            on_topic = _on_topic(
                SOPRetriever().retrieve_chunks(
                    query_text=transcript_text,
                    collection_name=_settings.QDRANT_COLLECTION_SOP_PARENTS,
                    top_k=max(5, _settings.SOP_RETRIEVAL_TOP_K * 2),
                    org_filter=org_filter,
                    doc_type="sop",
                )
            )
        except Exception as exc:
            logger.warning("SOP topic re-retrieval failed (%s)", exc)
    if on_topic and len(on_topic) != len(sop_chunks):
        logger.info("SOP topic filter: %d -> %d chunks (topic=%r)", len(sop_chunks), len(on_topic), topic)
    return on_topic or sop_chunks


async def evaluate_interaction_triggers(
    session: AsyncSession,
    interaction_id: UUID,
    retrieved_sop_from_pinecone: str = "",
    ground_truth_policy: str = "",
    org_filter: str | None = None,
    requester_organization_id: UUID | None = None,
    force_rerun: bool = False,
    commit_cache: bool = False,
    force_persist: bool = False,
    knowledge_version_override: int | None = None,
) -> InteractionLLMTriggerReport:
    """
    Orchestrate the interaction-level trigger pipeline with explicit layer roles:

    1) RAG retrieval layer resolves SOP/policy grounding context.
    2) PolicyComplianceEvaluator produces transcript-level compliance report.
    3) NLI policy check validates single agent claims against policy context.
    """
    _log_step(interaction_id, "start", force_rerun=force_rerun, org_filter=org_filter)
    use_cached_report = (
        not force_rerun
        and not retrieved_sop_from_pinecone.strip()
        and not ground_truth_policy.strip()
    )
    if use_cached_report:
        cached_report = await _load_cached_trigger_report(
            session=session,
            interaction_id=interaction_id,
            org_filter=org_filter,
        )
        if cached_report is not None:
            _log_step(interaction_id, "cache_hit")
            return cached_report

    interaction_stmt = select(Interaction).where(Interaction.id == interaction_id)
    if requester_organization_id is not None:
        interaction_stmt = interaction_stmt.where(
            Interaction.organization_id == requester_organization_id
        )
    interaction_result = await session.exec(interaction_stmt)
    interaction = interaction_result.first()
    if not interaction:
        raise ValueError("Interaction not found.")

    scoped_org_id = interaction.organization_id
    if requester_organization_id is not None and scoped_org_id != requester_organization_id:
        raise ValueError("Interaction not found.")

    transcript_result = await session.exec(
        select(Transcript)
        .join(Interaction, Transcript.interaction_id == Interaction.id)
        .where(
            Transcript.interaction_id == interaction_id,
            Interaction.organization_id == scoped_org_id,
        )
    )
    transcript = transcript_result.first()

    utterance_result = await session.exec(
        select(Utterance)
        .join(Interaction, Utterance.interaction_id == Interaction.id)
        .where(Utterance.interaction_id == interaction_id)
        .where(Interaction.organization_id == scoped_org_id)
        .order_by(Utterance.sequence_index)
    )
    utterances = list(utterance_result.all())

    agent_result = await session.exec(select(User).where(User.id == interaction.agent_id))
    agent = agent_result.first()

    transcript_text = (transcript.full_text if transcript and transcript.full_text else "").strip()
    if not transcript_text:
        transcript_text = _reconstruct_transcript(utterances)

    if not transcript_text:
        raise ValueError("No transcript text available for this interaction.")

    rolling_windows = _build_rolling_windows(utterances)
    selected_emotion_window = _select_emotion_window(rolling_windows, utterances)
    process_windows = _select_process_windows(rolling_windows)

    process_context_text = _render_window_bundle(process_windows) or transcript_text

    agent_context, customer_fragments_text, acoustic_emotion, fused_emotion, agent_fragments_text = _derive_llm_inputs(
        utterances=utterances,
        transcript_text=transcript_text,
        agent_name=agent.name if agent else None,
    )

    # Honest, speaker-attributed text for the manager-facing UI. When diarization
    # could not isolate a speaker we say so rather than dumping the entire
    # (cross-contaminated) transcript into both the customer and agent panels.
    roles_unavailable_note = "Speaker roles were unavailable for this call — see the full transcript."
    display_customer_text = customer_fragments_text or roles_unavailable_note
    display_agent_statement = agent_fragments_text or roles_unavailable_note

    # LLM-side inputs may fall back to the full transcript so the chains still
    # have content to reason over even when role attribution failed.
    transcript_fallback = _truncate_text(transcript_text, 900) if transcript_text else ""
    customer_text = customer_fragments_text or transcript_fallback or "No customer text available."
    agent_statement = agent_fragments_text or transcript_fallback or "No agent statement available."

    if selected_emotion_window:
        agent_context += (
            f" Focus window: {selected_emotion_window.window_id} "
            f"(turns {selected_emotion_window.start_index}-{selected_emotion_window.end_index}, "
            f"time {_format_timestamp(selected_emotion_window.start_seconds)}-"
            f"{_format_timestamp(selected_emotion_window.end_seconds)})."
        )
        focus_block = (
            "\n\n---\n[Focus window — peak emotional signal]\n"
            f"{selected_emotion_window.text.strip()}\n---"
        )
        if focus_block.strip() and focus_block not in customer_text:
            customer_text = _truncate_text(customer_text + focus_block, 3600)

    try:
        sop_resolution = resolve_retrieved_sop_context(
            transcript_text=transcript_text,
            retrieved_sop_from_pinecone=retrieved_sop_from_pinecone,
            org_filter=org_filter,
        )
        sop_context = sop_resolution.text
        sop_chunks = sop_resolution.chunks
        if sop_resolution.retrieval_failed:
            logger.warning(
                "Trigger SOP retrieval degraded [interaction_id=%s org=%s]",
                interaction_id,
                org_filter or "<none>",
            )
    except Exception:
        logger.warning(
            "Trigger SOP retrieval threw [interaction_id=%s org=%s]",
            interaction_id,
            org_filter or "<none>",
            exc_info=True,
        )
        sop_context = ""
        sop_chunks = []

    topic = await classify_topic(transcript_text)
    _log_step(interaction_id, "topic_classified", topic=topic)
    on_topic_chunks = _ensure_on_topic_sop_chunks(sop_chunks, topic, transcript_text, org_filter)
    if on_topic_chunks != sop_chunks:
        sop_chunks = on_topic_chunks
        sop_context = "\n\n---\n\n".join(c.text for c in sop_chunks if c.text)

    policy_context = await _resolve_active_policy_context(
        session=session,
        organization_id=interaction.organization_id,
        ground_truth_policy=ground_truth_policy,
        fallback_sop=sop_context,
        query_text=agent_statement or transcript_text,
        org_filter=org_filter,
    )

    emotion_pipeline_task = _evaluate_emotion_pipeline(
        agent_context=agent_context,
        customer_text=customer_text,
        fused_emotion=fused_emotion,
        conversation_text=_reconstruct_transcript(utterances) or transcript_text,
    )
    grounded_trigger_checks_task = _evaluate_policy_and_sop_trigger_checks(
        process_context_text=process_context_text,
        sop_context=sop_context,
        sop_chunks=sop_chunks,
        org_filter=org_filter,
        agent_statement=agent_statement,
        policy_context=policy_context.text,
        full_transcript_text=transcript_text,
        topic=topic,
    )
    transcript_policy_task = _evaluate_transcript_policy_pipeline(
        transcript_text=process_context_text,
        org_filter=org_filter,
    )

    emotion_shift, grounded_trigger_checks, transcript_policy_report = await asyncio.gather(
        emotion_pipeline_task,
        grounded_trigger_checks_task,
        transcript_policy_task,
    )
    _log_step(interaction_id, "llm_chains_complete")
    if transcript_policy_report is not None:
        _log_step(
            interaction_id,
            "transcript_policy_report_complete",
            compliance_score=getattr(transcript_policy_report, "compliance_score", None),
            violations=len(getattr(transcript_policy_report, "violations", []) or []),
        )
    process_adherence, nli_policy = grounded_trigger_checks

    _backfill_transcript_citation_indices(emotion_shift.citations, utterances)
    _backfill_transcript_citation_indices(process_adherence.citations, utterances)
    _backfill_transcript_citation_indices(nli_policy.citations, utterances)

    if not _has_mapped_transcript_citation(emotion_shift.citations):
        emotion_shift.root_cause = INSUFFICIENT_EVIDENCE_LABEL
        emotion_shift.insufficient_evidence = True

    if not _has_mapped_transcript_citation(process_adherence.citations):
        process_adherence.justification = INSUFFICIENT_EVIDENCE_LABEL
        process_adherence.insufficient_evidence = True

    has_policy_citation = any(c.source == "policy" and bool((c.quote or "").strip()) for c in nli_policy.citations)
    if not has_policy_citation:
        nli_policy.justification = INSUFFICIENT_EVIDENCE_LABEL
        nli_policy.insufficient_evidence = True

    nli_policy.policy_version = policy_context.version
    nli_policy.policy_effective_at = policy_context.effective_at
    nli_policy.policy_category = policy_context.category
    nli_policy.conflict_resolution_applied = policy_context.conflict_resolution_applied
    try:
        policy_chunks = retrieve_policy_chunks(
            query_text=agent_statement,
            org_filter=org_filter,
            top_k=3,
        )
    except Exception:
        logger.warning(
            "Explainability policy retrieval failed [interaction_id=%s org=%s agent_statement_len=%d]",
            interaction_id,
            org_filter or "<none>",
            len(agent_statement or ""),
            exc_info=True,
        )
        policy_chunks = []
    explainability = _build_explainability_layer(
        emotion_shift=emotion_shift,
        process_adherence=process_adherence,
        nli_policy=nli_policy,
        utterances=utterances,
        acoustic_emotion=acoustic_emotion,
        sop_context=sop_context,
        sop_chunks=sop_chunks,
        policy_context=policy_context,
        policy_chunks=policy_chunks,
        agent_statement=agent_statement,
        org_filter=org_filter,
    )

    report = InteractionLLMTriggerReport(
        interaction_id=interaction_id,
        emotion_shift=emotion_shift,
        process_adherence=process_adherence,
        nli_policy=nli_policy,
        derived_customer_text=display_customer_text,
        derived_acoustic_emotion=acoustic_emotion,
        derived_fused_emotion=fused_emotion,
        derived_agent_statement=display_agent_statement,
        explainability=explainability,
    )

    if force_persist or (not retrieved_sop_from_pinecone.strip() and not ground_truth_policy.strip()):
        await _persist_trigger_report(
            session=session,
            report=report,
            org_filter=org_filter,
            commit=commit_cache,
            knowledge_version_override=knowledge_version_override,
        )
        _log_step(interaction_id, "cache_persisted")

    _log_step(interaction_id, "complete")
    return report
