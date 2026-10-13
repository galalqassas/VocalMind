# VocalMind

AI quality assurance for call centers. Upload a recorded call and VocalMind will:
- transcribe it and separate the speakers;
- detect emotion from both voice and text;
- check the agent against company policy and SOP documents, using an LLM grounded in retrieved evidence;
- show scores and explanations on manager and agent dashboards.

| Part | Stack |
|---|---|
| Backend | FastAPI, SQLModel, PostgreSQL |
| Frontend | React 18, Vite, Tailwind v4, MUI, Radix |
| Speech & emotion | Whisper + pyannote, emotion2vec, DistilRoBERTa text emotion |
| Reasoning | LangChain → Ollama Cloud (default) or Groq |
| RAG | Docling, Snowflake Arctic embeddings, Qdrant |

All models run on a **free Kaggle GPU notebook** by default, so your machine only runs the light app stack (Postgres, Qdrant, backend, frontend). A fully local mode is available.

## Quick start

You need:
- Docker with Compose v2;
- an `OLLAMA_API_KEY` (https://ollama.com/settings), or a `GROQ_API_KEY` with `LLM_PROVIDER=groq`;
- a Kaggle account for the GPU server.

1. **Start the GPU server.** Follow [services/kaggle/README.md](services/kaggle/README.md#run-on-kaggle): import the notebook, add the secrets, then run all cells.
2. **Start the app:**
   ```bash
   cp .env.example .env                   # set OLLAMA_API_KEY (KAGGLE_SERVER_URL = your notebook tunnel)
   cp backend/.env.example backend/.env   # for Docker, set both DB URLs to host db:5432
   make build && make up                  # Windows: make build-retry
   ```
3. **Open the app:**
   - UI: http://localhost:3000. Log in as `manager@nexalink.com` / `password123`; agents are `agent.<name>@nexalink.com`.
   - API docs: http://localhost:8000/docs

Demo orgs (NexaLink, Meridian) are seeded at startup. Audio dropped into `storage/audio/<org>/` is ingested automatically when it follows the pattern `CALL_<NN>_<agent>_<scenario>.wav`. If the Kaggle notebook isn't running, new calls are marked **failed**; reprocess them once it is running.

**Fully local models (no Kaggle; downloads several GB):** run `make up-local` (or `make up-gpu` with an NVIDIA GPU), then `make ollama-pull-embed`. You also need an `HF_TOKEN` with access to pyannote. Re-ingest the policy docs after switching (see [services/rag/README.md](services/rag/README.md)).

## Local development

```bash
make support-up                   # db + qdrant (support-up-local adds the model containers)
make be-install && make be-dev    # backend on :8000
make fe-install && make fe-dev    # frontend on :3000
```

**UI-only demo (no backend):** `cd frontend && VITE_USE_OFFLINE_DEMO=true pnpm run dev`.

## Tests

```bash
make be-test be-lint          # backend (pytest, ruff)
make fe-lint fe-test          # frontend (tsc, Cypress); unit: cd frontend && pnpm run test
make rag-test                 # RAG service
make quality-eval-all         # quality gates vs gold labels
```

Run `make help` to list all targets.

## Docs

- [AGENTS.md](AGENTS.md): architecture, repo map, configuration, production and gotchas (start here)
- [docs/README.md](docs/README.md): full documentation index
