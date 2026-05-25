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
    build_emotion_shift_chain,
    build_nli_policy_chain,
    build_process_adherence_chain,
)
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

CACHE_SCHEMA_VERSION = 4
_evaluator_lock = threading.Lock()
_policy_compliance_evaluator = None


RESOLUTION_GRAPHS: dict[str, list[str]] = {
    "refund_request": [
        "Acknowledge customer issue",
        "Collect order identifier",
        "Verify refund eligibility window",
        "Confirm refund method and timeline",
        "Close with summary and next steps",
    ],
    "billing_issue": [
        "Acknowledge billing concern",
        "Verify account and charge details",
        "Explain charge source or correction",
        "Confirm customer understanding",
        "Close with follow-up path",
    ],
    "technical_support": [
        "Acknowledge the technical issue",
        "Collect device or account context",
        "Run step-by-step troubleshooting",
        "Validate issue resolution",
        "Document next escalation path",
    ],
    "account_access": [
        "Acknowledge access issue",
        "Verify user identity",
        "Guide reset or unlock steps",
        "Confirm successful login",
        "Close with prevention advice",
    ],
    "account_opening": [
        "Greet and confirm intent to open account",
        "Collect identity documents and KYC data",
        "Disclose required fees and terms",
        "Capture customer signature / consent",
        "Confirm account number and next steps (debit card mailing, online banking)",
    ],
    "fraud_dispute": [
        "Acknowledge and reassure the customer",
        "Confirm card status and freeze if needed",
        "Collect transaction details (date, amount, merchant)",
        "Open the fraud / Reg E dispute ticket",
        "Explain provisional credit timeline and follow-up SLA",
    ],
    "fee_adjustment": [
        "Acknowledge the fee concern",
        "Verify the fee against account history and policy",
        "Check waiver authority and frequency cap",
        "Apply waiver or open Manager Approval ticket",
        "Confirm outcome and document the case",
    ],
    "aml_review": [
        "Acknowledge customer without alerting to SAR review",
        "Collect transaction context (purpose, source of funds)",
        "Flag the account for AML / BSA review without disclosure",
        "Open suspicious-activity ticket per regulation",
        "Close call neutrally without confirming the review",
    ],
    "retention": [
        "Acknowledge cancellation intent without resistance",
        "Identify root cause for the cancellation",
        "Offer the appropriate retention play (loyalty credit, plan change)",
        "Confirm customer decision",
        "Close: process cancellation OR confirm retention outcome",
    ],
}


ROLLING_WINDOW_TURNS = 8
ROLLING_WINDOW_STRIDE = 4
MAX_PROCESS_WINDOWS = 3
INSUFFICIENT_EVIDENCE_LABEL = "insufficient evidence"
POLICY_PRIORITY_BUCKETS: tuple[str, ...] = ("regulatory", "legal")
DEGRADED_MODE_SUFFIX = " [DEGRADED: LLM unavailable — heuristic fallback used]"


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


def _detect_cross_modal_dissonance(customer_text: str, acoustic_emotion: str, text_emotion: str | None = None) -> bool:
    if text_emotion is None:
        text_emotion, _ = infer_text_emotion_with_provider(customer_text)
    text_polarity = _emotion_polarity(text_emotion)
    acoustic_polarity = _emotion_polarity(acoustic_emotion)
    if "!" in customer_text and acoustic_polarity == "negative" and text_polarity != "negative":
        return True
    return (text_polarity == "positive" and acoustic_polarity == "negative") or (
        text_polarity == "negative" and acoustic_polarity == "positive"
    )


_TOPIC_KEYWORDS: dict[str, dict[str, float]] = {
    "refund_request": {
        "refund": 3.0,
        "chargeback": 3.0,
        "reimburse": 3.0,
        "money back": 3.0,
        "credit on": 2.0,
        "credit my": 2.0,
        "outage credit": 3.0,
        "service outage": 2.5,
        "prorated": 2.5,
        "compensation": 2.0,
        "goodwill": 2.0,
        "return": 1.0,
    },
    "billing_issue": {
        "invoice": 2.5,
        "double charge": 3.0,
        "overcharge": 3.0,
        "billing error": 3.0,
        "bill": 1.5,
        "charge": 1.5,
        "payment": 1.5,
        "statement": 1.5,
        "balance": 1.0,
    },
    "technical_support": {
        "outage": 0.5,
        "no internet": 0.5,
        "router": 2.0,
        "modem": 2.0,
        "wifi": 2.0,
        "wi-fi": 2.0,
        "speed test": 2.5,
        "reboot": 2.0,
        "firmware": 2.5,
        "crash": 2.0,
        "error code": 2.5,
        "not connecting": 1.5,
        "troubleshoot": 2.5,
        "blue screen": 3.0,
        "ping": 1.5,
    },
    "account_access": {
        "password": 2.5,
        "login": 2.5,
        "log in": 2.5,
        "sign in": 2.5,
        "locked out": 3.0,
        "reset my": 2.0,
        "two-factor": 2.5,
        "2fa": 2.5,
        "verification code": 2.5,
        "authenticator": 2.5,
        "recovery code": 2.5,
        "username": 2.0,
        "pin reset": 3.0,
    },
    "account_opening": {
        "open an account": 3.0,
        "open a new account": 3.0,
        "opening an account": 3.0,
        "kyc": 3.0,
        "know your customer": 3.0,
        "driver's license": 2.0,
        "passport": 2.0,
        "social security number": 2.0,
        "proof of address": 2.5,
        "debit card mailing": 2.5,
        "account number generated": 2.5,
        "checking account": 1.5,
        "savings account": 1.5,
    },
    "fraud_dispute": {
        "unauthorized charge": 3.0,
        "unauthorized transaction": 3.0,
        "card fraud": 3.0,
        "stolen card": 3.0,
        "lost card": 2.0,
        "didn't make this": 3.0,
        "i did not make": 3.0,
        "fraudulent": 3.0,
        "freeze the card": 3.0,
        "close the card": 2.5,
        "provisional credit": 2.5,
        "reg e": 3.0,
        "dispute the": 2.5,
        "elder financial exploitation": 3.0,
        "check fraud": 3.0,
    },
    "fee_adjustment": {
        "overdraft fee": 3.0,
        "overdraft": 2.0,
        "waive the fee": 3.0,
        "waive this fee": 3.0,
        "fee waiver": 3.0,
        "courtesy waiver": 2.5,
        "monthly fee": 2.0,
        "service fee": 2.0,
        "nsf fee": 3.0,
        "insufficient funds fee": 3.0,
    },
    "aml_review": {
        "wire transfer": 2.0,
        "structuring": 3.0,
        "large cash": 2.5,
        "suspicious activity": 3.0,
        "aml": 3.0,
        "bsa": 3.0,
        "money laundering": 3.0,
        "ctr": 2.0,
        "currency transaction": 2.5,
    },
    "retention": {
        "cancel my account": 3.0,
        "cancel the account": 3.0,
        "i want to cancel": 3.0,
        "close my account": 3.0,
        "switching to": 2.5,
        "competitor": 2.0,
        "leave you guys": 2.0,
        "cancellation": 2.5,
        "early termination fee": 2.5,
        "etf": 2.5,
        "downgrade": 1.5,
    },
}


