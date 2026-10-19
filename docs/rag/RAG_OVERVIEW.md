# RAG Overview

Retrieval layer that grounds LLM-trigger verdicts in organization policy, SOP, and knowledge-base documents. Service code: `services/rag/` (runbook: [services/rag/README.md](../../services/rag/README.md)). Ingestion: [INGESTION_PIPELINE.md](INGESTION_PIPELINE.md). Evaluation: [RAGAS_EVALUATION.md](RAGAS_EVALUATION.md).

## Document types

| Folder under `storage/docs/{org}/` | `doc_type` | Indexed into |
|---|---|---|
| `policy-docs/` (and org-root PDFs when no typed folder exists) | `policy` | `vocalmind_parents` + `vocalmind_children` |
| `sop-procedures/`, legacy `faq-docs/` | `sop` | `vocalmind_sop_parents` |
| `knowledge-base/`, legacy `kb/` | `kb` | `vocalmind_sop_parents` |

## Collections

| Collection (env var) | Content | Used by |
|---|---|---|
| `vocalmind_parents` (`QDRANT_COLLECTION_PARENTS`) | Policy sections split on H1/H2/H3 | NLI policy context and claim cards (`PolicyRetriever`), `PolicyComplianceEvaluator`, `/api/v1/rag/query` mode `compliance` |
| `vocalmind_children` (`QDRANT_COLLECTION_CHILDREN`) | Policy children: one atomic chunk per rule-table row, other tables kept whole, free text split 400 chars / 80 overlap | `/api/v1/rag/query` mode `answer`, `AnswerCorrectnessEvaluator`, `main.py -q`, RAGAS Q&A queries |
| `vocalmind_sop_parents` (`QDRANT_COLLECTION_SOP_PARENTS`) | SOP and KB sections (parents only) | Process-adherence SOP context (`SOPRetriever`, `doc_type=sop`); `KBRetriever` (`doc_type=kb`) |

Rule: parents when the consumer needs the whole rule or procedure; children when it needs a short span to quote. Vectors: `snowflake-arctic-embed2`, 1024-d, cosine.

## Retrieval paths

**Backend** (`backend/app/llm_trigger/retrieval.py`): embeds via Ollama (`/api/embed`, fallback `/api/embeddings`; Ollama Cloud `/embeddings` when `OLLAMA_CLOUD_EMBED_ENABLED=true`), queries Qdrant with filters `org` + `doc_type`, and drops any chunk without `doc_type`. No reranking. SOP context prefers manual org files over Qdrant and policy context prefers Qdrant over DB policies — see [LLM_TRIGGER_FEATURE_GUIDE.md](../llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md#orchestration-evaluate_interaction_triggers).

**RAG service** (`services/rag/query_engine.py`, `RAGQueryEngine`):

1. Optional HyDE expansion (`HYDE_ENABLED`, default off).
2. Qdrant query filtered by `org` (+ `doc_type` when given; retried without `doc_type` if empty), fetching `RERANK_CANDIDATE_K` (20) candidates when `RERANK_ENABLED` (default on).
3. Cross-encoder rerank (`reranker.py`, `BAAI/bge-reranker-v2-m3`) to `similarity_top_k` (3); falls back to dense order if the model cannot load. `RERANK_MIN_SCORE` defaults to −1000 (no cut).
4. Optional synthesis (LlamaIndex, `response_mode=compact`) for `query()`, `query_compliance()`, `query_answer()`; `retrieve_*_context()` skip it.

Synthesis LLM: `SYNTHESIS_BASE_URL` (any OpenAI-compatible endpoint) if set; else Ollama Cloud with the `rag_synthesis` stage model (`OLLAMA_MODEL_RAG_SYNTHESIS` or `OLLAMA_CLOUD_FAST_MODEL`) when `LLM_PROVIDER=ollama_cloud`; else Groq `LLM_MODEL`. `SYNTHESIS_PROMPT_MODE` = `safe` (default; admits missing context) or `assertive`.

`backend/app/api/routes/rag.py` imports `RAGQueryEngine` from the `services/rag` mount (`/app/rag` in compose) and exposes `GET /api/v1/rag/health` and `POST /api/v1/rag/query` (adds `retrieval_provenance`; see [explainability](../explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md#api-surface)).

## Tenancy and prompt safety

- Every query filters on payload `org`, which ingestion sets to the org folder name (slug). Missing org → `__missing_org_scope__` (no results).
- `services/rag/prompt_safety.py`: `sanitize_prompt_text` neutralizes role prefixes and code fences and truncates; `with_injection_guard` appends `INJECTION_GUARD` to synthesis questions. The evaluators sanitize transcript, answer, and context text.

## Known issues

- `POST /api/v1/rag/query` passes `str(current_user.organization_id)` (a UUID) as `org_filter`, but points are tagged with the org slug, so it returns no chunks.
- `retrieve_kb_chunks` / `KBRetriever` is defined but has no caller; KB documents are not used for claim validation at runtime.
- Toggling or deleting a policy in the Knowledge Base UI does not remove its Qdrant points (see [KNOWLEDGE_BASE_MANAGEMENT.md](../operations/KNOWLEDGE_BASE_MANAGEMENT.md)).
- The manager assistant is text-to-SQL only; it does not query the children collection.

## Tests

`make rag-test` (`services/rag/tests/`: `test_config.py`, `test_ingest.py`, `test_query_engine.py`, `test_evaluator.py`, `test_ragas_eval.py`); backend: `backend/tests/test_sop_retrieval.py`.
