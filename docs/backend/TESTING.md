# VocalMind Verification & Testing Guide

This guide details the test suites, execution commands, and verification benchmarks used to validate VocalMind's stability and correctness.

---

## 1. Backend API Test Suite (pytest)

The backend gateway contains 23 testing files built with `pytest` using an asynchronous driver (`pytest-asyncio`) and an in-memory SQLite database.

### 1.1 Core Test Files

*   **Authentication & User**:
    *   `test_auth.py`: Tests login, logout, and token expiration controller endpoints.
    *   `test_auth_service.py`: Service-level token generation and verification logic.
*   **Security & Hardening**:
    *   `test_p0_security.py` / `test_security.py` / `test_security_headers.py`: Tests CORS headers, frame DENY headers, and secure access restrictions.
    *   `test_unauthorized_access.py`: Asserts that unauthenticated calls receive `401 Unauthorized`.
*   **Audio Pipeline**:
    *   `test_pipeline.py`: Tests the execution flow of the async processing queue.
    *   `test_interaction_ingestion.py` / `test_interaction_processing_quality.py`: Validates audio parsing, ingestion contracts, and job status transitions.
*   **Emotion & Fusion**:
    *   `test_emotion.py` / `test_emotion_service.py`: Evaluates proxy endpoints.
    *   `test_emotion_fusion.py`: Validates fusion mathematics (agreement bonuses and disagreement penalties).
*   **LLM Triggers & RAG**:
    *   `test_llm_trigger_service.py` / `test_sop_retrieval.py`: Tests SOP step graph resolution and LLM judging logic.
    *   `test_assistant.py`: Asserts that Text-to-SQL returns valid data and rejects non-read-only queries.
*   **Dashboard & Infrastructure**:
    *   `test_dashboard.py`: Evaluates cached stats generation.
    *   `test_model_validation.py` / `test_main.py`: Checks DB schema validations and API startup health.

### 1.2 Execution Command
```bash
make be-test
# OR inside the backend folder:
uv run pytest
```

---

## 2. Frontend Test Suites

The frontend utilizes two verification mechanisms:

### 2.1 Vitest Unit Tests
Verifies React component rendering, state contexts, and sidebar layouts in isolation:
*   **Path**: `frontend/src/tests/`
*   **Command**:
    ```bash
    cd frontend && pnpm run test
    ```

### 2.2 Cypress End-to-End (E2E)
Spins up a headless Chrome browser to walk through login, call reviews, AI Assistant chat, and dispute submissions.
*   **Path**: `frontend/cypress/e2e/`
*   **Requirement**: The frontend must be built and run in preview mode (dev server is not supported).
*   **Command**:
    ```bash
    make fe-test
    ```

---

## 3. Ingestion & Quality Benchmarks

*   **RAG Tests**: Located under `services/rag/tests/`, running pytest against Docling parsers, chunking strategies, and Qdrant retrieval queries.
*   **Quality benchmarks**: Compares current backend audio processing results against expected gold-standard outputs.
    *   **Command**:
        ```bash
        make quality-eval-all
        ```
    *   **Metric Report**: Generates `tools/reports/EVAL_REPORT.md` analyzing topic matching, turn ratio correctness, diarization delta, and emotion cosine similarity.

---

## 4. SQLite vs. PostgreSQL Caveats

> [!WARNING]
> While backend unit tests execute against an in-memory SQLite database for speed, production runs utilize PostgreSQL. Some PostgreSQL-specific operations (such as JSONB fields or indexing formats) behave differently in SQLite. Always perform manual verification against a running PostgreSQL container before production deployments.