def _detect_topic(transcript_text: str, retrieved_sop: str) -> str:
    topic, _ = _score_topic(transcript_text, retrieved_sop)
    return topic or "billing_issue"


def _score_topic(transcript_text: str, retrieved_sop: str) -> tuple[str | None, float]:
    """Return (best_topic, score). best_topic is None when no keyword fired."""
    source = f"{transcript_text}\n{retrieved_sop}".lower()
    scores: dict[str, float] = {}
    for topic, keyword_weights in _TOPIC_KEYWORDS.items():
        score = 0.0
        for keyword, weight in keyword_weights.items():
            if keyword in source:
                score += weight * source.count(keyword)
        scores[topic] = score
    best_topic = max(scores, key=scores.get)
    best_score = scores[best_topic]
    if best_score <= 0:
        return None, 0.0
    return best_topic, best_score


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


def _step_keywords(step: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "with",
        "from",
        "that",
        "this",
        "for",
        "then",
        "into",
        "customer",
        "agent",
    }
    return {token for token in _tokenize(step) if len(token) > 3 and token not in stop_words}


def _trajectory_missing_steps(transcript_text: str, expected_steps: list[str]) -> list[str]:
    transcript_tokens = set(_tokenize(transcript_text))
    missing: list[str] = []
    for step in expected_steps:
        keywords = _step_keywords(step)
        if not keywords:
            continue
        overlap = len(keywords.intersection(transcript_tokens))
        threshold = max(1, len(keywords) // 3)
        if overlap < threshold:
            missing.append(step)
    return missing


def _merge_missing_steps(
    deterministic_missing: list[str],
    llm_missing: list[str],
) -> list[str]:
    if not llm_missing:
        return deterministic_missing
    if not deterministic_missing:
        return llm_missing

    normalized_deterministic = {step.lower(): step for step in deterministic_missing}
    merged = list(deterministic_missing)
    for llm_step in llm_missing:
        llm_keywords = _step_keywords(llm_step)
        matched = False
        for expected_lower, original_step in normalized_deterministic.items():
            expected_keywords = _step_keywords(expected_lower)
            if llm_keywords and expected_keywords and llm_keywords.intersection(expected_keywords):
                matched = True
                break
        if not matched and llm_step not in merged:
            merged.append(llm_step)
    return merged


def _is_resolved_heuristic(transcript_text: str) -> bool:
    """Detect call-level resolution.

    Strategy:
      1) Hard NEGATIVE markers (escalation / no-resolution) → not resolved.
      2) Strong POSITIVE markers (concrete outcome delivered) → resolved.
      3) Otherwise weight positive vs negative soft signals; tie/none → not resolved.

    Bare 'thank you' alone is never enough; every polite call ends with it.
    """
    text = transcript_text.lower()

    # ── Hard negative: explicit non-resolution / escalation ─────────────
    hard_negative = (
        "still not working",
        "didn't work",
        "not fixed",
        "we cannot",
        "we can't process",
        "unable to process",
        "won't be able to",
        "outside my authority",
        "manager approval ticket",
        "back-office ticket",
        "needs more information",
        "have to escalate",
        "still being investigated",
        "three-strike termination",
        "ending this call",
        "i have to disconnect",
        "freeze the account",
    )
    if any(marker in text for marker in hard_negative):
        return False

    # ── Strong positive: concrete outcome delivered on the call ─────────
    strong_positive = (
        "credit has been applied",
        "credit has been approved",
        "credit has been processed",
        "credit of $",
        "credit of about $",
        "refund of $",
        "refund has been processed",
        "fee has been waived",
        "fee waived",
        "fee is waived",
        "i've waived",
        "i have waived",
        "i've applied",
        "i have applied",
        "i applied a",
        "applied a $",
        "applied a credit",
        "applied the credit",
        "applied the refund",
        "approved the credit",
        "approved the refund",
        "approved a credit",
        "credit to your account",
        "credit on the account",
        "credit on your account",
        "your account is now open",
        "account is now active",
        "your new account number",
        "you should see this on your next",
        "appear on your next",
        "applied to your next",
        "reflected on your next",
        "issue has been resolved",
        "issue is resolved",
        "problem is resolved",
        "is fixed",
        "is now working",
        "works now",
        "back online",
        "successfully reset",
        "successfully verified",
        "your plan has been upgraded",
        "your plan has been updated",
        "your plan is now",
        "plan change has been applied",
        "your account has been updated",
        "case reference number for today",
        "ticket has been created",
    )
    if any(marker in text for marker in strong_positive):
        return True

    # ── Soft signals — need a small majority to count as resolved ──────
    soft_positive = (
        "case reference number is",
        "case reference number:",
        "ticket number is",
        "ticket reference",
        "ticket id is",
        "i have processed",
        "i have applied",
        "all set",
        "all set with",
        "confirmation number is",
        "confirmation email",
        "you'll receive an email",
        "you should receive",
        "anything else i can help",
    )
    soft_negative = (
        "i'll have to",
        "call back",
        "i'll follow up",
        "i will follow up",
        "we'll get back",
        "needs further review",
        "review by our team",
        "manager will review",
    )
    pos = sum(1 for m in soft_positive if m in text)
    neg = sum(1 for m in soft_negative if m in text)
    return pos >= 2 and pos > neg


def _efficiency_score_heuristic(transcript_text: str, missing_steps: list[str], expected_steps: list[str]) -> int:
    if not expected_steps:
        return 6
    missing_ratio = min(len(missing_steps), len(expected_steps)) / len(expected_steps)
    coverage = 1.0 - missing_ratio
    score = int(round(1 + 9 * coverage))
    turns = len([line for line in transcript_text.splitlines() if line.strip()])
    if turns > 20:
        score -= 1
    if turns > 30:
        score -= 1
    return max(1, min(10, score))


def _split_sentences(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]


EMOTIONAL_QUOTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "negative": (
        "frustrat",
        "angry",
        "upset",
        "terrible",
        "unacceptable",
        "not working",
        "still",
        "again",
        "delay",
        "waiting",
        "issue",
        "problem",
        "broken",
        "failed",
        "cannot",
        "can't",
        "won't",
        "refund",
        "complaint",
    ),
    "positive": (
        "thank",
        "great",
        "resolved",
        "fixed",
        "helpful",
        "perfect",
        "appreciate",
    ),
}


