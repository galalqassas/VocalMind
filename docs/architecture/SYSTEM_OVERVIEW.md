# System Overview

Multi-tenant call-center QA: audio → transcript + diarization → emotion → LLM trigger reasoning → scores → dashboard. Service wiring is defined in `docker-compose.yml` (GPU overlay: `docker-compose.gpu.yml`).

By default every model (ASR, diarization, speech and text emotion, embeddings, PDF parsing, reranking) runs on the **Kaggle GPU server** (`services/kaggle/server.py`; API contract and setup in [services/kaggle/README.md](../../services/kaggle/README.md)). The local model containers are optional and live in the compose profile `local-ml`.

## Components

| Compose service | Profile | Host → container port | Code | Role |
|---|---|---|---|---|
| `frontend` | default | 3000 | `frontend/` | React SPA; Vite dev server proxies `/api` to the backend (`VITE_DEV_PROXY_TARGET`) |
| `backend` | default | 8000 | `backend/app/` | FastAPI API, in-process processing worker, LLM trigger engine, assistant |
| `db` | default | 5434 → 5432 | `infra/db/` | PostgreSQL 17 (init scripts mounted from `infra/db`) |
| `qdrant` | default | 6333, 6334 | — | Vector store (`vocalmind_parents`, `vocalmind_children`, `vocalmind_sop_parents`) |
| `ingestion` | default | — | `services/rag/` | Runs `main.py --watch`: PDFs in `storage/docs` → Qdrant |
| `whisperx` | `local-ml` | 8003 → 8000 | `services/whisperx/app.py` | ASR + alignment + diarization (`POST /transcribe`) |
| `emotion` | `local-ml` | 8001 → 8000 | `services/emotion/app.py` | emotion2vec speech emotion, per segment (`/predict`) + DistilRoBERTa text emotion (`/predict_text`) |
| `vad` | `local-ml` | 8002 | `services/vad/app.py` | Standalone Silero VAD splitter (`/split`). The pipeline runs VAD inside `/full` instead (Kaggle `server.py`, WhisperX `vad_method="silero"`) |
| `ollama` | `local-ml` | 11434 | — | Local embeddings (`snowflake-arctic-embed2`) |

External LLMs: Ollama Cloud (compose default `LLM_PROVIDER=ollama_cloud`) or Groq (`LLM_PROVIDER=groq`; also the `Settings` default in `backend/app/core/config.py`).

```
upload / watcher → backend worker → Kaggle /full  (or local whisperx /transcribe + emotion /predict)
                                  → LLM trigger chains (Ollama Cloud | Groq) ← Qdrant + embeddings (Kaggle | Ollama)
                                  → scores → PostgreSQL → frontend
```

Details: [Audio pipeline](AUDIO_PROCESSING_PIPELINE.md) · [Emotion fusion](EMOTION_FUSION.md) · [LLM triggers](../llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md) · [RAG](../rag/RAG_OVERVIEW.md) · [Assistant](../llm_trigger/MANAGER_ASSISTANT.md).

## Where models run

Two independent switches:

| Switch | Controls | `kaggle` / `false` (compose default) | Local |
|---|---|---|---|
| `IS_LOCAL` | Speech: ASR, diarization, speech emotion, text emotion | `false`: `KAGGLE_SERVER_URL` (or `KAGGLE_NGROK_URL`) endpoints `/full`, `/emotion`, `/vad`, `/predict_text`, with header `ngrok-skip-browser-warning` | `true`: `WHISPERX_API_URL`, `EMOTION_API_URL`, `VAD_API_URL` |
| `RAG_MODELS_HOST` | Embeddings (backend queries + ingestion), Docling PDF parsing, reranking | `kaggle`: `/embed`, `/parse`, `/rerank` on the Kaggle server | `local`: Ollama embeddings, in-process Docling + cross-encoder (`local-models` extra) |

- Speech clients subclass `BaseKaggleClient` (`backend/app/core/kaggle_client.py`). `Settings` defaults are `IS_LOCAL=True` and `RAG_MODELS_HOST=local`; compose and both `.env.example` files set `false` / `kaggle`.
- `make up-local` / `make up-gpu` start the `local-ml` profile with `IS_LOCAL=true RAG_MODELS_HOST=local RAG_LOCAL_MODELS=true`.
- The two hosts use different embedding models (Kaggle `Snowflake/snowflake-arctic-embed-l-v2.0`, Ollama `snowflake-arctic-embed2`). After switching `RAG_MODELS_HOST`, re-ingest: `cd services/rag && uv run python main.py --ingest --force`.
- `POST /api/v1/internal/set-kaggle-url` (called by the Kaggle notebook on start) sets the backend's `KAGGLE_SERVER_URL` and `IS_LOCAL=false` in memory only.

There is no keyword or rule fallback for any model. A model or LLM failure fails that processing stage ([Audio pipeline](AUDIO_PROCESSING_PIPELINE.md#failure-semantics)).

## Multi-tenancy

- Every `Interaction` carries `organization_id`; `_interaction_scope_filters` (`backend/app/api/routes/interactions.py`) restricts managers to their org and agents to rows where `agent_id` is themselves.
- Qdrant points carry an `org` payload equal to the org folder name under `storage/docs/` (the org slug). Retrievers in `backend/app/llm_trigger/retrieval.py` and `services/rag/query_engine.py` always filter on `org`; an empty filter becomes `__missing_org_scope__` (matches nothing).
- The LLM trigger cache, knowledge versions, and assistant sessions are org-scoped.
