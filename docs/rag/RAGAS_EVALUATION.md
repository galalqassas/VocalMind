# RAGAS Evaluation

Measures the RAG service's retrieval + synthesis quality (`RAGQueryEngine` in `services/rag/query_engine.py`) with [RAGAS](https://docs.ragas.io/). Implementation: `services/rag/ragas_eval.py`. Domain judges (`PolicyComplianceEvaluator`, `AnswerCorrectnessEvaluator` in `services/rag/evaluator.py`) are separate.

## Modes

| Mode | Command | What runs |
|---|---|---|
| `reference-free` | `make ragas-eval-quick` (also `make quality-eval-ragas`) | 15 policy queries via `query_compliance` (parents, `doc_type=policy`) + 15 Q&A queries via `query_answer` (children); metrics Faithfulness, AnswerRelevancy (`strictness=3`), LLMContextPrecisionWithoutReference |
| `generate` | `make ragas-generate-testset` (`--size 50`; CLI default 20) | RAGAS `TestsetGenerator` over every `*.md` under `storage/docs/{org}/parsed-docs/`; writes `services/rag/ragas_testset.json` |
| `full` | `make ragas-eval-full` | Each testset sample through `query()` (children); Faithfulness, AnswerRelevancy, ContextPrecision, plus ContextRecall and AnswerCorrectness when samples have a `reference` |

CLI: `cd services/rag && uv run python ragas_eval.py --mode <mode> [--org nexalink] [--size N] [--testset PATH] [--verbose]`. `--org` defaults to `nexalink` and must match the `org` payload (org slug). Samples with no retrieved context are skipped.

Testset format: `{"samples": [{"user_input": "...", "reference": "..."}, ...]}`; extra keys are kept. Hand-written samples can be appended in the same shape.

## Prerequisites

1. Qdrant running (`make support-up`) and the embedding host used at ingest: the Kaggle server (`RAG_MODELS_HOST=kaggle`, `KAGGLE_SERVER_URL`) or Ollama (`make support-up-local` + `make ollama-pull-embed`).
2. Documents ingested: `cd services/rag && uv run python main.py --ingest`.
3. A synthesis LLM: Groq key, `LLM_PROVIDER=ollama_cloud` + Ollama Cloud key, or `SYNTHESIS_BASE_URL` (see [RAG_OVERVIEW.md](RAG_OVERVIEW.md#retrieval-paths)).
4. A judge LLM (below).

## Judge and embeddings

`RAGAS_JUDGE_PROVIDER`:

- `local` (default): OpenAI-compatible endpoint `RAGAS_JUDGE_BASE_URL` (default `http://localhost:1234/v1`, LM Studio) with `RAGAS_JUDGE_MODEL` (default `qwen2.5-7b-instruct`), `max_tokens=2048`.
- `groq`: `llama-3.3-70b-versatile`, `max_tokens=2048`.
- `vertex`: Vertex AI OpenAI-compatible endpoint using service account `VERTEX_SA_FILE`, `VERTEX_LOCATION`, model `RAGAS_JUDGE_MODEL`, `max_tokens=8192`.

RAGAS embeddings use the same embedding host as retrieval (`_OllamaEmbeddings`, which calls Kaggle `/embed` when `RAG_MODELS_HOST=kaggle`). `RunConfig(max_workers=2, timeout=180)` limits concurrency for rate-limited providers.

Synthesis knobs that move the scores: `SYNTHESIS_PROMPT_MODE` (`safe` admits missing context; `assertive` never hedges and scores higher on AnswerRelevancy), `RERANK_ENABLED`, `RERANK_CANDIDATE_K`, `similarity_top_k`, `HYDE_ENABLED`.

## Outputs and thresholds

Reports: `services/rag/reports/ragas_<mode>_<YYYYMMDD_HHMMSS>.json` with `timestamp`, `mode`, `org_filter`, `total_samples`, `metrics`, `per_sample`, `duration_seconds`.

`full` mode prints PASS/FAIL against the `ragas` section of `infra/benchmarks/schema/thresholds.json` (`min_faithfulness` 0.7, `min_answer_relevancy` 0.7, `min_context_precision` 0.6, `min_context_recall` 0.6, `min_answer_correctness` 0.6). It does not change the exit code; `reference-free` mode does not check thresholds.

## Results

Latest committed run: `services/rag/reports/ragas_reference_free_20260620_121710.json` — `reference-free`, org `nexalink`, 30 samples.

| Metric | Score |
|---|---|
| Faithfulness | 0.82 |
| Answer Relevancy | 0.81 |
| Context Precision | 0.82 |

The report file does not record the judge or synthesis model. Earlier runs in the same folder show the faithfulness/relevancy trade-off driven by the synthesis prompt (e.g. `…_113130.json`: 0.90 / 0.53 / 0.78; `…_115645.json`: 0.82 / 0.69 / 0.80).

Limits of these numbers:

- Reference-free only: ContextRecall and AnswerCorrectness need a testset (`generate` then `full`).
- Scores depend on the judge model; small local judges can return unparseable verdicts that RAGAS records as NaN.
- 30 hand-written queries (`_POLICY_COMPLIANCE_QUERIES`, `_QA_QUERIES` in `ragas_eval.py`).

## Interpreting

- Low Context Precision → tune retrieval (reranker, `similarity_top_k`, chunking) before prompts.
- High Faithfulness but low domain-judge scores → the issue is in judge prompts or document coverage, not retrieval.

## Known issues

- `RAGAS_JUDGE_PROVIDER=vertex` reads `settings.VERTEX_PROJECT`, which `services/rag/config.py` does not define (it has `GEMINI_PROJECT`), so the Vertex judge raises `AttributeError`.
- `generate` loads every Markdown file in `parsed-docs/`, including `*_raw.md` and `*_chunks.md` debug artifacts.