def _sentence_emotion_score(sentence: str, target_emotion: str | None = None) -> float:
    text = sentence.lower()
    score = 0.0

    negative_hits = sum(1 for token in EMOTIONAL_QUOTE_KEYWORDS["negative"] if token in text)
    positive_hits = sum(1 for token in EMOTIONAL_QUOTE_KEYWORDS["positive"] if token in text)

    score += (negative_hits * 1.6)
    score += (positive_hits * 0.9)

    if "!" in sentence:
        score += 0.8
    if "?" in sentence:
        score += 0.3
    if len(sentence.split()) >= 8:
        score += 0.4

    if target_emotion:
        target_polarity = _emotion_polarity(target_emotion)
        if target_polarity == "negative":
            score += (negative_hits * 1.1)
            score -= (positive_hits * 0.4)
        elif target_polarity == "positive":
            score += (positive_hits * 0.6)

    # Down-rank identity-only lines that often pollute evidence snippets.
    if "my name is" in text or "pin is" in text:
        score -= 1.8

    return score


def _quote_candidates(text: str, max_quotes: int = 3, target_emotion: str | None = None) -> list[str]:
    if not text:
        return []

    sentences = _split_sentences(text)
    scored_sentences: list[tuple[float, int, str]] = []
    for sentence in sentences:
        cleaned = sentence.strip().strip('"')
        if len(cleaned.split()) < 4:
            continue

        score = _sentence_emotion_score(cleaned, target_emotion=target_emotion)
        scored_sentences.append((score, len(scored_sentences), cleaned))

    if scored_sentences:
        scored_sentences.sort(key=lambda item: (-item[0], item[1]))
        return [sentence for _, _, sentence in scored_sentences[:max_quotes]]

    quotes: list[str] = []
    for sentence in sentences:
        cleaned = sentence.strip().strip('"')
        if len(cleaned.split()) < 4:
            continue
        quotes.append(cleaned)
        if len(quotes) >= max_quotes:
            break

    if quotes:
        return quotes

    fallback = text.strip().replace("\n", " ")
    return [fallback[:180]] if fallback else []


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    trimmed = normalized[:max_chars].rsplit(" ", 1)[0].strip()
    return trimmed or normalized[:max_chars].strip()


def _llm_failure_reason(exc: Exception) -> str:
    message = str(exc or "").strip().lower()
    if "rate limit" in message or "rate_limit_exceeded" in message or "error code: 429" in message:
        return "the LLM provider rate limit was reached"
    if "api key" in message or "unauthorized" in message or "forbidden" in message or "authentication" in message:
        return "LLM authentication failed"
    if "timeout" in message or "timed out" in message:
        return "the LLM request timed out"
    if "connection" in message or "refused" in message or "unavailable" in message:
        return "the LLM service was unavailable"
    return "the LLM service was unavailable"


def _build_customer_emotion_reasoning(emotion: str, root_cause: str, quotes: list[str]) -> str:
    quote = quotes[0] if quotes else ""
    emotional_state = _normalize_acoustic_label(emotion)
    root = (root_cause or "").strip()
    if root and INSUFFICIENT_EVIDENCE_LABEL not in root.lower():
        return root

    baseline_reasons: dict[str, str] = {
        "angry": "Customer language and tone indicate perceived service failure and elevated agitation.",
        "frustrated": "Customer appears blocked in issue resolution and expresses repeated dissatisfaction.",
        "sad": "Customer wording suggests disappointment and low-confidence expectations.",
        "happy": "Customer language and tone indicate satisfaction with the handling and outcome.",
        "neutral": "Customer wording remains informational without strong affective escalation.",
    }
    reason = baseline_reasons.get(
        emotional_state,
        "Customer emotion is present but transcript evidence is limited for a detailed causal explanation.",
    )
    if quote:
        return f"{reason} Evidence: \"{quote}\""
    return reason


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


