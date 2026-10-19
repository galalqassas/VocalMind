from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "VocalMind API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:3000"

    # Security
    SECRET_KEY: str = "CHANGE_THIS_TO_A_STRONG_SECRET_KEY_32B"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Google sign-in
    GOOGLE_CLIENT_ID: str = ""
    # ollama_cloud | groq | ollama | auto (auto = Groq, then Ollama Cloud)
    ASSISTANT_LLM_PROVIDER: str = "auto"
    ASSISTANT_OLLAMA_MODEL: str = "qwen2.5:7b"
    ASSISTANT_OLLAMA_TIMEOUT_SECONDS: float = 120.0

    # Database (Docker Postgres)
    DATABASE_URL: str = "postgresql+asyncpg://vocalmind:vocalmind_dev@localhost:5434/vocalmind"
    ASSISTANT_DATABASE_URL: str = "postgresql+asyncpg://vocalmind_readonly:vocalmind_readonly_dev@localhost:5434/vocalmind"
    LOCAL_AUDIO_STORAGE_DIR: str = "storage/uploads"
    AUDIO_STORAGE_BACKEND: str = "local"  # local | supabase
    # Colon- or os-pathsep-separated extra roots for resolve_local_audio_path (e.g. /app/storage/audio_import)
    EXTRA_AUDIO_ROOTS: str = ""

    # AI service routing: True = Docker containers, False = Kaggle server
    IS_LOCAL: bool = True

    # Docker container URLs (used when IS_LOCAL=true)
    EMOTION_API_URL: str = "http://localhost:8001"
    VAD_API_URL: str = "http://localhost:8002"
    WHISPERX_API_URL: str = "http://localhost:8003"

    # Kaggle inference server (used when IS_LOCAL=false); KAGGLE_NGROK_URL is the legacy name
    KAGGLE_SERVER_URL: str = Field(
        default="",
        validation_alias=AliasChoices("KAGGLE_SERVER_URL", "KAGGLE_NGROK_URL"),
    )

    # Supabase (for routes that use Supabase client directly)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_AUDIO_BUCKET: str = "recordings"

    # LLM trigger (Groq + LangChain)
    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 1024
    LLM_REQUEST_TIMEOUT_SECONDS: float = 60.0

    # ── Ollama Cloud ──
    OLLAMA_CLOUD_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_CLOUD_API_KEY", "OLLAMA_API_KEY"),
    )
    OLLAMA_CLOUD_BASE_URL: str = "https://ollama.com/v1"
    OLLAMA_CLOUD_HEAVY_MODEL: str = "kimi-k2.6:cloud"
    OLLAMA_CLOUD_FAST_MODEL: str = "ministral-3:8b"
    # Per-stage overrides, used only when LLM_PROVIDER=ollama_cloud; blank = heavy/fast default.
    OLLAMA_MODEL_EMOTION_SHIFT: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_MODEL_EMOTION_SHIFT", "OLLAMA_EMOTION_SHIFT_MODEL"),
    )
    OLLAMA_MODEL_PROCESS_ADHERENCE: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_MODEL_PROCESS_ADHERENCE", "OLLAMA_PROCESS_ADHERENCE_MODEL"),
    )
    OLLAMA_MODEL_NLI_POLICY: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_MODEL_NLI_POLICY", "OLLAMA_NLI_MODEL"),
    )
    OLLAMA_MODEL_RAG_JUDGE: str = ""
    OLLAMA_MODEL_TEXT_TO_SQL: str = ""
    OLLAMA_MODEL_FAST_CLASSIFICATION: str = ""
    OLLAMA_MODEL_RAG_SYNTHESIS: str = ""
    OLLAMA_CLOUD_EMBED_ENABLED: bool = False
    # Where RAG models run (query embeddings here; ingestion uses the same switch):
    # "local" = Ollama container, "kaggle" = Kaggle GPU server (services/kaggle).
    RAG_MODELS_HOST: str = "local"

    # LLM provider for triggers and RAG: "ollama_cloud" or "groq"
    LLM_PROVIDER: str = "groq"

    # Qdrant / Embeddings retrieval for SOP context
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_PARENTS: str = "vocalmind_parents"
    QDRANT_COLLECTION_SOP_PARENTS: str = "vocalmind_sop_parents"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "snowflake-arctic-embed2"
    EMBEDDING_TIMEOUT_SECONDS: float = 60.0
    SOP_RETRIEVAL_TOP_K: int = 4
    RAG_SUPPORTED_THRESHOLD: float = 0.82
    RAG_NEUTRAL_THRESHOLD: float = 0.55
    POLICY_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    SOP_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    KNOWLEDGE_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    SOP_PARSED_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    SEED_EVALUATION_SESSIONS: bool = False

    # When True, lifespan runs seed_nexalink + seed_meridian on every boot.
    # Always True for local dev; MUST be False for any deployment pointed at a
    # shared/production database, otherwise startup will re-seed the demo orgs
    # alongside whatever orgs are already there.
    SEED_DEMO_DATA: bool = True

    # Auto-ingest watcher: scans storage/audio/<org_slug>/ and enqueues new
    # audio files for processing via the existing in-memory worker.
    # Default OFF: ingestion is manual (UI upload). Opt in via .env if needed.
    AUDIO_FOLDER_WATCHER_ENABLED: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")


settings = Settings()

_DEFAULT_SECRET = "CHANGE_THIS_TO_A_STRONG_SECRET_KEY_32B"


def validate_startup_settings(cfg: Settings) -> None:
    """Fail-fast startup validation for required auth/provider secrets."""
    if cfg.SECRET_KEY == _DEFAULT_SECRET:
        raise RuntimeError(
            "SECRET_KEY is still the default placeholder. "
            "Generate a strong key (e.g. `openssl rand -hex 32`) and set SECRET_KEY in your .env before starting the app."
        )

    provider = (cfg.LLM_PROVIDER or "").strip().lower()
    if provider == "groq" and not (cfg.GROQ_API_KEY or "").strip():
        raise RuntimeError(
            "LLM_PROVIDER=groq requires GROQ_API_KEY, but it is empty. "
            "Set GROQ_API_KEY in your .env before starting the app."
        )
    if provider == "ollama_cloud" and not (cfg.OLLAMA_CLOUD_API_KEY or "").strip():
        raise RuntimeError(
            "LLM_PROVIDER=ollama_cloud requires OLLAMA_CLOUD_API_KEY (or OLLAMA_API_KEY), but none is set. "
            "Set OLLAMA_CLOUD_API_KEY or OLLAMA_API_KEY in your .env before starting the app."
        )


def resolve_embedding_base_url() -> str:
    """Embed API root URL (Kaggle server, Ollama Cloud or the local Ollama container)."""
    if settings.RAG_MODELS_HOST == "kaggle":
        base_url = settings.KAGGLE_SERVER_URL
        if not base_url:
            raise ValueError("RAG_MODELS_HOST=kaggle but KAGGLE_SERVER_URL is not set.")
        return base_url.rstrip("/")
    if settings.OLLAMA_CLOUD_EMBED_ENABLED:
        return settings.OLLAMA_CLOUD_BASE_URL.replace("/v1", "").rstrip("/")
    return settings.OLLAMA_BASE_URL.rstrip("/")


def embedding_request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.RAG_MODELS_HOST == "kaggle":
        headers["ngrok-skip-browser-warning"] = "true"
    elif settings.OLLAMA_CLOUD_EMBED_ENABLED and settings.OLLAMA_CLOUD_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OLLAMA_CLOUD_API_KEY}"
    return headers
