#!/usr/bin/env python3
"""Print a side-by-side summary table from tools/reports/<org>/_all_compare.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def fmt(value, max_len: int = 60) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"[{len(value)}]"
    s = str(value)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True, choices=["nexalink", "meridian"])
    args = parser.parse_args()

    path = Path("tools/reports") / args.org / "_all_compare.json"
    if not path.exists():
        sys.exit(f"missing {path}")

    rows = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n=== {args.org} — {len(rows)} call(s) ===\n")

    for row in rows:
        gt = row.get("ground_truth") or {}
        pr = row.get("pipeline_result") or {}
        print(f"\n----- {row['call_id']} -----")
        agent_str = (gt.get('primary_agent') or '?')[:8]
        print(f"GT  agent={agent_str:<8} turns={gt.get('turn_count')}  dur={gt.get('duration_estimate')}  sop={gt.get('sop_primary')}")
        print(f"PR  agent={fmt(pr.get('agent')):<8} utts ={pr.get('utterance_count')}  dur={pr.get('duration')}  topic={fmt(pr.get('process_topic'))}")
        print(f"GT  emotion_dist={gt.get('emotion_distribution')}")
        print(f"PR  ac_dist     ={pr.get('emotion_distribution_acoustic')}")
        print(f"PR  tx_dist     ={pr.get('emotion_distribution_text')}")
        print(f"PR  fused_dist  ={pr.get('emotion_distribution_fused')}")
        scores = pr.get("scores") or {}
        print(f"PR  scores overall={scores.get('overall')} empathy={scores.get('empathy')} policy={scores.get('policy')} resolution={scores.get('resolution')}  resolved={pr.get('resolved')}")
        print(f"PR  LLM available={pr.get('llm_trigger_available')}  process_resolved={pr.get('process_resolved')}  eff={pr.get('process_efficiency')}")
        print(f"PR  process missing steps: {pr.get('process_missing_steps')}")
        print(f"PR  policy NLI verdict={pr.get('policy_nli_verdict')} alignment={pr.get('policy_alignment')}  violations={pr.get('policy_violations')}")
        print(f"PR  emotion dissonance={pr.get('emotion_dissonance')} type={fmt(pr.get('emotion_dissonance_type'))}")
        print(f"PR  trigger_attributions={len(pr.get('explain_trigger_attributions') or [])}  claim_provenance={len(pr.get('explain_claim_provenance') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
