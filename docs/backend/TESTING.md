# Testing

All commands come from the root `Makefile` unless noted. For what CI runs, see `.github/workflows/`.

## Suites

| Suite | Location | Command | Notes |
|---|---|---|---|
| Backend unit/API | `backend/tests/` (38 `test_*.py` + `conftest.py`) | `make be-test` (`uv run pytest tests/ -v`) | SQLite in-memory via `conftest.py`. `make be-test-cov` adds coverage. |
| Backend lint | `backend/` | `make be-lint` | Ruff |
| Frontend unit | `frontend/src/tests/` (13 Vitest files) | `cd frontend && pnpm run test` | jsdom; `make fe-test-cov` adds coverage |
| Frontend typecheck | `frontend/` | `make fe-lint` | `tsc --noEmit` |
| Frontend E2E | `frontend/cypress/e2e/` (14 specs) | `make fe-test` | Builds, then runs `vite preview` on :3000 (never the dev server). API calls are stubbed by `cy.useE2eApiFixtures()` in `cypress/support/e2e.ts`, so no backend is needed. |
| RAG service | `services/rag/tests/` | `make rag-test`, `make rag-lint` | |
| LLM-trigger slice | backend, RAG and frontend | `make llm-trigger-test` | Runs `test_llm_trigger_service.py`, `test_interactions_llm_triggers.py`, `test_sop_retrieval.py`, the RAG `test_ingest.py` and `AgentCallDetail.test.tsx` |
| Quality benchmarks | `infra/scripts/eval/` | `make quality-eval-all` (or `quality-eval-{transcript,emotion,policy,rag,resolution}`) | By default scores the fixture `infra/benchmarks/fixtures/baseline_predictions.json` (not a live run; pass `--predictions` to score your own) against `infra/benchmarks/expected/` using `infra/benchmarks/schema/thresholds.json`. Exits non-zero on regression. |
| Live local E2E | `infra/scripts/e2e_local_audio.py` | `make e2e-local-audio` | Needs the running stack: login, ingest, poll, assert |

`make test-all` runs backend lint+test, frontend lint/build/unit/E2E, RAG lint+test and `quality-eval-all`, then `make clean`.

## Backend test areas (`backend/tests/`)

- **Auth and security:** `test_auth*.py`, `test_security*.py`, `test_p0_security.py`, `test_unauthorized_access.py`, `test_error_sanitization.py`, `test_config_startup_validation.py`
- **Tenant isolation:** `test_agents_isolation.py`, `test_*_isolation.py`, `test_assistant_tenant_guard.py`
- **Assistant SQL guards:** `test_assistant*.py`, including the read-only DB permissions and SQL-structure validator tests
- **Pipeline and inference:** `test_pipeline.py`, `test_interaction_*.py`, `test_inference_*.py`, `test_audio_folder_watcher.py`
- **Emotion:** `test_emotion*.py`
- **LLM triggers and RAG:** `test_llm_trigger_*.py`, `test_llm_circuit_breaker.py`, `test_sop_retrieval.py`
- **Knowledge versioning:** `test_knowledge_versioning.py`
- **App and dashboard:** `test_main.py`, `test_dashboard.py`

## CI

| Workflow | Trigger paths | Steps |
|---|---|---|
| `backend.yml` ("Backend CI") | `backend/**` | `ruff check`, `pytest`, `infra/scripts/eval/eval_all.py`, license audit. A pass on `main` triggers the deploy; see [DEPLOYMENT.md](../operations/DEPLOYMENT.md). |
| `frontend.yml` | `frontend/**` | `pnpm run lint`, `pnpm run build`, Cypress against `pnpm run preview`. Vitest does not run in CI. |
| `rag_ci.yml` | `services/rag/**` | `ruff check`, `pytest` |
| `ci.yml` | every push/PR | Gitleaks |

## Caveat

Tests use SQLite, so Postgres-only behaviour (JSONB, partial indexes, enum types, the `vocalmind_readonly` grants) is not covered. Verify schema-sensitive changes against the compose Postgres.