def _ensure_minimum_policy_citation(nli_policy: NLIEvaluation, policy_text: str) -> None:
    has_policy_citation = any(c.source == "policy" and bool((c.quote or "").strip()) for c in nli_policy.citations)
    if has_policy_citation:
        return

    fallback_quotes = _quote_candidates(policy_text, max_quotes=1)
    if fallback_quotes:
        nli_policy.citations.append(
            EvidenceCitation(source="policy", speaker="system", quote=fallback_quotes[0])
        )


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
    if retrieval_query:
        try:
            retrieved_policy_chunks = retrieve_policy_chunks(
                query_text=retrieval_query,
                org_filter=org_filter,
                top_k=2,
            )
        except Exception:
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
        return ResolvedPolicyContext(text=text, version="fallback", category="fallback")

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
        _label, text_confidence = infer_text_emotion_with_provider(span.quote)

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
        title=emotion_shift.dissonance_type or "Cross-Modal Dissonance",
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


def _fallback_claim_citations(agent_statement: str) -> list[EvidenceCitation]:
    return [
        EvidenceCitation(source="transcript", speaker="agent", quote=quote)
        for quote in _quote_candidates(agent_statement, max_quotes=2)
    ]


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
    if not claim_citations:
        claim_citations = _fallback_claim_citations(agent_statement)
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
                per_claim_chunks = []
        candidate_chunks = _filter_chunks_by_policy_context(
            per_claim_chunks or policy_chunks,
            policy_context,
        )
        best_policy_chunk = _best_retrieved_chunk(candidate_chunks, claim_text)
        policy_reference = _build_policy_reference_from_chunk(
            best_policy_chunk,
            source_kind="policy",
            fallback_text=fallback_policy_text,
            fallback_reference=f"{policy_context.category or 'Policy'} reference",
            version=policy_context.version,
            category=policy_context.category,
        )
        if not policy_reference and fallback_policy_text.strip():
            policy_reference = PolicyReference(
                source="policy",  # type: ignore[arg-type]
                reference=f"{policy_context.category or 'Policy'} reference",
                clause=_truncate_text(_clean_display_text(fallback_policy_text), 260) or "Active policy context",
                doc_type="policy",  # type: ignore[arg-type]
                policy_ref=[],
                version=policy_context.version,
                category=policy_context.category,
            )
        if not policy_reference:
            continue

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
                semantic_similarity=_clamp_unit(best_policy_chunk.score) if best_policy_chunk and best_policy_chunk.score is not None else None,
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


def _count_role_lines(window_text: str, role: str) -> int:
    prefix = f"{role.lower()}:"
    return sum(1 for line in window_text.splitlines() if line.lower().startswith(prefix))


def _emotion_window_score(window: TranscriptWindow) -> tuple[int, int, int]:
    customer_lines = [
        line.split(":", 1)[1].strip()
        for line in window.text.splitlines()
        if line.lower().startswith("customer:") and ":" in line
    ]
    joined_customer = " ".join(customer_lines)
    text_emotion, text_confidence = infer_text_emotion_with_provider(joined_customer)
    polarity_conflict_markers = int(round(text_confidence * 10))
    if _emotion_polarity(text_emotion) == "negative":
        polarity_conflict_markers += 2
    if "!" in joined_customer:
        polarity_conflict_markers += 1
    return (
        polarity_conflict_markers,
        _count_role_lines(window.text, "customer"),
        window.end_index,
    )


def _select_emotion_window(windows: list[TranscriptWindow]) -> TranscriptWindow | None:
    if not windows:
        return None
    return max(windows, key=_emotion_window_score)


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


def _window_citations(windows: list[TranscriptWindow]) -> list[EvidenceCitation]:
    citations: list[EvidenceCitation] = []
    for window in windows:
        snippet = window.text.splitlines()[0].strip() if window.text.splitlines() else ""
        if not snippet:
            continue
        citations.append(
            EvidenceCitation(
                source="transcript",
                speaker="unknown",
                utterance_index=window.start_index,
                quote=snippet[:220],
            )
        )
    return citations


