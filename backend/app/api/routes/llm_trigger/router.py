import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.request_context import outbound_request_headers
from app.llm_trigger.schemas import InteractionLLMTriggerReport
from app.llm_trigger.service import LLMUnavailableError, evaluate_interaction_triggers

router = APIRouter()
logger = logging.getLogger(__name__)

_UNAVAILABLE = {503: {"description": "LLM unavailable — no heuristic fallback; retry later"}}


async def _llm_or_503(coro):
    try:
        return await coro
    except LLMUnavailableError as exc:
        logger.warning("LLM trigger request failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="The LLM reasoning service is unavailable; this analysis cannot run right now. Retry later.",
        ) from exc


class InteractionTriggerRequest(BaseModel):
    retrieved_sop_from_pinecone: str = Field(
        default="",
        description="Optional SOP context override. If empty, backend retrieves from Qdrant.",
    )
    ground_truth_policy: str = Field(
        default="",
        description="Optional policy override for NLI. Falls back to retrieved SOP when missing.",
    )
    org_filter: str | None = Field(
        default=None,
        description="Optional org metadata filter used during Qdrant retrieval.",
    )
    force_rerun: bool = Field(
        default=False,
        description="When true, ignore any saved report and recompute triggers.",
    )


@router.get(
    "/health",
    summary="Health check for LLM trigger dependencies",
)
async def llm_trigger_health():
    """
    Verify health status of LLM trigger backend services, including Qdrant and Ollama.
    """
    checks: dict[str, str] = {}

    try:
        from app.llm_trigger.retrieval import _get_shared_qdrant_client
        client = _get_shared_qdrant_client()
        collections = [c.name for c in client.get_collections().collections]
        checks["qdrant"] = "ok" if collections else "empty"
    except Exception:
        logger.warning("LLM trigger health qdrant check failed", exc_info=True)
        checks["qdrant"] = "error"

    # Embeddings health check
    if settings.RAG_MODELS_HOST == "kaggle":
        try:
            import httpx

            from app.core.config import embedding_request_headers, resolve_embedding_base_url

            response = httpx.get(
                f"{resolve_embedding_base_url()}/health",
                headers=embedding_request_headers(),
                timeout=5.0,
            )
            checks["embeddings"] = "ok" if response.status_code == 200 else f"status:{response.status_code}"
        except Exception:
            logger.warning("LLM trigger health kaggle embedding check failed", exc_info=True)
            checks["embeddings"] = "error"
    elif settings.OLLAMA_CLOUD_EMBED_ENABLED:
        try:
            import httpx

            response = httpx.get(
                settings.OLLAMA_CLOUD_BASE_URL.rstrip("/").replace("/v1", "") + "/api/tags",
                headers={"Authorization": f"Bearer {settings.OLLAMA_CLOUD_API_KEY}"},
                timeout=5.0,
            )
            checks["ollama"] = "ok" if response.status_code == 200 else f"status:{response.status_code}"
        except Exception:
            logger.warning("LLM trigger health ollama cloud check failed", exc_info=True)
            checks["ollama"] = "error"
    else:
        try:
            import httpx

            response = httpx.get(
                f"{settings.OLLAMA_BASE_URL}/api/tags",
                timeout=5.0,
                headers=outbound_request_headers(),
            )
            checks["ollama"] = "ok" if response.status_code == 200 else f"status:{response.status_code}"
        except Exception:
            logger.warning("LLM trigger health ollama check failed", exc_info=True)
            checks["ollama"] = "error"

    critical = {k: v for k, v in checks.items() if k not in {"ollama", "embeddings"}}
    overall = "ok" if all(v == "ok" for v in critical.values()) else "degraded"
    return {"status": overall, "dependencies": checks}


@router.post(
    "/interaction/{interaction_id}/run",
    response_model=InteractionLLMTriggerReport,
    summary="Run all LLM trigger checks for one interaction",
    responses={401: {"description": "Not authenticated"}, 403: {"description": "Access denied - credentials invalid or cross-organization violation"}, 404: {"description": "Interaction not found"}, 422: {"description": "Invalid interaction ID or request payload"}, **_UNAVAILABLE},
)
async def run_interaction_trigger_endpoint(
    interaction_id: UUID = Path(..., description="The unique UUID of the interaction to run LLM trigger checks on."),
    payload: InteractionTriggerRequest = None,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> InteractionLLMTriggerReport:
    """
    Execute the full suite of compliance and trigger checks for a specific interaction.
    """
    try:
        return await _llm_or_503(evaluate_interaction_triggers(
            session=session,
            interaction_id=interaction_id,
            retrieved_sop_from_pinecone=payload.retrieved_sop_from_pinecone if payload else "",
            ground_truth_policy=payload.ground_truth_policy if payload else "",
            org_filter=payload.org_filter if payload else None,
            requester_organization_id=current_user.organization_id,
            force_rerun=payload.force_rerun if payload else False,
            commit_cache=True,
        ))
    except ValueError as exc:
        message = str(exc)
        if message == "Interaction not found.":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
