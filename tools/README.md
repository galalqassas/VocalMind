# Pipeline Evaluation Tools

A harness that compares live pipeline output with the ground-truth call JSONs in `storage/audio/<org>/evaluation/`. For an overview of all harnesses, see [docs/operations/EVALUATION_HARNESS.md](../docs/operations/EVALUATION_HARNESS.md). Outputs go to `tools/reports/`, which is gitignored.

## Files

| File | Purpose |
|---|---|
| `reprocess_and_compare.py` | Logs in as the seeded org manager. Optionally calls `POST /interactions/{id}/reprocess` (retries with `?force=true` on 409) and polls `/processing-status`. Then fetches `GET /interactions/{id}?include_llm_triggers=true&llm_force_rerun=true` and writes `tools/reports/<org>/<CALL>_{detail,gt,compare}.json`. |
| `evaluate_pipeline.py` | Scores the `*_detail.json` files against ground truth for a fixed 9-call set (nexalink CALL_01/06/07/15, meridian CALL_21/22/24/30/35); missing files are skipped. Writes `tools/reports/EVAL_REPORT.{md,json}`. |
| `compare_summary.py` | Prints the per-call table from `tools/reports/<org>/_all_compare.json`. |
| `download_mlflow_model.py` | Lists or downloads runs of the `customer-agent-classification` experiment on DagsHub MLflow. Needs `MLFLOW_TRACKING_PASSWORD`. Its default `--output-dir` (`services/whisperx/models/speaker_role`) is not used at runtime; the backend loads `backend/app/core/model.pkl` + `vectorizer.pkl`. |
| `sync_remote_supabase.sql` | One-off SQL that deletes the legacy NileTech/CairoConnect orgs from a Supabase database. |

## Usage

```bash
python tools/reprocess_and_compare.py --org nexalink --calls CALL_01,CALL_07,CALL_15
python tools/reprocess_and_compare.py --org nexalink --calls CALL_01 --no-reprocess   # LLM triggers only
python tools/evaluate_pipeline.py
python tools/compare_summary.py --org nexalink
```

Run the commands from the repo root; the scripts use relative paths.

## Axes (`evaluate_pipeline.py`)

| Axis | Scores | Source |
|---|---|---|
| `agent_match` | Right agent assigned | `gt.primary_agent` vs `agentName` |
| `topic_match` | Detected topic matches the expected SOP family | `processAdherence.detectedTopic` vs topic derived from `gt.sop_primary` |
| `sop_retrieval_match` | Correct SOP file cited | Trigger attributions, claim provenance, and `processAdherence.citations` |
| `resolution_match` | Resolved/escalated matches GT | `processAdherence.isResolved`, falling back to `interaction.resolved` |
| `turn_ratio` | Over/under-segmentation (1.0 ideal) | Utterance count / `gt.turn_count` |
| `diar_share_delta` | Agent talk-share error (0 ideal) | \|PR agent share − GT agent share\| |
| `emotion_cosine_fused` | Emotion distribution similarity over 7 canonical labels | `emotionComparison.distributions.fused` vs `gt.emotion_distribution` |
| `coverage_recall` | GT coverage elements present in the transcript | ≥ 30 % token overlap, or a verbatim rule-ID match |

## Prerequisites

- Backend on `http://localhost:8000` with the seeded NexaLink/Meridian managers (password `password123`).
- The backend can resolve the audio files, via `LOCAL_AUDIO_STORAGE_DIR` or `EXTRA_AUDIO_ROOTS`.
- `storage/audio/<org>/evaluation/` is present for ground-truth lookup.
