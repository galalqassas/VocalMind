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
| Speech | Silero VAD, WhisperX + pyannote, emotion2vec (FunASR) |
| Reasoning | LangChain → Ollama Cloud (default) or Groq |
| RAG | Docling, Ollama embeddings, Qdrant |

## Quick start (Docker)

You need:
- Docker with Compose v2;
- an `OLLAMA_API_KEY` (https://ollama.com/settings), or a `GROQ_API_KEY` with `LLM_PROVIDER=groq`;
- an `HF_TOKEN` with access to pyannote.

```bash
cp .env.example .env
cp backend/.env.example backend/.env   # set OLLAMA_API_KEY, HF_TOKEN; for Docker set both DB URLs to host db:5432
make build                             # first build downloads several GB (Windows: make build-retry)
make up                                # or make up-gpu with the NVIDIA Container Toolkit
make ollama-pull-embed                 # once: embedding model for RAG
```

- UI: http://localhost:3000. Log in as `manager@nexalink.com` / `password123`; agents are `agent.<name>@nexalink.com`.
- API docs: http://localhost:8000/docs

Demo orgs (NexaLink, Meridian) are seeded automatically at startup. Audio dropped into `storage/audio/<org>/` is ingested automatically, using the filename pattern `CALL_<NN>_<agent>_<scenario>.wav`.

## Local development

```bash
make support-up               # db, ollama, qdrant + inference containers
make be-install && make be-dev    # backend on :8000
make fe-install && make fe-dev    # frontend on :3000
```

To skip the heavy inference containers, set `IS_LOCAL=false` in `backend/.env` (the default in `.env.example`). Inference then runs on the remote Kaggle server (`KAGGLE_SERVER_URL`), so instead of `make support-up` you only need `docker compose up -d db ollama qdrant`.

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
