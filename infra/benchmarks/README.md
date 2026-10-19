# Benchmarks

Data for the component quality gates in `infra/scripts/eval/eval_*.py`. Paths are defined in `infra/scripts/eval/eval_common.py`. Usage: [docs/operations/EVALUATION_HARNESS.md](../../docs/operations/EVALUATION_HARNESS.md).

| Path | Contents |
|---|---|
| `expected/` | Gold labels per component: `transcript`, `emotion`, `policy`, `rag`, `resolution` (`*_gold.json`), plus `embedding_pairs.json`. Regenerate with `infra/scripts/eval/generate_nexalink_gold.py`. |
| `fixtures/` | Prediction inputs. `baseline_predictions.json` (default input, committed snapshot), `oracle_predictions.json` (mirror of gold, should score 100%), and `pipeline_predictions_live.json` (from `build_transcript_predictions_from_db.py`). |
| `schema/thresholds.json` | Pass/fail thresholds per component (also diarization and RAGAS). |
| `reports/` | Evaluator outputs (`*_report.json`, `aggregate_report.json`). `reports/overnight_20260614/FINAL_*.md` holds the final LLM model-selection results. |

Run every gate from the repo root (exits 1 if any component fails):

```bash
make quality-eval-all
```