async def analyze_emotion_shift(
    agent_context: str,
    customer_text: str,
    acoustic_emotion: str,
) -> EmotionShiftAnalysis:
    inferred_emotion = _normalize_acoustic_label(acoustic_emotion)
    _text_emotion, text_confidence = infer_text_emotion_with_provider(customer_text)
    if not _detect_cross_modal_dissonance(customer_text, acoustic_emotion, text_emotion=_text_emotion):
        quotes = _quote_candidates(customer_text, max_quotes=2, target_emotion=inferred_emotion)
        return EmotionShiftAnalysis(
            is_dissonance_detected=False,
            dissonance_type="None",
            root_cause="No strong contradiction detected between text sentiment and acoustic emotion.",
            counterfactual_correction="If the agent had continued the same supportive approach, the interaction likely would have remained stable.",
            evidence_quotes=quotes,
            current_customer_emotion=inferred_emotion,
            current_emotion_reasoning=_build_customer_emotion_reasoning(
                emotion=inferred_emotion,
                root_cause="",
                quotes=quotes,
            ),
            citations=[
                EvidenceCitation(
                    source="transcript",
                    speaker="customer",
                    quote=quote,
                )
                for quote in quotes
            ],
            confidence_score=_clamp_unit(text_confidence),
        )

    chain = build_emotion_shift_chain()
    try:
        from app.llm_trigger.chains import _invoke_chain_with_retry
        result = await _invoke_chain_with_retry(
            chain,
            {
                "agent_context": _sanitize_for_prompt(agent_context),
                "customer_text": _sanitize_for_prompt(customer_text),
                "acoustic_emotion": acoustic_emotion,
            },
        )
    except Exception as exc:
        logger.warning("Emotion shift LLM chain failed, using fallback: %s", exc)
        quotes = _quote_candidates(customer_text, max_quotes=2, target_emotion=inferred_emotion)
        return EmotionShiftAnalysis(
            is_dissonance_detected=True,
            dissonance_type="Unknown",
            root_cause=INSUFFICIENT_EVIDENCE_LABEL + DEGRADED_MODE_SUFFIX,
            counterfactual_correction="If the agent had acknowledged the concern and confirmed a clear next action, escalation risk could have decreased.",
            evidence_quotes=quotes,
            citations=[
                EvidenceCitation(source="transcript", speaker="customer", quote=quote)
                for quote in quotes
            ],
            current_customer_emotion=inferred_emotion,
            current_emotion_reasoning=_build_customer_emotion_reasoning(
                emotion=inferred_emotion,
                root_cause=INSUFFICIENT_EVIDENCE_LABEL,
                quotes=quotes,
            ),
            insufficient_evidence=True,
            confidence_score=None,
        )
    result.is_dissonance_detected = True
    if result.dissonance_type.strip().lower() == "none":
        result.dissonance_type = "Sarcasm"
    if not result.evidence_quotes:
        result.evidence_quotes = _quote_candidates(customer_text, max_quotes=3, target_emotion=inferred_emotion)
    if not result.root_cause.strip():
        result.root_cause = INSUFFICIENT_EVIDENCE_LABEL
    if not result.evidence_quotes:
        result.root_cause = INSUFFICIENT_EVIDENCE_LABEL
    if INSUFFICIENT_EVIDENCE_LABEL in result.root_cause.lower():
        result.root_cause = INSUFFICIENT_EVIDENCE_LABEL
    if not result.citations:
        result.citations = [
            EvidenceCitation(source="transcript", speaker="customer", quote=quote)
            for quote in result.evidence_quotes
        ]
    result.current_customer_emotion = inferred_emotion
    result.current_emotion_reasoning = _build_customer_emotion_reasoning(
        emotion=inferred_emotion,
        root_cause=result.root_cause,
        quotes=result.evidence_quotes,
    )
    if result.confidence_score is None:
        result.confidence_score = _clamp_unit(text_confidence)
    return result


