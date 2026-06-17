.PHONY: help up up-gpu down build build-retry logs support-up support-up-gpu support-down be-dev be-test be-test-cov be-lint be-install fe-dev fe-build fe-lint fe-test fe-e2e-summary fe-e2e-cov fe-test-cov fe-install rag-lint rag-test rag-install llm-trigger-test quality-eval-transcript quality-eval-emotion quality-eval-policy quality-eval-rag quality-eval-resolution quality-eval-all e2e-local-audio seed-manager-supabase-audio seed migrate prepare-speaker-model clean test-all audit audit-backend-rag audit-cuda-services

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Docker ────────────────────────────────────────────────────────────────

up: ## Start all services (CPU)
	docker compose up -d

up-gpu: ## Start all services with NVIDIA GPU acceleration (whisperx/emotion/ollama)
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

down: ## Stop all services
	docker compose down

support-up: ## Start only supporting services for local backend/frontend development (CPU)
	docker compose up -d db ollama qdrant vad emotion whisperx

support-up-gpu: ## Start supporting services with GPU acceleration enabled
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d db ollama qdrant vad emotion whisperx

support-down: ## Stop supporting services used by local backend/frontend development
	docker compose stop db ollama qdrant vad emotion whisperx

build: ## Build all Docker images
	docker compose build

build-retry: ## Build/start with retry logic for transient Docker daemon EOF/500 errors (Windows PowerShell)
	powershell -ExecutionPolicy Bypass -File infra/scripts/docker_compose_retry.ps1 -ComposeArgs "up -d --build"

logs: ## Follow logs for all services
	docker compose logs -f

# ── Backend ───────────────────────────────────────────────────────────────

be-dev: ## Run backend in dev mode
	cd backend && uv run uvicorn app.main:app --reload --port 8000

be-test: ## Run backend tests
	cd backend && uv run pytest tests/ -v

be-test-cov: ## Run backend tests with coverage
	cd backend && uv run pytest --cov=app --cov-report=term --cov-report=html tests/ -v

be-lint: ## Lint backend code
	cd backend && uv run ruff check .

be-install: ## Install backend dependencies
	cd backend && uv sync

# ── Frontend ──────────────────────────────────────────────────────────────

fe-dev: ## Run frontend in dev mode
	cd frontend && pnpm run dev

fe-build: ## Build frontend
	cd frontend && pnpm run build

fe-lint: ## Lint frontend code
	cd frontend && pnpm run lint

fe-test: ## Run frontend E2E tests (Cypress)
	cd frontend && pnpm run build
	cd frontend && npx -y concurrently -k -s first "pnpm run preview" "npx -y wait-on http-get://localhost:3000/ && pnpm run cy:run"

fe-e2e-summary: ## Run frontend E2E tests with concise summary
	cd frontend && pnpm run build
	cd frontend && npx -y concurrently -k -s first "pnpm run preview" "npx -y wait-on http-get://localhost:3000/ && npx cypress run --reporter list"

fe-e2e-cov: ## Run frontend E2E tests and generate code coverage report
	npx -y rimraf frontend/.nyc_output frontend/coverage frontend/dist
	cd frontend && npx -y cross-env CYPRESS_COVERAGE=true pnpm run build
	cd frontend && npx -y concurrently -k -s first "pnpm exec vite preview --port 3005 --strictPort" "npx -y wait-on http-get://localhost:3005/ && npx -y cross-env CYPRESS_COVERAGE=true CYPRESS_baseUrl=http://localhost:3005 npx cypress run --env coverage=true" && npx nyc report --reporter=html --reporter=text-summary

fe-test-cov: ## Run frontend unit tests with coverage report
	cd frontend && npx vitest run --coverage.enabled --coverage.reporter=text --coverage.reporter=html

fe-install: ## Install frontend dependencies
	cd frontend && pnpm install

# ── RAG ───────────────────────────────────────────────────────────────────

rag-lint: ## Lint RAG code
	cd services/rag && uv run ruff check .

rag-test: ## Run RAG tests
	cd services/rag && uv run pytest tests/ -v

rag-install: ## Install RAG dependencies
	cd services/rag && uv sync

