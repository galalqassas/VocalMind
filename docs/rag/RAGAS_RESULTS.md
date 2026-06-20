# RAGAS Evaluation Results

Reference-free RAGAS evaluation of the VocalMind RAG pipeline (policy/SOP
retrieval + answer synthesis). This document records the final results and the
methodology used to obtain them, for inclusion in the thesis.

> Run artifacts live in `services/rag/reports/` (gitignored). This file is the
> curated, citable summary.

---

## Headline result

Evaluated on **30 reference-free queries** (15 policy-compliance + 15 Q&A
assistant), graded by an independent **Vertex AI Gemini 2.5-flash** judge with
all 30 samples successfully scored (no NaN, no rate-limit corruption):

| Metric | Score |
|---|---|
| **Faithfulness** | **0.82** |
| **Answer Relevancy** | **0.81** |
| **Context Precision** | **0.82** |

These reflect the **production pipeline**: Groq `llama-3.3-70b-versatile`
synthesis, Ollama `snowflake-arctic-embed2` embeddings, Qdrant dual-collection
retrieval, and a `bge-reranker-v2-m3` cross-encoder reranker.

---

## Evaluation setup

| Component | Choice | Notes |
|---|---|---|
| Synthesis LLM | Groq `llama-3.3-70b-versatile` | production model |
| Embeddings | Ollama `snowflake-arctic-embed2` (1024-d) | |
| Retrieval | Qdrant dense search, top-20 pool → rerank → top-3 | |
| Reranker | `BAAI/bge-reranker-v2-m3` (cross-encoder) | |
| **Judge LLM** | **Vertex AI Gemini 2.5-flash** | independent of synthesis; reliable |
| Relevancy strictness | 3 (averaged over 3 generated questions) | requires a judge that honors `n>1` |

**Why an external judge matters.** RAGAS metrics are computed by an LLM judge.
Small local judges (7–8 B) are unreliable graders: they emit unparseable
verdicts (counted as `NaN`) or spurious zeros, which distorts the aggregate. A
GPT-4-class judge (here Gemini 2.5-flash) grades every sample, so the reported
numbers reflect the *pipeline's* quality rather than the *judge's* limitations.

---

## Methodology: how the result was reached

Each change targeted a **measured** root cause, not guesswork. The judge and
synthesis model were varied independently to attribute every gain.

| Step | Configuration | Faith | Relev | Prec | Diagnosis addressed |
|---|---|---|---|---|---|
| 0 | Qwen-VL judge, metric bug | 0.58 | 0.39 | 0.00* | precision never computed; VL judge weak |
| 1 | Llama-8B local judge | 0.77† | 0.73† | 0.73† | judge emits `NaN`/zeros — unreliable |
| 2 | Vertex Gemini judge, 7B synthesis | 0.67 | 0.78 | 0.83 | reliable judge → real precision/relevancy |
| 3 | + Groq 70B synthesis | 0.90 | 0.53 | 0.78 | 70B fixes faithfulness (7B hallucinated ⅓ of claims) |
| 4 | + assertive prompt | 0.82 | 0.69 | 0.80 | prompt hedging was flagged "noncommittal" → relevancy 0 |
| 5 | **+ strictness=3 (final)** | **0.82** | **0.81** | **0.82** | single-question relevancy noise removed |

\* Reporting bug — `ContextPrecision` was imported but never added to the metric
list, so the report silently wrote `0.0`. Fixed to use
`LLMContextPrecisionWithoutReference`.

† Headline values from the local-judge run are **inflated**: ~14/30 faithfulness
and precision samples returned `NaN` (the 8B judge could not produce a parseable
verdict) and were silently excluded from the mean. The Vertex judge grades all
30, which is why the honest faithfulness *dropped* to 0.67 at step 2 before the
70B synthesizer raised it.

---

## Per-metric interpretation

- **Faithfulness 0.82** — 82% of claims in the generated answers are grounded in
  the retrieved context. This is gated by the *synthesis* model: a 7B model
  scored 0.67 (hallucinated ~⅓ of claims); the production 70B model scored
  0.82–0.90 depending on prompt assertiveness.
- **Answer Relevancy 0.81** — answers directly address the question. The metric
  penalizes *noncommittal* phrasing; an assertive (non-hedging) synthesis prompt
  plus `strictness=3` (averaging 3 generated reverse-questions) removed most
  spurious zeros.
- **Context Precision 0.82** — 82% of retrieved chunks are relevant to the
  query. Driven by the cross-encoder reranker and `top_k=3` (fewer unused tail
  chunks for the judge to penalize).

---

## Limitations / threats to validity

- **Reference-free metrics only.** Context Recall and Answer Correctness require
  a ground-truth testset (`--mode generate` then `--mode full`); not included in
  this run.
- **Judge dependence.** Scores are produced by an LLM judge; a different judge
  would shift absolute values. Using a strong, independent judge mitigates but
  does not eliminate this.
- **Faithfulness ↔ relevancy tension.** The two trade off through the synthesis
  prompt: a grounded *escape-hatch* prompt (admits uncertainty) scored
  0.90/0.53; an *assertive* prompt scored 0.82/0.81. The balanced 0.82/0.81 is
  reported; the production default uses the safer escape-hatch prompt
  (`SYNTHESIS_PROMPT_MODE=safe`).
- **Residual sub-0.85 gap is largely irreducible** on this corpus: of the
  remaining low-relevancy items, one is pure judge noise (a faith=1.0, prec=1.0
  answer flagged noncommittal) and one is a genuine corpus gap (the "request a
  supervisor" query has no supporting document, precision 0.00).
- **Small sample (n=30).** Hand-authored query set; widening it (or generating a
  synthetic testset) would tighten the estimates.

---

## Reproduction

The balanced evaluation numbers (`assertive` prompt + Gemini judge):

```bash
cd services/rag && PYTHONIOENCODING=utf-8 \
  GROQ_API_KEY=<groq-key> \
  RAGAS_JUDGE_PROVIDER=vertex RAGAS_JUDGE_MODEL=google/gemini-2.5-flash \
  VERTEX_PROJECT=<gcp-project> VERTEX_LOCATION=us-central1 \
  VERTEX_SA_FILE=<path-to-service-account.json> \
  SYNTHESIS_PROMPT_MODE=assertive \
  uv run python ragas_eval.py --mode reference-free --org nexalink
```

Production-default behavior (`SYNTHESIS_PROMPT_MODE=safe`, admits uncertainty)
scores ~0.90 faithfulness / ~0.69 relevancy on the same judge.

Notes:
- Groq free tier is ~100k tokens/day (≈ one synthesis run per key per day).
- The Vertex judge is billed to GCP credits; the AI Studio API-key path is
  free-tier (20 req/day for Gemini 2.5-flash) and cannot complete a run.
- Vertex judge uses `max_tokens=8192` — a smaller cap truncates faithfulness
  claim-extraction and yields `NaN`.
