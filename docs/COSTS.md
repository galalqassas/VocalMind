# Per-Call Cost Model

> **Targets and estimates, not measured.** Nothing in the repo records cost or token usage. The `/metrics` endpoint (`prometheus_fastapi_instrumentator` in `backend/app/main.py`) exposes HTTP metrics only. Re-derive the figures from real billing before quoting them.

## Cost drivers (from code)

| Component | What costs money | Scales with | Knobs |
|---|---|---|---|
| WhisperX (`services/whisperx`) | GPU time for ASR, alignment and PyAnnote diarization | Audio length | `WHISPER_MODEL_SIZE` (default `large-v2`), `WHISPER_BATCH_SIZE`, `WHISPER_COMPUTE_TYPE` |
| Emotion (`services/emotion`) | emotion2vec inference per segment | Segment count (each clip capped at `EMOTION_MAX_AUDIO_SECONDS`, default 30) | GPU overlay `docker-compose.gpu.yml` |
| VAD (`services/vad`) | Silero, small | Audio length | none |
| LLM triggers (`backend/app/llm_trigger/`) | Three chains per call (emotion shift, process adherence, NLI policy) over 8-turn windows (stride 4, at most 3 process windows) | Transcript length | `LLM_PROVIDER`; per-stage model overrides (see `backend/.env.example`) |
| Manager Assistant | One or more LLM calls per question (SQL generation, repair, answer) | Questions asked, not calls processed | `ASSISTANT_LLM_PROVIDER` |
| RAG | Qdrant and Ollama (`snowflake-arctic-embed2`) containers; embeddings at ingest only | Fixed | none |
| Postgres + `storage/` | DB and disk | Fixed (small) | none |

Compose defaults: `LLM_PROVIDER=ollama_cloud` (heavy `kimi-k2.6:cloud`, fast `ministral-3:8b`) and `ASSISTANT_LLM_PROVIDER=ollama_cloud`. On a flat-rate LLM plan, the marginal LLM cost per call is about zero until the plan's limits are hit, which leaves GPU time as the dominant variable cost.

## Model

```
cost/call ≈ GPU_seconds(WhisperX + emotion) × GPU_rate
          + Σ_chains (input_tokens × in_price + output_tokens × out_price)    # 0 on flat-rate plans
          + fixed_infra / calls_per_month
```

Inputs to measure before using this model:

- GPU seconds per audio minute for WhisperX and emotion, from processing-job timestamps (`processing_jobs.started_at` / `completed_at`).
- Tokens per chain per call. Nothing logs these today.
- Current GPU and LLM provider rate cards.

## Target

- Keep the variable cost per 5-minute call under **$0.10** and make GPU the only meaningful variable term. This is a target, not an observation.

## Levers, in expected order of impact

1. **GPU utilisation.** One in-process worker handles one interaction at a time (see [ADR-002](ADR-002-job-queue.md)), so the GPU idles between stages. Spot or on-demand GPU pricing matters more than anything else here.
2. **WhisperX model size.** `medium` vs `large-v2` trades GPU time for accuracy. Re-run the transcript gate (`make quality-eval-transcript`) after changing it.
3. **Prompt size.** Fewer or smaller rolling windows, or fewer few-shot examples, cut tokens on metered providers.

Related: [SLA.md](SLA.md) (latency targets), [ADR-001](ADR-001-architecture.md) (why WhisperX is isolated).
