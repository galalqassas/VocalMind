# System Overview

Multi-tenant call-center QA: audio → transcript + diarization → emotion → LLM trigger reasoning → scores → dashboard. Service wiring is defined in `docker-compose.yml` (GPU overlay: `docker-compose.gpu.yml`).

## Components

| Compose service | Host → container port | Code | Role |
|---|---|---|---|
| `frontend` | 3000 | `frontend/` | React SPA; Vite dev server proxies `/api` to the backend (`VITE_DEV_PROXY_TARGET`) |
| `backend` | 8000 | `backend/app/` | FastAPI API, in-process processing worker, LLM trigger engine, assistant |
| `db` | 5434 → 5432 | `infra/db/` | PostgreSQL 17 (init scripts mounted from `infra/db`) |
| `whisperx` | 8003 → 8000 | `services/whisperx/app.py` | ASR + alignment + diarization (`POST /transcribe`) |
| `emotion` | 8001 → 8000 | `services/emotion/app.py` | emotion2vec acoustic emotion (`/predict`) + DistilRoBERTa text emotion (`/predict_text`) |
| `vad` | 8002 | `services/vad/app.py` | Silero VAD splitter (`/split`); not used by the main worker pipeline |
| `qdrant` | 6333, 6334 | — | Vector store (`vocalmind_parents`, `vocalmind_children`, `vocalmind_sop_parents`) |
| `ollama` | 11434 | — | Local embeddings (`snowflake-arctic-embed2`) |
| `ingestion` | — | `services/rag/` | Runs `main.py --watch`: PDFs in `storage/docs` → Qdrant |

External LLMs: Ollama Cloud (compose default `LLM_PROVIDER=ollama_cloud`) or Groq (`LLM_PROVIDER=groq`; also the `Settings` default in `backend/app/core/config.py`).

```
upload / watcher → backend worker → whisperx /transcribe → emotion /predict
                                  → LLM trigger chains (Ollama Cloud | Groq) ← Qdrant + Ollama embeddings
                                  → scores → PostgreSQL → frontend
```

Details: [Audio pipeline](AUDIO_PROCESSING_PIPELINE.md) · [Emotion fusion](EMOTION_FUSION.md) · [LLM triggers](../llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md) · [RAG](../rag/RAG_OVERVIEW.md) · [Assistant](../llm_trigger/MANAGER_ASSISTANT.md).

## Inference routing (`IS_LOCAL`)

All inference clients subclass `BaseKaggleClient` (`backend/app/core/kaggle_client.py`):

- `IS_LOCAL=true` (Settings default; forced in compose): calls `WHISPERX_API_URL`, `EMOTION_API_URL`, `VAD_API_URL`.
- `IS_LOCAL=false`: calls `KAGGLE_SERVER_URL` (or `KAGGLE_NGROK_URL`) endpoints `/full`, `/transcribe`, `/emotion`, `/predict_text`, sending `ngrok-skip-browser-warning`.

`backend/.env.example` ships `IS_LOCAL=false`; set it to `true` for host-run dev against `make support-up`.

## Multi-tenancy

- Every `Interaction` carries `organization_id`; `_interaction_scope_filters` (`backend/app/api/routes/interactions.py`) restricts managers to their org and agents to rows where `agent_id` is themselves.
- Qdrant points carry an `org` payload equal to the org folder name under `storage/docs/` (the org slug). Retrievers in `backend/app/llm_trigger/retrieval.py` and `services/rag/query_engine.py` always filter on `org`; an empty filter becomes `__missing_org_scope__` (matches nothing).
- The LLM trigger cache, knowledge versions, and assistant sessions are org-scoped.
