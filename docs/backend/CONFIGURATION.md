# VocalMind Configuration & Environment Variables

This document provides a detailed reference for all configuration variables supported by the VocalMind backend.

---

## 1. Environment Reference Dictionary

VocalMind reads settings from `backend/.env` using Pydantic `BaseSettings`. Below is the complete dictionary of variables:

### 1.1 Core App & Security Settings
*   **`PROJECT_NAME`** (string): Defaults to `"VocalMind API"`. Displays in OpenAPI docs.
*   **`VERSION`** (string): Defaults to `"1.0.0"`. Exposes application version.
*   **`API_V1_STR`** (string): Defaults to `"/api/v1"`. Prefix for all API routes.
*   **`SECRET_KEY`** (string, **Required**): Secret key used to sign JWT token cookies. Generate using `openssl rand -hex 32`.
*   **`ALGORITHM`** (string): Signature hashing algorithm. Defaults to `"HS256"`.
*   **`ACCESS_TOKEN_EXPIRE_MINUTES`** (integer): Token lifetime duration. Defaults to `30`.

### 1.2 Database Settings
*   **`DATABASE_URL`** (string, **Required**): SQLAlchemy connection string.
    *   Docker: `postgresql+asyncpg://vocalmind:vocalmind_dev@localhost:5433/vocalmind` (port `5433` maps to internal container `5432`).
    *   Testing: Overridden at runtime to use an in-memory SQLite engine (`sqlite+aiosqlite://`).

### 1.3 AI Assistant Settings
*   **`GOOGLE_API_KEY`** (string, Optional): API key for Gemini models.
*   **`ASSISTANT_LLM_PROVIDER`** (string): LLM provider for SQL generation.
    *   `auto` (default): Uses Gemini if `GOOGLE_API_KEY` is present, else falls back to local Ollama.
    *   `gemini`: Forces Gemini API.
    *   `ollama`: Forces Ollama engine.
*   **`ASSISTANT_GEMINI_MODEL`** (string): Comma-separated list of candidate Gemini models (e.g. `gemini-2.0-flash,gemini-2.5-flash`).
*   **`ASSISTANT_OLLAMA_MODEL`** (string): Local model name for Text-to-SQL fallback (defaults to `qwen2.5:7b`).

### 1.4 Inference Routing Settings
*   **`IS_LOCAL`** (boolean): Routes pipeline ML requests.
    *   `true`: Routes VAD, WhisperX, and Emotion processing directly to local containers (`:8001`, `:8002`, `:8003`).
    *   `false` (default in example): Routes requests to a remote Kaggle server.
*   **`EMOTION_API_URL`** (string): Endpoint for the local Emotion microservice. Defaults to `"http://localhost:8001"`.
*   **`VAD_API_URL`** (string): Endpoint for the local VAD microservice. Defaults to `"http://localhost:8002"`.
*   **`WHISPERX_API_URL`** (string): Endpoint for the local WhisperX microservice. Defaults to `"http://localhost:8003"`.

### 1.5 Speaker & Emotion Tuning
*   **`BACKEND_SPEAKER_RELABEL_ENABLED`** (boolean): If `true`, enables a second speaker role relabel pass. **Must remain `false`** when using WhisperX to avoid double relabeling conflicts.
*   **`TEXT_EMOTION_PROVIDER`** (string): Provider for text sentiment classification. Defaults to `"hf_transformers"`.
*   **`TEXT_EMOTION_MODEL`** (string): Hugging Face model path. Defaults to `"j-hartmann/emotion-english-distilroberta-base"`.
*   **`EMOTION_MIN_SEGMENT_SECS`** (string): Minimum duration gate for emotion classification. Segments shorter than this (e.g., `"1.0"`) inherit the previous turn's emotion.

### 1.6 Remote Kaggle / NGROK Settings
*   **`KAGGLE_SERVER_URL`** (string): Direct URL to a running remote Kaggle kernel server.
*   **`KAGGLE_NGROK_URL`** (string): Fallback URL mapping the Kaggle NGROK tunnel.
*   **`HF_TOKEN`** (string, **Required**): HuggingFace user access token. Necessary to download PyAnnote speaker diarization models inside WhisperX.
*   **`FFMPEG_PATH`** (string, Optional): Path to local FFmpeg binaries if not present in the global PATH environment.

### 1.7 OAuth & Frontend Settings
*   **`FRONTEND_URL`** (string): URL of the React frontend application (defaults to `http://localhost:3000`). Used for CORS configuration and OAuth redirections.
*   **`GOOGLE_CLIENT_ID`** (string): Google OAuth client ID credentials.
*   **`GOOGLE_CLIENT_SECRET`** (string): Google OAuth client secret credentials.
*   **`GOOGLE_REDIRECT_URI`** (string): OAuth redirect callback endpoint (defaults to `http://localhost:8000/api/v1/auth/google/callback`).

### 1.8 Storage & Supabase Settings
*   **`LOCAL_AUDIO_STORAGE_DIR`** (string): Root directory where uploaded audio call recordings are stored (defaults to `"storage/uploads"`).
*   **`SPEAKER_ROLE_MODEL_DIR`** (string, Optional): Path containing extracted DistilBERT speaker-role models.
*   **`SUPABASE_URL`** (string, Optional): Supabase project URL, used when resolving files from Supabase Storage.
*   **`SUPABASE_SERVICE_KEY`** (string, Optional): Supabase service role API key.

