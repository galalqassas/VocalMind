from __future__ import annotations

import asyncio
import logging
import threading
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.request_context import outbound_request_headers


logger = logging.getLogger(__name__)

router = APIRouter()

def _candidate_rag_roots() -> list[Path]:
    """
    Return possible parents that contain the ``rag`` package, ordered by preference.

    1) ``/app`` in the Docker container (services/rag is bind-mounted at /app/rag).
    2) Repo-relative ``services/`` from this source file (local dev / pytest).
    """
    here = Path(__file__).resolve()
    return [Path("/app"), here.parents[4] / "services"]


def _ensure_rag_on_path() -> None:
    import sys
    for root in _candidate_rag_roots():
        if (root / "rag" / "query_engine.py").exists():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.append(root_str)
            return


class RAGQueryRequest(BaseModel):
    query: str = Field(..., description="The query string or question to search within the vector database.")
    mode: str = Field("answer", description="The search mode ('answer' for general Q&A retrieval or 'compliance' for policy compliance checks).")


class RAGQueryResponse(BaseModel):
    response: str = Field(..., description="The generated/retrieved answer text.")
    chunks: list[dict] = Field(..., description="List of raw source document text chunks retrieved from the vector database.")
    timing: dict = Field(..., description="A dictionary of timing durations for query stages.")
    retrieval_provenance: list[dict] = Field(default_factory=list, description="Structured attribution evidence cards tracing the source document metadata.")


_engine_lock = threading.Lock()
_engine = None


def _build_retrieval_provenance(query: str, chunks: list[dict]) -> list[dict]:
    """
    Build retrieval provenance cards from chunk metadata.

    This route intentionally stays in the retrieval layer; it surfaces grounded
    evidence and similarity metadata only. The ``verdict`` field is retained
    for response compatibility, but it means retrieval support level, not a
    compliance or NLI judgment.
    """
    retrieval_provenance: list[dict] = []
    supported_threshold = settings.RAG_SUPPORTED_THRESHOLD
    neutral_threshold = settings.RAG_NEUTRAL_THRESHOLD
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        similarity = float(chunk.get("score", 0.0))
        header_path = " > ".join(
            str(metadata.get(key)).strip()
            for key in ("Header 1", "Header 2", "Header 3")
            if metadata.get(key)
        )
        reference = header_path or str(metadata.get("source_file") or metadata.get("doc_id") or "Retrieved chunk")
        retrieval_support_label = (
            "supported"
            if similarity >= supported_threshold
            else "neutral"
            if similarity >= neutral_threshold
            else "insufficient_evidence"
        )
        retrieval_provenance.append(
            {
                "claim": query,
                "chunkRank": chunk.get("rank"),
                "semanticSimilarity": similarity,
                "verdict": retrieval_support_label,
                "docType": metadata.get("doc_type"),
                "policyRef": metadata.get("policy_ref") or [],
                "reference": reference,
                "excerpt": chunk.get("text", "")[:220],
                "provenance": {
                    "docId": metadata.get("doc_id"),
                    "sourceFile": metadata.get("source_file"),
                    "headerPath": header_path or None,
                },
            }
        )
    return retrieval_provenance


@router.get(
    "/health",
    summary="Health check for RAG service dependencies",
    responses={500: {"description": "RAG engine initialization failed"}}
)
async def rag_health():
    """
    Check the health status of RAG service dependencies, including Qdrant and Ollama.
    """
    checks: dict[str, str] = {}
    engine_available = False
    try:
        engine = _get_engine()
        engine_available = True
        collections = [c.name for c in engine.qdrant.get_collections().collections]
        checks["qdrant"] = "ok" if collections else "empty"
    except HTTPException:
        checks["engine"] = "unavailable"
    except Exception:
        logger.warning("RAG health qdrant check failed", exc_info=True)
        checks["qdrant"] = "error"

    if engine_available:
        try:
            import httpx as _httpx
            _response = _httpx.get(
                f"{settings.OLLAMA_BASE_URL}/api/tags",
                timeout=5.0,
                headers=outbound_request_headers(),
            )
            checks["ollama"] = "ok" if _response.status_code == 200 else f"status:{_response.status_code}"
        except Exception:
            logger.warning("RAG health ollama check failed", exc_info=True)
            checks["ollama"] = "error"

    checks["groq_api_key"] = "configured" if settings.GROQ_API_KEY else "missing"
    overall = "ok" if all(v == "ok" or v == "configured" for v in checks.values()) else "degraded"
    return {"status": overall, "dependencies": checks}


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            _ensure_rag_on_path()
            from rag.query_engine import RAGQueryEngine
            _engine = RAGQueryEngine()
        except Exception as exc:
            error_id = str(uuid4())
            logger.error("Failed to initialize RAG engine [error_id=%s]", error_id, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Internal error. Reference ID: {error_id}",
            ) from exc
        return _engine


@router.post("/query", response_model=RAGQueryResponse, responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}, 500: {"description": "RAG engine query processing failed"}, 422: {"description": "Invalid query input parameters"}})
async def query_rag_endpoint(request: RAGQueryRequest, current_user: CurrentUser):
    """Retrieve grounded context from RAG collections and expose provenance."""
    engine = _get_engine()
    org_filter = str(current_user.organization_id)
    try:
        if request.mode == "compliance":
            result = await asyncio.to_thread(engine.query_compliance, text=request.query, org_filter=org_filter)
        else:
            result = await asyncio.to_thread(engine.query_answer, question=request.query, org_filter=org_filter)
        retrieval_provenance = _build_retrieval_provenance(request.query, result.get("chunks", []))
        return RAGQueryResponse(
            response=result["response"],
            chunks=result.get("chunks", []),
            timing=result.get("timing", {}),
            retrieval_provenance=retrieval_provenance,
        )
    except HTTPException:
        raise
    except Exception as exc:
        error_id = str(uuid4())
        logger.error("RAG query failed [error_id=%s]", error_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error. Reference ID: {error_id}",
        ) from exc
