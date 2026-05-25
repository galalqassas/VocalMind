# Pipeline Evaluation Tools

Reproducible harness for comparing the LLM-trigger pipeline output against
the synthesized ground-truth scripts in `storage/audio/<org>/evaluation/`.

## Files

| File | Purpose |
|---|---|
| `reprocess_and_compare.py` | Logs into the backend as the org manager, optionally `POST /reprocess` per call, polls the processing status, then `GET /interactions/{id}?include_llm_triggers=true&llm_force_rerun=true` and writes the full detail + ground truth + summary diff to `tools/reports/<org>/`. |
| `evaluate_pipeline.py` | Reads the per-call detail JSON from `tools/reports/<org>/` and the matching `storage/audio/<org>/evaluation/<call>_*.json`, then computes 8 axis scores (agent match, topic, SOP retrieval, resolution, turn ratio, diarization delta, emotion cosine, coverage recall) and writes `tools/reports/EVAL_REPORT.{md,json}`. |
| `compare_summary.py` | Pretty-prints the per-call comparison from `tools/reports/<org>/_all_compare.json`. |

`tools/reports/` is **gitignored** — outputs are regenerable.

## Usage

```bash
# 1) Reprocess (re-transcribe + re-run LLM triggers) on a comma-separated list of calls
python tools/reprocess_and_compare.py --org nexalink --calls CALL_01,CALL_07,CALL_15
python tools/reprocess_and_compare.py --org meridian --calls CALL_21,CALL_24,CALL_30

# 1b) Refresh just the LLM trigger output (no retranscribe) — much faster
python tools/reprocess_and_compare.py --org nexalink --calls CALL_01 --no-reprocess

# 2) Score against ground truth
python tools/evaluate_pipeline.py
#    → tools/reports/EVAL_REPORT.md   (markdown table)
#    → tools/reports/EVAL_REPORT.json (machine-readable)

# 3) Optional: pretty-print one org's per-call diff
python tools/compare_summary.py --org nexalink
```

## What the eval measures

| axis | what it scores | source of truth |
|---|---|---|
| `agent_match` | did the pipeline assign the right agent? | `gt.primary_agent` vs `interaction.agentName` |
| `topic_match` | did `processAdherence.detectedTopic` match the SOP family the call should follow? | regex over `gt.sop_primary` → expected topic |
| `sop_retrieval_match` | did the pipeline cite the correct SOP source_file? | substring search across `triggerAttributions.policyReference.reference`, `claimProvenance.retrievedPolicy.reference`, and `processAdherence.citations[source=sop].quote` |
| `resolution_match` | did the pipeline correctly mark the call resolved or escalated? | prefers `processAdherence.isResolved`, falls back to `interaction.resolved` |
| `turn_ratio` | over/under-segmentation, `PR utts / GT turns` (1.0 ideal) | `len(utterances)` vs `gt.turn_count` |
| `diar_share_delta` | how off is the agent/customer ratio? | `|PR agent_share − GT agent_share|` |
| `emotion_cosine_fused` | how close is the PR emotion distribution to GT? cosine over canonical 7 labels | `emotionComparison.distributions.fused` vs `gt.emotion_distribution` |
| `coverage_recall` | for each GT coverage element, did the transcript actually contain it? | loose token overlap (≥ 30 %) or a verbatim rule-ID match |

## Prereqs

- Backend running on `http://localhost:8000` (native or Docker)
- Audio files accessible to the backend — either via `LOCAL_AUDIO_STORAGE_DIR` mount or via `EXTRA_AUDIO_ROOTS` env var
- For ground-truth lookup, the `storage/audio/<org>/evaluation/` folder needs to be present in the worktree (junction-linked from the original repo is fine)
