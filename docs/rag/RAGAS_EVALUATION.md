# RAGAS Evaluation

## Overview

[RAGAS](https://docs.ragas.io/) (Retrieval Augmented Generation Assessment) is a framework for evaluating RAG pipelines with standardized, reproducible metrics. VocalMind uses RAGAS to measure how well the retrieval layer (Qdrant + Ollama embeddings) and the synthesis layer (Groq LLM) perform together — independently of the domain-specific evaluators in [`evaluator.py`](../../services/rag/evaluator.py).

**Why RAGAS?** The existing `PolicyComplianceEvaluator` and `AnswerCorrectnessEvaluator` measure domain-specific quality (does the agent comply? is the answer factually correct?). RAGAS measures the *underlying retrieval and generation pipeline quality* — faithfulness, relevancy, precision, and recall — which are prerequisites for those domain evaluators to work well.

---

## Metrics Reference

| Metric | What it measures | Ground truth required? | Range |
|---|---|---|---|
| **Faithfulness** | Is every claim in the answer traceable to the retrieved context? Penalizes hallucinated statements. | No | 0 → 1 |
| **Answer Relevancy** | Is the answer relevant and on-topic for the question? Penalizes vague or off-topic responses. | No | 0 → 1 |
| **Context Precision** | Are the retrieved chunks relevant to the question? Penalizes noisy retrieval. | No | 0 → 1 |
| **Context Recall** | Did retrieval find all the information needed to answer? Measures coverage. | **Yes** | 0 → 1 |
| **Answer Correctness** | Is the answer factually correct compared to a known ground truth? | **Yes** | 0 → 1 |

> [!TIP]
> Start with the three reference-free metrics (Faithfulness, Answer Relevancy, Context Precision) for quick feedback loops. Only invest in ground truth when you need the full picture.

---

## Three Evaluation Modes

### 1. Reference-Free (`--mode reference-free`)

Runs **Faithfulness + Answer Relevancy + Context Precision** against a set of sample queries. No ground truth needed.

```bash
make ragas-eval-quick
# or directly:
cd services/rag && uv run python ragas_eval.py --mode reference-free
```

**How it works:**
1. A predefined set of sample queries (in `ragas_eval.py`) is sent to the RAG pipeline
2. The pipeline retrieves context from Qdrant and generates answers via Groq
3. RAGAS scores each (question, answer, contexts) triple on the three reference-free metrics

**When to use:** Quick iteration after changing chunking parameters, embeddings, or retrieval settings.

### 2. Testset Generation (`--mode generate`)

Uses RAGAS `TestsetGenerator` to create synthetic Q&A pairs with ground truth from your policy/SOP documents.

```bash
make ragas-generate-testset
# or directly:
cd services/rag && uv run python ragas_eval.py --mode generate
```

**How it works:**
1. Loads all PDFs from `storage/docs/nexalink/` (policy-docs, sop-procedures, knowledge-base)
2. RAGAS generates diverse question types (simple, multi-hop, reasoning) with reference answers
3. Saves the testset to `services/rag/ragas_testset.json`

> [!IMPORTANT]
> Review the generated testset before running full evaluation. Remove low-quality or ambiguous Q&A pairs that could skew results.

### 3. Full Evaluation (`--mode full`)

Runs **all 5 metrics** against the generated or curated testset.

```bash
make ragas-eval-full
# or directly:
cd services/rag && uv run python ragas_eval.py --mode full
```

**How it works:**
1. Loads the testset from `services/rag/ragas_testset.json`
2. For each test case, retrieves context and generates an answer via the RAG pipeline
3. Scores all 5 metrics including Context Recall and Answer Correctness (which need the ground truth answers from the testset)

---

## Running Evaluations

### Make Targets

| Target | Mode | What it does |
|---|---|---|
| `make ragas-eval-quick` | reference-free | Runs 3 metrics on sample queries, no ground truth |
| `make ragas-generate-testset` | generate | Creates synthetic testset from docs in `storage/docs/nexalink/` |
| `make ragas-eval-full` | full | Runs all 5 metrics against `ragas_testset.json` |

### Direct CLI

```bash
cd services/rag

# Reference-free (quick)
uv run python ragas_eval.py --mode reference-free

# Generate testset
uv run python ragas_eval.py --mode generate --size 20

# Full evaluation
uv run python ragas_eval.py --mode full

# Full evaluation with verbose output
uv run python ragas_eval.py --mode full --verbose
```

---

## Prerequisites

Before running any RAGAS evaluation:

```bash
# 1. Start infrastructure (Qdrant, Ollama, PostgreSQL)
make support-up

# 2. Pull the embedding model
docker exec vocalmind-ollama ollama pull snowflake-arctic-embed2

# 3. Ingest documents into Qdrant
cd services/rag && uv run python main.py --ingest storage/docs/nexalink

# 4. Ensure GROQ_API_KEY is set
echo $GROQ_API_KEY  # must be valid
```

> [!CAUTION]
> All four prerequisites must be met. Without ingested documents, retrieval returns empty contexts and all scores will be near zero.

| Dependency | Required for | How to verify |
|---|---|---|
| Qdrant (`:6333`) | Vector retrieval | `curl http://localhost:6333/healthz` |
| Ollama + `snowflake-arctic-embed2` | Query embedding | `curl http://localhost:11434/api/tags` |
| `GROQ_API_KEY` | Judge LLM + synthesis | Set in `services/rag/.env` or `backend/.env` |
| Ingested docs | Non-empty retrieval | `make ragas-eval-quick` returns scores > 0 |

---

## Interpreting Results

### Report Location

Reports are saved to `services/rag/reports/` with timestamped filenames:

```
services/rag/reports/
├── ragas_reference_free_20260619_181400.json
├── ragas_full_20260619_182000.json
└── ragas_testset.json
```

### Report Structure

```json
{
  "timestamp": "2026-06-19T18:14:00Z",
  "mode": "reference-free",
  "metrics": {
    "faithfulness": 0.87,
    "answer_relevancy": 0.91,
    "context_precision": 0.82
  },
  "per_question": [
    {
      "question": "What is the refund policy?",
      "faithfulness": 0.95,
      "answer_relevancy": 0.88,
      "context_precision": 0.90
    }
  ]
}
```

### Quality Thresholds

Existing thresholds are in [`infra/benchmarks/schema/thresholds.json`](../../infra/benchmarks/schema/thresholds.json). The `rag` section defines:

```json
{
  "rag": {
    "min_correctness_accuracy": 0.75,
    "min_evidence_coverage": 0.70
  }
}
```

RAGAS-specific thresholds to target:

| Metric | Target | Action if below |
|---|---|---|
| Faithfulness | ≥ 0.85 | Check synthesis prompt — LLM may be hallucinating beyond context |
| Answer Relevancy | ≥ 0.80 | Check query formulation or synthesis prompt |
| Context Precision | ≥ 0.75 | Tune `similarity_top_k`, chunking params, or embedding model |
| Context Recall | ≥ 0.70 | Increase `top_k`, improve chunking coverage, or add missing docs |
| Answer Correctness | ≥ 0.75 | Combination of retrieval + synthesis issues |

---

## Adding Custom Q&A Pairs

The generated testset at `services/rag/ragas_testset.json` can be extended with manually curated test cases. This is recommended for edge cases or critical policy questions that synthetic generation may miss.

### Format

```json
[
  {
    "question": "What is the maximum refund amount for NexaLink customers?",
    "ground_truth": "The maximum refund amount is $500 for standard customers and $1000 for premium customers.",
    "metadata": {
      "source": "manual",
      "category": "policy",
      "difficulty": "simple"
    }
  },
  {
    "question": "When should an agent escalate a billing dispute to a supervisor?",
    "ground_truth": "Agents must escalate billing disputes over $200 or when the customer has filed more than 2 disputes in 30 days.",
    "metadata": {
      "source": "manual",
      "category": "sop",
      "difficulty": "reasoning"
    }
  }
]
```

> [!NOTE]
> The `metadata` field is optional but useful for filtering results by category or difficulty in reports.

### Tips for Curating Q&A Pairs

1. **Cover all doc types** — include questions that require policy, SOP, and KB retrieval
2. **Include multi-hop questions** — "If a customer requests a refund AND has an open complaint, what should the agent do?"
3. **Test negatives** — questions where the correct answer is "this is not covered by policy"
4. **Mirror real queries** — use actual manager-assistant questions from production logs

---

## Architecture

```
 ragas_eval.py
   │
   ├── Local LM Studio (Judge LLM) — configurable
   │    └── LangchainLLMWrapper(ChatOpenAI → http://localhost:1234/v1)
   │         RAGAS uses this for metric computation
   │         (faithfulness reasoning, relevancy scoring, etc.)
   │         Set RAGAS_JUDGE_MODEL to a plain INSTRUCT model
   │         (e.g. qwen2.5-7b-instruct) — NOT a vision "-vl" variant.
   │
   ├── Ollama (Embeddings)
   │    └── Custom OllamaEmbeddingWrapper
   │         Wraps Ollama HTTP API for RAGAS embedding calls
   │         Model: snowflake-arctic-embed2 (1024-dim)
   │
   └── RAGQueryEngine
        └── Qdrant retrieval + Groq synthesis
             The pipeline under evaluation
```

### Key Integration Points

| Component | Role | Implementation |
|---|---|---|
| **Judge LLM** | Computes RAGAS metrics (faithfulness decomposition, relevancy scoring) | `LangchainLLMWrapper(ChatOpenAI(...))` → local LM Studio; set `RAGAS_JUDGE_MODEL` to a plain instruct model |
| **Embeddings** | RAGAS-internal embedding for answer relevancy computation | Custom `OllamaEmbeddingWrapper` hitting Ollama's `/api/embed` |
| **RunConfig** | Controls parallelism | `RunConfig(max_workers=2)` — prevents Groq rate limiting |
| **RAGQueryEngine** | The pipeline being evaluated | [`query_engine.py`](../../services/rag/query_engine.py) — retrieves from Qdrant, synthesizes via Groq |

### Testset Generation Architecture

```
 storage/docs/nexalink/
   ├── policy-docs/*.pdf
   ├── sop-procedures/*.pdf
   └── knowledge-base/*.pdf
         │
         ▼
   Docling/LangChain document loaders
         │
         ▼
   RAGAS TestsetGenerator
   (uses Groq LLM to create diverse Q&A pairs)
         │
         ▼
   services/rag/ragas_testset.json
```

---

## Rate Limiting

RAGAS makes **many LLM calls** internally — each metric decomposes answers into claims, evaluates each claim, and aggregates. A single evaluation of 20 questions can make 100+ LLM calls.

```python
from ragas import RunConfig

run_config = RunConfig(max_workers=2)  # limit concurrent LLM calls
```

> [!WARNING]
> Without `max_workers=2`, RAGAS will fire parallel requests that quickly hit Groq's rate limits (30 requests/minute on free tier). If you see `429 Too Many Requests` errors, reduce `max_workers` to 1.

| Groq tier | Recommended `max_workers` | Approx. time for 20 questions (full mode) |
|---|---|---|
| Free | 1 | ~15 min |
| Developer | 2 | ~8 min |
| Production | 4 | ~4 min |

---

## Relation to Existing Evaluators

VocalMind has two layers of evaluation. RAGAS and the existing evaluators are **complementary**, not redundant.

| Aspect | RAGAS | Existing evaluators ([`evaluator.py`](../../services/rag/evaluator.py)) |
|---|---|---|
| **What it measures** | Retrieval quality + generation faithfulness | Domain-specific compliance + factual correctness |
| **Scope** | Pipeline-level (is the RAG system working?) | Task-level (did the agent follow policy?) |
| **Ground truth** | Synthetic or curated Q&A pairs | Retrieved context (no external ground truth) |
| **When to run** | After changing retrieval/chunking/embeddings | On every interaction (production pipeline) |
| **Key metrics** | Faithfulness, Relevancy, Precision, Recall | `compliance_score`, `correctness_score` |

### How They Complement Each Other

```
RAGAS (pipeline quality)              Existing evaluators (domain quality)
─────────────────────────             ──────────────────────────────────────
"Is retrieval finding the             "Does this transcript violate
 right chunks?"                        refund policy section 3.2?"

"Is the LLM faithful to               "Is the agent's answer about
 retrieved context?"                    billing correct per our KB?"

        ▲                                       ▲
        │                                       │
        └── Fix chunking, embeddings,           └── Fix prompts, policy docs,
            top_k, collection routing                SOP definitions
```

> [!TIP]
> If `PolicyComplianceEvaluator` scores are low but RAGAS Faithfulness is high, the issue is likely in the compliance prompt or policy doc coverage — not in retrieval. If RAGAS Context Precision is low, fix retrieval first before tuning domain evaluators.
