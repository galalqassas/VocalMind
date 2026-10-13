# Emotion Service

`services/emotion/app.py` — FastAPI. Compose service `emotion` in profile `local-ml` (`make up-local`), host port 8001 → container 8000; the backend uses it only when `IS_LOCAL=true`, via `EMOTION_API_URL` (`http://emotion:8000` in compose). With `IS_LOCAL=false` (default) the same models run on the Kaggle server ([services/kaggle/README.md](../../services/kaggle/README.md)). CUDA when available, else CPU (GPU overlay: `docker-compose.gpu.yml`).

## Models (loaded at startup)

- Audio: FunASR `AutoModel("iic/emotion2vec_plus_base", trust_remote_code=True)`.
- Text: Hugging Face `pipeline("text-classification", "j-hartmann/emotion-english-distilroberta-base", top_k=None)`. If it fails to load, the service still starts and `/predict_text` returns 503.

## Endpoints

| Method | Path | Behaviour |
|---|---|---|
| POST | `/predict` | Multipart `file` (`.wav`/`.mp3`), optional form field `segments` (JSON list of `{start, end}`). Clip level: ffmpeg converts to mono 16 kHz and keeps the first `EMOTION_MAX_AUDIO_SECONDS` (default 30); returns `{emotion, confidence, raw_result: {labels, scores}}` (labels stripped of the Chinese prefix). With `segments`, also returns `segment_emotions`: one `{emotion, confidence, emotion_scores}` per segment, inferred on a window centred on the segment (at least 0.8 s, at most `EMOTION_MAX_AUDIO_SECONDS`; `segment_windows`). Inference is serialized by a lock. 400 on decode failure, 422 on bad `segments` JSON. |
| POST | `/predict_text` | JSON `{text}`. Empty text → `{"emotion": "neutral", "confidence": 0.2}`. Returns the top label with `confidence` and the full `raw_result` list. 503 if the text model is not loaded. |
| GET | `/health` | `{status, audio_model_loaded, text_model_loaded}` |

## Backend use (`IS_LOCAL=true`)

- `/predict` with `segments` is called once per interaction by `full_client` (`backend/app/api/routes/full/service.py` → `emotion_client.analyze_segments`), using the WhisperX segments; this gives each utterance its acoustic emotion. Per-clip `/predict` calls also happen in `POST /api/v1/emotion/process` (after VAD splitting).
- `/predict_text` is called by `infer_text_emotion_with_provider` (`backend/app/core/emotion_fusion.py`). Any failure raises `TextEmotionUnavailable`; there is no fallback.
- Label normalization and fusion: [EMOTION_FUSION.md](../architecture/EMOTION_FUSION.md).

Tests: `services/emotion/tests/test_segment_windows.py`.
