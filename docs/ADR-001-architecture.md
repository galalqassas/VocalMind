# ADR-001 — Hybrid: Monolithic Backend + ML Microservices

**Status:** Accepted
**Date:** 2026-06-15
**Decision drivers:** graduation project scope, GPU isolation, deploy simplicity, defendability.

## Context

VocalMind ingests call audio and runs it through five distinct ML stages
(VAD, ASR + alignment, diarization, acoustic emotion, text emotion + LLM
reasoning) before exposing scored interactions to a manager / agent web UI.

Each ML stage has different runtime needs:

| Stage | Heavy dep | GPU? | Memory | Restart cost |
|---|---|---|---|---|
| VAD (Silero) | torch | optional | small | seconds |
| WhisperX (ASR + align + diar) | torch, ctranslate2, pyannote | yes | ~6 GB | minutes |
| Emotion (acoustic + text) | transformers | optional | ~2 GB | tens of seconds |
| LLM trigger | groq/langchain | none | small | seconds |
| RAG | qdrant, ollama embeddings, llm | none | medium | seconds |

The business layer — auth, RBAC, dashboards, evaluation persistence, the
manager assistant, the HITL feedback loop — is comparatively cheap: pure
async FastAPI + Postgres.

## Decision

**One business-logic monolith (FastAPI + Postgres + SQLModel) plus four
ML microservices behind HTTP boundaries** (VAD, WhisperX, Emotion, RAG).
Compose orchestrates them; the backend fans out via async HTTP.

```
                ┌────────────────────────────────────────┐
                │   FastAPI backend (monolith)           │
                │   auth, RBAC, persistence, scoring,    │
                │   review queue, notifications, RAG     │
                │   client, manager assistant            │
                └─────────────┬──────────────────────────┘
                              │  async HTTP fan-out
        ┌──────────┬──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼          ▼
       VAD     WhisperX     Emotion     RAG      Ollama
     (Silero) (GPU svc)   (text+acoustic) (qdrant+gen)
```

## Why not microservices everywhere?

- **No team to operate them.** Two-person undergrad team. A genuine
  microservice topology (one bounded context per service, each with its
  own DB) doubles the deploy and observability surface while we still
  share *one* Postgres conceptually.
- **Business contexts barely change shape.** Interactions, scores,
  policies, feedback, notifications all share the interaction lifecycle —
  splitting them across services would mean a lot of cross-service joins
  or duplicated state.
- **The split that *does* matter is runtime, not domain.** GPU /
  large-model isolation is the actual reason to split, and that's
  exactly where we drew the line.

## Why not a pure monolith?

- **WhisperX needs CUDA and ~6 GB of GPU memory** during transcription
  but is idle most of the time. Embedding it in the backend pins those
  resources to every backend replica.
- **Restart blast radius.** A torch / CUDA crash inside the backend
  process kills the whole API. Isolating WhisperX behind HTTP turns it
  into a recoverable upstream.
- **Independent scaling.** WhisperX can scale to N GPU workers without
  scaling FastAPI replicas, and vice versa.
- **Language flexibility.** The RAG service was easier to write against
  llama-index + qdrant in its own venv than to drag those deps into the
  backend's resolution.

## Trade-offs accepted

| Trade-off | Why we accept it |
|---|---|
| Cross-service HTTP latency (~10–30 ms / hop) | Negligible vs. WhisperX itself (tens of seconds) |
| No service mesh / circuit breaker yet | LLM trigger has retry + degraded fallback; ML services have timeouts; good enough for the load we serve |
| One Postgres for everything | Simplifies transactions, FK integrity, manager dashboards; revisit when traffic forces a split |
| `audio_folder_watcher` + `processing_worker` are in-process | Limits backend to 1 replica today. Migration path: move queue to Redis / Postgres `LISTEN/NOTIFY` when we need to scale horizontally — model layer already supports it |
| No Alembic | Schema bootstraps from [`infra/db/01_schema.sql`](../infra/db/01_schema.sql). Acceptable while the team is two devs on one branch at a time; introduce Alembic before bringing on a third contributor |

## Failure modes & responses

| Failure | Current handling | Future improvement |
|---|---|---|
| LLM trigger timeout | tenacity retry → degraded deterministic verdict | budget caching per interaction |
| LLM produces malformed JSON | Pydantic rejects → degraded fallback | structured-output mode (when supported by SDK) |
| WhisperX down | pipeline halts, `processing_jobs.status=failed` surfaced in UI | fallback queue + manual replay button |
| Qdrant empty / missing | file-system SOP fallback in `retrieval.py` | warm-up health probe at lifespan startup |
| Backend pod restart mid-job | next worker tick picks up `pending` rows | move to Postgres `SKIP LOCKED` queue |

## Consequences for new work

- **New domain features stay in the monolith** unless they introduce a
  new heavy dependency. The notifications + HITL feedback work landed
  in-process for this reason.
- **New ML / heavy work gets a new service** with its own venv and
  Dockerfile; backend talks to it over HTTP.
- **Schema changes:** until Alembic lands, update
  [`infra/db/01_schema.sql`](../infra/db/01_schema.sql) *and* register
  the new model in `app/models/__init__.py` *and*
  `create_db_and_tables()` so dev-mode auto-create stays in sync.
