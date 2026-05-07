# VocalMind

VocalMind is a modular AI ecosystem integrating speech processing (ASR, Diarization, Synthesis) with retrieval-augmented generation (RAG) to create context-aware conversational agents, designed for call center and telecom use cases.

---

## Architecture

| Component    | Tech Stack | Description |
| :----------- | :--------- | :---------- |
| **Backend**  | FastAPI, SQLModel, asyncpg | Central API gateway with auth (JWT/Google OAuth), Supabase integration, and dispute handling. |
| **Frontend** | React 18, Vite, Tailwind v4, MUI, Radix UI | Manager and agent dashboards with session analysis. Tested with Cypress E2E and Vitest. |
| **VAD**      | Silero VAD, FastAPI | Voice Activity Detection microservice. |
| **WhisperX** | WhisperX, pyannote, FastAPI | Automatic Speech Recognition and Diarization microservice. |
| **Emotion**  | Transformers, FastAPI | Speech emotion recognition microservice. |
| **RAG**      | LlamaIndex, Qdrant, Groq, Ollama | Retrieval-Augmented Generation for knowledge queries. |
| **Ingestion**| LlamaIndex | Automated pipeline for RAG document ingestion. |
| **Explainability** | FastAPI, React, LLM/NLI attribution | Evidence-anchored layer that links triggers and compliance verdicts to transcript spans and retrieved policy/SOP evidence. |
| **Research** | Jupyter | Reference experiments for speech pipelines and voice generation. |

---

## Quick Start

### Prerequisites

- **Python 3.12+** (via [uv](https://github.com/astral-sh/uv))
- **Node.js 20+** (via [pnpm v10+](https://pnpm.io/))
- **Docker & Docker Compose**

### Configuration
For local API development, copy `backend/.env.example` to `backend/.env`.
If you run services that load config from the repository root, also copy `.env.example` to `.env`.

```bash
cp backend/.env.example backend/.env
cp .env.example .env
```

### Option A. Run The Full Stack In Docker

Start the full stack in containers (Database, Backend, Frontend, Ollama, Qdrant, Ingestion, VAD, Emotion, WhisperX):

```bash
make up
```

This serves the app at:
- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

### Option B. Run Backend And Frontend Locally

Start only the supporting services needed by the local apps:

```bash
make support-up
```

If you want the local backend to use the local Dockerized inference services, set `IS_LOCAL=true` in `backend/.env`.

**Backend:**
```bash
make be-install
make be-dev          # -> http://localhost:8000
```

**Frontend:**
```bash
make fe-install
make fe-dev          # -> http://localhost:3000
```

Stop only the supporting containers when you are done with local development:

```bash
make support-down
```

---

## Project Structure

```text
VocalMind/
├── backend/          # FastAPI API gateway
├── frontend/         # React dashboard (Manager & Agent routes)
├── services/         # Microservices (VAD, WhisperX, Emotion, RAG)
├── infra/            # DB init, seed/eval scripts, quality benchmarks, test fixtures
│   ├── db/           # PostgreSQL schema & seed SQL
│   ├── benchmarks/   # Quality benchmark data (expected, fixtures, schema)
│   ├── scripts/      # Operational scripts (seed/, eval/, e2e, migrate)
│   └── fixtures/     # Test audio files & external API fixtures
├── storage/          # Unified local storage (docs, audio, uploads)
│   ├── docs/         #   Organization documents (policy, SOP, KB)
│   ├── audio/        #   Per-org audio drop folders (e.g. nexalink/), auto-ingested
│   │                 #   on backend startup. Audio files (.wav/.mp3) are gitignored —
│   │                 #   filename pattern CALL_<NN>_<agent>_<scenario>.<ext> assigns
│   │                 #   the call to the correct seeded agent.
│   └── uploads/      #   Runtime upload buffer (gitignored)
├── research/         # Jupyter notebooks & prototype scripts
├── docs/             # Documentation (explainability, LLM trigger, RAG, design, frontend)
├── tools/            # Local CLI tools (Supabase CLI)
├── .github/          # CI workflows (ci.yml, backend.yml, frontend.yml, rag_ci.yml)
├── docker-compose.yml# Multi-container service definitions
├── Makefile          # Unified development commands
└── README.md
```

---

## Useful Commands

### Backend
```bash
make be-install       # Install dependencies
make be-dev           # Run api gateway
make be-test          # Run pytest suite
make be-lint          # Run Ruff linter
```

### Frontend
```bash
make fe-install       # Install dependencies (pnpm)
make fe-test          # Run Cypress E2E tests
make fe-e2e-cov       # Run E2E tests with Istanbul code coverage
make fe-lint          # Run ESLint/Type-check validation
make fe-build         # Build production bundle
```

### Docker
```bash
make up               # Start all services
make support-up       # Start only supporting services for local app development
make logs             # Tail container logs
make build            # Rebuild images
make down             # Stop all services
make support-down     # Stop supporting services only
```

### General
```bash
make clean            # Remove caches and build artifacts
make prepare-speaker-model  # Extract speaker-role classifier for WhisperX
```

### Utility Scripts
```bash
python infra/scripts/measure_dashboard_baseline.py --api-base http://localhost:8000/api/v1
python infra/fixtures/kaggle/scripts/kaggle_api_smoke_test.py --audio-file storage/audio/nexalink/CALL_01_priya_refund_outage.wav
```

### Speaker Classifier Artifact

`speaker_classifier_export.zip` is treated as a one-time import artifact.  
Run `make prepare-speaker-model` to extract only the `distilbert/` model into
`services/whisperx/models/speaker_role/distilbert`, then remove the zip.

### Audio Auto-Ingest

The backend ships an audio folder watcher
([`backend/app/core/audio_folder_watcher.py`](backend/app/core/audio_folder_watcher.py))
that runs on startup and every 15 seconds while the server is up. It scans
`storage/audio/<org_slug>/` for any `.wav` or `.mp3` file that is not yet
recorded as an interaction, and:

1. Reads the agent token from the filename
   (`CALL_<NN>_<agent>_<scenario>.<ext>`).
2. Creates an `Interaction` row owned by that agent with status `pending`.
3. Seeds the `processing_jobs` records for the full pipeline.
4. Enqueues the interaction onto the in-memory worker queue.

Drop a properly-named audio file into the folder — the manager dashboard will
pick it up without any manual upload step. If the filename does not match the
pattern, the file is still ingested but assigned to a deterministic fallback
agent and a warning is logged. Set `AUDIO_FOLDER_WATCHER_ENABLED=false` in
`.env` to disable.

The seeded NexaLink organization comes with one manager
(`manager@nexalink.com`) and exactly five agents — Priya, Daniel, Marcus,
Aisha, Hannah — one per scripted call in `storage/audio/nexalink/`.

## Key Docs

- [Documentation Index](docs/README.md)
- [Evidence-Anchored Explainability Layer](docs/explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md)
- [LLM Trigger Feature Guide](docs/llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)
- [RAG Overview](docs/rag/RAG_OVERVIEW.md)