### 1.9 LLM Triggers & Groq Settings
*   **`GROQ_API_KEY`** (string, **Required** for LLM triggers): API key for Groq Cloud inference (e.g. `gsk_...`).
*   **`LLM_MODEL`** (string): Main Chat model for trigger evaluation (defaults to `"llama-3.3-70b-versatile"`).
*   **`LLM_TEMPERATURE`** (float): Sampling temperature for trigger generation. Defaults to `0.0`.
*   **`LLM_MAX_TOKENS`** (integer): Maximum output tokens per LangChain response. Defaults to `1024`.
*   **`LLM_REQUEST_TIMEOUT_SECONDS`** (float): Timeout for Groq API requests. Defaults to `60.0`.

### 1.10 RAG & Vector DB Settings
*   **`QDRANT_URL`** (string): Endpoint of the Qdrant Vector database. Defaults to `"http://localhost:6333"`.
*   **`QDRANT_COLLECTION_PARENTS`** (string): Target Qdrant collection name for parent compliance chunks. Defaults to `"vocalmind_parents"`.
*   **`QDRANT_COLLECTION_SOP_PARENTS`** (string): Target collection name for SOP/KB parent chunks. Defaults to `"vocalmind_sop_parents"`.
*   **`OLLAMA_BASE_URL`** (string): Endpoint for the Ollama embedding service. Defaults to `"http://localhost:11434"`.
*   **`EMBEDDING_MODEL`** (string): Name of the embedding model to load in Ollama. Defaults to `"snowflake-arctic-embed2"`.
*   **`EMBEDDING_TIMEOUT_SECONDS`** (float): Timeout for generating RAG query embeddings. Defaults to `60.0`.
*   **`SOP_RETRIEVAL_TOP_K`** (integer): Number of closest chunks to retrieve for context in SOP evaluation. Defaults to `4`.
*   **`SOP_MAX_CHUNKS`** (integer): Max SOP chunks to inject. Defaults to `2`.
*   **`RAG_SUPPORTED_THRESHOLD`** (float): Confidence threshold for RAG evaluation agreement. Defaults to `0.82`.
*   **`RAG_NEUTRAL_THRESHOLD`** (float): Threshold above which RAG evaluations are mapped as neutral/benign. Defaults to `0.55`.
*   **`POLICY_DOCS_ROOT`** (string): Directory containing original PDF/DOCX policy files. Defaults to `"storage/docs"`.
*   **`SOP_DOCS_ROOT`** (string): Directory containing original SOP procedure files. Defaults to `"storage/docs"`.
*   **`KNOWLEDGE_DOCS_ROOT`** (string): Directory containing original general knowledge-base files. Defaults to `"storage/docs"`.
*   **`POLICY_PARSED_DOCS_ROOT`** (string): Directory containing parsed Markdown policy documents. Defaults to `"storage/docs"`.
*   **`SOP_PARSED_DOCS_ROOT`** (string): Directory containing parsed Markdown SOP documents. Defaults to `"storage/docs"`.

### 1.11 General / Misc Settings
*   **`ASSISTANT_OLLAMA_TIMEOUT_SECONDS`** (float): Timeout for Assistant Ollama requests. Defaults to `120.0`.
*   **`OPENAI_API_KEY`** (string, Optional): API key for OpenAI fallback assistant.
*   **`SEED_MOCK_INTERACTIONS`** (boolean): Flag to toggle mock interaction seeding. Defaults to `false`.
*   **`AUDIO_FOLDER_WATCHER_ENABLED`** (boolean): Set to `false` to disable the background storage-folder auto-ingestion watcher scanner. Defaults to `true`.

---

## 2. Direct Environment Variable Lookups (Hidden Config)

The following variables are read directly via `os.getenv` without being defined inside the Pydantic Settings class:

*   **`EXTRA_AUDIO_ROOTS`** (string): Semicolon-separated (`;`) list of alternative root directories for resolving local audio files.
*   **`SQLALCHEMY_ECHO`** (boolean/string): Toggles printing raw SQL statements compiled by SQLAlchemy. Set to `true` to enable.
*   **`DB_POOL_SIZE`** (integer): The number of concurrent connections to keep open in the PostgreSQL connection pool.
*   **`DB_MAX_OVERFLOW`** (integer): Max overflow connections allowed beyond the standard pool size limit.
*   **`LLM_TRIGGER_EVAL_TIMEOUT_SECONDS`** (float): Limit on how long a three-chain evaluation can run before raising a TimeoutError.
*   **`EMOTION_MAX_AUDIO_SECONDS`** (float): Maximum length in seconds for audio clips processed by the Emotion microservice (caps at `30.0`).
*   **`WHISPER_MODEL_SIZE`** (string): Model size constraint for WhisperX transcription.
*   **`CHANNEL_DIARIZATION_ENABLED`** (boolean): Enables separate channel diarization.
*   **`SPEAKER_ROLE_MODEL_ENABLED`** (boolean): Toggles using Hugging Face classifier inside WhisperX.
*   **`STRICT_DIARIZATION`** (boolean): Toggles strict overlapping speaker segments handling.
*   **`WHISPER_COMPUTE_TYPE`** (string): Torch float precision mode for WhisperX inference.
*   **`CHANNEL_DIARIZATION_MAX_CORR`** (float): Maximum correlation threshold for diarization.
*   **`AGENT_CHANNEL`** (integer): Explicit channel index designated as the agent speaker.

