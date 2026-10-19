from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator

from app.llm_trigger.prompt_constants import RESOLUTION_GRAPHS, UNKNOWN_TOPIC


CitationSource = Literal["transcript", "policy", "sop", "acoustic", "kb"]
CitationSpeaker = Literal["customer", "agent", "system", "unknown"]
ExplainabilityFamily = Literal["emotion", "sop", "policy"]
ExplainabilityVerdict = Literal[
    "Supported",
    "Partial Attempt",
    "Neutral",
    "Contradiction",
    "Cross-Modal Mismatch",
    "No Trigger",
    "Insufficient Evidence",
]


class EvidenceCitation(BaseModel):
    source: CitationSource = Field(description="Origin of the supporting quote.")
    quote: str = Field(description="Exact quote supporting the claim.")
    speaker: CitationSpeaker = Field(default="unknown", description="Speaker tied to the quote when available.")
    utterance_index: int | None = Field(
        default=None,
        ge=0,
        description="Utterance index for transcript citations when known.",
    )


class EvidenceSpan(BaseModel):
    utterance_index: int | None = Field(
        default=None,
        ge=0,
        description="Sequence index for the supporting utterance when the evidence comes from the transcript.",
    )
    speaker: CitationSpeaker = Field(default="unknown")
    quote: str = Field(description="Span quote shown to supervisors.")
    timestamp: str | None = Field(default=None, description="Clock timestamp for the supporting span.")
    start_seconds: float | None = Field(default=None, ge=0, description="Audio jump target in seconds.")
    end_seconds: float | None = Field(default=None, ge=0, description="Span end time in seconds.")


class PolicyReference(BaseModel):
    source: Literal["policy", "sop", "kb"] = Field(description="Whether the reference came from a policy, SOP, or KB document.")
    reference: str = Field(description="Human-readable document or section reference.")
    clause: str = Field(description="Policy or SOP clause used as evidence.")
    doc_type: Literal["policy", "sop", "kb"] | None = Field(
        default=None,
        description="Document type carried from retrieval metadata.",
    )
    doc_id: str | None = Field(
        default=None,
        description="Document identifier from ingestion metadata.",
    )
    rule_id: str | None = Field(
        default=None,
        description="Policy rule ID when source is a policy chunk.",
    )
    step_number: str | None = Field(
        default=None,
        description="SOP step number when source is an SOP chunk.",
    )
    severity: str | None = Field(
        default=None,
        description="Rule severity level (critical/major/minor) when available.",
    )
    policy_ref: list[str] = Field(
        default_factory=list,
        description="Policy rule IDs referenced by an SOP chunk when available.",
    )
    version: str | None = Field(default=None, description="Version or policy token when available.")
    category: str | None = Field(default=None, description="Policy category when available.")
    provenance: str | None = Field(
        default=None,
        description="Retrieval provenance such as document path, parent section, or chunk label.",
    )


class TriggerAttribution(BaseModel):
    attribution_id: str = Field(description="Stable identifier for the trigger attribution card.")
    family: ExplainabilityFamily = Field(description="High-level explainability family.")
    trigger_type: str = Field(description="Trigger class such as Acoustic-Transcript Dissonance or SOP Violation.")
    title: str = Field(description="Short manager-facing title.")
    verdict: ExplainabilityVerdict = Field(description="Final explainability verdict.")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_span: EvidenceSpan | None = Field(default=None)
    policy_reference: PolicyReference | None = Field(default=None)
    reasoning: str = Field(description="Plain-English reason for the verdict.")
    evidence_chain: list[str] = Field(
        default_factory=list,
        description="Structured reasoning steps that connect the span to the verdict.",
    )
    supporting_quotes: list[str] = Field(default_factory=list)


class ClaimProvenance(BaseModel):
    claim_id: str = Field(description="Stable identifier for the claim provenance card.")
    claim_text: str = Field(description="Agent claim or answer sentence.")
    claim_span: EvidenceSpan | None = Field(default=None)
    retrieved_policy: PolicyReference | None = Field(default=None)
    semantic_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    nli_verdict: ExplainabilityVerdict = Field(description="Policy-grounded verdict for the claim.")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str = Field(description="Manager-facing explanation of how the claim was judged.")
    provenance: str = Field(description="Compact retrieval provenance trail.")
    supporting_quotes: list[str] = Field(default_factory=list)


