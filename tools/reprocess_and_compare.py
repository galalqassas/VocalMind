#!/usr/bin/env python3
"""Reprocess selected interactions and dump their detail JSON next to GT for diffing.

Usage:
  python tools/reprocess_and_compare.py --org nexalink --calls CALL_01,CALL_06,CALL_15
  python tools/reprocess_and_compare.py --org meridian --calls CALL_21,CALL_30,CALL_34
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
GT_DIR = Path("storage/audio")
OUT_DIR = Path("tools/reports")

MANAGERS = {
    "nexalink": ("manager@nexalink.com", "password123"),
    "meridian": ("manager@meridian.com", "password123"),
}


def http(method: str, url: str, *, data: dict | bytes | None = None,
         headers: dict[str, str] | None = None, timeout: float = 60.0,
         retries: int = 4):
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except (ConnectionResetError, urllib.error.URLError, OSError) as e:
            last_exc = e
            if attempt == retries:
                break
            time.sleep(2 ** attempt)
    raise last_exc  # type: ignore[misc]


def login(org: str) -> str:
    email, password = MANAGERS[org]
    form = urllib.parse.urlencode({"username": email, "password": password}).encode()
    status, body = http("POST", f"{BASE}/auth/login/access-token", data=form,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        sys.exit(f"login failed {status}: {body}")
    return json.loads(body)["access_token"]


def list_interactions(token: str) -> list[dict]:
    status, body = http("GET", f"{BASE}/interactions", headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        sys.exit(f"list failed {status}: {body}")
    return json.loads(body)


def reprocess(token: str, interaction_id: str) -> None:
    for force in (False, True):
        url = f"{BASE}/interactions/{interaction_id}/reprocess" + ("?force=true" if force else "")
        status, body = http("POST", url, headers={"Authorization": f"Bearer {token}"})
        if status == 200:
            return
        if status == 409 and not force:
            continue
        sys.exit(f"reprocess {interaction_id} failed {status}: {body}")


def poll_until_done(token: str, interaction_id: str, max_wait: int = 900) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + max_wait
    last = ""
    while time.time() < deadline:
        status, body = http("GET", f"{BASE}/interactions/{interaction_id}/processing-status", headers=headers)
        if status == 200:
            d = json.loads(body)
            s = (d.get("status") or "").lower()
            if s != last:
                print(f"  [{interaction_id[:8]}] status -> {s}")
                last = s
            if s in {"completed", "failed"}:
                return s
        time.sleep(5)
    return "timeout"


def fetch_detail(token: str, interaction_id: str) -> dict:
    url = f"{BASE}/interactions/{interaction_id}?include_llm_triggers=true&llm_force_rerun=true"
    status, body = http("GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=700.0)
    if status != 200:
        sys.exit(f"detail {interaction_id} failed {status}: {body}")
    return json.loads(body)


def find_interaction(interactions: list[dict], call_id_prefix: str) -> dict | None:
    """Match call by prefix like 'CALL_01' against audio_file_path."""
    norm = call_id_prefix.upper()
    for it in interactions:
        path = (it.get("audioFilePath") or "").upper()
        if f"/{norm}_" in path or path.endswith(f"/{norm}.WAV") or f"\\{norm}_" in path:
            return it
    return None


def load_ground_truth(org: str, call_id_prefix: str) -> dict | None:
    eval_dir = GT_DIR / org / "evaluation"
    matches = list(eval_dir.glob(f"{call_id_prefix}_*.json")) + list(eval_dir.glob(f"{call_id_prefix}.json"))
    if not matches:
        return None
    return json.loads(matches[0].read_text(encoding="utf-8"))


def gt_summary(gt: dict) -> dict:
    """Boil GT down to a comparable shape."""
    return {
        "call_id": gt.get("call_id"),
        "primary_agent": gt.get("primary_agent"),
        "turn_count": gt.get("turn_count"),
        "duration_estimate": gt.get("duration_estimate"),
        "emotion_distribution": gt.get("emotion_distribution"),
        "sop_primary": gt.get("sop_primary"),
        "policy_refs": gt.get("policy_refs"),
        "kb_refs": gt.get("kb_refs"),
        "expected_outcome": gt.get("expected_outcome"),
        "emotional_arc": gt.get("emotional_arc"),
        "coverage_elements": [c.get("element") for c in gt.get("coverage") or []],
    }


def detail_summary(detail: dict) -> dict:
    inter = detail.get("interaction") or {}
    utts = detail.get("utterances") or []
    triggers = detail.get("llmTriggers") or {}
    ec = detail.get("emotionComparison") or {}
    nli = (triggers or {}).get("nliPolicy") or {}
    process = (triggers or {}).get("processAdherence") or {}
    shift = (triggers or {}).get("emotionShift") or {}
    explain = (triggers or {}).get("explainability") or {}

    def dist(items): return {i["emotion"]: i["count"] for i in (items or [])}

    return {
        "agent": inter.get("agentName"),
        "duration": inter.get("duration"),
        "utterance_count": len(utts),
        "scores": {
            "overall": inter.get("overallScore"),
            "empathy": inter.get("empathyScore"),
            "policy": inter.get("policyScore"),
            "resolution": inter.get("resolutionScore"),
        },
        "resolved": inter.get("resolved"),
        "status": inter.get("status"),
        "emotion_distribution_acoustic": dist(ec.get("distributions", {}).get("acoustic")),
        "emotion_distribution_text": dist(ec.get("distributions", {}).get("text")),
        "emotion_distribution_fused": dist(ec.get("distributions", {}).get("fused")),
        "acoustic_text_agreement_rate": ec.get("quality", {}).get("acousticTextAgreementRate"),
        "llm_trigger_available": triggers.get("available"),
        "process_topic": process.get("detectedTopic"),
        "process_resolved": process.get("isResolved"),
        "process_efficiency": process.get("efficiencyScore"),
        "process_missing_steps": process.get("missingSopSteps"),
        "policy_nli_verdict": nli.get("nliCategory"),
        "policy_alignment": nli.get("policyAlignmentScore"),
        "policy_violations": len(detail.get("policyViolations") or []),
        "emotion_dissonance": shift.get("isDissonanceDetected"),
        "emotion_dissonance_type": shift.get("dissonanceType"),
        "explain_trigger_attributions": [
            {"family": t.get("family"), "title": t.get("title"), "verdict": t.get("verdict")}
            for t in (explain.get("triggerAttributions") or [])
        ],
        "explain_claim_provenance": [
            {"verdict": c.get("nliVerdict"), "claim": (c.get("claimText") or "")[:120]}
            for c in (explain.get("claimProvenance") or [])
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True, choices=["nexalink", "meridian"])
    parser.add_argument("--calls", required=True, help="Comma-separated CALL prefixes, e.g. CALL_01,CALL_06")
    parser.add_argument("--no-reprocess", action="store_true", help="Skip reprocess; just fetch & dump")
    args = parser.parse_args()

    call_prefixes = [c.strip() for c in args.calls.split(",") if c.strip()]
    out_dir = OUT_DIR / args.org
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Login as {args.org} manager...")
    token = login(args.org)

    print("Listing interactions...")
    interactions = list_interactions(token)

    summary_rows = []
    for prefix in call_prefixes:
        print(f"\n=== {prefix} ===")
        inter = find_interaction(interactions, prefix)
        if not inter:
            print(f"  no DB interaction matching {prefix}")
            continue
        iid = inter["id"]
        gt = load_ground_truth(args.org, prefix)

        if not args.no_reprocess:
            print(f"  reprocess id={iid[:8]} status={inter.get('status')}")
            reprocess(token, iid)
            outcome = poll_until_done(token, iid)
            print(f"  pipeline outcome: {outcome}")

        print(f"  fetching detail with LLM triggers...")
        detail = fetch_detail(token, iid)

        (out_dir / f"{prefix}_detail.json").write_text(
            json.dumps(detail, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if gt:
            (out_dir / f"{prefix}_gt.json").write_text(
                json.dumps(gt, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        side_by_side = {
            "call_id": prefix,
            "ground_truth": gt_summary(gt) if gt else None,
            "pipeline_result": detail_summary(detail),
        }
        (out_dir / f"{prefix}_compare.json").write_text(
            json.dumps(side_by_side, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        summary_rows.append(side_by_side)

    (out_dir / "_all_compare.json").write_text(
        json.dumps(summary_rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(summary_rows)} comparison files to {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