llm-trigger-test: ## Run full LLM-trigger validation (backend + RAG + frontend)
	cd backend && uv run pytest tests/test_llm_trigger_service.py tests/test_interactions_llm_triggers.py tests/test_sop_retrieval.py -q
	cd services/rag && uv run pytest tests/test_ingest.py -q
	cd frontend && pnpm run test -- --run src/tests/AgentCallDetail.test.tsx

quality-eval-transcript: ## Run transcript quality benchmark
	python infra/scripts/eval/eval_transcript.py

quality-eval-emotion: ## Run emotion quality benchmark
	python infra/scripts/eval/eval_emotion.py

quality-eval-policy: ## Run policy quality benchmark
	python infra/scripts/eval/eval_policy.py

quality-eval-rag: ## Run RAG quality benchmark
	python infra/scripts/eval/eval_rag.py

quality-eval-resolution: ## Run resolution quality benchmark
	python infra/scripts/eval/eval_resolution.py

quality-eval-all: ## Run all component quality benchmarks (fails on regression)
	python infra/scripts/eval/eval_all.py

e2e-local-audio: ## Full local E2E on default mounted audio (login, ingest, poll, assert)
	python infra/scripts/e2e_local_audio.py --include-llm

seed-manager-supabase-audio: ## Clear manager org via Supabase, upload audio to Storage, POST from-storage (see supabase_seed_audio.py --help)
	cd backend && uv run python ../infra/scripts/seed/supabase_seed_audio.py

# ── CI/CD ─────────────────────────────────────────────────────────────────

test-all: ## Run all tests required for CI/CD and clean up
	$(MAKE) -j test-backend test-frontend test-rag quality-eval-all
	$(MAKE) clean

test-backend: be-lint be-test

test-frontend:
	$(MAKE) fe-lint
	$(MAKE) fe-build
	$(MAKE) fe-test-cov
	$(MAKE) fe-test

test-rag: rag-lint rag-test
# ── Security Audit ────────────────────────────────────────────────────────

audit: audit-backend-rag ## Run supply-chain audit gate for backend + RAG

audit-backend-rag: ## Run pip-audit in backend and ingestion containers (fails on vulnerabilities)
	docker compose run --rm backend sh -c "python -m ensurepip --upgrade >/tmp/ensurepip.log 2>&1 && python -m pip install pip-audit >/tmp/pip-audit-install.log 2>&1 && pip-audit"
	docker compose run --rm ingestion sh -c "python -m ensurepip --upgrade >/tmp/ensurepip.log 2>&1 && python -m pip install pip-audit >/tmp/pip-audit-install.log 2>&1 && pip-audit"

audit-cuda-services: ## Run pip-audit for whisperx/emotion after local image pull/build
	@echo "NOTE: whisperx/emotion use large CUDA base images; pull/build first before auditing."
	@echo "Run manually:"
	@echo "  docker compose run --rm whisperx sh -c \"python3 -m ensurepip --upgrade && python3 -m pip install pip-audit && pip-audit\""
	@echo "  docker compose run --rm emotion sh -c \"python -m ensurepip --upgrade && python -m pip install pip-audit && pip-audit\""

# ── Database ──────────────────────────────────────────────────────────────

seed: ## Seed the database
	cd backend && uv run python ../infra/scripts/seed/seed_database.py

migrate: ## Run database migrations
	cd backend && uv run python ../infra/scripts/migrate.py

prepare-speaker-model: ## Extract speaker-role DistilBERT for WhisperX + backend (docker-compose mounts this path)
	python infra/scripts/prepare_speaker_role_model.py --delete-zip

# ── Utilities ─────────────────────────────────────────────────────────────

clean: ## Remove all caches and build artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .nyc_output -o -name coverage \) -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/dist frontend/.nyc_output

run-ci: ## Trigger manual CI/CD run via GitHub CLI (Usage: make run-ci [sha=<SHA_OR_REF>] [workflow=<ci.yml|backend.yml|...>])
	@gh workflow run $(if $(workflow),$(workflow),ci.yml) $(if $(sha),-f commit_sha=$(sha))