class EvidenceAnchoredExplainability(BaseModel):
    trigger_attributions: list[TriggerAttribution] = Field(default_factory=list)
    claim_provenance: list[ClaimProvenance] = Field(default_factory=list)


def _normalize_quote_list(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        items = value

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        quote = (item or "").strip().strip('"')
        if not quote:
            continue
        if quote in seen:
            continue
        seen.add(quote)
        normalized.append(quote)
    return normalized


def _clean_citations(value: list | None) -> list:
    if not value:
        return []
    cleaned = []
    for c in value:
        # Drop malformed citations the model sometimes emits (e.g. a trailing
        # {"source": "policy"} with no quote). A citation without a quote carries
        # no evidence, and keeping it would fail EvidenceCitation's required
        # `quote` field and discard the whole response into the degraded fallback.
        if isinstance(c, dict):
            if not c:
                continue
            if not str(c.get("quote") or "").strip():
                continue
        cleaned.append(c)
    return cleaned


class EmotionShiftAnalysis(BaseModel):
    # NOTE: these four carry defaults so a partial-but-valid JSON object from the
    # model (models often omit counterfactual_correction)
    # still parses and we keep the model's dissonance_type signal, rather than
    # discarding the whole response and dropping empathy to the 0.8 fallback.
    is_dissonance_detected: bool = Field(
        default=False,
        description="Whether acoustic emotion contradicts text sentiment.",
    )
    dissonance_type: str = Field(
        default="none",
        description=(
            'Agent friction root cause — exactly one of: "interruption", "dismissive_tone", '
            '"missing_acknowledgment", "none" (mirrors friction_root_cause / shift_type).'
        ),
    )
    root_cause: str = Field(
        default="insufficient evidence",
        description="Transcript-grounded explanation of the mismatch.",
    )
    counterfactual_correction: str = Field(
        default="If the agent had used a clearer empathy-and-verification step, escalation risk could have decreased.",
        description='Actionable rewrite starting with "If the agent had...".',
    )
    evidence_quotes: list[str] = Field(
        default_factory=list,
        description="Short verbatim quotes from transcript used as evidence.",
    )
    citations: list[EvidenceCitation] = Field(
        default_factory=list,
        description="Structured evidence citations supporting the analysis.",
    )
    current_customer_emotion: str = Field(
        default="neutral",
        description="Current dominant customer emotion label inferred for this interaction slice.",
    )
    current_emotion_reasoning: str = Field(
        default="insufficient evidence",
        description="Reasoning for why the customer appears in the current emotional state.",
    )
    insufficient_evidence: bool = Field(
        default=False,
        description="True when the analysis had to be downgraded due to missing or unmapped evidence.",
    )
    # Optional: models often omit confidence_score from otherwise-valid JSON.
    # Keeping it required discarded the whole response and forced the degraded
    # heuristic fallback. Downstream code backfills None from a signal estimate.
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model or signal confidence for the dissonance verdict when available.",
    )

    @field_validator("counterfactual_correction", mode="before")
    @classmethod
    def ensure_counterfactual_prefix(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return "If the agent had used a clearer empathy-and-verification step, escalation risk could have decreased."
        if text.lower().startswith("if the agent had"):
            return text
        return f"If the agent had {text[0].lower() + text[1:] if len(text) > 1 else text.lower()}"

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def normalize_emotion_evidence_quotes(cls, value: list[str] | str | None) -> list[str]:
        return _normalize_quote_list(value)

    @field_validator("root_cause", mode="before")
    @classmethod
    def enforce_root_cause_fallback(cls, value: str | None) -> str:
        text = (value or "").strip()
        return text or "insufficient evidence"

    @field_validator("citations", mode="before")
    @classmethod
    def drop_empty_citations(cls, value: list | None) -> list:
        return _clean_citations(value)


class TopicClassification(BaseModel):
    topic: str = Field(description="One RESOLUTION_GRAPHS topic key, or 'unknown'.")

    @field_validator("topic", mode="before")
    @classmethod
    def normalize_topic(cls, value: str | None) -> str:
        topic = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return topic if topic in RESOLUTION_GRAPHS else UNKNOWN_TOPIC


class ProcessAdherenceReport(BaseModel):
    # is_resolved / efficiency_score are required: they come from the model only.
    detected_topic: str = Field(default="", description="Detected customer-service topic.")
    is_resolved: bool = Field(description="Whether issue appears resolved by end of dialogue.")
    efficiency_score: int = Field(
        ge=1,
        le=10,
        description="Resolution efficiency score where 10 is optimal process adherence.",
    )
    justification: str = Field(
        default="",
        description="A short, quote-grounded paragraph explaining exactly why the efficiency score was given and why any steps were missed.",
    )
    missing_sop_steps: list[str] = Field(
        default_factory=list,
        description=(
            "SOP steps absent or weakly executed — use RESOLUTION_GRAPH step_key strings "
            "(snake_case, e.g. verify_refund_eligibility_window) only."
        ),
    )
    evidence_quotes: list[str] = Field(
        default_factory=list,
        description="Verbatim transcript quotes supporting topic and adherence findings.",
    )
    citations: list[EvidenceCitation] = Field(
        default_factory=list,
        description="Structured citations mapped to transcript and SOP evidence.",
    )
    insufficient_evidence: bool = Field(
        default=False,
        description="True when process verdict could not be grounded to transcript evidence.",
    )
    # Optional: see EmotionShiftAnalysis.confidence_score — models omit this and a
    # required field was forcing the degraded heuristic fallback. Backfilled downstream.
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model confidence for the process adherence assessment when available.",
    )

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def normalize_process_evidence_quotes(cls, value: list[str] | str | None) -> list[str]:
        return _normalize_quote_list(value)

    @field_validator("citations", mode="before")
    @classmethod
    def drop_empty_citations(cls, value: list | None) -> list:
        return _clean_citations(value)


