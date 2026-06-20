"""Map LLM trigger signals to company-policy violations (single source of truth)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.policy import CompanyPolicy, OrganizationPolicy, PolicyCompliance

RULE_ID_PATTERN = re.compile(r"\b((?:CS|FIN|SEC|BNK)-RULE-\d+)\b", re.I)

RULE_PREFIX_POLICY_HINTS: dict[str, list[str]] = {
    "CS-RULE": ["policy 01", "call conduct"],
    "SEC-RULE": ["policy 02", "data privacy", "security"],
    "FIN-RULE": ["policy 03", "refund", "compensation"],
    "BNK-RULE": ["policy 03", "refund", "compensation", "banking"],
}

DISSONANCE_VIOLATIONS: dict[str, tuple[str, str, list[str]]] = {
    "interruption": (
        "CS-RULE-008",
        "Call Conduct — Interruption",
        ["call conduct", "interruption", "talk over"],
    ),
    "dismissive_tone": (
        "CS-RULE-010",
        "Call Conduct — Dismissive Tone",
        ["call conduct", "dismissive", "tone"],
    ),
    "missing_acknowledgment": (
        "CS-RULE-011",
        "A.C.E.S. — Acknowledgment",
        ["call conduct", "acknowledge", "aces"],
    ),
}

NLI_VIOLATION_CATEGORIES = frozenset({"Contradiction", "Policy Hallucination"})

NON_COMPLIANT_ATTRIBUTION_VERDICTS = frozenset(
    {
        "Partial Attempt",
        "Contradiction",
        "Cross-Modal Mismatch",
    }
)

SOP_STEP_CATEGORY_HINTS: dict[str, tuple[str, str, list[str]]] = {
    "acknowledge": ("CS-RULE-011", "A.C.E.S. — Acknowledgment", ["call conduct", "acknowledge"]),
    "empath": ("CS-RULE-011", "A.C.E.S. — Empathize", ["call conduct", "empathize"]),
    "verify": ("CS-RULE-004", "Process — Identity Verification", ["call conduct", "verification"]),
    "identity": ("CS-RULE-004", "Process — Identity Verification", ["call conduct", "verification"]),
    "close": ("CS-RULE-019", "Process — Resolution Summary", ["call conduct", "closure"]),
    "summary": ("CS-RULE-019", "Process — Resolution Summary", ["call conduct", "closure"]),
    "refund": ("FIN-RULE-001", "Process — Refund Eligibility", ["refund", "compensation"]),
    "credit": ("FIN-RULE-001", "Process — Credit Eligibility", ["refund", "compensation"]),
    "fraud": ("FIN-RULE-008", "Process — Fraud Investigation", ["refund", "compensation", "fraud"]),
    "password": ("SEC-RULE-008", "Process — Security Advisory", ["data privacy", "security"]),
    "de-escalat": ("CS-RULE-013", "Call Conduct — De-escalation", ["call conduct", "de-escalation"]),
    "forbidden": ("CS-RULE-012", "Call Conduct — Forbidden Phrases", ["call conduct", "forbidden"]),
}

RULE_ID_TITLES: dict[str, str] = {
    "CS-RULE-008": "Call Conduct — Interruption",
    "CS-RULE-010": "Call Conduct — Talk Ratio / Engagement",
    "CS-RULE-011": "A.C.E.S. — Acknowledgment",
    "CS-RULE-012": "Call Conduct — Forbidden Phrases",
    "CS-RULE-013": "Call Conduct — De-escalation",
    "CS-RULE-016": "Call Conduct — 3-Strike Protocol",
    "CS-RULE-022": "Call Conduct — Customer Conduct Logging",
    "FIN-RULE-001": "Refund — Eligibility Criteria",
    "FIN-RULE-003": "Refund — Evidence Requirements",
    "FIN-RULE-010": "Refund — Approved Script / Timeline",
    "SEC-RULE-008": "Security — Customer Advisory",
    "SEC-RULE-009": "Data Privacy — Deletion Request",
}


@dataclass
class ViolationSpec:
    violation_key: str
    rule_ids: list[str] = field(default_factory=list)
    title: str = ""
    reasoning: str = ""
    evidence_text: str = ""
    compliance_score: float = 0.25
    policy_match_hints: list[str] = field(default_factory=list)
    degraded: bool = False


@dataclass
class ViolationMappingInput:
    is_dissonance_detected: bool = False
    dissonance_type: str = "none"
    emotion_root_cause: str = ""
    emotion_evidence_quotes: list[str] = field(default_factory=list)
    nli_category: str = "Entailment"
    nli_justification: str = ""
    nli_evidence_quotes: list[str] = field(default_factory=list)
    nli_policy_category: str | None = None
    missing_sop_steps: list[str] = field(default_factory=list)
    process_justification: str = ""
    process_evidence_quotes: list[str] = field(default_factory=list)
    trigger_attributions: list[dict[str, Any]] = field(default_factory=list)
    coverage_items: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_llm_trigger_report(cls, report) -> ViolationMappingInput:
        attributions = [
            {
                "attribution_id": item.attribution_id,
                "family": item.family,
                "trigger_type": item.trigger_type,
                "title": item.title,
                "verdict": item.verdict,
                "reasoning": item.reasoning,
                "supporting_quotes": list(item.supporting_quotes or []),
                "policy_reference": (
                    item.policy_reference.model_dump() if item.policy_reference else None
                ),
            }
            for item in report.explainability.trigger_attributions
        ]
        return cls(
            is_dissonance_detected=bool(report.emotion_shift.is_dissonance_detected),
            dissonance_type=(report.emotion_shift.dissonance_type or "none").strip().lower(),
            emotion_root_cause=report.emotion_shift.root_cause or "",
            emotion_evidence_quotes=list(report.emotion_shift.evidence_quotes or []),
            nli_category=report.nli_policy.nli_category or "Entailment",
            nli_justification=report.nli_policy.justification or "",
            nli_evidence_quotes=list(report.nli_policy.evidence_quotes or []),
            nli_policy_category=report.nli_policy.policy_category,
            missing_sop_steps=list(report.process_adherence.missing_sop_steps or []),
            process_justification=report.process_adherence.justification or "",
            process_evidence_quotes=list(report.process_adherence.evidence_quotes or []),
            trigger_attributions=attributions,
        )

    @classmethod
    def from_dataset_payload(
        cls,
        *,
        emotion_shift: dict[str, Any],
        process_adherence: dict[str, Any],
        nli_policy: dict[str, Any],
        explainability: dict[str, Any] | None = None,
        coverage: list[dict[str, Any]] | None = None,
        reference_dissonance: tuple[bool, str] | None = None,
    ) -> ViolationMappingInput:
        detected = bool(emotion_shift.get("isDissonanceDetected"))
        dtype = (emotion_shift.get("dissonanceType") or "none").strip().lower()
        if reference_dissonance is not None:
            detected, ref_type = reference_dissonance
            if detected:
                dtype = (ref_type or dtype or "none").strip().lower()
            else:
                dtype = "none"

        raw_attributions = list((explainability or {}).get("triggerAttributions") or [])
        if reference_dissonance is not None and not reference_dissonance[0]:
            raw_attributions = [
                item
                for item in raw_attributions
                if not (
                    (item.get("family") or "").lower() == "emotion"
                    and (item.get("verdict") or "") == "Cross-Modal Mismatch"
                )
            ]

        return cls(
            is_dissonance_detected=detected,
            dissonance_type=dtype if detected else "none",
            emotion_root_cause=emotion_shift.get("rootCause") or "",
            emotion_evidence_quotes=list(emotion_shift.get("evidenceQuotes") or []),
            nli_category=nli_policy.get("nliCategory") or "Entailment",
            nli_justification=nli_policy.get("justification") or "",
            nli_evidence_quotes=list(nli_policy.get("evidenceQuotes") or []),
            nli_policy_category=nli_policy.get("policyCategory"),
            missing_sop_steps=list(process_adherence.get("missingSopSteps") or []),
            process_justification=process_adherence.get("justification") or "",
            process_evidence_quotes=list(process_adherence.get("evidenceQuotes") or []),
            trigger_attributions=raw_attributions,
            coverage_items=list(coverage or []),
        )


def _normalize_lookup_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _rule_prefix(rule_id: str) -> str:
    match = re.match(r"([A-Z]+-RULE)", rule_id.upper())
    return match.group(1) if match else ""


def _hints_for_rule_id(rule_id: str) -> list[str]:
    prefix = _rule_prefix(rule_id)
    hints = list(RULE_PREFIX_POLICY_HINTS.get(prefix, ["call conduct"]))
    title = RULE_ID_TITLES.get(rule_id.upper())
    if title:
        hints.extend(_normalize_lookup_text(title).split())
    return hints


def _merge_spec(existing: ViolationSpec, incoming: ViolationSpec) -> None:
    for rule_id in incoming.rule_ids:
        if rule_id not in existing.rule_ids:
            existing.rule_ids.append(rule_id)
    if incoming.evidence_text and incoming.evidence_text not in (existing.evidence_text or ""):
        existing.evidence_text = "; ".join(
            part for part in (existing.evidence_text, incoming.evidence_text) if part
        )
    if len(incoming.reasoning) > len(existing.reasoning):
        existing.reasoning = incoming.reasoning


def _spec_from_rule_id(
    rule_id: str,
    *,
    reasoning: str,
    evidence: str,
    element: str | None = None,
) -> ViolationSpec:
    rule_id = rule_id.upper()
    title = RULE_ID_TITLES.get(rule_id) or element or f"Policy rule {rule_id}"
    return ViolationSpec(
        violation_key=f"rule:{rule_id}",
        rule_ids=[rule_id],
        title=title,
        reasoning=reasoning or f"Ground-truth coverage flagged {rule_id}.",
        evidence_text=evidence,
        compliance_score=0.22,
        policy_match_hints=_hints_for_rule_id(rule_id),
    )


def _coverage_rule_ids(items: list[dict[str, Any]]) -> set[str]:
    rule_ids: set[str] = set()
    for item in items:
        notes = (item.get("notes") or "").strip()
        if not notes or "fail" not in notes.lower():
            continue
        rule_ids.update(rid.upper() for rid in RULE_ID_PATTERN.findall(notes))
    return rule_ids


def _has_coverage_fail(items: list[dict[str, Any]]) -> bool:
    return any("fail" in (item.get("notes") or "").lower() for item in items)


def _derive_from_coverage(items: list[dict[str, Any]]) -> list[ViolationSpec]:
    specs: dict[str, ViolationSpec] = {}
    for item in items:
        notes = (item.get("notes") or "").strip()
        if not notes or "fail" not in notes.lower():
            continue
        element = (item.get("element") or "").strip()
        rule_ids = [rid.upper() for rid in RULE_ID_PATTERN.findall(notes)]
        if not rule_ids:
            continue
        for rule_id in rule_ids:
            spec = _spec_from_rule_id(
                rule_id,
                reasoning=f"{element}: {notes}" if element else notes,
                evidence=element or notes,
            )
            bucket = specs.setdefault(spec.violation_key, spec)
            if bucket is not spec:
                _merge_spec(bucket, spec)
    return list(specs.values())


def _dissonance_reasoning(dtype: str, evidence: str) -> str:
    dtype = (dtype or "none").strip().lower()
    if dtype == "interruption":
        return (
            "Agent advanced the workflow before acknowledging the customer (CS-RULE-008 interruption). "
            + (f"Evidence: {evidence}" if evidence else "")
        ).strip()
    if dtype == "missing_acknowledgment":
        return (
            "A.C.E.S. acknowledgment step was skipped before troubleshooting (CS-RULE-011). "
            + (f"Evidence: {evidence}" if evidence else "")
        ).strip()
    if dtype == "dismissive_tone":
        return (
            "Agent tone remained procedural while the customer needed more empathetic engagement "
            "(CS-RULE-010 / CS-RULE-013). "
            + (f"Evidence: {evidence}" if evidence else "")
        ).strip()
    return f"Cross-modal friction flagged: {dtype.replace('_', ' ')}."


def _derive_from_dissonance(inp: ViolationMappingInput) -> list[ViolationSpec]:
    if not inp.is_dissonance_detected:
        return []
    dtype = (inp.dissonance_type or "none").strip().lower()
    if dtype in {"", "none"}:
        return []

    mapping = DISSONANCE_VIOLATIONS.get(dtype)
    if not mapping:
        return []

    rule_id, title, hints = mapping
    if rule_id in _coverage_rule_ids(inp.coverage_items):
        return []
    evidence = "; ".join(q for q in inp.emotion_evidence_quotes[:2] if q)
    return [
        ViolationSpec(
            violation_key=f"dissonance:{dtype}",
            rule_ids=[rule_id],
            title=title,
            reasoning=_dissonance_reasoning(dtype, evidence),
            evidence_text=evidence or title,
            compliance_score=0.28,
            policy_match_hints=list(hints),
        )
    ]


def _derive_from_nli(inp: ViolationMappingInput) -> list[ViolationSpec]:
    category = (inp.nli_category or "").strip()
    if category not in NLI_VIOLATION_CATEGORIES:
        return []

    hints = ["refund", "compensation"]
    topic = (inp.nli_policy_category or "").lower()
    if any(token in topic for token in ("privacy", "security", "gdpr", "data")):
        hints = ["data privacy", "security"]
    elif any(token in topic for token in ("conduct", "communication", "greeting")):
        hints = ["call conduct"]

    evidence = "; ".join(q for q in inp.nli_evidence_quotes[:2] if q)
    return [
        ViolationSpec(
            violation_key=f"nli:{category}",
            rule_ids=[],
            title=f"NLI — {category}",
            reasoning=inp.nli_justification or f"Transcript-level NLI category: {category}.",
            evidence_text=evidence,
            compliance_score=0.18 if category == "Policy Hallucination" else 0.24,
            policy_match_hints=hints,
        )
    ]


def _sop_step_category(step: str) -> tuple[str, str, list[str]] | None:
    normalized = _normalize_lookup_text(step.replace("_", " "))
    for token, mapping in SOP_STEP_CATEGORY_HINTS.items():
        if token in normalized:
            return mapping
    return ("CS-RULE-019", f"Process — {step.replace('_', ' ').title()}", ["call conduct", "process"])


def _derive_from_missing_sop_steps(inp: ViolationMappingInput) -> list[ViolationSpec]:
    specs: dict[str, ViolationSpec] = {}
    for step in inp.missing_sop_steps:
        step_key = (step or "").strip()
        if not step_key:
            continue
        mapping = _sop_step_category(step_key)
        if not mapping:
            continue
        rule_id, title, hints = mapping
        category_key = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        spec = ViolationSpec(
            violation_key=f"sop:{category_key}",
            rule_ids=[rule_id],
            title=title,
            reasoning=inp.process_justification or f"Missing SOP step: {step_key}.",
            evidence_text="; ".join(q for q in inp.process_evidence_quotes[:1] if q) or step_key,
            compliance_score=0.32,
            policy_match_hints=list(hints),
        )
        bucket = specs.setdefault(spec.violation_key, spec)
        if bucket is not spec:
            _merge_spec(bucket, spec)
    return list(specs.values())


def _derive_from_attributions(
    items: list[dict[str, Any]],
    *,
    skip_emotion_cross_modal: bool = False,
    coverage_items: list[dict[str, Any]] | None = None,
) -> list[ViolationSpec]:
    specs: dict[str, ViolationSpec] = {}
    has_coverage_fail = _has_coverage_fail(coverage_items or [])
    for item in items:
        verdict = (item.get("verdict") or "").strip()
        if verdict not in NON_COMPLIANT_ATTRIBUTION_VERDICTS:
            continue
        family = (item.get("family") or "").strip().lower()
        if has_coverage_fail and family == "sop":
            continue
        if skip_emotion_cross_modal and family == "emotion" and verdict == "Cross-Modal Mismatch":
            continue
        attribution_id = (item.get("attribution_id") or item.get("attributionId") or "").strip()
        policy_ref = item.get("policy_reference") or item.get("policyReference") or {}
        rule_id = (policy_ref.get("rule_id") or policy_ref.get("ruleId") or "").strip().upper()
        rule_ids = [rule_id] if rule_id else []
        hints = _hints_for_rule_id(rule_id) if rule_id else ["call conduct"]
        if family == "sop":
            hints = ["call conduct", "process"]
        title = (item.get("title") or item.get("trigger_type") or item.get("triggerType") or "SOP attribution").strip()
        if verdict == "Cross-Modal Mismatch":
            dtype = "interruption"
            title = DISSONANCE_VIOLATIONS.get(dtype, ("", title, []))[1] or title
            if not rule_ids:
                rule_ids = ["CS-RULE-008"]
                hints = _hints_for_rule_id("CS-RULE-008")

        key = f"attribution:{attribution_id or title}:{verdict}"
        quotes = item.get("supporting_quotes") or item.get("supportingQuotes") or []
        evidence = "; ".join(q for q in quotes[:2] if q)
        attribution_reasoning = (item.get("reasoning") or "").strip()
        if family == "sop" and verdict == "Partial Attempt":
            attribution_reasoning = (
                attribution_reasoning
                or f"SOP adherence partial: {title}."
            )
        elif not attribution_reasoning:
            attribution_reasoning = f"Attribution verdict: {verdict}."
        spec = ViolationSpec(
            violation_key=key,
            rule_ids=rule_ids,
            title=title,
            reasoning=attribution_reasoning,
            evidence_text=evidence or title,
            compliance_score=0.3,
            policy_match_hints=list(hints),
        )
        bucket = specs.setdefault(spec.violation_key, spec)
        if bucket is not spec:
            _merge_spec(bucket, spec)
    return list(specs.values())


def derive_violation_specs(inp: ViolationMappingInput) -> list[ViolationSpec]:
    """Derive deduplicated violation specs from trigger / GT signals."""
    merged: dict[str, ViolationSpec] = {}

    def absorb(batch: list[ViolationSpec]) -> None:
        for spec in batch:
            bucket = merged.setdefault(spec.violation_key, spec)
            if bucket is not spec:
                _merge_spec(bucket, spec)

    absorb(_derive_from_coverage(inp.coverage_items))
    absorb(_derive_from_dissonance(inp))
    has_dissonance = any(key.startswith("dissonance:") for key in merged)
    has_coverage_fail = _has_coverage_fail(inp.coverage_items)
    coverage_rules = _coverage_rule_ids(inp.coverage_items)
    emotion_conduct_rules = frozenset(
        mapping[0] for mapping in DISSONANCE_VIOLATIONS.values()
    ) | frozenset({"CS-RULE-013"})
    skip_emotion_cross_modal = has_dissonance or bool(coverage_rules & emotion_conduct_rules)
    if not has_coverage_fail:
        absorb(_derive_from_nli(inp))
        absorb(_derive_from_missing_sop_steps(inp))
    absorb(
        _derive_from_attributions(
            inp.trigger_attributions,
            skip_emotion_cross_modal=skip_emotion_cross_modal,
            coverage_items=inp.coverage_items,
        )
    )

    return list(merged.values())


def resolve_policy_for_spec(
    policies: list[CompanyPolicy],
    spec: ViolationSpec,
) -> CompanyPolicy | None:
    if not policies:
        return None

    hints = [_normalize_lookup_text(h) for h in spec.policy_match_hints if h]
    for rule_id in spec.rule_ids:
        hints.extend(_hints_for_rule_id(rule_id))

    best_policy: CompanyPolicy | None = None
    best_score = -1
    for policy in policies:
        title_norm = _normalize_lookup_text(policy.policy_title)
        category_norm = _normalize_lookup_text(policy.policy_category)
        corpus = f"{title_norm} {category_norm}"
        score = 0
        for hint in hints:
            if not hint:
                continue
            if hint in corpus or hint in _normalize_lookup_text(policy.policy_text):
                score += 6
            score += len(set(hint.split()).intersection(set(corpus.split())))
        if score > best_score:
            best_score = score
            best_policy = policy

    return best_policy or policies[0]


async def load_active_org_policies(
    session: AsyncSession,
    organization_id: UUID,
) -> list[CompanyPolicy]:
    result = await session.exec(
        select(CompanyPolicy)
        .join(OrganizationPolicy, OrganizationPolicy.policy_id == CompanyPolicy.id)
        .where(
            OrganizationPolicy.organization_id == organization_id,
            OrganizationPolicy.is_active.is_(True),
            CompanyPolicy.is_active.is_(True),
        )
    )
    return list(result.all())


async def ensure_organization_policies_from_source(
    session: AsyncSession,
    target_organization_id: UUID,
    *,
    source_org_slug: str = "nexalink",
) -> int:
    """Link source org's active policies to target org when missing."""
    from app.models.organization import Organization

    source_result = await session.exec(select(Organization).where(Organization.slug == source_org_slug))
    source_org = source_result.first()
    if not source_org:
        return 0

    links_result = await session.exec(
        select(OrganizationPolicy).where(
            OrganizationPolicy.organization_id == source_org.id,
            OrganizationPolicy.is_active.is_(True),
        )
    )
    source_links = list(links_result.all())
    if not source_links:
        return 0

    existing_result = await session.exec(
        select(OrganizationPolicy.policy_id).where(
            OrganizationPolicy.organization_id == target_organization_id,
        )
    )
    existing_ids = {row for row in existing_result.all()}
    added = 0
    for link in source_links:
        if link.policy_id in existing_ids:
            continue
        session.add(
            OrganizationPolicy(
                organization_id=target_organization_id,
                policy_id=link.policy_id,
                is_active=True,
            )
        )
        added += 1
    if added:
        await session.flush()
    return added


