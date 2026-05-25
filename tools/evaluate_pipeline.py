#!/usr/bin/env python3
"""Evaluate pipeline output against ground truth across multiple dimensions.

For each (org, call):
  - Reads tools/reports/<org>/<CALL>_detail.json (pipeline output) and
    storage/audio/<org>/evaluation/<CALL>_*.json (ground truth)
  - Computes per-axis scores and dumps a report to tools/reports/EVAL_REPORT.{json,md}.

Axes:
  - agent_match            agent name matches GT primary_agent
  - turn_count_ratio       PR utterances / GT turns (1.0 ideal)
  - diarization_share      |PR agent_share - GT agent_share|  (lower = better)
  - emotion_distribution   cosine sim between PR fused dist and GT dist over canonical 7 labels
  - topic_match            does PR process_topic match expected_topic derived from GT sop_primary
  - resolution_match       PR resolved == GT_resolved (inferred from expected_outcome)
  - sop_retrieval_match    is the right SOP doc cited in trigger_attributions / claim_provenance
  - coverage_recall        for each GT coverage element, did PR mention/cover it (loose token overlap)
  - score_diff             per sub-score (overall/empathy/policy/resolution) just for inspection
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

CANONICAL_EMOTIONS = ("happy", "sad", "angry", "frustrated", "neutral", "surprised", "unknown")

# Map sop_primary text snippets to expected PR topic
SOP_TO_TOPIC = [
    (r"refund", "refund_request"),
    (r"billing", "billing_issue"),
    (r"plan change", "billing_issue"),
    (r"technical support|troubleshoot", "technical_support"),
    (r"account access|2FA|password|recovery|access recovery", "account_access"),
    (r"retention|cancel|cancellation", "retention"),
    (r"KYC|account opening", "account_opening"),
    (r"fraud|card fraud|reg e|dispute", "fraud_dispute"),
    (r"fee waiver|overdraft|adjustment", "fee_adjustment"),
    (r"AML|BSA|suspicious", "aml_review"),
]

# Map sop_primary to the *expected SOP doc filename token(s)*. Multiple
# tokens means the GT call legitimately covers either SOP (e.g. card-fraud
# disputes can be cited from BOTH the Reg E and Fraud Investigation SOPs).
SOP_TO_FILENAME: list[tuple[str, tuple[str, ...]]] = [
    (r"SOP-01.*Refund|01_refund", ("01_refund",)),
    (r"SOP-02.*Billing|02_billing", ("02_billing",)),
    (r"SOP-03.*Technical|03_technical", ("03_technical",)),
    (r"SOP-04.*Access|04_account_access", ("04_account_access",)),
    (r"SOP-05.*Retention|05_customer_retention", ("05_customer_retention",)),
    (r"BNK-SOP-01|01_account_opening", ("01_account_opening",)),
    (r"BNK-SOP-02|BNK-SOP-03|Card Fraud|Reg E|02_reg_e|03_fraud", ("02_reg_e", "03_fraud")),
    (r"BNK-SOP-04|fee waiver|04_account_closure", ("04_account_closure", "02_reg_e", "fee")),
    (r"BNK-SOP-05|05_aml", ("05_aml",)),
]


def expected_topic_from_sop(sop_primary: str | None) -> str | None:
    if not sop_primary:
        return None
    for pattern, topic in SOP_TO_TOPIC:
        if re.search(pattern, sop_primary, re.IGNORECASE):
            return topic
    return None


def expected_sop_tokens(sop_primary: str | None) -> tuple[str, ...]:
    if not sop_primary:
        return ()
    for pattern, tokens in SOP_TO_FILENAME:
        if re.search(pattern, sop_primary, re.IGNORECASE):
            return tokens
    return ()


def cosine_sim(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    av = [float(a.get(k, 0)) for k in keys]
    bv = [float(b.get(k, 0)) for k in keys]
    na = math.sqrt(sum(x * x for x in av)) or 1.0
    nb = math.sqrt(sum(x * x for x in bv)) or 1.0
    dot = sum(x * y for x, y in zip(av, bv))
    return dot / (na * nb)


def gt_agent_share(turns: list[dict]) -> tuple[int, int]:
    agent = sum(1 for t in turns if (t.get("speaker") or "").upper() == "AGENT")
    customer = sum(1 for t in turns if (t.get("speaker") or "").upper() == "CUSTOMER")
    return agent, customer


def pr_agent_share(utterances: list[dict]) -> tuple[int, int]:
    agent = sum(1 for u in utterances if (u.get("speaker") or "").lower() == "agent")
    customer = sum(1 for u in utterances if (u.get("speaker") or "").lower() == "customer")
    return agent, customer


def infer_gt_resolved(expected_outcome: str | None) -> bool:
    """Infer whether GT considers the call resolved on-the-line.
    Conservative: escalation/ticket-only-handoff counts as NOT resolved.
    """
    if not expected_outcome:
        return False
    text = expected_outcome.lower()
    # Hard negatives first (escalation / hand-off)
    hard_negative = (
        "manager approval ticket",
        "back-office ticket",
        "fraud investigation",
        "fraud operations ticket",
        "data compliance ticket",
        "manager approval",
        "ended in abuse",
        "termination",
        "three-strike",
        "dropped without resolution",
        "no resolution",
        "cannot resolve",
        "still open",
        "not resolved",
        "ticket opened (no resolution",
        "follow-up within",  # callback-only outcomes
    )
    if any(p in text for p in hard_negative):
        return False

    # Strong positives: concrete on-call outcome
    strong_positive = (
        "credit applied",
        "credit was applied",
        "credit of $",
        "refund applied",
        "waiver granted",
        "fee waived",
        "fee was waived",
        "fee waiver applied",
        "opens a new",
        "opens the account",
        "account opened",
        "successfully reset",
        "successfully enrolls",
        "walks the customer through enrolling",
        "completes full",  # "completes full 3-of-5 verification" etc.
        "pin reset",
        "plan upgrade applied",
        "upgraded to",
        "issue resolved",
        "resolved on the call",
        "applied directly",
        "without ticket",
        "without escalation",
    )
    return any(p in text for p in strong_positive)


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def coverage_recall(coverage_items: list[dict], pipeline_text_blob: str) -> tuple[float, list[dict]]:
    """Loose-overlap recall: an element is 'covered' if EITHER any policy rule ID
    from its notes appears in the transcript, OR ≥30% of the element's content
    tokens are present. This is intentionally lenient — it's a proxy not a proof
    that the agent followed the step verbatim.
    """
    if not coverage_items:
        return 1.0, []
    blob_lower = (pipeline_text_blob or "").lower()
    blob_toks = tokens(pipeline_text_blob)
    hits = []
    rule_id_re = re.compile(r"\b([A-Z]{2,5}-RULE-\d+)\b")
    for item in coverage_items:
        element = item.get("element", "")
        notes = item.get("notes", "")

        # Rule ID short-circuit: if the GT notes cite a rule like CS-RULE-001
        # and the transcript names that rule, count it as covered.
        rule_ids = rule_id_re.findall(f"{element} {notes}")
        if rule_ids and any(rid.lower() in blob_lower for rid in rule_ids):
            hits.append({"element": element, "matched": True, "overlap": 1.0, "rule_id_match": True})
            continue

        ref_toks = (tokens(element) | tokens(notes)) - {
            "and", "the", "for", "with", "via", "rule", "from", "via",
            "verbatim", "full", "sequence", "note", "notes", "cap",
        }
        if not ref_toks:
            hits.append({"element": element, "matched": True, "overlap": 0.0})
            continue
        overlap = len(ref_toks & blob_toks) / len(ref_toks)
        hits.append({
            "element": element,
            "overlap": round(overlap, 2),
            "matched": overlap >= 0.3,
        })
    matched = sum(1 for h in hits if h["matched"])
    return matched / len(hits), hits


def sop_retrieval_match(detail: dict, expected_tokens: tuple[str, ...]) -> tuple[bool | None, list[str]]:
    if not expected_tokens:
        return None, []
    cites: list[str] = []
    explain = (detail.get("llmTriggers") or {}).get("explainability") or {}
    for attr in (explain.get("triggerAttributions") or []):
        ref = (attr.get("policyReference") or {})
        cite = " ".join(str(v) for v in (ref.get("reference"), ref.get("provenance"), ref.get("clause")) if v)
        if cite:
            cites.append(cite[:200])
    for prov in (explain.get("claimProvenance") or []):
        ref = (prov.get("retrievedPolicy") or {})
        cite = " ".join(str(v) for v in (ref.get("reference"), ref.get("provenance"), ref.get("clause")) if v)
        if cite:
            cites.append(cite[:200])
    # Also sweep process_adherence.citations — the LLM cites the SOP source
    # in the SOP-source citation entries even when no missing step needs a
    # trigger attribution card.
    process = (detail.get("llmTriggers") or {}).get("processAdherence") or {}
    for c in (process.get("citations") or []):
        if (c.get("source") or "").lower() == "sop":
            cites.append((c.get("quote") or "")[:200])
    blob = " ".join(cites).lower()
    matched = any(token.lower() in blob for token in expected_tokens)
    return matched, cites


def evaluate_one(detail: dict, gt: dict) -> dict:
    inter = detail.get("interaction") or {}
    utts = detail.get("utterances") or []
    triggers = detail.get("llmTriggers") or {}
    process = (triggers or {}).get("processAdherence") or {}
    nli = (triggers or {}).get("nliPolicy") or {}
    shift = (triggers or {}).get("emotionShift") or {}

    # Agent match
    gt_agent = (gt.get("primary_agent") or "").strip()
    pr_agent = (inter.get("agentName") or "").strip()
    agent_match = bool(gt_agent and pr_agent.lower() == gt_agent.lower())

    # Turn count ratio
    gt_turns_total = gt.get("turn_count") or 0
    pr_utts_total = len(utts)
    turn_ratio = (pr_utts_total / gt_turns_total) if gt_turns_total else None

    # Diarization share
    gt_a, gt_c = gt_agent_share(gt.get("turns") or [])
    pr_a, pr_c = pr_agent_share(utts)
    gt_share = (gt_a / (gt_a + gt_c)) if (gt_a + gt_c) else None
    pr_share = (pr_a / (pr_a + pr_c)) if (pr_a + pr_c) else None
    diar_delta = abs(gt_share - pr_share) if (gt_share is not None and pr_share is not None) else None

    # Emotion distribution cosine
    gt_dist = gt.get("emotion_distribution") or {}
    ec = detail.get("emotionComparison") or {}
    pr_fused = {row.get("emotion"): row.get("count", 0) for row in ec.get("distributions", {}).get("fused", [])}
    pr_acoustic = {row.get("emotion"): row.get("count", 0) for row in ec.get("distributions", {}).get("acoustic", [])}
    emo_cos_fused = round(cosine_sim(gt_dist, pr_fused), 3)
    emo_cos_acoustic = round(cosine_sim(gt_dist, pr_acoustic), 3)

    # Topic match
    expected_topic = expected_topic_from_sop(gt.get("sop_primary"))
    pr_topic = process.get("detectedTopic")
    topic_match = (pr_topic == expected_topic) if expected_topic else None

    # Resolution match — prefer the fresh LLM trigger output over the
    # interaction_scores row, which is only updated on a full reprocess.
    gt_resolved = infer_gt_resolved(gt.get("expected_outcome"))
    pr_resolved = (
        bool(process.get("isResolved"))
        if process and "isResolved" in process
        else bool(inter.get("resolved"))
    )
    res_match = (gt_resolved == pr_resolved)

    # SOP retrieval match
    expected_sop = expected_sop_tokens(gt.get("sop_primary"))
    sop_match, citations = sop_retrieval_match(detail, expected_sop)

    # Coverage recall (matches GT coverage elements against full transcript text)
    transcript_blob = " ".join((u.get("text") or "") for u in utts)
    cov_recall, cov_hits = coverage_recall(gt.get("coverage") or [], transcript_blob)

    # Scores (raw, for inspection)
    scores = {
        "overall": inter.get("overallScore"),
        "empathy": inter.get("empathyScore"),
        "policy": inter.get("policyScore"),
        "resolution": inter.get("resolutionScore"),
    }

    return {
        "call_id": gt.get("call_id"),
        "agent_match": agent_match,
        "agent_gt": gt_agent, "agent_pr": pr_agent,
        "turn_ratio": round(turn_ratio, 2) if turn_ratio is not None else None,
        "gt_turns": gt_turns_total, "pr_utts": pr_utts_total,
        "diar_share_gt": round(gt_share, 2) if gt_share is not None else None,
        "diar_share_pr": round(pr_share, 2) if pr_share is not None else None,
        "diar_share_delta": round(diar_delta, 2) if diar_delta is not None else None,
        "emotion_cosine_fused": emo_cos_fused,
        "emotion_cosine_acoustic": emo_cos_acoustic,
        "topic_expected": expected_topic, "topic_pr": pr_topic, "topic_match": topic_match,
        "resolved_gt": gt_resolved, "resolved_pr": pr_resolved, "resolution_match": res_match,
        "sop_expected_tokens": list(expected_sop), "sop_retrieval_match": sop_match,
        "sop_citations_sample": citations[:2],
        "coverage_recall": round(cov_recall, 2),
        "coverage_missed": [h["element"] for h in cov_hits if not h["matched"]][:5],
        "scores": scores,
        "process_efficiency": process.get("efficiencyScore"),
        "nli_verdict": nli.get("nliCategory"),
        "trigger_attrib_count": len((triggers.get("explainability") or {}).get("triggerAttributions") or []),
    }


def load_pair(org: str, call_prefix: str) -> tuple[dict, dict] | None:
    detail_path = Path("tools/reports") / org / f"{call_prefix}_detail.json"
    if not detail_path.exists():
        return None
    eval_dir = Path("storage/audio") / org / "evaluation"
    matches = sorted(eval_dir.glob(f"{call_prefix}_*.json")) + sorted(eval_dir.glob(f"{call_prefix}.json"))
    if not matches:
        return None
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    gt = json.loads(matches[0].read_text(encoding="utf-8"))
    return detail, gt


def main() -> int:
    rows: list[dict] = []
    targets = {
        "nexalink": ["CALL_01", "CALL_07", "CALL_15"],
        "meridian": ["CALL_21", "CALL_24", "CALL_30"],
    }
    for org, calls in targets.items():
        for call in calls:
            pair = load_pair(org, call)
            if not pair:
                print(f"skip {org}/{call} (missing file)")
                continue
            detail, gt = pair
            row = evaluate_one(detail, gt)
            row["org"] = org
            rows.append(row)

    if not rows:
        print("no evaluations produced")
        return 1

    out_dir = Path("tools/reports")
    out_dir.mkdir(exist_ok=True, parents=True)
    (out_dir / "EVAL_REPORT.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # Aggregate
    def avg(key, allow_none=True):
        vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    def pct_true(key):
        vals = [r.get(key) for r in rows if isinstance(r.get(key), bool)]
        return round(100 * sum(vals) / len(vals), 1) if vals else None

    summary = {
        "n_calls": len(rows),
        "agent_match_pct": pct_true("agent_match"),
        "topic_match_pct": pct_true("topic_match"),
        "resolution_match_pct": pct_true("resolution_match"),
        "sop_retrieval_match_pct": pct_true("sop_retrieval_match"),
        "avg_turn_ratio (1.0 ideal)": avg("turn_ratio"),
        "avg_diar_share_delta (0 ideal)": avg("diar_share_delta"),
        "avg_emotion_cosine_fused (1 ideal)": avg("emotion_cosine_fused"),
        "avg_emotion_cosine_acoustic (1 ideal)": avg("emotion_cosine_acoustic"),
        "avg_coverage_recall (1 ideal)": avg("coverage_recall"),
    }

    md_lines = ["# Pipeline Evaluation vs Ground Truth", "", f"N calls: {len(rows)}", "", "## Aggregate"]
    for k, v in summary.items():
        md_lines.append(f"- **{k}**: {v}")
    md_lines.append("")
    md_lines.append("## Per call")
    md_lines.append("")
    md_lines.append("| call | agent | turn_ratio | diar_delta | emo_cos_fused | topic | sop_retrieved | resolved | cov_recall | NLI | eff |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        cid = r["call_id"] or "?"
        agent = "✓" if r["agent_match"] else "✗"
        tm = "✓" if r["topic_match"] else ("✗" if r["topic_match"] is False else "?")
        res = "✓" if r["resolution_match"] else "✗"
        sop = "✓" if r["sop_retrieval_match"] else ("✗" if r["sop_retrieval_match"] is False else "?")
        md_lines.append(
            f"| {cid} | {agent} {r['agent_pr']} | {r['turn_ratio']} ({r['pr_utts']}/{r['gt_turns']}) | "
            f"{r['diar_share_delta']} (PR {r['diar_share_pr']} vs GT {r['diar_share_gt']}) | "
            f"{r['emotion_cosine_fused']} | "
            f"{tm} PR={r['topic_pr']} expect={r['topic_expected']} | "
            f"{sop} expect={r['sop_expected_tokens']} | "
            f"{res} (PR {r['resolved_pr']} / GT {r['resolved_gt']}) | "
            f"{r['coverage_recall']} | {r['nli_verdict']} | {r['process_efficiency']} |"
        )
    (out_dir / "EVAL_REPORT.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nFull report: tools/reports/EVAL_REPORT.md  +  EVAL_REPORT.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