NLICategory = Literal[
    "Entailment",
    "Benign Deviation",
    "Contradiction",
    "Policy Hallucination",
]


class NLIEvaluation(BaseModel):
    nli_category: NLICategory = Field(
        validation_alias=AliasChoices("nli_category", "verdict", "category"),
    )
    justification: str = Field(description="Short evidence-backed rationale for the label.")
    evidence_quotes: list[str] = Field(
        default_factory=list,
        description="Verbatim quotes from policy/agent statement supporting NLI label.",
    )
    citations: list[EvidenceCitation] = Field(
        default_factory=list,
        description="Structured policy and transcript citations used for the NLI decision.",
    )
    policy_version: str | None = Field(
        default=None,
        description="Version token for the policy used during evaluation.",
    )
    policy_effective_at: str | None = Field(
        default=None,
        description="Effective timestamp metadata for the selected policy version.",
    )
    policy_category: str | None = Field(
        default=None,
        description="Category of the selected policy document.",
    )
    conflict_resolution_applied: bool = Field(
        default=False,
        description="True when policy conflict resolution rules were applied.",
    )
    insufficient_evidence: bool = Field(
        default=False,
        description="True when NLI verdict had insufficient policy-grounded evidence.",
    )
    # Optional: see EmotionShiftAnalysis.confidence_score — models omit this and a
    # required field was forcing the degraded heuristic fallback.
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model confidence for the final NLI category when available.",
    )
    policy_alignment_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How strongly the statement is supported by policy. Low values imply contradiction or hallucination.",
    )
    severity: Literal["critical", "major", "minor", "none"] = Field(
        default="none",
        description=(
            "Severity of the policy breach: 'critical' (regulatory/financial/identity harm), "
            "'major' (clear violation, limited harm), 'minor' (small procedural slip such as a "
            "missing recording notice), or 'none' for Entailment / Benign Deviation."
        ),
    )

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: str | None) -> str:
        normalized = (value or "none").strip().lower()
        return normalized if normalized in {"critical", "major", "minor", "none"} else "none"

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def normalize_nli_evidence_quotes(cls, value: list[str] | str | None) -> list[str]:
        return _normalize_quote_list(value)

    @field_validator("citations", mode="before")
    @classmethod
    def drop_empty_citations(cls, value: list | None) -> list:
        return _clean_citations(value)


class InteractionLLMTriggerReport(BaseModel):
    interaction_id: UUID
    emotion_shift: EmotionShiftAnalysis
    process_adherence: ProcessAdherenceReport
    nli_policy: NLIEvaluation
    derived_customer_text: str
    derived_acoustic_emotion: str
    derived_fused_emotion: str
    derived_agent_statement: str
    explainability: EvidenceAnchoredExplainability = Field(default_factory=EvidenceAnchoredExplainability)
