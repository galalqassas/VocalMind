"""
Configuration module for VocalMind Final RAG.

Uses Pydantic Settings for type-safe config with .env file support.
Architecture:
  Parsing    → Docling  (AI-powered PDF → Markdown)
  Embeddings → Ollama   (snowflake-arctic-embed2, 1024-dim)
  Vector DB  → Qdrant   (dual collections: parents + children)
  LLM        → Ollama Cloud (production; LLM_PROVIDER=ollama_cloud); Groq optional fallback
"""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

SERVICE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_DIR.parent.parent


# ── Sub-configs ───────────────────────────────────────────────────────────────


class GroqConfig(BaseSettings):
    """Groq LLM configuration."""

    api_key: SecretStr = Field(alias="GROQ_API_KEY")
    model: str = Field(default="llama-3.3-70b-versatile", alias="LLM_MODEL")
    temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")
    context_window: int = 131_072


class EmbeddingConfig(BaseSettings):
    """Ollama embedding model configuration."""

    model: str = Field(default="snowflake-arctic-embed2", alias="EMBEDDING_MODEL")
    base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    dimension: int = Field(default=1024, alias="EMBEDDING_DIMENSION")
    request_timeout: float = 120.0


class QdrantConfig(BaseSettings):
    """Qdrant vector store configuration."""

    url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    collection_parents: str = Field(default="vocalmind_parents", alias="QDRANT_COLLECTION_PARENTS")
    collection_children: str = Field(default="vocalmind_children", alias="QDRANT_COLLECTION_CHILDREN")
    collection_sop_parents: str = Field(default="vocalmind_sop_parents", alias="QDRANT_COLLECTION_SOP_PARENTS")


class ParentChunkingConfig(BaseSettings):
    """Parent chunking: Markdown header splitting on H1/H2/H3."""

    headers_to_split_on: list[tuple[str, str]] = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    empty_section_min_words: int = 4


class ChildChunkingConfig(BaseSettings):
    """Child chunking: Recursive character splitting for precision snippets."""

    chunk_size: int = 400
    chunk_overlap: int = 80
    min_chunk_length: int = 30


