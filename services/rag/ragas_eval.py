"""
RAGAS evaluation for VocalMind RAG pipeline.

Provides three evaluation modes:
  1. reference-free  — Faithfulness + Answer Relevancy + Context Precision
                       (no ground truth needed)
  2. generate        — Synthetic testset from policy/SOP documents
  3. full            — All 5 RAGAS metrics against a testset with ground truth

Usage:
    python ragas_eval.py --mode reference-free [--org nexalink]
    python ragas_eval.py --mode generate [--size 20] [--org nexalink]
    python ragas_eval.py --mode full [--testset ragas_testset.json] [--org nexalink]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# --- MONKEY PATCH FOR RAGAS ---
# Ragas has a hard dependency on an old langchain_community.chat_models.vertexai import
# that crashes in newer versions of langchain_community. We mock it here before importing ragas.
import langchain_community
if not hasattr(langchain_community, "chat_models"):
    langchain_community.chat_models = MagicMock()
sys.modules["langchain_community.chat_models"] = langchain_community.chat_models
sys.modules["langchain_community.chat_models.vertexai"] = MagicMock()
sys.modules["langchain_community.chat_models.vertexai"].ChatVertexAI = MagicMock
# ------------------------------

import httpx  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

try:
    from .config import settings, embedding_http_base_url, embedding_http_headers
    from .query_engine import RAGQueryEngine
except ImportError:  # pragma: no cover - allows direct script/test imports
    from config import settings, embedding_http_base_url, embedding_http_headers
    from query_engine import RAGQueryEngine

logger = logging.getLogger(__name__)


# ── Sample queries for reference-free evaluation ─────────────────────────────

# Policy compliance queries → evaluated against parents collection
_POLICY_COMPLIANCE_QUERIES = [
    "What is the refund policy for customers who have been with the company for less than 6 months?",
    "What is the escalation procedure when a customer reports unauthorized charges?",
    "What are the data privacy requirements when handling customer personal information?",
    "What is the maximum refund amount an agent can authorize without manager approval?",
    "What are the required greeting and closing scripts for customer calls?",
    "How should an agent handle a request to change the account billing address?",
    "What is the policy regarding sharing account information with a spouse or family member?",
    "Under what circumstances can a late payment fee be waived?",
    "What is the standard SLA for resolving technical support tickets?",
    "What are the rules for placing a customer on hold during a call?",
    "How must agents document the outcome of a customer interaction in the CRM?",
    "What is the policy for handling calls from minors under 18 years old?",
    "When is a customer eligible for a hardware replacement?",
    "What is the protocol for transferring a call to another department?",
    "What are the consequences of violating the customer data privacy policy?",
]

# Manager assistant Q&A queries → evaluated against children collection
_QA_QUERIES = [
    "How should an agent handle a customer who is threatening to cancel their subscription?",
    "What are the required steps for verifying a customer's identity before making account changes?",
    "How should agents handle requests for compensation due to service outages?",
    "What steps must be followed for a billing dispute resolution?",
    "How should an agent respond to a customer requesting access to their account after a lockout?",
    "What is the correct way to handle an angry or abusive customer on a call?",
    "How should an agent guide a customer through troubleshooting a connectivity issue?",
    "What steps should be taken if a customer requests a supervisor?",
    "How can an agent process an account upgrade request over the phone?",
    "What is the procedure for handling a customer who received a defective product?",
    "How should an agent respond if they don't know the answer to a customer's question?",
    "What are the best practices for de-escalating a tense customer interaction?",
    "How should an agent handle a request to pause or temporarily suspend an account?",
    "What steps are required to process a customer's request for data deletion under privacy laws?",
    "How should an agent handle a situation where a customer's payment method is repeatedly declined?",
]


# ── Report Model ─────────────────────────────────────────────────────────────


class RagasReport(BaseModel):
    """RAGAS evaluation report."""

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: str
    org_filter: str = ""
    total_samples: int = 0
    metrics: dict[str, float] = Field(default_factory=dict)
    per_sample: list[dict[str, Any]] = Field(default_factory=list)
    duration_seconds: float = 0.0


# ── Ollama Embeddings Wrapper ────────────────────────────────────────────────


class _OllamaEmbeddings:
    """
    Minimal LangChain-compatible embeddings wrapper using VocalMind's
    Ollama embedding infrastructure (snowflake-arctic-embed2).
    """

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        return [self._embed(t) for t in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    @staticmethod
    def _embed(text: str) -> list[float]:
        """Call Ollama embed endpoint."""
        base_url = embedding_http_base_url()
        headers = embedding_http_headers()
        payloads = (
            ("/api/embed", {"model": settings.embedding.model, "input": text}),
            ("/api/embeddings", {"model": settings.embedding.model, "prompt": text}),
        )
        last_error: Exception | None = None
        for path, payload in payloads:
            try:
                response = httpx.post(
                    f"{base_url}{path}",
                    json=payload,
                    headers=headers,
                    timeout=settings.embedding.request_timeout,
                )
                response.raise_for_status()
                data = response.json()
                vector = data.get("embedding")
                if vector:
                    return vector
            except Exception as exc:
                last_error = exc
                logger.debug("Embedding endpoint %s failed: %s", path, exc)
        raise ConnectionError(
            f"Cannot reach Ollama embeddings at {base_url}: {last_error}"
        )


# ── Core Evaluation Functions ────────────────────────────────────────────────


def _build_ragas_llm():
    """Build a RAGAS-compatible LLM wrapper.

    Provider is controlled by RAGAS_JUDGE_PROVIDER:
      "groq"  — Groq llama-3.3-70b-versatile (strongly recommended).
                Reliably generates 3 question-variations for AnswerRelevancy
                and performs accurate claim decomposition for Faithfulness.
                Local 8B models frequently return only 1/3 generations,
                capping both metrics below 0.85.
      "local" — Local LM Studio endpoint (RAGAS_JUDGE_MODEL/BASE_URL/API_KEY).
                Use only when offline or when Groq tokens are exhausted.
    """
    from ragas.llms import LangchainLLMWrapper

    if settings.RAGAS_JUDGE_PROVIDER == "vertex":
        from google.oauth2 import service_account
        import google.auth.transport.requests as gtr
        from langchain_openai import ChatOpenAI

        creds = service_account.Credentials.from_service_account_file(
            settings.VERTEX_SA_FILE,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(gtr.Request())
        loc = settings.VERTEX_LOCATION
        base_url = (
            f"https://{loc}-aiplatform.googleapis.com/v1beta1/projects/"
            f"{settings.VERTEX_PROJECT}/locations/{loc}/endpoints/openapi"
        )
        llm = ChatOpenAI(
            model=settings.RAGAS_JUDGE_MODEL,
            base_url=base_url,
            api_key=creds.token,  # OAuth token, valid ~1h — ample for one run
            temperature=0.0,
            # Faithfulness decomposes verbose answers into many claims; a small
            # cap truncates that step and yields NaN. Gemini handles large output.
            max_tokens=8192,
            request_timeout=180.0,
        )
        print(f"  Judge LLM: Vertex AI {settings.RAGAS_JUDGE_MODEL} @ {loc}")
    elif settings.RAGAS_JUDGE_PROVIDER == "groq":
        from langchain_groq import ChatGroq

        judge_model = "llama-3.3-70b-versatile"
        llm = ChatGroq(
            model=judge_model,
            api_key=settings.groq.api_key.get_secret_value(),
            temperature=0.0,
            max_tokens=2048,
        )
        print(f"  Judge LLM: Groq {judge_model}")
    else:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.RAGAS_JUDGE_MODEL,
            base_url=settings.RAGAS_JUDGE_BASE_URL,
            api_key=settings.RAGAS_JUDGE_API_KEY,
            temperature=0.0,
            max_tokens=2048,
            request_timeout=120.0,
        )
        print(f"  Judge LLM: {settings.RAGAS_JUDGE_MODEL} @ {settings.RAGAS_JUDGE_BASE_URL}")
    return LangchainLLMWrapper(llm)


def _build_ragas_embeddings():
    """Build a RAGAS-compatible embeddings wrapper using Ollama."""
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(_OllamaEmbeddings())


def _get_run_config():
    """Build a RunConfig that respects Groq rate limits.

    max_workers=2 prevents hitting Groq's 30 req/min limit on the free tier.
    When RAGAS_JUDGE_PROVIDER=groq the judge also counts against that limit,
    so keep workers low to avoid 429s mid-evaluation.
    """
    from ragas.run_config import RunConfig

    return RunConfig(max_workers=2, timeout=180)


def run_reference_free_eval(
    org_filter: str = "nexalink",
    verbose: bool = False,
) -> RagasReport:
    """
    Run reference-free RAGAS evaluation on both RAG pipelines.

    Evaluates policy compliance retrieval (parents collection) and
    manager assistant Q&A (children collection) using Faithfulness,
    Answer Relevancy, and Context Precision — no ground truth needed.
    """
    from ragas import evaluate, EvaluationDataset, SingleTurnSample
    from ragas.metrics import (
        Faithfulness,
        AnswerRelevancy,
        LLMContextPrecisionWithoutReference,
    )

    engine = RAGQueryEngine()
    evaluator_llm = _build_ragas_llm()
    evaluator_embeddings = _build_ragas_embeddings()

    # Evaluate both pipelines for the thesis
    query_sets = [
        ("policy_compliance", _POLICY_COMPLIANCE_QUERIES, "query_compliance"),
        ("qa_assistant", _QA_QUERIES, "query_answer"),
    ]

    samples: list[SingleTurnSample] = []
    sample_pipelines: list[str] = []
    total_queries = len(_POLICY_COMPLIANCE_QUERIES) + len(_QA_QUERIES)

    print(f"\n{'='*60}")
    print(f"RAGAS Reference-Free Evaluation ({total_queries} queries)")
    print(f"  Policy compliance: {len(_POLICY_COMPLIANCE_QUERIES)} queries (parents)")
    print(f"  Q&A assistant:     {len(_QA_QUERIES)} queries (children)")
    print(f"{'='*60}")

    idx = 0
    for pipeline_name, queries, query_method in query_sets:
        print(f"\n  -- {pipeline_name} --")
        for query in queries:
            idx += 1
            print(f"\n  [{idx}/{total_queries}] {query[:70]}...")
            result = getattr(engine, query_method)(
                query if query_method == "query_answer" else query,
                org_filter=org_filter,
                verbose=verbose,
            )
            contexts = [c["text"] for c in result["chunks"] if c.get("text")]
            response = result["response"]

            if not contexts:
                print("    ⚠ No contexts retrieved, skipping")
                continue

            samples.append(
                SingleTurnSample(
                    user_input=query,
                    retrieved_contexts=contexts,
                    response=response,
                )
            )
            sample_pipelines.append(pipeline_name)
            print(f"    ✓ {len(contexts)} contexts, {len(response)} chars response")

    if not samples:
        print("\n  ✗ No valid samples collected. Is Qdrant running with ingested docs?")
        return RagasReport(mode="reference-free", org_filter=org_filter)

    eval_dataset = EvaluationDataset(samples=samples)

    metrics = [
        Faithfulness(llm=evaluator_llm),
        # strictness=3 (RAGAS default): averages relevancy over 3 generated
        # reverse-questions, reducing single-sample noise. Requires a judge that
        # honors n>1 — Vertex Gemini does; local LM Studio does NOT (it silently
        # returns 1). Use strictness=1 only when judging on a local endpoint.
        AnswerRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings, strictness=3),
        # Reference-free precision: the judge decides whether each retrieved
        # context was useful for the response (no ground truth required).
        LLMContextPrecisionWithoutReference(llm=evaluator_llm),
    ]

    print(f"\n  Running RAGAS evaluation on {len(samples)} samples...")
    t0 = time.perf_counter()
    results = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        run_config=_get_run_config(),
    )
    duration = time.perf_counter() - t0

    # Build report
    df = results.to_pandas()

    # RAGAS names the precision column after the metric instance, e.g.
    # "llm_context_precision_without_reference" — normalize it to
    # "context_precision" for stable reporting.
    _precision_candidates = (
        "llm_context_precision_without_reference",
        "context_precision",
        "context_utilization",
    )
    precision_col = next((c for c in _precision_candidates if c in df), None)

    def _col_mean(col: str | None) -> float:
        if col and col in df:
            val = df[col].mean()
            return float(val) if val == val else 0.0  # NaN guard
        return 0.0

    metric_means = {
        "faithfulness": _col_mean("faithfulness"),
        "answer_relevancy": _col_mean("answer_relevancy"),
        "context_precision": _col_mean(precision_col),
    }

    def _row_val(row, col: str | None) -> float:
        if not col or col not in row:
            return 0.0
        val = row.get(col, 0)
        return float(val) if val == val else 0.0

    per_sample = []
    for i, (_, row) in enumerate(df.iterrows()):
        per_sample.append({
            "user_input": row.get("user_input", ""),
            "pipeline": sample_pipelines[i] if i < len(sample_pipelines) else "unknown",
            "faithfulness": _row_val(row, "faithfulness"),
            "answer_relevancy": _row_val(row, "answer_relevancy"),
            "context_precision": _row_val(row, precision_col),
        })

    report = RagasReport(
        mode="reference-free",
        org_filter=org_filter,
        total_samples=len(samples),
        metrics=metric_means,
        per_sample=per_sample,
        duration_seconds=round(duration, 2),
    )

    _print_metrics(report)
    _save_report(report, "reference_free")
    return report


def generate_synthetic_testset(
    org_filter: str = "nexalink",
    testset_size: int = 20,
    output_path: Path | None = None,
    verbose: bool = False,
) -> Path:
    """
    Generate a synthetic RAGAS testset from policy/SOP documents.

    Uses RAGAS TestsetGenerator to create Q&A pairs with ground truth
    from the documents in storage/docs/{org}/.
    """
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from ragas.testset import TestsetGenerator

    evaluator_llm = _build_ragas_llm()
    evaluator_embeddings = _build_ragas_embeddings()

    # Discover parsed markdown docs (Docling outputs in parsed-docs/)
    docs_base = settings.DOCS_DIR
    org_dirs = [d for d in docs_base.iterdir() if d.is_dir() and d.name == org_filter]
    if not org_dirs:
        raise FileNotFoundError(
            f"No document directory found for org '{org_filter}' in {docs_base}. "
            f"Available: {[d.name for d in docs_base.iterdir() if d.is_dir()]}"
        )

    # Load parsed markdown files from the parsed-docs subdirectory
    parsed_dir = org_dirs[0] / "parsed-docs"
    if not parsed_dir.exists():
        raise FileNotFoundError(
            f"No parsed-docs directory at {parsed_dir}. "
            f"Run document ingestion first: python main.py --ingest"
        )

    print(f"\n{'='*60}")
    print("RAGAS Synthetic Testset Generation")
    print(f"  Org: {org_filter}")
    print(f"  Docs: {parsed_dir}")
    print(f"  Target size: {testset_size}")
    print(f"{'='*60}")

    loader = DirectoryLoader(
        str(parsed_dir),
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
    )
    documents = loader.load()

    if not documents:
        raise FileNotFoundError(
            f"No markdown files found in {parsed_dir}. "
            f"Run document ingestion first: python main.py --ingest"
        )

    print(f"\n  Loaded {len(documents)} documents")

    # Ensure documents have filename metadata (required by TestsetGenerator)
    for doc in documents:
        if "filename" not in doc.metadata and "source" in doc.metadata:
            doc.metadata["filename"] = Path(doc.metadata["source"]).name

    generator = TestsetGenerator(
        llm=evaluator_llm,
        embedding_model=evaluator_embeddings,
    )

    print(f"  Generating {testset_size} synthetic Q&A pairs...")
    t0 = time.perf_counter()
    testset = generator.generate_with_langchain_docs(
        documents=documents,
        testset_size=testset_size,
    )
    duration = time.perf_counter() - t0
    print(f"  Generated in {duration:.1f}s")

    # Export to JSON
    output_path = output_path or (settings.BASE_DIR / "ragas_testset.json")
    df = testset.to_pandas()
    records = []
    for _, row in df.iterrows():
        record = {
            "user_input": row.get("user_input", ""),
            "reference": row.get("reference", ""),
        }
        # Include any extra columns from the generated testset
        for col in df.columns:
            if col not in ("user_input", "reference") and not col.startswith("_"):
                val = row.get(col)
                if val is not None:
                    record[col] = val if not hasattr(val, "tolist") else val.tolist()
        records.append(record)

    testset_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "org": org_filter,
        "generator_llm": settings.groq.model,
        "total_samples": len(records),
        "samples": records,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(testset_data, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n  ✓ Testset saved → {output_path}")
    print(f"  Total samples: {len(records)}")
    return output_path


def run_full_eval(
    org_filter: str = "nexalink",
    testset_path: Path | None = None,
    verbose: bool = False,
) -> RagasReport:
    """
    Run full RAGAS evaluation with all metrics (requires ground truth).

    Uses a testset from generate_synthetic_testset() or a hand-curated file.
    """
    from ragas import evaluate, EvaluationDataset, SingleTurnSample
    from ragas.metrics import (
        Faithfulness,
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        AnswerCorrectness,
    )

    testset_path = testset_path or (settings.BASE_DIR / "ragas_testset.json")
    if not testset_path.exists():
        raise FileNotFoundError(
            f"Testset not found at {testset_path}. "
            f"Generate one first: python ragas_eval.py --mode generate"
        )

    with open(testset_path, encoding="utf-8") as f:
        testset_data = json.load(f)

    raw_samples = testset_data.get("samples", [])
    if not raw_samples:
        raise ValueError("Testset contains no samples.")

    engine = RAGQueryEngine()
    evaluator_llm = _build_ragas_llm()
    evaluator_embeddings = _build_ragas_embeddings()

    print(f"\n{'='*60}")
    print(f"RAGAS Full Evaluation ({len(raw_samples)} samples)")
    print(f"{'='*60}")

    # For each testset sample, run the RAG pipeline to get contexts + response
    samples: list[SingleTurnSample] = []
    for i, raw in enumerate(raw_samples, 1):
        question = raw["user_input"]
        reference = raw.get("reference", "")
        print(f"\n  [{i}/{len(raw_samples)}] {question[:70]}...")

        result = engine.query(
            question=question,
            org_filter=org_filter,
            verbose=verbose,
        )
        contexts = [c["text"] for c in result["chunks"] if c.get("text")]
        response = result["response"]

        if not contexts:
            print("    ⚠ No contexts retrieved, skipping")
            continue

        sample_kwargs: dict[str, Any] = {
            "user_input": question,
            "retrieved_contexts": contexts,
            "response": response,
        }
        if reference:
            sample_kwargs["reference"] = reference

        samples.append(SingleTurnSample(**sample_kwargs))
        print(f"    ✓ {len(contexts)} contexts, {len(response)} chars response")

    if not samples:
        print("\n  ✗ No valid samples collected.")
        return RagasReport(mode="full", org_filter=org_filter)

    eval_dataset = EvaluationDataset(samples=samples)

    # Use all metrics — Context Recall and Answer Correctness need ground truth
    has_references = any(s.reference for s in samples)
    metrics = [
        Faithfulness(llm=evaluator_llm),
        AnswerRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings),
        ContextPrecision(llm=evaluator_llm),
    ]
    if has_references:
        metrics.extend([
            ContextRecall(llm=evaluator_llm),
            AnswerCorrectness(llm=evaluator_llm),
        ])
    else:
        print("\n  ⚠ No reference answers found — skipping Context Recall and Answer Correctness")

    print(f"\n  Running RAGAS evaluation on {len(samples)} samples with {len(metrics)} metrics...")
    t0 = time.perf_counter()
    results = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        run_config=_get_run_config(),
    )
    duration = time.perf_counter() - t0

    # Build report
    df = results.to_pandas()
    metric_cols = [c for c in df.columns if c not in ("user_input", "retrieved_contexts", "response", "reference")]
    metric_means = {}
    for col in metric_cols:
        if col in df:
            val = df[col].mean()
            metric_means[col] = round(float(val), 4) if not (val != val) else 0.0  # handle NaN

    per_sample = []
    for _, row in df.iterrows():
        sample_data: dict[str, Any] = {"user_input": row.get("user_input", "")}
        for col in metric_cols:
            if col in row:
                val = row[col]
                sample_data[col] = round(float(val), 4) if not (val != val) else 0.0
        per_sample.append(sample_data)

    report = RagasReport(
        mode="full",
        org_filter=org_filter,
        total_samples=len(samples),
        metrics=metric_means,
        per_sample=per_sample,
        duration_seconds=round(duration, 2),
    )

    _print_metrics(report)
    _check_thresholds(report)
    _save_report(report, "full")
    return report


# ── Helpers ──────────────────────────────────────────────────────────────────


def _print_metrics(report: RagasReport) -> None:
    """Pretty-print RAGAS metrics."""
    print(f"\n{'─'*40}")
    print(f"  RAGAS Results ({report.mode})")
    print(f"  Samples: {report.total_samples}")
    print(f"  Duration: {report.duration_seconds:.1f}s")
    print(f"{'─'*40}")
    for name, value in report.metrics.items():
        bar = "#" * int(value * 20) + "." * (20 - int(value * 20))
        print(f"  {name:<25} {value:.4f}  [{bar}]")
    print(f"{'─'*40}")


def _check_thresholds(report: RagasReport) -> None:
    """Check RAGAS metrics against thresholds."""
    thresholds_path = Path(__file__).resolve().parent.parent.parent / "infra" / "benchmarks" / "schema" / "thresholds.json"
    if not thresholds_path.exists():
        logger.debug("Thresholds file not found at %s", thresholds_path)
        return

    with open(thresholds_path, encoding="utf-8") as f:
        all_thresholds = json.load(f)

    ragas_thresholds = all_thresholds.get("ragas", {})
    if not ragas_thresholds:
        return

    passed = True
    for metric_name, threshold in ragas_thresholds.items():
        # Threshold keys like "min_faithfulness" → metric name "faithfulness"
        metric_key = metric_name.removeprefix("min_")
        actual = report.metrics.get(metric_key, 0.0)
        status = "PASS" if actual >= threshold else "FAIL"
        if status == "FAIL":
            passed = False
        print(f"  Threshold: {metric_key} >= {threshold:.2f} → {actual:.4f} [{status}]")

    if passed:
        print("\n  ✓ All RAGAS thresholds passed")
    else:
        print("\n  ✗ Some RAGAS thresholds failed")


def _save_report(report: RagasReport, prefix: str) -> Path:
    """Save RAGAS report to JSON."""
    reports_dir = settings.BASE_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"ragas_{prefix}_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    print(f"\n  Report saved → {path}")
    return path


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAGAS evaluation for VocalMind RAG pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ragas_eval.py --mode reference-free
  python ragas_eval.py --mode generate --size 20
  python ragas_eval.py --mode full --testset ragas_testset.json
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["reference-free", "generate", "full"],
        required=True,
        help="Evaluation mode",
    )
    parser.add_argument("--org", default="nexalink", help="Organization filter (default: nexalink)")
    parser.add_argument("--size", type=int, default=20, help="Testset size for generation (default: 20)")
    parser.add_argument("--testset", type=Path, default=None, help="Path to testset JSON for full eval")
    parser.add_argument("--verbose", action="store_true", help="Print verbose output")
    args = parser.parse_args()

    if args.mode == "reference-free":
        run_reference_free_eval(org_filter=args.org, verbose=args.verbose)
    elif args.mode == "generate":
        generate_synthetic_testset(
            org_filter=args.org,
            testset_size=args.size,
            verbose=args.verbose,
        )
    elif args.mode == "full":
        run_full_eval(
            org_filter=args.org,
            testset_path=args.testset,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
