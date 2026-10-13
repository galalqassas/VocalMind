# Evaluation Harnesses

There are two independent harnesses:

| Harness | Location | Input | Output |
|---|---|---|---|
| Component quality gates | `infra/scripts/eval/` | Gold files in `infra/benchmarks/expected/` and a predictions JSON | `infra/benchmarks/reports/*_report.json`; exits 1 on regression |
| Pipeline vs ground truth | `tools/` | Live backend API and `storage/audio/<org>/evaluation/*.json` | `tools/reports/EVAL_REPORT.{md,json}` (gitignored) |

RAGAS evaluation of the RAG service is a separate tool: [RAGAS_EVALUATION.md](../rag/RAGAS_EVALUATION.md).

## 1. Component quality gates (`infra/scripts/eval/`)

| Command | Script | Measures |
|---|---|---|
| `make quality-eval-transcript` | `eval_transcript.py` | WER and speaker accuracy |
| `make quality-eval-emotion` | `eval_emotion.py` | Emotion label F1 and shift F1 |
| `make quality-eval-policy` | `eval_policy.py` | Violation precision/recall and policy attribution |
| `make quality-eval-rag` | `eval_rag.py` | Answer correctness and evidence coverage |
| `make quality-eval-resolution` | `eval_resolution.py` | Resolved accuracy and missing-step F1 |
| `make quality-eval-all` | `eval_all.py` | All five above; writes `aggregate_report.json` |

- Thresholds live in `infra/benchmarks/schema/thresholds.json`, and a component fails when it misses one.
- Every script takes `--predictions`. The default is `infra/benchmarks/fixtures/baseline_predictions.json`, a committed snapshot, so `make quality-eval-all` checks the evaluators against that snapshot and does not run the live pipeline.
- To score live output, run `extract_pipeline_predictions.py --token <JWT> --pair CALL_01=<uuid> ...`. It **overwrites** `baseline_predictions.json` unless you pass `--output`. Known issue: the script requests `/api/interactions/{id}` without the `/v1` prefix, so it currently fails against the backend.

Supporting scripts:

- `generate_nexalink_gold.py` rebuilds `expected/*_gold.json` from `storage/audio/nexalink/evaluation/CALL_01`–`CALL_05`.
- `make_oracle_predictions.py` writes `fixtures/oracle_predictions.json`, which mirrors the gold files and should score 100%. Use it to check that the evaluators are wired correctly.
- `eval_pipeline_audio_live.py` and `build_transcript_predictions_from_db.py` read stored utterances straight from Postgres (`localhost:5434`) to measure real WER and speaker accuracy. Both hardcode interaction UUIDs in `CALL_MAP`; edit the map for your database.
- `eval_diarization.py` downloads VoxConverse and computes DER against the WhisperX service (`--server-url`, default `http://localhost:8003`).

## 2. Pipeline vs ground truth (`tools/`)

Logs in as the org manager, optionally reprocesses selected calls, fetches the full detail with LLM triggers, and scores 8 axes: agent, topic, resolution, SOP retrieval, turn ratio, diarization share delta, fused emotion cosine and coverage recall. Usage and axis definitions: [tools/README.md](../../tools/README.md). Dated results: [PIPELINE_FINDINGS.md](../eval/PIPELINE_FINDINGS.md).

## Rate limits

Each processed call runs three LLM chains. `_invoke_chain_with_retry` in `backend/app/llm_trigger/chains.py` makes up to 3 attempts on transient errors (rate limit, timeout, connection), with exponential backoff between them. If the provider stays rate-limited, the trigger stage falls back to its deterministic heuristics, which skews scores, so check the backend logs before trusting a run.