# ── Main Settings ─────────────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Application-wide settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=(
            SERVICE_DIR / ".env",
            REPO_ROOT / ".env",
            REPO_ROOT / "backend" / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    # Paths
    BASE_DIR: Path = SERVICE_DIR
    DOCS_DIR: Path = Field(
        default_factory=lambda: REPO_ROOT / "storage" / "docs",
        alias="DOCS_DIR",
    )
    PARSED_DIR: Path = Field(
        default_factory=lambda: REPO_ROOT / "storage" / "docs",
        alias="PARSED_DIR",
    )
    POLICY_DOCS_DIR: Path = Field(
        default_factory=lambda: REPO_ROOT / "storage" / "docs",
        alias="POLICY_DOCS_DIR",
    )
    KNOWLEDGE_DOCS_DIR: Path = Field(
        default_factory=lambda: REPO_ROOT / "storage" / "docs",
        alias="KNOWLEDGE_DOCS_DIR",
    )
    PARSED_POLICY_DIR: Path = Field(
        default_factory=lambda: REPO_ROOT / "storage" / "docs",
        alias="PARSED_POLICY_DIR",
    )
    PARSED_SOP_DIR: Path = Field(
        default_factory=lambda: REPO_ROOT / "storage" / "docs",
        alias="PARSED_SOP_DIR",
    )

    # ── Ollama Cloud (mirrors backend/app/core/config.py) ──
    LLM_PROVIDER: str = Field(default="groq", alias="LLM_PROVIDER")
    OLLAMA_CLOUD_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_CLOUD_API_KEY", "OLLAMA_API_KEY"),
    )
    OLLAMA_CLOUD_BASE_URL: str = Field(
        default="https://ollama.com/v1",
        alias="OLLAMA_CLOUD_BASE_URL",
    )
    OLLAMA_CLOUD_HEAVY_MODEL: str = Field(
        default="kimi-k2.6:cloud",
        alias="OLLAMA_CLOUD_HEAVY_MODEL",
    )
    OLLAMA_CLOUD_FAST_MODEL: str = Field(
        default="ministral-3:8b",
        alias="OLLAMA_CLOUD_FAST_MODEL",
    )
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
    OLLAMA_MODEL_RAG_JUDGE: str = Field(default="", alias="OLLAMA_MODEL_RAG_JUDGE")
    OLLAMA_MODEL_TEXT_TO_SQL: str = Field(default="", alias="OLLAMA_MODEL_TEXT_TO_SQL")
    OLLAMA_MODEL_FAST_CLASSIFICATION: str = Field(default="", alias="OLLAMA_MODEL_FAST_CLASSIFICATION")
    OLLAMA_MODEL_RAG_SYNTHESIS: str = Field(default="", alias="OLLAMA_MODEL_RAG_SYNTHESIS")
    OLLAMA_CLOUD_EMBED_ENABLED: bool = Field(
        default=False,
        alias="OLLAMA_CLOUD_EMBED_ENABLED",
    )
    # Where RAG models run (embeddings, Docling parsing, reranking):
    #   local  — Ollama container + in-process Docling / cross-encoder
    #   kaggle — the Kaggle GPU server (services/kaggle) at KAGGLE_SERVER_URL
    RAG_MODELS_HOST: Literal["local", "kaggle"] = Field(default="local", alias="RAG_MODELS_HOST")
    KAGGLE_SERVER_URL: str = Field(default="", alias="KAGGLE_SERVER_URL")

    # Sub-configs
    groq: GroqConfig = Field(default_factory=GroqConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    parent_chunking: ParentChunkingConfig = Field(default_factory=ParentChunkingConfig)
    child_chunking: ChildChunkingConfig = Field(default_factory=ChildChunkingConfig)

    # Query defaults
    # top_k=3: the reranker scans a wide pool (RERANK_CANDIDATE_K) and returns
    # only the 3 best chunks. Fewer unused tail chunks → higher context precision,
    # since the precision judge penalizes retrieved contexts the answer didn't use.
    similarity_top_k: int = 3
    response_mode: Literal["compact", "refine", "tree_summarize"] = "compact"
    RAG_QUERY_LOG_ENABLED: bool = Field(default=False, alias="RAG_QUERY_LOG_ENABLED")

    # ── Synthesis prompt mode ──
    # "safe"      — grounded + honest escape-hatch (admits when context lacks the
    #               answer). Production default: safer for a compliance assistant.
    # "assertive" — grounded but never hedges; states policy as fact. Maximizes
    #               RAGAS answer-relevancy for evaluation, at some cost to honesty.
    SYNTHESIS_PROMPT_MODE: Literal["safe", "assertive"] = Field(
        default="safe", alias="SYNTHESIS_PROMPT_MODE"
    )

    # ── HyDE (Hypothetical Document Embeddings) ──
    # When enabled, the LLM drafts a hypothetical answer passage for each query;
    # that passage (concatenated with the query) is embedded for retrieval.
    # Closes the question↔statement embedding gap on policy/SOP corpora.
    HYDE_ENABLED: bool = Field(default=False, alias="HYDE_ENABLED")
    HYDE_MAX_TOKENS: int = Field(default=200, alias="HYDE_MAX_TOKENS")

    # ── Reranking (cross-encoder) ──
    # When enabled, retrieval pulls `rerank_candidate_k` chunks from Qdrant,
    # reranks them with a cross-encoder, and keeps the top `similarity_top_k`.
    RERANK_ENABLED: bool = Field(default=True, alias="RERANK_ENABLED")
    RERANK_MODEL: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANK_MODEL")
    RERANK_CANDIDATE_K: int = Field(default=20, alias="RERANK_CANDIDATE_K")

    # ── RAGAS judge LLM (local LM Studio / OpenAI-compatible endpoint) ──
    RAGAS_JUDGE_MODEL: str = Field(default="qwen2.5-7b-instruct", alias="RAGAS_JUDGE_MODEL")
    RAGAS_JUDGE_BASE_URL: str = Field(default="http://localhost:1234/v1", alias="RAGAS_JUDGE_BASE_URL")
    RAGAS_JUDGE_API_KEY: str = Field(default="lm-studio", alias="RAGAS_JUDGE_API_KEY")
    # Judge provider: "local" | "groq".
    #   groq   — Groq llama-3.3-70b (good, but free tier has a 100k token/day cap
    #            and rejects n>1 for AnswerRelevancy).
    #   local  — LM Studio endpoint (offline; weakest, capped ~0.74).
    RAGAS_JUDGE_PROVIDER: str = Field(default="local", alias="RAGAS_JUDGE_PROVIDER")

    # ── Reranker score threshold ──
    # Cross-encoder chunks below this score are dropped before synthesis.
    # Disabled by default (very low sentinel): empirically, dropping chunks
    # produced terser responses that LOWERED RAGAS context precision on the
    # local-judge setup. Raise this only with evidence it helps your corpus.
    RERANK_MIN_SCORE: float = Field(default=-1000.0, alias="RERANK_MIN_SCORE")

    # ── Local synthesis override (overrides Groq for RAG answer generation) ──
    # Set SYNTHESIS_BASE_URL to an OpenAI-compatible endpoint (e.g. LM Studio)
    # to avoid Groq token limits during evaluation / offline runs.
    SYNTHESIS_BASE_URL: str = Field(default="", alias="SYNTHESIS_BASE_URL")
    SYNTHESIS_MODEL: str = Field(default="", alias="SYNTHESIS_MODEL")
    SYNTHESIS_API_KEY: str = Field(default="lm-studio", alias="SYNTHESIS_API_KEY")

    def model_post_init(self, __context) -> None:
        """Resolve relative env paths from the RAG service directory."""
        self.DOCS_DIR = self._resolve_path(self.DOCS_DIR)
        self.PARSED_DIR = self._resolve_path(self.PARSED_DIR)
        self.POLICY_DOCS_DIR = self._resolve_path(self.POLICY_DOCS_DIR)
        self.KNOWLEDGE_DOCS_DIR = self._resolve_path(self.KNOWLEDGE_DOCS_DIR)
        self.PARSED_POLICY_DIR = self._resolve_path(self.PARSED_POLICY_DIR)
        self.PARSED_SOP_DIR = self._resolve_path(self.PARSED_SOP_DIR)

    @staticmethod
    def _resolve_path(path: Path) -> Path:
        """Resolve relative paths against services/rag/."""
        return path if path.is_absolute() else (SERVICE_DIR / path).resolve()

    def validate_config(self) -> None:
        """Validate critical config at startup."""
        if not self.DOCS_DIR.exists():
            raise ValueError(f"Docs directory {self.DOCS_DIR} does not exist.")


settings = Settings()


_HEAVY_STAGE = "heavy"
_FAST_STAGE = "fast"
# NOTE: fast_classification is benchmarked and configurable, but currently has
# no production runtime call site wired in backend/service flows.
_STAGE_MODEL_CLASS: dict[str, str] = {
    "emotion_shift": _HEAVY_STAGE,
    "process_adherence": _HEAVY_STAGE,
    "text_to_sql": _HEAVY_STAGE,
    "nli_policy": _FAST_STAGE,
    "rag_judge": _FAST_STAGE,
    "fast_classification": _FAST_STAGE,
    "rag_synthesis": _FAST_STAGE,
}


def recognized_stage_names() -> tuple[str, ...]:
    """Expose recognized stage names for cross-service sync tests."""
    return tuple(sorted(_STAGE_MODEL_CLASS))


def resolve_model_for_stage(stage: str) -> str:
    """Model for a stage: on Ollama Cloud the per-stage override or the heavy/fast default; on Groq its model."""
    key = stage.lower().replace("-", "_")
    if key == "nli":
        key = "nli_policy"
    if key not in _STAGE_MODEL_CLASS:
        allowed = ", ".join(sorted(_STAGE_MODEL_CLASS))
        raise ValueError(f"Unknown LLM stage '{stage}'. Allowed stages: {allowed}")
    if settings.LLM_PROVIDER != "ollama_cloud":
        return settings.groq.model

    overrides = {
        "emotion_shift": settings.OLLAMA_MODEL_EMOTION_SHIFT,
        "process_adherence": settings.OLLAMA_MODEL_PROCESS_ADHERENCE,
        "nli_policy": settings.OLLAMA_MODEL_NLI_POLICY,
        "rag_judge": settings.OLLAMA_MODEL_RAG_JUDGE,
        "text_to_sql": settings.OLLAMA_MODEL_TEXT_TO_SQL,
        "fast_classification": settings.OLLAMA_MODEL_FAST_CLASSIFICATION,
        "rag_synthesis": settings.OLLAMA_MODEL_RAG_SYNTHESIS,
    }
    override = (overrides[key] or "").strip()
    if override:
        return override
    if _STAGE_MODEL_CLASS[key] == _FAST_STAGE:
        return settings.OLLAMA_CLOUD_FAST_MODEL
    return settings.OLLAMA_CLOUD_HEAVY_MODEL


def rag_judge_model() -> str:
    """Model ID for RAG evaluator judge calls."""
    return resolve_model_for_stage("rag_judge")


def rag_synthesis_model() -> str:
    """Model ID for RAG synthesis calls in query_engine."""
    return resolve_model_for_stage("rag_synthesis")


def build_rag_llm_client():
    """
    OpenAI-compatible chat client for RAG judge calls.
    Groq SDK when LLM_PROVIDER=groq; OpenAI client → Ollama Cloud otherwise.
    """
    if settings.LLM_PROVIDER == "ollama_cloud":
        from openai import OpenAI

        api_key = settings.OLLAMA_CLOUD_API_KEY
        if not api_key:
            raise ValueError(
                "OLLAMA_CLOUD_API_KEY is not set. "
                "Set it in .env or keep LLM_PROVIDER=groq."
            )
        return OpenAI(
            api_key=api_key,
            base_url=settings.OLLAMA_CLOUD_BASE_URL,
        )
    from groq import Groq

    return Groq(api_key=settings.groq.api_key.get_secret_value())


def embedding_http_base_url() -> str:
    if settings.OLLAMA_CLOUD_EMBED_ENABLED:
        return settings.OLLAMA_CLOUD_BASE_URL.replace("/v1", "").rstrip("/")
    return settings.embedding.base_url.rstrip("/")


def embedding_http_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.OLLAMA_CLOUD_EMBED_ENABLED and settings.OLLAMA_CLOUD_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OLLAMA_CLOUD_API_KEY}"
    return headers


# ── Kaggle GPU server (RAG_MODELS_HOST=kaggle) ────────────────────────────────

KAGGLE_HEADERS = {"ngrok-skip-browser-warning": "true"}


def use_kaggle_models() -> bool:
    return settings.RAG_MODELS_HOST == "kaggle"


def kaggle_post(path: str, timeout: float = 300.0, **kwargs) -> dict:
    """POST to the Kaggle server and return its JSON body; raises on any failure."""
    import httpx

    base_url = settings.KAGGLE_SERVER_URL.rstrip("/")
    if not base_url:
        raise ValueError("RAG_MODELS_HOST=kaggle but KAGGLE_SERVER_URL is not set.")
    response = httpx.post(f"{base_url}{path}", headers=KAGGLE_HEADERS, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response.json()


def kaggle_embed(texts: list[str]) -> list[list[float]]:
    """Embed texts on the Kaggle server (snowflake-arctic-embed-l-v2.0, 1024-d)."""
    vectors = kaggle_post("/embed", json={"texts": texts}).get("embeddings") or []
    if len(vectors) != len(texts):
        raise ValueError(f"Kaggle /embed returned {len(vectors)} vectors for {len(texts)} texts.")
    return vectors
