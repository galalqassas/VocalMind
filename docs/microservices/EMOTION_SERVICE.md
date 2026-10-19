# Emotion Service

`services/emotion/app.py` — FastAPI. Compose service `emotion`, host port 8001 → container 8000; backend uses `EMOTION_API_URL` (`http://emotion:8000` in compose). CUDA when available, else CPU (GPU overlay: `docker-compose.gpu.yml`).

## Models (loaded at startup)

- Audio: FunASR `AutoModel("iic/emotion2vec_plus_base", trust_remote_code=True)`.
- Text: Hugging Face `pipeline("text-classification", "j-hartmann/emotion-english-distilroberta-base", top_k=None)`. If it fails to load, the service still starts and `/predict_text` returns 503.

## Endpoints

| Method | Path | Behaviour |
|---|---|---|
| POST | `/predict` | Multipart `file` (`.wav`/`.mp3`). ffmpeg converts to mono 16 kHz and keeps the first `EMOTION_MAX_AUDIO_SECONDS` (default 30). Returns `{emotion, confidence, raw_result: {labels, scores}}` (labels stripped of the Chinese prefix). Inference is serialized by a lock. 400 on decode failure. |
| POST | `/predict_text` | JSON `{text}`. Empty text → `{"emotion": "neutral", "confidence": 0.2}`. Returns the top label with `confidence` and the full `raw_result` list. 503 if the text model is not loaded. |
| GET | `/health` | `{status, audio_model_loaded, text_model_loaded}` |

## Backend use

- `/predict` is called once per interaction on the whole file by `full_client` (`backend/app/api/routes/full/service.py`, 3 attempts); per-segment `/predict` calls happen only in `POST /api/v1/emotion/process` (after VAD splitting).
- `/predict_text` is called by `infer_text_emotion_with_provider` when `TEXT_EMOTION_PROVIDER=hf_transformers`; any failure switches the backend process to the rule-based provider.
- Label normalization and fusion: [EMOTION_FUSION.md](../architecture/EMOTION_FUSION.md).
