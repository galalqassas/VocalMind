"""
VocalMind Final RAG — Retrieval + optional synthesis engine.

This module is the RAG retrieval layer for policy/SOP grounding.
It owns:
  1) embedding queries,
  2) vector retrieval from Qdrant collections,
  3) structured retrieval payload formatting.

It may optionally synthesize a response for compatibility endpoints, but it does
not perform compliance judging or NLI verdicting. Judging belongs to:
  - services/rag/evaluator.py (transcript-level policy compliance reports)
  - backend/app/llm_trigger/service.py (single-claim NLI policy checks)
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.llms.groq import Groq as LlamaGroq
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, ScoredPoint

try:
    from .config import (
        settings,
        build_rag_llm_client,
        embedding_http_base_url,
        embedding_http_headers,
        rag_synthesis_model,
    )
    from .prompt_safety import sanitize_prompt_text, with_injection_guard
    from .llm_circuit_breaker import get_breaker
    from .reranker import rerank_points
except ImportError:  # pragma: no cover - allows direct script/test imports
    from config import (
        settings,
        build_rag_llm_client,
        embedding_http_base_url,
        embedding_http_headers,
        rag_synthesis_model,
    )
    from prompt_safety import sanitize_prompt_text, with_injection_guard
    from llm_circuit_breaker import get_breaker
    from reranker import rerank_points


logger = logging.getLogger(__name__)


class RAGQueryEngine:
    """
    RAG retrieval engine backed by Qdrant vector search.

    Retrieval-first APIs:
      - ``retrieve_policy_context(text)``  → parent chunks (policy context)
      - ``retrieve_answer_context(question)`` → child chunks (answer context)
      - ``retrieve_context(question, collection)`` → generic retrieval

    Compatibility APIs with synthesis:
      - ``query_compliance(text)`` and ``query_answer(question)``
      - ``query(question, collection)``
    """

    def __init__(self) -> None:
        self.qdrant = QdrantClient(url=settings.qdrant.url)
        self._setup_llm()
        self.logs_dir = settings.BASE_DIR / "logs"
        try:
            self.logs_dir.mkdir(exist_ok=True)
        except OSError:
            self.logs_dir = Path("/tmp/rag_logs")
            self.logs_dir.mkdir(exist_ok=True)

    @staticmethod
    def _build_qa_prompt() -> str:
        """Return the synthesis prompt for the configured SYNTHESIS_PROMPT_MODE.

        Both variants are strictly grounded; they differ only in how they handle
        uncertainty:
          safe      — admits when the context lacks the answer (production default,
                      safer for a compliance assistant; higher RAGAS faithfulness).
          assertive — never hedges, states policy as fact (maximizes RAGAS
                      answer-relevancy by avoiding noncommittal phrasing).
        """
        header = (
            "You are a customer-service policy assistant. Answer the query using "
            "the policy/SOP context below.\n"
            "---------------------\n"
            "{context_str}\n"
            "---------------------\n"
            "Instructions:\n"
            "1. GROUNDING: Use ONLY information found in the context above. Every "
            "statement must be directly supported by the context. Never add facts, "
            "assumptions, or outside knowledge that is not present in the context.\n"
        )
        if settings.SYNTHESIS_PROMPT_MODE == "assertive":
            body = (
                "2. DIRECTNESS: Answer directly and assertively, as established "
                "policy. Open by restating the subject of the question, then state "
                "the answer plainly as fact. Do NOT hedge — never write phrases like "
                "'the context does not explicitly state', 'based on the provided "
                "information', or 'it appears that'. When the context supports an "
                "answer, state it with confidence and do not add disclaimers.\n"
                "3. COMPLETENESS: Synthesize all relevant details from the context "
                "into a clear, well-organized answer of several complete sentences. "
                "Stay on-topic and do not add unrelated policies. Never give "
                "one-line answers.\n"
            )
        else:  # "safe"
            body = (
                "2. RELEVANCE: Directly and fully answer the specific question "
                "asked. Restate the core of the question in your answer so it stands "
                "on its own. Do not introduce unrelated policies or steps the query "
                "did not ask about.\n"
                "3. COMPLETENESS: Synthesize all relevant details from the provided "
                "context into a clear, well-organized answer of several complete "
                "sentences. Never give one-word or one-line answers.\n"
                "4. HONESTY: If — and only if — the context genuinely does not "
                "contain the information needed to answer, say so plainly rather than "
                "guessing. Do not fabricate policy that is not supported by the "
                "context.\n"
            )
        return header + body + "Query: {query_str}\nAnswer: "

    def _setup_llm(self) -> None:
        """Configure LLM for response synthesis via LlamaIndex.

        Uses a local OpenAI-compatible endpoint (LM Studio) when
        SYNTHESIS_BASE_URL is set, otherwise Groq or Ollama Cloud.
        """
        from llama_index.core import PromptTemplate

        if settings.SYNTHESIS_BASE_URL:
            from llama_index.llms.openai_like import OpenAILike

            synthesis_model = settings.SYNTHESIS_MODEL or rag_synthesis_model()
            self.llm = OpenAILike(
                model=synthesis_model,
                api_base=settings.SYNTHESIS_BASE_URL,
                api_key=settings.SYNTHESIS_API_KEY,
                temperature=settings.groq.temperature,
                max_tokens=settings.groq.max_tokens,
                context_window=settings.groq.context_window,
                is_chat_model=True,
            )
            logger.info("Synthesis LLM: %s @ %s", synthesis_model, settings.SYNTHESIS_BASE_URL)
        else:
            synthesis_model = rag_synthesis_model()
            if settings.LLM_PROVIDER == "ollama_cloud":
                from llama_index.llms.openai_like import OpenAILike

                self.llm = OpenAILike(
                    model=synthesis_model,
                    api_base=settings.OLLAMA_CLOUD_BASE_URL,
                    api_key=settings.OLLAMA_CLOUD_API_KEY or "ollama",
                    is_chat_model=True,
                    temperature=settings.groq.temperature,
                    max_tokens=settings.groq.max_tokens,
                    context_window=settings.groq.context_window,
                )
            else:
                self.llm = LlamaGroq(
                    model=synthesis_model,
                    api_key=settings.groq.api_key.get_secret_value(),
                    temperature=settings.groq.temperature,
                    max_tokens=settings.groq.max_tokens,
                    context_window=settings.groq.context_window,
                )

        qa_prompt_tmpl = PromptTemplate(self._build_qa_prompt())

        self.synthesizer = get_response_synthesizer(
            llm=self.llm,
            text_qa_template=qa_prompt_tmpl,
            response_mode=settings.response_mode,
        )
        self.groq_client = build_rag_llm_client()

    # ── Embedding ─────────────────────────────────────────────────────────

    def _embed_query(self, text: str) -> list[float]:
        """Embed a query string via Ollama."""
        if settings.OLLAMA_CLOUD_EMBED_ENABLED:
            try:
                response = httpx.post(
                    f"{settings.OLLAMA_CLOUD_BASE_URL.rstrip('/')}/embeddings",
                    json={"model": settings.embedding.model, "input": text},
                    headers=embedding_http_headers(),
                    timeout=settings.embedding.request_timeout,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("data"):
                    embedding = data["data"][0].get("embedding")
                    if embedding:
                        return embedding
                vector = data.get("embedding")
                if vector:
                    return vector
            except Exception as exc:
                raise ConnectionError(
                    f"Cannot reach Ollama embeddings API at {settings.OLLAMA_CLOUD_BASE_URL} "
                    f"(last attempted endpoint: /embeddings): {exc}"
                ) from exc

        breaker = get_breaker("embedding")
        retry_delays = (0.4, 1.0, 2.0)
        payloads = (
            ("/api/embed", {"model": settings.embedding.model, "input": text}),
            ("/api/embeddings", {"model": settings.embedding.model, "prompt": text}),
        )
        last_error: Exception | None = None
        last_path: str | None = None
        for delay in (0.0, *retry_delays):
            if delay:
                time.sleep(delay)

            for path, payload in payloads:
                try:
                    response = breaker.call_sync(
                        lambda: httpx.post(
                            f"{embedding_http_base_url()}{path}",
                            json=payload,
                            headers=embedding_http_headers(),
                            timeout=settings.embedding.request_timeout,
                        )
                    )
                    response.raise_for_status()
                    data = response.json()
                    vector = data.get("embedding")
                    if vector:
                        return vector
                except Exception as exc:
                    last_error = exc
                    last_path = path
                    logger.debug("Embedding endpoint %s failed: %s", path, exc)

        raise ConnectionError(
            f"Cannot reach Ollama embeddings API at {settings.embedding.base_url} "
            f"(last attempted endpoint: {last_path}): {last_error}"
        )

    # ── HyDE query expansion ──────────────────────────────────────────────

    def _hyde_expand(self, query_text: str) -> str:
        """
        Generate a hypothetical answer passage and prepend it to the query.

        HyDE closes the question↔statement embedding gap: a query embeds in
        question-space, but the matching policy chunk is declarative. A drafted
        hypothetical answer embeds far closer to the real chunk. The original
        query is kept alongside so retrieval is never worse than baseline.
        Falls back to the raw query on any error.
        """
        prompt = (
            "Write a short, factual passage (2-3 sentences) that would plausibly "
            "appear in a customer-service policy or SOP document and that directly "
            "answers the following question. Do not hedge; state it as policy text.\n"
            f"Question: {query_text}\n"
            "Passage:"
        )
        try:
            from llama_index.core.llms import ChatMessage

            resp = self.llm.chat(
                [ChatMessage(role="user", content=prompt)],
                max_tokens=settings.HYDE_MAX_TOKENS,
            )
            hypothetical = str(resp).strip()
            if hypothetical:
                return f"{query_text}\n{hypothetical}"
        except Exception as exc:
            logger.warning("HyDE expansion failed (%s); using raw query.", exc)
        return query_text

    # ── Retrieval ─────────────────────────────────────────────────────────

    def _retrieve(
        self,
        query_text: str,
        collection: str,
        top_k: int | None = None,
        org_filter: str | None = None,
        doc_type: str | None = None,
    ) -> tuple[list[ScoredPoint], float]:
        """
        Embed the query and search Qdrant.

        Returns:
            (scored_points, retrieval_seconds)
        """
        top_k = top_k or settings.similarity_top_k
        # When reranking, pull a wider candidate pool from Qdrant and let the
        # cross-encoder pick the final top_k. Otherwise fetch exactly top_k.
        fetch_k = max(top_k, settings.RERANK_CANDIDATE_K) if settings.RERANK_ENABLED else top_k
        scoped_org = str(org_filter).strip() if org_filter is not None else ""
        if not scoped_org:
            # Deny-by-default: never issue unscoped multi-tenant vector queries.
            scoped_org = "__missing_org_scope__"

        t0 = time.perf_counter()
        # HyDE: embed a hypothetical-answer-expanded query, but keep the original
        # question for reranking so relevance is judged against the real intent.
        embed_text = self._hyde_expand(query_text) if settings.HYDE_ENABLED else query_text
        query_vector = self._embed_query(embed_text)

        def _build_filter(include_doc_type: bool) -> Filter | None:
            conditions = [FieldCondition(key="org", match=MatchValue(value=scoped_org))]
            if include_doc_type and doc_type:
                conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
            return Filter(must=conditions) if conditions else None

        query_filter = _build_filter(include_doc_type=bool(doc_type))
        results = self.qdrant.query_points(
            collection_name=collection,
            query=query_vector,
            limit=fetch_k,
            query_filter=query_filter,
        ).points
        if doc_type and not results:
            logger.warning(
                "No Qdrant chunks matched doc_type=%s in %s; retrying without doc_type filter for legacy data.",
                doc_type,
                collection,
            )
            results = self.qdrant.query_points(
                collection_name=collection,
                query=query_vector,
                limit=fetch_k,
                query_filter=_build_filter(include_doc_type=False),
            ).points

        # Cross-encoder rerank of the candidate pool down to top_k.
        results = rerank_points(query_text, results, top_k)

        retrieval_time = time.perf_counter() - t0
        return results, retrieval_time

    @staticmethod
    def _scored_points_to_nodes(points: list[ScoredPoint]) -> list[NodeWithScore]:
        """Convert Qdrant ScoredPoint results to LlamaIndex NodeWithScore."""
        nodes: list[NodeWithScore] = []
        for pt in points:
            text = sanitize_prompt_text(pt.payload.get("text", ""), max_length=2500)
            metadata = {k: v for k, v in pt.payload.items() if k != "text"}
            node = TextNode(text=text, metadata=metadata)
            nodes.append(NodeWithScore(node=node, score=pt.score))
        return nodes

    # ── Synthesis ─────────────────────────────────────────────────────────

    def _synthesize(
        self,
        question: str,
        nodes: list[NodeWithScore],
    ) -> tuple[str, float]:
        """Run LlamaIndex response synthesis and return (response_text, seconds)."""
        safe_question = with_injection_guard(question)
        t0 = time.perf_counter()
        response = self.synthesizer.synthesize(safe_question, nodes=nodes)
        synthesis_time = time.perf_counter() - t0
        return str(response), synthesis_time

    # ── Logging ───────────────────────────────────────────────────────────

    def _log_query(
        self,
        question: str,
        collection: str,
        chunks: list[dict],
        response_text: str,
        timing: dict,
    ) -> None:
        if not settings.RAG_QUERY_LOG_ENABLED:
            logger.debug(
                "RAG query log skipped [collection=%s question_len=%d chunk_count=%d response_len=%d]",
                collection,
                len(question or ""),
                len(chunks),
                len(response_text or ""),
            )
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.logs_dir / f"query_{timestamp}.json"
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "collection": collection,
            "model": rag_synthesis_model(),
            "similarity_top_k": settings.similarity_top_k,
            "timing_seconds": timing,
            "retrieved_chunks": chunks,
            "response": response_text,
        }
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to persist RAG query audit log", exc_info=True)

    # ── Public API ────────────────────────────────────────────────────────

    @staticmethod
    def _format_retrieved_chunks(scored_points: list[ScoredPoint]) -> list[dict]:
        chunks: list[dict] = []
        for i, pt in enumerate(scored_points, 1):
            chunks.append(
                {
                    "rank": i,
                    "score": float(pt.score),
                    "metadata": {k: v for k, v in pt.payload.items() if k != "text"},
                    "text": pt.payload.get("text", ""),
                    "text_length": len(pt.payload.get("text", "")),
                }
            )
        return chunks

    def retrieve_context(
        self,
        question: str,
        collection: str | None = None,
        top_k: int | None = None,
        org_filter: str | None = None,
        doc_type: str | None = None,
        verbose: bool = False,
    ) -> dict:
        """
        Retrieve grounded context chunks only (no judgment, no verdicting).

        Returns a retrieval payload shaped like the query payload for backward
        compatibility: ``{"response": "", "chunks": [...], "timing": {...}}``.
        """
        collection = collection or settings.qdrant.collection_children
        scored_points, retrieval_time = self._retrieve(question, collection, top_k, org_filter, doc_type)
        chunks = self._format_retrieved_chunks(scored_points)

        if verbose and chunks:
            print(f"\n{'='*60}")
            print(f"RETRIEVED CHUNKS ({retrieval_time:.2f}s) from [{collection}]")
            print(f"{'='*60}")
            for c in chunks:
                print(f"\n  [{c['rank']}] Score: {c['score']:.4f}")
                meta_str = " | ".join(
                    f"{k}: {v}" for k, v in c["metadata"].items() if k not in ("text", "ingested_at")
                )
                print(f"      Meta: {meta_str}")
                print(f"      Preview: {c['text'][:150]}...")

        timing = {
            "retrieval": round(retrieval_time, 4),
            "synthesis": 0.0,
            "total": round(retrieval_time, 4),
        }
        self._log_query(question, collection, chunks, "", timing)
        return {"response": "", "chunks": chunks, "timing": timing}

    def retrieve_policy_context(
        self,
        text: str,
        org_filter: str | None = None,
        top_k: int | None = None,
        verbose: bool = False,
    ) -> dict:
        """Retrieve policy-grounding context from the parents collection."""
        return self.retrieve_context(
            question=text,
            collection=settings.qdrant.collection_parents,
            top_k=top_k,
            org_filter=org_filter,
            doc_type="policy",
            verbose=verbose,
        )

    def retrieve_answer_context(
        self,
        question: str,
        org_filter: str | None = None,
        top_k: int | None = None,
        doc_type: str | None = None,
        verbose: bool = False,
    ) -> dict:
        """Retrieve answer-grounding context from the children collection."""
        return self.retrieve_context(
            question=question,
            collection=settings.qdrant.collection_children,
            top_k=top_k,
            org_filter=org_filter,
            doc_type=doc_type,
            verbose=verbose,
        )

    def query(
        self,
        question: str,
        collection: str | None = None,
        top_k: int | None = None,
        org_filter: str | None = None,
        doc_type: str | None = None,
        verbose: bool = False,
    ) -> dict:
        """
        Execute a RAG query against a Qdrant collection.

        Args:
            question:    The query text.
            collection:  Qdrant collection name. Defaults to children.
            top_k:       Number of results. Defaults to config.similarity_top_k.
            org_filter:  Optional org name to filter results.
            verbose:     Print retrieved chunks and timing.

        Returns:
            dict with keys: response, chunks, timing
        """
        collection = collection or settings.qdrant.collection_children

        # 1. Retrieve
        scored_points, retrieval_time = self._retrieve(question, collection, top_k, org_filter, doc_type)
        nodes = self._scored_points_to_nodes(scored_points)

        # 2. Format chunks for display/logging
        chunks = self._format_retrieved_chunks(scored_points)

        if verbose and chunks:
            print(f"\n{'='*60}")
            print(f"RETRIEVED CHUNKS ({retrieval_time:.2f}s) from [{collection}]")
            print(f"{'='*60}")
            for c in chunks:
                print(f"\n  [{c['rank']}] Score: {c['score']:.4f}")
                meta_str = " | ".join(
                    f"{k}: {v}" for k, v in c["metadata"].items()
                    if k not in ("text", "ingested_at")
                )
                print(f"      Meta: {meta_str}")
                print(f"      Preview: {c['text'][:150]}...")

        # 3. Synthesise
        if not nodes:
            response_text = "No relevant documents found."
            synthesis_time = 0.0
        else:
            response_text, synthesis_time = self._synthesize(question, nodes)

        total_time = retrieval_time + synthesis_time

        if verbose:
            print(
                f"\n  Retrieval {retrieval_time:.2f}s | "
                f"Synthesis {synthesis_time:.2f}s | "
                f"Total {total_time:.2f}s"
            )

        timing = {
            "retrieval": round(retrieval_time, 4),
            "synthesis": round(synthesis_time, 4),
            "total": round(total_time, 4),
        }

        # 4. Log
        self._log_query(question, collection, chunks, response_text, timing)

        return {
            "response": response_text,
            "chunks": chunks,
            "timing": timing,
        }

    def query_compliance(
        self, text: str, org_filter: str | None = None, verbose: bool = False
    ) -> dict:
        """
        Compatibility method: retrieve parents context and synthesize a response.

        Policy judging belongs in ``PolicyComplianceEvaluator``.
        """
        return self.query(
            question=text,
            collection=settings.qdrant.collection_parents,
            org_filter=org_filter,
            doc_type="policy",
            verbose=verbose,
        )

    def query_answer(
        self, question: str, org_filter: str | None = None, verbose: bool = False
    ) -> dict:
        """Compatibility method: retrieve children context and synthesize an answer."""
        return self.query(
            question=question,
            collection=settings.qdrant.collection_children,
            org_filter=org_filter,
            verbose=verbose,
        )
