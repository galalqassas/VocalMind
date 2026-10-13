# Per-Call Cost Model

> **Targets and estimates, not measured.** Nothing in the repo records cost or token usage. The `/metrics` endpoint (`prometheus_fastapi_instrumentator` in `backend/app/main.py`) exposes HTTP metrics only. Re-derive the figures from real billing before quoting them.

## Cost drivers (from code)

| Component | What costs money | Scales with | Knobs |
|---|---|---|---|
| Speech models (default: Kaggle `services/kaggle/server.py`; or `services/whisperx` + `services/emotion` in profile `local-ml`) | GPU time for ASR, diarization and per-segment emotion2vec | Audio length and segment count | Kaggle: free GPU quota. Local: `WHISPER_MODEL_SIZE` (default `large-v2`), `WHISPER_BATCH_SIZE`, `WHISPER_COMPUTE_TYPE`, GPU overlay |
| Text emotion | One `/predict_text` call per utterance on each detail read, plus one per trigger run | Utterances | none |
| LLM calls (`backend/app/llm_trigger/`) | Per call: `is_gibberish` gate, topic classification, three chains (emotion shift, process adherence over at most 3 8-turn windows, NLI policy), plus the `PolicyComplianceEvaluator` judge | Transcript length | `LLM_PROVIDER`; per-stage model overrides (see `backend/.env.example`) |
| Manager Assistant | One or more LLM calls per question (SQL generation, repair, answer) | Questions asked, not calls processed | `ASSISTANT_LLM_PROVIDER` |
| RAG | Qdrant container; embeddings, parsing and reranking on Kaggle (or Ollama + in-process models) at ingest and per query | Documents and queries | `RAG_MODELS_HOST` |
| Postgres + `storage/` | DB and disk | Fixed (small) | none |

Compose defaults: `LLM_PROVIDER=ollama_cloud` (heavy `kimi-k2.6:cloud`, fast `ministral-3:8b`) and `ASSISTANT_LLM_PROVIDER=ollama_cloud`. On a flat-rate LLM plan, the marginal LLM cost per call is about zero until the plan's limits are hit, which leaves GPU time as the dominant variable cost.

## Model

```
cost/call ≈ GPU_seconds(ASR + diarization + emotion) × GPU_rate     # 0 on the free Kaggle quota
          + Σ_llm_calls (input_tokens × in_price + output_tokens × out_price)    # 0 on flat-rate plans
          + fixed_infra / calls_per_month
```

Inputs to measure before using this model:

- GPU seconds per audio minute for speech inference, from processing-job timestamps (`processing_jobs.started_at` / `completed_at`).
- Tokens per LLM call. Nothing logs these today.
- Current GPU and LLM provider rate cards.

## Target

- Keep the variable cost per 5-minute call under **$0.10** and make GPU the only meaningful variable term. This is a target, not an observation.

## Levers, in expected order of impact

1. **GPU utilisation.** One in-process worker handles one interaction at a time (see [ADR-002](ADR-002-job-queue.md)), so the GPU idles between stages. Spot or on-demand GPU pricing matters more than anything else here.
2. **ASR model size.** Kaggle uses Whisper `medium`; local WhisperX defaults to `large-v2`. Smaller trades GPU time for accuracy. Re-run the transcript gate (`make quality-eval-transcript`) after changing it.
3. **Prompt size.** Fewer or smaller rolling windows, or fewer few-shot examples, cut tokens on metered providers.

Related: [SLA.md](SLA.md) (latency targets), [ADR-001](ADR-001-architecture.md) (why models are isolated behind HTTP).
