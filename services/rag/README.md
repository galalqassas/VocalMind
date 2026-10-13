# VocalMind RAG Service

Document ingestion, Qdrant retrieval, optional answer synthesis, and policy/answer judges. Python ≥ 3.11, managed with `uv`. In compose it runs as the `vocalmind-ingestion` container (`python main.py --watch`); the backend imports `query_engine.py` and `evaluator.py` from the `/app/rag` mount.

The models (embeddings, Docling PDF parsing, cross-encoder rerank) run where `RAG_MODELS_HOST` says:

- `kaggle` (compose and `.env.example` default) — on the Kaggle GPU server at `KAGGLE_SERVER_URL` ([services/kaggle](../kaggle/README.md)). Base install only: `uv sync`.
- `local` (`Settings` default) — Ollama for embeddings plus in-process Docling and cross-encoder: `uv sync --extra local-models` (Docker: build arg `RAG_LOCAL_MODELS=true`).

The two hosts use different embedding models, so after switching re-ingest with `uv run python main.py --ingest --force`.

Concepts and collection roles: [docs/rag/RAG_OVERVIEW.md](../../docs/rag/RAG_OVERVIEW.md). Pipeline details: [docs/rag/INGESTION_PIPELINE.md](../../docs/rag/INGESTION_PIPELINE.md). Evaluation: [docs/rag/RAGAS_EVALUATION.md](../../docs/rag/RAGAS_EVALUATION.md).

## Modules

| File | Role |
|---|---|
| `main.py` | CLI entry point |
| `ingest.py` | `DocumentIngestionPipeline`: Docling → clean → parent/child chunks → embeddings → Qdrant |
| `query_engine.py` | `RAGQueryEngine`: org-filtered retrieval, rerank, optional LlamaIndex synthesis, query logs |
| `reranker.py` | Cross-encoder rerank (`BAAI/bge-reranker-v2-m3`, Kaggle `/rerank` or in-process); keeps dense order if reranking fails |
| `evaluator.py` | `PolicyComplianceEvaluator` (parents) and `AnswerCorrectnessEvaluator` (children) LLM judges |
| `prompt_safety.py` | `sanitize_prompt_text`, `with_injection_guard`, `INJECTION_GUARD` |
| `llm_circuit_breaker.py` | Circuit breakers for judge and embedding calls (the backend's `app.core.llm_circuit_breaker` is preferred when importable) |
| `config.py` | `Settings` (env from `services/rag/.env`, repo `.env`, `backend/.env`); stage → model resolution; Kaggle helpers (`use_kaggle_models`, `kaggle_post`, `kaggle_embed`) |
| `ragas_eval.py` | RAGAS evaluation |

## Collections

| Collection | Content |
|---|---|
| `vocalmind_parents` | Policy H1/H2/H3 sections |
| `vocalmind_children` | Policy children (atomic rule rows, atomic tables, 400/80 text splits) |
| `vocalmind_sop_parents` | SOP and KB sections (no children) |

All vectors: 1024-d, cosine; `Snowflake/snowflake-arctic-embed-l-v2.0` (Kaggle) or `snowflake-arctic-embed2` (Ollama). Every point carries `org` (org folder name) and `doc_type` (`policy` / `sop` / `kb`).

## Documents

```
storage/docs/<org>/policy-docs/*.pdf      → policy
storage/docs/<org>/sop-procedures/*.pdf   → sop   (legacy: faq-docs/)
storage/docs/<org>/knowledge-base/*.pdf   → kb    (legacy: kb/)
```

Parsed output goes to `storage/docs/<org>/parsed-docs/{policies,sops,kb}/`.

## CLI (run from `services/rag`)

| Command | Action |
|---|---|
| `uv run python main.py --ingest [--force]` | Ingest all PDFs; `--force` drops and recreates the three collections first |
| `uv run python main.py --watch [--interval 60]` | Poll for PDF changes and re-run ingestion (container default) |
| `uv run python main.py -q "question" --org nexalink [--parents]` | Retrieve + synthesize from children (or parents) |
| `uv run python main.py --compliance "transcript" --org nexalink` | `PolicyComplianceEvaluator` |
| `uv run python main.py --check-answer --question "…" --answer "…" --org nexalink` | `AnswerCorrectnessEvaluator` |
| `uv run python main.py` | Interactive mode |

`--org` must be the org folder name; without it, queries match nothing.

## Configuration

Copy `.env.example` to `.env` (values from the repo `.env` and `backend/.env` are also read). Main variables:

| Variable | Default | Purpose |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | Vector DB |
| `QDRANT_COLLECTION_PARENTS` / `_CHILDREN` / `_SOP_PARENTS` | `vocalmind_parents` / `vocalmind_children` / `vocalmind_sop_parents` | Collection names |
| `RAG_MODELS_HOST`, `KAGGLE_SERVER_URL` | `local`, empty | Run embed/parse/rerank locally or on the Kaggle server |
| `OLLAMA_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` | `http://localhost:11434`, `snowflake-arctic-embed2`, `1024` | Embeddings when `local` |
| `OLLAMA_CLOUD_EMBED_ENABLED` | `false` | With `local`, embed via Ollama Cloud instead |
| `DOCS_DIR`, `POLICY_DOCS_DIR`, `KNOWLEDGE_DOCS_DIR`, `PARSED_DIR`, `PARSED_POLICY_DIR`, `PARSED_SOP_DIR` | `<repo>/storage/docs` | Source and output roots (relative paths resolve against `services/rag/`) |
| `LLM_PROVIDER` | `groq` (compose: `ollama_cloud`) | Synthesis and judge provider |
| `GROQ_API_KEY`, `LLM_MODEL` | —, `llama-3.3-70b-versatile` | Groq |
| `OLLAMA_CLOUD_API_KEY` (or `OLLAMA_API_KEY`), `OLLAMA_CLOUD_FAST_MODEL`, `OLLAMA_CLOUD_HEAVY_MODEL`, `OLLAMA_MODEL_RAG_SYNTHESIS`, `OLLAMA_MODEL_RAG_JUDGE` | | Ollama Cloud models |
| `SYNTHESIS_BASE_URL`, `SYNTHESIS_MODEL` | empty | Override synthesis with any OpenAI-compatible endpoint |
| `SYNTHESIS_PROMPT_MODE` | `safe` | `safe` or `assertive` |
| `RERANK_ENABLED`, `RERANK_MODEL`, `RERANK_CANDIDATE_K`, `RERANK_MIN_SCORE` | `true`, `BAAI/bge-reranker-v2-m3`, `20`, `-1000` | Reranking (`RERANK_MODEL` applies to `local` only) |
| `HYDE_ENABLED` | `false` | HyDE query expansion |
| `RAG_QUERY_LOG_ENABLED` | `false` | Write `logs/query_*.json` |

## Tests

`make rag-test` (or `uv run pytest tests/ -v`) and `make rag-lint`. Tests: `test_config.py`, `test_ingest.py`, `test_kaggle_models.py`, `test_query_engine.py`, `test_evaluator.py`, `test_ragas_eval.py`.
