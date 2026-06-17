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

- **Docker Desktop** (includes Docker Compose v2+)
- **Python 3.12+** (via [uv](https://github.com/astral-sh/uv)) — only needed for local development
- **Node.js 20+** (via [pnpm v10+](https://pnpm.io/)) — only needed for local frontend development
- **Git LFS** — if your fork includes large test fixtures
- **Hugging Face token** (`HF_TOKEN`) — required for WhisperX diarization (pyannote)
- **Groq API key** (`GROQ_API_KEY`) — required when `LLM_PROVIDER=groq` (default); optional when using Ollama Cloud
- **Ollama API key** (`OLLAMA_API_KEY`) — required when `LLM_PROVIDER=ollama_cloud`

### 1. Configure Environment Variables

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in the required secrets:

| Variable | Required | Notes |
|:---------|:--------|:------|
| `GROQ_API_KEY` | When `LLM_PROVIDER=groq` | Get from <https://console.groq.com> — LLM chains and trigger evaluation |
| `OLLAMA_API_KEY` | When `LLM_PROVIDER=ollama_cloud` | Get from <https://ollama.com/settings> — Ollama Cloud LLM + optional embeddings |
| `HF_TOKEN` | **Yes** | Get from <https://huggingface.co/settings/tokens> — pyannote diarization |
| `SECRET_KEY` | **Yes** | Generate with `openssl rand -hex 32` |
| `IS_LOCAL` | No | `true` = Docker containers (default in docker-compose.yml); `false` = Kaggle remote |

For Option A (full Docker), the root `.env` provides `GROQ_API_KEY` and `HF_TOKEN` which docker-compose.yml passes through. For Option B (local dev), set these in `backend/.env` and change the service URLs to `localhost`.

### 2. Prepare Speaker-Role Model (WhisperX)

WhisperX and the backend both mount the DistilBERT speaker-role classifier. Place the export archive at the repo root and run:

```bash
make prepare-speaker-model
```

This extracts `services/whisperx/models/speaker_role/distilbert/` from `speaker_classifier_export.zip` (which is gitignored). Without this step, WhisperX will fail at startup. Use `--delete-zip` to remove the archive after extraction:

```bash
python infra/scripts/prepare_speaker_role_model.py --delete-zip
```

### 3. Build Docker Images

```bash
make build
```

This builds all custom images: backend, frontend, ingestion (RAG), VAD, emotion, and WhisperX.

> **Windows tip:** If you encounter transient Docker daemon errors (EOF, 500 Internal Server Error, rpc Unavailable), use the built-in retry script instead:
>
> ```bash
> make build-retry
> ```
>
> This retries up to 4 times with 12-second delays for known transient Docker Desktop issues on Windows.

> **First build:** The emotion and WhisperX images use CUDA base images and download several GB of PyTorch/NVIDIA libraries. Expect 20–40 minutes on a fast connection depending on hardware.

### Option A. Run the Full Stack in Docker

Start all services (Database, Backend, Frontend, Ollama, Qdrant, Ingestion, VAD, Emotion, WhisperX):

```bash
make up
```

First-time startup also requires pulling the Ollama embedding model:

```bash
docker exec vocalmind-ollama ollama pull snowflake-arctic-embed2
```

Then seed the database with demo data:

```bash
make seed
```

The app is now available at:
- **Frontend:** `http://localhost:3000`
- **Backend API:** `http://localhost:8000`
- **API docs:** `http://localhost:8000/docs`

Audio files placed in `storage/audio/nexalink/` are auto-ingested on startup (see Audio Auto-Ingest below).

To stop:

```bash
make down
```

### Option B. Run Backend and Frontend Locally

Start only the supporting infrastructure (Database, Ollama, Qdrant, VAD, Emotion, WhisperX):

```bash
make support-up
make prepare-speaker-model   # if not done already
```

Set `IS_LOCAL=true` and point service URLs at `localhost` in `backend/.env`:

```
IS_LOCAL=true
EMOTION_API_URL=http://localhost:8001
VAD_API_URL=http://localhost:8002
WHISPERX_API_URL=http://localhost:8003
```

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

Pull the Ollama embedding model if using RAG:

```bash
docker exec vocalmind-ollama ollama pull snowflake-arctic-embed2
```

Seed demo data:

```bash
make seed
```

Stop supporting containers:

```bash
make support-down
```

#### GPU Acceleration (Optional)

For inference workloads that benefit from an NVIDIA GPU, use the GPU-enabled compose overlay:

```bash
make up-gpu            # full stack with GPU
make support-up-gpu    # supporting services only with GPU
```

This requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) and a compatible GPU driver.

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
make build            # Build all Docker images
make build-retry      # Build + start with retry for transient Docker daemon errors (Windows)
make up               # Start all services
make up-gpu           # Start all services with NVIDIA GPU acceleration
make support-up       # Start supporting services only (DB, Ollama, Qdrant, inference)
make support-up-gpu   # Same, with GPU acceleration
make down             # Stop all services
make support-down     # Stop supporting services only
make logs             # Tail container logs
make seed             # Seed database with demo data
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

### Speaker Classifier Artifacts

#### Option A: Logistic Regression Model (Hybrid Pipeline - Default)
The backend uses a hybrid speaker role classifier combining ML predictions and rule-based priors. The required model weights and TF-IDF vectorizer must be placed in:
* **Model Weights**: [model.pkl](file:///g:/projects/VocalMind/backend/app/core/model.pkl)
* **TF-IDF Vectorizer**: [vectorizer.pkl](file:///g:/projects/VocalMind/backend/app/core/vectorizer.pkl)

These files are excluded from Git via `.gitignore`. Teammates can retrieve them as follows:

1. **Download the model weights from MLflow**:
   Ensure `MLFLOW_TRACKING_PASSWORD` (your DagsHub Personal Access Token) is set in your `.env` or terminal environment, then run the download tool:
   ```bash
   python tools/download_mlflow_model.py --run-id 85c2377290ee459a8232c8136d0721c5 --output-dir backend/app/core/
   ```
   *Note: This downloads files into a subfolder. Move the model weights to the core directory using python (cross-platform):*
   ```bash
   python -c "import shutil; shutil.move('backend/app/core/model/model.pkl', 'backend/app/core/model.pkl'); shutil.rmtree('backend/app/core/model')"
   ```


2. **Retrieve the vectorizer**:
   Since the remote MLflow run only logged the model classifier and not the TF-IDF vectorizer, and regenerating it locally can cause a vocabulary alignment shift, teammates must copy the exact `vectorizer.pkl` from the team's shared/secured storage and place it directly under `backend/app/core/vectorizer.pkl`.


#### Option B: DistilBERT Model (WhisperX Speaker-Role Pass)
For the optional second-pass WhisperX relabeling:
Place `speaker_classifier_export.zip` at the repo root and run:
```bash
make prepare-speaker-model
```
This extracts the DistilBERT model into `services/whisperx/models/speaker_role/distilbert/`. The zip is gitignored — it must be provided separately. WhisperX will fail to start without these model files.



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
