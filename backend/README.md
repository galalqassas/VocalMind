# Backend

## Setup

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

### Installation

1. Install `uv`:

   ```bash
   pip install uv
   # or
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

### Running the Server

```bash
uv run uvicorn app.main:app --reload --port 8000
```

### Development

- Add a package:
  ```bash
  uv add <package>
  ```
- Run tests (if any):
  ```bash
  uv run pytest tests/ -v
  ```

### Project Layout

- `app/` - FastAPI application code.
- `tests/` - automated pytest suite.
- `scripts/` - repeatable maintenance and seed scripts.
- `scripts/manual/` - ad hoc local probes that are not collected by pytest.

- **[Evidence-Anchored Explainability Layer](../docs/explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md)**
- **[LLM Trigger Feature Guide](../docs/llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)**
- **[RAG Overview](../docs/rag/RAG_OVERVIEW.md)**

## Speaker Classification Setup

The backend uses a hybrid speaker role classifier that identifies the roles (`agent` vs `customer`) of raw speaker clusters.

### Dependencies
The model requires `scikit-learn` which has been added to `pyproject.toml`.
- **Docker**: Handled automatically. The container automatically installs it.
- **Local Dev**: Run `uv sync` to update your local virtualenv.

### Model Artifacts
Teammates must place the following binary files in the `app/core/` directory:
- `backend/app/core/model.pkl` (Logistic Regression weights)
- `backend/app/core/vectorizer.pkl` (Fitted TF-IDF vectorizer)

These files are ignored by Git. They can be obtained as follows:
1. **Download `model.pkl` from MLflow**:
   Ensure `MLFLOW_TRACKING_PASSWORD` is configured, then run:
   ```bash
   python tools/download_mlflow_model.py --run-id 85c2377290ee459a8232c8136d0721c5 --output-dir backend/app/core/
   python -c "import shutil; shutil.move('backend/app/core/model/model.pkl', 'backend/app/core/model.pkl'); shutil.rmtree('backend/app/core/model')"
   ```
2. **Obtain `vectorizer.pkl`**:
   The TF-IDF vectorizer was not logged in the MLflow run and must be copied from the team's shared storage directly to `backend/app/core/vectorizer.pkl` to prevent vocabulary shift alignment issues.

If not present, the pipeline falls back gracefully to rule-based heuristic phrase matching.


