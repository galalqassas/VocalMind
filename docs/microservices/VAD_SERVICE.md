# VAD Service

`services/vad/app.py` — FastAPI wrapper around Silero VAD with pydub slicing. Compose service `vad`, port 8002 (host and container); backend uses `VAD_API_URL`.

The model is loaded lazily via `torch.hub.load("snakers4/silero-vad", "silero_vad")` on the first `/split` request (cached in the `vad_torch_cache` volume), so startup and `/health` do not need network access.

## Endpoints

| Method | Path | Behaviour |
|---|---|---|
| POST | `/split` | Multipart `file`, `.wav` only (400 otherwise). Reads at 16 kHz, runs `get_speech_timestamps`, and returns `{total_segments, segments: [{index, start_time, end_time, audio_base64}]}` (each clip is a WAV). No speech → empty list. 503 if the model cannot load. |
| GET | `/health` | `{status, model_loaded}` |

## Backend use

The main processing worker does not call VAD. It is used by:

- `POST /api/v1/vad/analyze` and `POST /api/v1/vad/analyze-local` (proxies, `backend/app/api/routes/vad/`; no auth dependency).
- `POST /api/v1/emotion/process` in local mode (`backend/app/api/routes/emotion/pipeline.py`): split with VAD, then call Emotion `/predict` per clip. A VAD connection error returns 503, a non-200 response 502.