async def evaluate_process_adherence(
    transcript_text: str,
    retrieved_sop_from_pinecone: str,
    org_filter: str | None = None,
    retrieved_sop_chunks: list[RetrievedChunk] | None = None,
    full_transcript_text: str | None = None,
) -> ProcessAdherenceReport:
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
        except Exception:
            retrieved_sop = ""
            retrieved_sop_chunks = []

    # Two-pass topic detection: keyword score on the TRANSCRIPT is primary
    # (the transcript carries the strongest topic signal). The retrieved-chunk
    # source_file hint is only used when keyword scoring is genuinely weak
    # (no keyword fired) — using the file hint as primary would let a single
    # off-topic retrieved chunk hijack the whole pipeline (e.g. a retention
    # SOP getting recalled by 'credit' wording in a pure refund call).
    # Topic detection uses the FULL transcript (when available), not just the
    # rolling-window slice — keyword density on a short window is too noisy.
    topic_source_text = full_transcript_text or transcript_text
    keyword_topic, keyword_score = _score_topic(topic_source_text, "")
    file_topic = _detect_topic_from_sop_chunks(retrieved_sop_chunks or [])
    logger.debug(
        "topic_detect: keyword=%r score=%.1f file=%r tx_len=%d sop_chunks=%d",
        keyword_topic, keyword_score, file_topic, len(topic_source_text or ""), len(retrieved_sop_chunks or []),
    )
    if keyword_topic and keyword_score >= 3.0:
        # Strong keyword signal — trust the transcript regardless of file hint.
        topic_hint = keyword_topic
    elif keyword_topic and file_topic and keyword_topic == file_topic:
        # Both agree → confident
        topic_hint = keyword_topic
    elif file_topic:
        topic_hint = file_topic
    else:
        topic_hint = keyword_topic or "billing_issue"

    # Topic-aware SOP filter: drop chunks whose source_file doesn't match the topic,
    # so the LLM doesn't see retention SOP text when the call is about a refund.
    if retrieved_sop_chunks:
        filtered_chunks = _filter_chunks_by_topic(retrieved_sop_chunks, topic_hint)
        if filtered_chunks is not retrieved_sop_chunks and len(filtered_chunks) != len(retrieved_sop_chunks):
            retrieved_sop_chunks = filtered_chunks
            retrieved_sop = "\n\n---\n\n".join(chunk.text for chunk in filtered_chunks if chunk.text)

    extracted_sop_steps = _extract_sop_steps(retrieved_sop)
    if extracted_sop_steps:
        expected_steps = extracted_sop_steps[:8]
    else:
        expected_steps = RESOLUTION_GRAPHS.get(topic_hint, []).copy()[:8]

    deterministic_missing = _trajectory_missing_steps(transcript_text, expected_steps)
    deterministic_efficiency = _efficiency_score_heuristic(
        transcript_text=transcript_text,
        missing_steps=deterministic_missing,
        expected_steps=expected_steps,
    )
    deterministic_resolved = _is_resolved_heuristic(full_transcript_text or transcript_text)

    chain = build_process_adherence_chain()
    try:
        from app.llm_trigger.chains import _invoke_chain_with_retry
        result = await _invoke_chain_with_retry(
            chain,
            {
                "topic_hint": topic_hint,
                "transcript_text": _sanitize_for_prompt(transcript_text),
                "retrieved_sop": _sanitize_for_prompt(retrieved_sop or "No SOP context found.", max_length=6000),
                "expected_resolution_graph": "\n".join(
                    f"- {step}" for step in expected_steps
                )
                or "- No explicit graph available.",
            }
        )
    except Exception as exc:
        logger.warning("Process adherence LLM chain failed, using deterministic fallback: %s", exc)
        evidence_quotes = _quote_candidates(transcript_text, max_quotes=3)
        citations = [
            EvidenceCitation(source="transcript", speaker="unknown", quote=quote)
            for quote in evidence_quotes
        ]
        sop_quote = _quote_candidates(retrieved_sop, max_quotes=1)
        if sop_quote:
            citations.append(EvidenceCitation(source="sop", speaker="system", quote=sop_quote[0]))

        # Inject the reference-SOP citation here too so the degraded path
        # still surfaces WHICH SOP grounded the verdict.
        if retrieved_sop_chunks:
            primary = retrieved_sop_chunks[0]
            source_file = (primary.metadata.get("source_file") or "").strip()
            header_parts = " > ".join(
                str(primary.metadata.get(k)).strip()
                for k in ("Header 1", "Header 2", "Header 3")
                if primary.metadata.get(k)
            )
            label = f"{source_file} — {header_parts}" if source_file and header_parts else (source_file or "Retrieved SOP")
            citations.append(
                EvidenceCitation(source="sop", speaker="system", quote=f"[Reference SOP] {label}")
            )

        return ProcessAdherenceReport(
            detected_topic=topic_hint,
            is_resolved=deterministic_resolved,
            efficiency_score=deterministic_efficiency,
            justification=(
                f"LLM analysis is temporarily unavailable because {_llm_failure_reason(exc)}. "
                "Scores are provisional estimates from transcript and SOP keyword coverage."
                + DEGRADED_MODE_SUFFIX
            ),
            missing_sop_steps=deterministic_missing,
            evidence_quotes=evidence_quotes,
            citations=citations,
            insufficient_evidence=not bool(evidence_quotes),
            confidence_score=None,
        )

    # If the deterministic topic detector found a STRONG signal (high keyword score
    # or both heuristics agree), trust it over the LLM. The LLM has been observed
    # to default to refund_request/billing_issue for any call that mentions money
    # — overriding it with a strong-signal hint is safer than letting the LLM
    # mislabel KYC / fraud / 2FA / cancellation calls.
    llm_topic = (result.detected_topic or "").strip()
    if topic_hint and (
        not llm_topic
        or (keyword_score >= 6.0)
        or (keyword_topic and file_topic and keyword_topic == file_topic and keyword_score >= 3.0)
    ):
        if llm_topic != topic_hint:
            logger.info(
                "process_adherence topic override: llm=%r -> hint=%r (kw_score=%.1f, kw_topic=%r, file_topic=%r)",
                llm_topic, topic_hint, keyword_score, keyword_topic, file_topic,
            )
        result.detected_topic = topic_hint

    result.missing_sop_steps = _merge_missing_steps(
        deterministic_missing=deterministic_missing,
        llm_missing=result.missing_sop_steps,
    )
    result.efficiency_score = max(
        1,
        min(10, int(round((result.efficiency_score + deterministic_efficiency) / 2))),
    )
    result.is_resolved = result.is_resolved and deterministic_resolved
    if not result.evidence_quotes:
        result.evidence_quotes = _quote_candidates(transcript_text, max_quotes=3)
    if not result.citations:
        result.citations = [
            EvidenceCitation(source="transcript", speaker="unknown", quote=quote)
            for quote in result.evidence_quotes
        ]
        sop_quote = _quote_candidates(retrieved_sop, max_quotes=1)
        if sop_quote:
            result.citations.append(
                EvidenceCitation(source="sop", speaker="system", quote=sop_quote[0])
            )

    # Ensure the response always names WHICH SOP grounded the verdict, even
    # when the LLM returned no missing-step (i.e. fully adherent calls). We
    # prepend a synthetic SOP citation whose quote is the SOP file name +
    # section header — that way the UI explainability panel and downstream
    # eval can both see the retrieval source without having to read the prompt.
    if retrieved_sop_chunks:
        has_sop_citation_with_source = any(
            (c.source or "").lower() == "sop" and any(
                tok in (c.quote or "").lower()
                for tok in ("sop_", "policy_", ".pdf")
            )
            for c in (result.citations or [])
        )
        if not has_sop_citation_with_source:
            primary = retrieved_sop_chunks[0]
            source_file = (primary.metadata.get("source_file") or "").strip()
            header_parts = " > ".join(
                str(primary.metadata.get(k)).strip()
                for k in ("Header 1", "Header 2", "Header 3")
                if primary.metadata.get(k)
            )
            label = f"{source_file} — {header_parts}" if source_file and header_parts else (source_file or "Retrieved SOP")
            result.citations.append(
                EvidenceCitation(
                    source="sop",
                    speaker="system",
                    quote=f"[Reference SOP] {label}",
                )
            )

    if result.confidence_score is None and retrieved_sop_chunks:
        scored_chunks = [chunk.score for chunk in retrieved_sop_chunks if chunk.score is not None]
        if scored_chunks:
            result.confidence_score = _clamp_unit(max(scored_chunks))
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
    chain = build_nli_policy_chain()
    try:
        from app.llm_trigger.chains import _invoke_chain_with_retry
        result = await _invoke_chain_with_retry(
            chain,
            {
                "agent_statement": _sanitize_for_prompt(agent_statement),
                "ground_truth_policy": _sanitize_for_prompt(ground_truth_policy, max_length=6000),
            }
        )
    except Exception as exc:
        logger.warning("NLI policy LLM chain failed, using deterministic fallback: %s", exc)
        statement_quote = _quote_candidates(agent_statement, max_quotes=1)
        policy_quote = _quote_candidates(ground_truth_policy, max_quotes=1)
        evidence_quotes = statement_quote + [q for q in policy_quote if q not in statement_quote]
        citations: list[EvidenceCitation] = []
        if statement_quote:
            citations.append(EvidenceCitation(source="transcript", speaker="agent", quote=statement_quote[0]))
        if policy_quote:
            citations.append(EvidenceCitation(source="policy", speaker="system", quote=policy_quote[0]))

        return NLIEvaluation(
            nli_category="Benign Deviation",
            justification=(
                "Deterministic fallback was used because the LLM NLI service was unavailable. "
                "This label is provisional and should be revalidated when LLM connectivity is restored."
                + DEGRADED_MODE_SUFFIX
            ),
            evidence_quotes=evidence_quotes,
            citations=citations,
            insufficient_evidence=not bool(citations),
            confidence_score=None,
            policy_alignment_score=None,
        )
    if not result.evidence_quotes:
        result.evidence_quotes = _quote_candidates(
            f"{agent_statement}\n{ground_truth_policy}",
            max_quotes=3,
        )
    if not result.citations:
        citations: list[EvidenceCitation] = []
        statement_quote = _quote_candidates(agent_statement, max_quotes=1)
        if statement_quote:
            citations.append(
                EvidenceCitation(source="transcript", speaker="agent", quote=statement_quote[0])
            )
        policy_quote = _quote_candidates(ground_truth_policy, max_quotes=1)
        if policy_quote:
            citations.append(
                EvidenceCitation(source="policy", speaker="system", quote=policy_quote[0])
            )
        result.citations = citations
    if result.policy_alignment_score is None:
        category = (result.nli_category or "").strip().lower()
        if category == "entailment":
            result.policy_alignment_score = 0.85
        elif category == "benign deviation":
            result.policy_alignment_score = 0.45
        elif category in {"contradiction", "policy hallucination"}:
            result.policy_alignment_score = 0.1
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

    customer_text = _truncate_text("\n".join(customer_fragments), 2400)
    agent_statement = _truncate_text("\n".join(agent_fragments), 2400)

    if not customer_text:
        customer_text = _truncate_text(transcript_text, 900) if transcript_text else "No customer text available."

    if not agent_statement:
        agent_statement = _truncate_text(transcript_text, 900) if transcript_text else "No agent statement available."

    agent_label = agent_name or "Unknown Agent"
    agent_context = (
        f"Agent name: {agent_label}. "
        "Analyze full-call behavior in a customer-service quality assurance setting."
    )
    fused = fuse_emotion_signals(
        text=customer_text,
        acoustic_emotion=acoustic_emotion,
        acoustic_confidence=acoustic_confidence,
    )
    return agent_context, customer_text, acoustic_emotion, fused.emotion, agent_statement


