from uuid import UUID

import logging

from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.request_context import outbound_request_headers
from app.llm_trigger.schemas import (
    EmotionShiftAnalysis,
    InteractionLLMTriggerReport,
    NLIEvaluation,
    ProcessAdherenceReport,
)
from app.llm_trigger.service import (
    analyze_emotion_shift,
    evaluate_interaction_triggers,
    evaluate_process_adherence,
    run_nli_policy_check,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class EmotionShiftRequest(BaseModel):
    agent_context: str = Field(default="", description="Agent-side context for the interaction.")
    customer_text: str = Field(description="Customer utterance or text span to analyze.")
    acoustic_emotion: str = Field(description="Detected acoustic emotion label.")


class ProcessAdherenceRequest(BaseModel):
    transcript_text: str = Field(description="Full transcript text for process evaluation.")
    retrieved_sop_from_pinecone: str = Field(
        default="",
        description="Optional pre-retrieved SOP text. If empty, system retrieves from Qdrant.",
    )
    org_filter: str | None = Field(
        default=None,
        description="Optional organization filter used in Qdrant metadata filtering.",
    )


class NLIPolicyCheckRequest(BaseModel):
    agent_statement: str = Field(description="Single claim/statement made by the agent.")
    ground_truth_policy: str = Field(description="Single policy context used as NLI ground truth.")


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
    if settings.OLLAMA_CLOUD_EMBED_ENABLED:
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

    critical = {k: v for k, v in checks.items() if k != "ollama"}
    overall = "ok" if all(v == "ok" for v in critical.values()) else "degraded"
    return {"status": overall, "dependencies": checks}


@router.post(
    "/emotion-shift",
    response_model=EmotionShiftAnalysis,
    summary="Cross-Modal Dissonance and Counterfactual Analysis",
)
async def emotion_shift_endpoint(payload: EmotionShiftRequest) -> EmotionShiftAnalysis:
    return await analyze_emotion_shift(
        agent_context=payload.agent_context,
        customer_text=payload.customer_text,
        acoustic_emotion=payload.acoustic_emotion,
    )


@router.post(
    "/process-adherence",
    response_model=ProcessAdherenceReport,
    summary="Topic Detection and SOP Process Adherence",
)
async def process_adherence_endpoint(payload: ProcessAdherenceRequest) -> ProcessAdherenceReport:
    return await evaluate_process_adherence(
        transcript_text=payload.transcript_text,
        retrieved_sop_from_pinecone=payload.retrieved_sop_from_pinecone,
        org_filter=payload.org_filter,
    )


@router.post(
    "/nli-policy-check",
    response_model=NLIEvaluation,
    summary="Single-Claim NLI Policy Alignment Check",
)
async def nli_policy_check_endpoint(payload: NLIPolicyCheckRequest) -> NLIEvaluation:
    return await run_nli_policy_check(
        agent_statement=payload.agent_statement,
        ground_truth_policy=payload.ground_truth_policy,
    )


@router.post(
    "/interaction/{interaction_id}/run",
    response_model=InteractionLLMTriggerReport,
    summary="Run all LLM trigger checks for one interaction",
)
async def run_interaction_trigger_endpoint(
    interaction_id: UUID,
    payload: InteractionTriggerRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> InteractionLLMTriggerReport:
    try:
        return await evaluate_interaction_triggers(
            session=session,
            interaction_id=interaction_id,
            retrieved_sop_from_pinecone=payload.retrieved_sop_from_pinecone,
            ground_truth_policy=payload.ground_truth_policy,
            org_filter=payload.org_filter,
            requester_organization_id=current_user.organization_id,
            force_rerun=payload.force_rerun,
            commit_cache=True,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Interaction not found.":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
