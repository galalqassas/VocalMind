# Central API aggregator.
# Logic: All domain routers are registered here — one clean import in app/main.py.

from fastapi import APIRouter

from app.api.routes.agents import router as agents_router
from app.api.routes.assistant import router as assistant_router
from app.api.routes.auth import router as auth_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.diarization import router as diarization_router
from app.api.routes.emotion import router as emotion_router
from app.api.routes.emotion.dispute_router import router as dispute_router
from app.api.routes.full import router as full_router
from app.api.routes.interactions import router as interactions_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.llm_trigger import router as llm_trigger_router
from app.api.routes.rag import router as rag_router
from app.api.routes.transcription import router as transcription_router
from app.api.routes.users import router as users_router
from app.api.routes.vad import router as vad_router
from app.api.routes.internal import router as internal_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.compliance_disputes import router as compliance_disputes_router

api_router = APIRouter()

api_router.include_router(auth_router.router, prefix="/auth", tags=["auth"])
api_router.include_router(emotion_router.router, prefix="/emotion", tags=["emotion"])
api_router.include_router(dispute_router, prefix="/interactions", tags=["emotion-events"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(interactions_router, prefix="/interactions", tags=["interactions"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(agents_router, prefix="/agents", tags=["agents"])
api_router.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(llm_trigger_router.router, prefix="/llm-trigger", tags=["llm-trigger"])
api_router.include_router(rag_router, prefix="/rag", tags=["rag"])
api_router.include_router(diarization_router.router, prefix="/diarization", tags=["diarization"])
api_router.include_router(transcription_router.router, prefix="/transcription", tags=["transcription"])
api_router.include_router(vad_router.router, prefix="/vad", tags=["vad"])
api_router.include_router(full_router.router, prefix="/full", tags=["full"])
api_router.include_router(internal_router, prefix="/internal", tags=["internal"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(reviews_router, prefix="/reviews", tags=["reviews"])
api_router.include_router(feedback_router, prefix="/feedback", tags=["feedback"])
api_router.include_router(compliance_disputes_router, prefix="/policy-compliance", tags=["compliance-disputes"])
