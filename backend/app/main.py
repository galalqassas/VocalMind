from contextlib import asynccontextmanager
import logging
from uuid import uuid4

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

from app.core.config import settings, validate_startup_settings
from app.core.database import create_db_and_tables
from app.core.interaction_processing import start_processing_worker, stop_processing_worker
from app.core.audio_folder_watcher import start_audio_folder_watcher, stop_audio_folder_watcher
from app.core.llm_circuit_breaker import get_breaker_states
from app.core.rate_limit import limiter
from app.core.request_context import install_request_id_logging, reset_request_id, set_request_id
from app.api.main import api_router
from scripts.seed_nexalink import main as seed_nexalink_main
from scripts.seed_meridian import main as seed_meridian_main


from app.api.routes.dashboard import prewarm_dashboard_cache


logger = logging.getLogger(__name__)
install_request_id_logging()

async def _prewarm_with_log() -> None:
    try:
        await prewarm_dashboard_cache()
    except Exception:
        logger.exception("Dashboard cache pre-warm failed at startup — first load will be cold")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup_settings(settings)
    await create_db_and_tables()
    if settings.SEED_DEMO_DATA:
        await seed_nexalink_main()
        await seed_meridian_main()
    else:
        logger.info("SEED_DEMO_DATA=false — skipping Nexalink/Meridian demo seeding")
    await start_processing_worker()
    await start_audio_folder_watcher()
    # Pre-warm the dashboard cache so the first manager load is instantaneous
    import asyncio
    asyncio.create_task(_prewarm_with_log())
    try:
        yield
    finally:
        await stop_audio_folder_watcher()
        await stop_processing_worker()


tags_metadata = [
    {"name": "auth", "description": "Authentication, Google OAuth, and session management."},
    {"name": "emotion", "description": "Speech and text emotion analysis and dual-emotion fusion."},
    {"name": "emotion-events", "description": "Agent-disputed emotion events and manager reviews."},
    {"name": "dashboard", "description": "Call center performance indicators, trends, and leaderboard statistics."},
    {"name": "interactions", "description": "Call recording interactions upload, reprocessing, listing, and analysis details."},
    {"name": "knowledge", "description": "Policy, FAQ, and KB document CRUD operations and PDF ingestion."},
    {"name": "agents", "description": "Agent performance tracking and profile administration."},
    {"name": "assistant", "description": "Natural-language-to-SQL AI Manager Assistant chat and query processing."},
    {"name": "users", "description": "User profile management and password operations."},
    {"name": "llm-trigger", "description": "Compliance, emotion shift, process adherence, and policy check LLM triggers."},
    {"name": "rag", "description": "RAG querying and vector DB retrieval proxy endpoints."},
    {"name": "diarization", "description": "Voice activity detection and speaker diarization endpoints."},
    {"name": "transcription", "description": "Speech-to-text transcription endpoints."},
    {"name": "vad", "description": "Audio voice activity detection split endpoints."},
    {"name": "full", "description": "Unified pipeline (VAD + ASR + Emotion) execution endpoint."},
    {"name": "internal", "description": "Internal developer diagnostics, system status, and backend configuration."},
    {"name": "notifications", "description": "In-app notifications CRUD operations and polling endpoints."},
    {"name": "reviews", "description": "Agent compliance/emotion dispute coaching and review queue management."},
    {"name": "feedback", "description": "Post-interaction compliance and emotion feedback collection."},
    {"name": "compliance-disputes", "description": "Policy compliance dispute workflow for agents and managers."},
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
    summary="Call-center AI platform for audio transcription, diarization, emotion fusion, and LLM compliance scoring.",
    description="""
VocalMind is a multi-tenant call-center AI platform that provides:
* **Speech Processing**: VAD, WhisperX transcription, and speaker diarization.
* **Dual-Emotion Fusion**: Joint acoustic and text emotion analysis per utterance.
* **LLM Compliance scoring**: Evidence-anchored policy validation and process adherence tracking.
* **AI Manager Assistant**: Natural-language-to-SQL dashboard querying.
* **RAG System**: Dual Qdrant collections for compliance validation and FAQ Q&A.
    """,
    contact={
        "name": "VocalMind Engineering Team",
        "email": "engineering@vocalmind.ai",
        "url": "https://vocalmind.ai",
    },
    openapi_tags=tags_metadata,
)

# Prometheus /metrics endpoint. Excludes itself and /health so the counters
# don't bloat with health-check noise. Request-id correlation is provided by
# the existing app.core.request_context middleware below.
Instrumentator(
    excluded_handlers=["/metrics", "/health"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Rate limiting (default 60/min/IP, see app/core/rate_limit.py).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    token = set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Request-ID"] = request_id
    reset_request_id(token)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    error_id = str(uuid4())
    logger.error(
        "Unhandled exception [error_id=%s] path=%s method=%s",
        error_id,
        request.url.path,
        request.method,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred.", "error_id": error_id},
    )

# Single router include — all domains registered in app/api/main.py
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    """
    Root endpoint that provides a welcoming message for the VocalMind API.
    """
    return {"message": "Welcome to VocalMind API"}


@app.get("/health")
async def health():
    """
    Verify application health by testing the backend database connection.
    Returns 200 OK if successful, or 503 Service Unavailable if the database is unreachable.
    """
    try:
        dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(dsn=dsn, timeout=3.0)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
    except Exception:
        logger.error("Health DB check failed", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "unreachable"})


@app.get("/health/circuit-breakers")
async def circuit_breakers_health():
    """
    Retrieve current state of all LLM and third-party API circuit breakers.
    Used for monitoring service degradation and diagnostic health checks.
    """
    # Diagnostic-only endpoint. Restrict to internal/admin access before exposing publicly.
    return JSONResponse(status_code=200, content=get_breaker_states())