async def _evaluate_emotion_pipeline(
    agent_context: str,
    customer_text: str,
    fused_emotion: str,
) -> EmotionShiftAnalysis:
    return await analyze_emotion_shift(
        agent_context=agent_context,
        customer_text=customer_text,
        acoustic_emotion=fused_emotion,
    )


async def _evaluate_policy_and_sop_trigger_checks(
    process_context_text: str,
    sop_context: str,
    sop_chunks: list[RetrievedChunk],
    org_filter: str | None,
    agent_statement: str,
    policy_context: str,
    full_transcript_text: str | None = None,
) -> tuple[ProcessAdherenceReport, NLIEvaluation]:
    """
    Run trigger checks that consume retrieved SOP/policy context.

    RAG has already retrieved the context before this function is called. This
    helper only performs judgment:
      - SOP process adherence for a transcript window.
      - NLI policy alignment for one agent statement.

    `full_transcript_text` is forwarded so the topic & resolution heuristics
    can see the whole call, not just the rolling-window slice (which is too
    sparse for reliable keyword detection).
    """
    process_task = evaluate_process_adherence(
        transcript_text=process_context_text,
        retrieved_sop_from_pinecone=sop_context,
        org_filter=org_filter,
        retrieved_sop_chunks=sop_chunks,
        full_transcript_text=full_transcript_text,
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


async def _persist_trigger_report(
    session: AsyncSession,
    report: InteractionLLMTriggerReport,
    org_filter: str | None,
    *,
    commit: bool,
) -> None:
    if org_filter is not None:
        org_filter = str(org_filter)
    cached_result = await session.exec(
        select(InteractionLLMTriggerCache).where(InteractionLLMTriggerCache.interaction_id == report.interaction_id)
    )
    cached = cached_result.first() or InteractionLLMTriggerCache(interaction_id=report.interaction_id)
    cached.org_filter = org_filter
    cached.report_payload = {**report.model_dump(mode="json"), "_schema_version": CACHE_SCHEMA_VERSION}
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


async def evaluate_interaction_triggers(
    session: AsyncSession,
    interaction_id: UUID,
    retrieved_sop_from_pinecone: str = "",
    ground_truth_policy: str = "",
    org_filter: str | None = None,
    force_rerun: bool = False,
    commit_cache: bool = False,
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

    interaction_result = await session.exec(
        select(Interaction).where(Interaction.id == interaction_id)
    )
    interaction = interaction_result.first()
    if not interaction:
        raise ValueError("Interaction not found.")

    transcript_result = await session.exec(
        select(Transcript).where(Transcript.interaction_id == interaction_id)
    )
    transcript = transcript_result.first()

    utterance_result = await session.exec(
        select(Utterance)
        .where(Utterance.interaction_id == interaction_id)
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
    selected_emotion_window = _select_emotion_window(rolling_windows)
    process_windows = _select_process_windows(rolling_windows)

    process_context_text = _render_window_bundle(process_windows) or transcript_text

    agent_context, customer_text, acoustic_emotion, fused_emotion, agent_statement = _derive_llm_inputs(
        utterances=utterances,
        transcript_text=transcript_text,
        agent_name=agent.name if agent else None,
    )

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
    except Exception:
        sop_context = ""
        sop_chunks = []

    # Topic-aware SOP re-retrieval: if the dense retriever picked off-topic
    # chunks (e.g. retention SOP for a refund call because "credit" appears
    # in both), do a targeted lookup against the expected SOP source_file
    # and replace the chunk list. This keeps the LLM grounded on the correct
    # SOP rather than letting the wrong chunk's missing-steps pollute output.
    try:
        full_topic, full_topic_score = _score_topic(transcript_text, "")
        wanted_tokens = _TOPIC_TO_SOP_FILE_TOKENS.get(full_topic or "", ())
        on_topic_already = any(
            any(tok in str(c.metadata.get("source_file") or "").lower() for tok in wanted_tokens)
            for c in sop_chunks
        )
        logger.debug(
            "sop_topic_check: topic=%r score=%.1f wanted=%r on_topic=%s n_chunks=%d srcs=%r",
            full_topic, full_topic_score, wanted_tokens, on_topic_already,
            len(sop_chunks), [c.metadata.get("source_file") for c in sop_chunks],
        )
        if full_topic and full_topic_score >= 3.0 and wanted_tokens and not on_topic_already:
            from app.core.config import settings as _settings
            from app.llm_trigger.retrieval import SOPRetriever
            retriever = SOPRetriever()
            try:
                extra = retriever.retrieve_chunks(
                    query_text=transcript_text,
                    collection_name=_settings.QDRANT_COLLECTION_SOP_PARENTS,
                    top_k=max(5, _settings.SOP_RETRIEVAL_TOP_K * 2),
                    org_filter=org_filter,
                    doc_type="sop",
                )
                on_topic_extra = [
                    c for c in extra
                    if any(tok in str(c.metadata.get("source_file") or "").lower() for tok in wanted_tokens)
                ]
                if on_topic_extra:
                    logger.info(
                        "sop_retrieval topic override: topic=%r tokens=%r added %d chunk(s)",
                        full_topic, wanted_tokens, len(on_topic_extra),
                    )
                    sop_chunks = on_topic_extra + [c for c in sop_chunks if c not in on_topic_extra]
                    sop_context = "\n\n---\n\n".join(c.text for c in sop_chunks if c.text)
            except Exception as inner_exc:
                logger.warning("sop topic re-retrieval inner failure (%s)", inner_exc)

        # ALWAYS hard-filter to on-topic chunks when we have a strong signal,
        # even if the dense retriever already included one. This keeps the
        # trigger attribution builder + LLM prompt strictly on-topic.
        if full_topic and full_topic_score >= 3.0 and wanted_tokens:
            on_topic_only = [
                c for c in sop_chunks
                if any(tok in str(c.metadata.get("source_file") or "").lower() for tok in wanted_tokens)
            ]
            if on_topic_only and len(on_topic_only) != len(sop_chunks):
                logger.info(
                    "sop topic hard-filter: %d -> %d chunks (topic=%r)",
                    len(sop_chunks), len(on_topic_only), full_topic,
                )
                sop_chunks = on_topic_only
                sop_context = "\n\n---\n\n".join(c.text for c in sop_chunks if c.text)
    except Exception as exc:
        logger.warning("sop topic re-retrieval skipped (%s)", exc)

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
    )
    grounded_trigger_checks_task = _evaluate_policy_and_sop_trigger_checks(
        process_context_text=process_context_text,
        sop_context=sop_context,
        sop_chunks=sop_chunks,
        org_filter=org_filter,
        agent_statement=agent_statement,
        policy_context=policy_context.text,
        full_transcript_text=transcript_text,
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

    window_citations = _window_citations(process_windows)
    if window_citations:
        if not process_adherence.citations:
            process_adherence.citations = []
        process_adherence.citations.extend(window_citations)

    if selected_emotion_window:
        emotion_window_quote = _quote_candidates(selected_emotion_window.text, max_quotes=1)
        if emotion_window_quote:
            emotion_shift.citations.append(
                EvidenceCitation(
                    source="transcript",
                    speaker="unknown",
                    utterance_index=selected_emotion_window.start_index,
                    quote=emotion_window_quote[0],
                )
            )

    _backfill_transcript_citation_indices(emotion_shift.citations, utterances)
    _backfill_transcript_citation_indices(process_adherence.citations, utterances)
    _backfill_transcript_citation_indices(nli_policy.citations, utterances)

    if not _has_mapped_transcript_citation(emotion_shift.citations):
        emotion_shift.root_cause = INSUFFICIENT_EVIDENCE_LABEL
        emotion_shift.insufficient_evidence = True

    if not _has_mapped_transcript_citation(process_adherence.citations):
        process_adherence.justification = INSUFFICIENT_EVIDENCE_LABEL
        process_adherence.insufficient_evidence = True

    _ensure_minimum_policy_citation(nli_policy, policy_context.text)
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
        derived_customer_text=customer_text,
        derived_acoustic_emotion=acoustic_emotion,
        derived_fused_emotion=fused_emotion,
        derived_agent_statement=agent_statement,
        explainability=explainability,
    )

    if not retrieved_sop_from_pinecone.strip() and not ground_truth_policy.strip():
        await _persist_trigger_report(
            session=session,
            report=report,
            org_filter=org_filter,
            commit=commit_cache,
        )
        _log_step(interaction_id, "cache_persisted")

    _log_step(interaction_id, "complete")
    return report
