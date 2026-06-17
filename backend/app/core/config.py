import warnings
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

    # Google OAuth / AI
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    GOOGLE_API_KEY: str = ""
    # Manager Assistant text-to-SQL (Gemini). Comma-separated fallbacks if a model ID is unavailable.
    # Prefer 2.0-flash first for broad API availability; 2.5 when your project supports it.
    ASSISTANT_GEMINI_MODEL: str = "gemini-2.0-flash,gemini-2.5-flash,gemini-1.5-flash"
    # gemini | groq | ollama_cloud | ollama | auto
    ASSISTANT_LLM_PROVIDER: str = "auto"
    ASSISTANT_OLLAMA_MODEL: str = "qwen2.5:7b"
    ASSISTANT_OLLAMA_TIMEOUT_SECONDS: float = 120.0

    # Database (Docker Postgres)
    DATABASE_URL: str = "postgresql+asyncpg://vocalmind:vocalmind_dev@localhost:5434/vocalmind"
    ASSISTANT_DATABASE_URL: str = "postgresql+asyncpg://vocalmind_readonly:vocalmind_readonly_dev@localhost:5434/vocalmind"
    LOCAL_AUDIO_STORAGE_DIR: str = "storage/uploads"

    # AI service routing: True = Docker containers, False = Kaggle server
    IS_LOCAL: bool = True

    # Docker container URLs (used when IS_LOCAL=true)
    EMOTION_API_URL: str = "http://localhost:8001"
    VAD_API_URL: str = "http://localhost:8002"
    WHISPERX_API_URL: str = "http://localhost:8003"

    # Optional: Hugging Face export dir for DistilBERT agent/customer classifier (same bundle as WhisperX).
    # When set, the backend relabels transcript segments after full analysis.
    SPEAKER_ROLE_MODEL_DIR: str = ""
    # Keep backend relabeling disabled by default to avoid double relabeling with WhisperX.
    BACKEND_SPEAKER_RELABEL_ENABLED: bool = False

    # Kaggle inference server (used when IS_LOCAL=false)
    KAGGLE_SERVER_URL: str = ""
    KAGGLE_NGROK_URL: str = ""

    # Supabase (for routes that use Supabase client directly)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    HF_TOKEN: str = ""

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
    OLLAMA_MODEL_EMOTION_SHIFT: str = ""
    OLLAMA_MODEL_PROCESS_ADHERENCE: str = ""
    OLLAMA_MODEL_NLI_POLICY: str = ""
    OLLAMA_MODEL_RAG_JUDGE: str = ""
    OLLAMA_MODEL_TEXT_TO_SQL: str = ""
    OLLAMA_MODEL_FAST_CLASSIFICATION: str = ""
    OLLAMA_MODEL_RAG_SYNTHESIS: str = ""
    OLLAMA_EMOTION_SHIFT_MODEL: str = ""
    OLLAMA_PROCESS_ADHERENCE_MODEL: str = ""
    OLLAMA_NLI_MODEL: str = ""
    OLLAMA_CLOUD_EMBED_ENABLED: bool = False

    # ── Provider switch ──
    # "groq"         → current production behaviour
    # "ollama_cloud" → all LLM calls route to Ollama Cloud
    LLM_PROVIDER: str = "groq"

    # Qdrant / Embeddings retrieval for SOP context
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_PARENTS: str = "vocalmind_parents"
    QDRANT_COLLECTION_SOP_PARENTS: str = "vocalmind_sop_parents"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "snowflake-arctic-embed2"
    EMBEDDING_TIMEOUT_SECONDS: float = 60.0
    SOP_RETRIEVAL_TOP_K: int = 4
    SOP_MAX_CHUNKS: int = 2
    RAG_SUPPORTED_THRESHOLD: float = 0.82
    RAG_NEUTRAL_THRESHOLD: float = 0.55
    POLICY_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    SOP_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    KNOWLEDGE_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    POLICY_PARSED_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")
    SOP_PARSED_DOCS_ROOT: str = str(Path.cwd() / "storage" / "docs")

    # Text emotion model used in text+acoustic fusion
    TEXT_EMOTION_PROVIDER: str = "rule_based"  # rule_based | hf_transformers
    TEXT_EMOTION_MODEL: str = "j-hartmann/emotion-english-distilroberta-base"

    # OpenAI API Key for Assistant
    OPENAI_API_KEY: str = ""
    SEED_MOCK_INTERACTIONS: bool = False

    # When True, lifespan runs seed_nexalink + seed_meridian on every boot.
    # Always True for local dev; MUST be False for any deployment pointed at a
    # shared/production database, otherwise startup will re-seed the demo orgs
    # alongside whatever orgs are already there.
    SEED_DEMO_DATA: bool = True

    # Auto-ingest watcher: scans storage/audio/<org_slug>/ and enqueues new
    # audio files for processing via the existing in-memory worker.
    AUDIO_FOLDER_WATCHER_ENABLED: bool = True

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

    if not (cfg.HF_TOKEN or "").strip():
        warnings.warn(
            "HF_TOKEN is not set; diarization is disabled. "
            "Set HF_TOKEN to enable pyannote diarization in WhisperX.",
            stacklevel=1,
        )



def resolve_embedding_base_url() -> str:
    """Ollama embed API root URL (local container or Ollama Cloud)."""
    if settings.OLLAMA_CLOUD_EMBED_ENABLED:
        return settings.OLLAMA_CLOUD_BASE_URL.replace("/v1", "").rstrip("/")
    return settings.OLLAMA_BASE_URL.rstrip("/")


def embedding_request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.OLLAMA_CLOUD_EMBED_ENABLED and settings.OLLAMA_CLOUD_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OLLAMA_CLOUD_API_KEY}"
    return headers