async def persist_policy_violations(
    session: AsyncSession,
    *,
    interaction_id: UUID,
    organization_id: UUID,
    specs: list[ViolationSpec],
    replace_existing: bool = True,
) -> list[PolicyCompliance]:
    if replace_existing:
        from sqlalchemy import delete

        await session.exec(
            delete(PolicyCompliance).where(PolicyCompliance.interaction_id == interaction_id)
        )

    policies = await load_active_org_policies(session, organization_id)
    if not policies or not specs:
        return []

    rows: list[PolicyCompliance] = []
    for spec in specs:
        policy = resolve_policy_for_spec(policies, spec)
        if not policy:
            continue
        rows.append(
            PolicyCompliance(
                interaction_id=interaction_id,
                policy_id=policy.id,
                is_compliant=False,
                compliance_score=max(0.0, min(1.0, spec.compliance_score)),
                degraded=spec.degraded,
                llm_reasoning=spec.reasoning,
                evidence_text=spec.evidence_text or spec.title,
                retrieved_policy_text=policy.policy_text,
            )
        )
        session.add(rows[-1])

    if rows:
        await session.flush()
    return rows


def specs_to_api_violations(
    specs: list[ViolationSpec],
    *,
    interaction_id: str,
    policies: list[CompanyPolicy] | None = None,
) -> list[dict[str, Any]]:
    """Serialize violation specs to API policyViolations shape (dataset / preview)."""
    policies = policies or []
    rows: list[dict[str, Any]] = []
    for spec in specs:
        policy = resolve_policy_for_spec(policies, spec) if policies else None
        policy_title = policy.policy_title if policy else (spec.title or "Policy violation")
        category = policy.policy_category if policy else "Compliance"
        score_pct = round(spec.compliance_score * 100.0, 0)
        severity = "high" if spec.compliance_score < 0.3 else ("medium" if spec.compliance_score < 0.6 else "low")
        rows.append(
            {
                "interactionId": interaction_id,
                "policyName": policy_title,
                "policyTitle": policy_title,
                "category": category,
                "description": spec.evidence_text or spec.title,
                "reasoning": spec.reasoning,
                "degraded": spec.degraded,
                "severity": severity,
                "score": score_pct,
                "ruleIds": spec.rule_ids,
            }
        )
    return rows
