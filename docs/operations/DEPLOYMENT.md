# VocalMind Operations, Setup & Developer Guide

VocalMind is a modular, multi-service AI application. It coordinates transcription (WhisperX), voice activity detection (Silero VAD), speech emotion recognition (emotion2vec), vector storage (Qdrant), and LLM reasoning (Groq/Gemini/Ollama) to evaluate call center interactions.

This operations manual details deployment patterns, environment configurations, background processes, testing, and continuous integration.

---

## 1. System Architecture & Port Mapping

When executing the multi-container stack, services communicate across the internal Docker network. The following host ports are exposed:

| Service | Port | Description |
| :--- | :--- | :--- |
| **Frontend** | `:3000` | React Single Page Application (Vite dev server or preview). |
| **Backend** | `:8000` | FastAPI Gateway. Exposes OpenAPI docs at `/docs`. |
| **VAD Service** | `:8002` | Silero Voice Activity Detection microservice. |
| **WhisperX** | `:8003` | Speech-to-Text alignment and diarization microservice. |
| **Emotion Service**| `:8001` | funASR emotion2vec speech emotion recognition microservice. |
| **Qdrant** | `:6333` | Vector Database storing parsed Policy, SOP, and KB chunks. |
| **Ollama** | `:11434` | Running Snowflake Arctic Embed2 for RAG vector encodings. |
| **PostgreSQL** | `:5432` | Relational storage for transactional tables. |

---

## 2. Environment Variables Configuration

VocalMind coordinates settings via two configurations:

### 2.1 Root `.env`
Used by Docker Compose to pass variables into containers.
*   `GROQ_API_KEY`: Required. Authenticates calls to Groq Cloud LLM trigger chains.
*   `HF_TOKEN`: Required. Authenticates pyannote model downloads inside the WhisperX container.

### 2.2 Backend `.env` (`backend/.env`)
Used when running the FastAPI backend gateway natively on the host:
*   `IS_LOCAL`: Boolean flag. `true` directs inference requests to local Docker microservices (`:8001`, `:8002`, `:8003`). `false` redirects inference to a remote Kaggle environment via a secure fallback client.
*   `DATABASE_URL`: Connection string. Defaults to `postgresql+asyncpg://vocalmind:vocalmind_dev@db:5432/vocalmind` in Docker, and `postgresql+asyncpg://...` or SQLite fallback for unit tests.
*   `ASSISTANT_LLM_PROVIDER`: Provider for NL-to-SQL Assistant (`gemini`, `groq`, or `ollama`).
*   `BACKEND_SPEAKER_RELABEL_ENABLED`: Must remain `false` while WhisperX is running to avoid double speaker labeling conflicts.
*   `AUDIO_FOLDER_WATCHER_ENABLED`: Set to `true` to enable automatic background file ingestion.

---

## 3. Deployment & Execution Modes

### 3.1 Option A: Full Stack in Docker (CPU Mode)
Ideal for quick evaluations. Starts the entire system inside Docker containers:
```bash
make build           # Builds all service images
make up              # Launches all containers in the background
# Initialize embedding models:
docker exec vocalmind-ollama ollama pull snowflake-arctic-embed2
make seed            # Seeds mock NileTech and Meridian organizations
```

### 3.2 Option B: Local Developer Mode (Hybrid)
Runs heavy ML pipelines and databases in Docker, while running backend and frontend code natively on the host for hot-reloading:
1.  Launch infra services: `make support-up`.
2.  Launch Backend:
    ```bash
    cd backend
    uv sync
    uv run uvicorn app.main:app --reload --port 8000
    ```
3.  Launch Frontend:
    ```bash
    cd frontend
    pnpm install
    pnpm run dev
    ```

### 3.3 Option C: GPU Acceleration
To utilize an NVIDIA graphics card, run the GPU compose overlay:
```bash
make up-gpu           # Full stack with CUDA bindings
make support-up-gpu   # Supporting infra only with CUDA bindings
```
*   **Performance Note**: Processing a 3-minute call takes ~30+ minutes on CPU, but drops to ~2 minutes using a GPU.

---

## 4. Audio Auto-Ingest Scanner

The backend contains a background folder watcher process (`backend/app/core/audio_folder_watcher.py`) that runs on startup and loops every 15 seconds:
*   **Drop Location**: Scans directory paths matching `storage/audio/{org_slug}/` for `.wav` or `.mp3` files.
*   **Filename Convention**: Expects files named `CALL_<NN>_<agent>_<scenario>.<ext>` (e.g. `CALL_01_priya_refund_outage.wav`). 
*   **Ingestion Mechanics**: The scanner extracts the agent's name, creates a new `Interaction` row in the database assigned to that agent, creates the 6 sequential `ProcessingJob` stages, and enqueues the interaction into the memory-processing worker loop.

---

## 5. Testing & Verification Suites

VocalMind enforces quality checks across three separate test suites:

### 5.1 Backend Pytests
Verifies API gateway routers, emotion fusion math, and database models using an in-memory SQLite backend:
```bash
make be-test
```

### 5.2 Frontend Unit Tests
Verifies component rendering, auth contexts, and details layouts:
```bash
cd frontend && pnpm run test
```

### 5.3 Cypress End-to-End (E2E)
Spins up a headless browser to walk through login, call reviews, AI Assistant chats, and disputes. Requires building the frontend first:
```bash
make fe-test
```

### 5.4 Quality Benchmark Evaluations
Evaluates the ML pipeline output against expected gold-standard outputs (ground truths) located in `infra/benchmarks/expected/`:
```bash
make quality-eval-all
```
This runs the script `infra/scripts/eval/eval_all.py` and checks metrics like topic classification correctness, SOP step coverage recall, and speaker turn segment ratios.

---

## 6. Continuous Integration (GitHub Workflows)

CI pipelines are separated into distinct YAML workflows under `.github/workflows/`:
1.  `ci.yml`: Performs Gitleaks security scans to prevent API key leaks.
2.  `backend.yml`: Automatically triggers on backend changes. Runs Ruff checks, Pytest, and Pip-licenses audits.
3.  `frontend.yml`: Runs type validation (`tsc --noEmit`), builds the React bundle, and runs Cypress E2E tests.
4.  `rag_ci.yml`: Validates LlamaIndex ingestion files and searches.
5.  `quality-benchmarks.yml`: Run manually to compare current pipeline scores against baseline records.
