# Kaggle GPU server

Runs every heavy model for VocalMind on a free Kaggle GPU so the local stack stays small. The backend reaches it at `KAGGLE_SERVER_URL` when `IS_LOCAL=false`, and RAG uses it when `RAG_MODELS_HOST=kaggle`. Every request sends the header `ngrok-skip-browser-warning: true`.

## API contract

| Method & path | Request | Response |
|---|---|---|
| `GET /health` | — | `{"status": "ok", "models": {name: bool}}` |
| `POST /transcribe` | multipart `file` | `{"text", "language", "segments": [{"start", "end", "text"}]}` |
| `POST /emotion` | multipart `file` | `{"top_emotion", "emotions": [{"label", "score"}]}` (whole clip) |
| `POST /diarize` | multipart `file` | `{"segments": [{"start", "end", "speaker"}]}` |
| `POST /vad` | multipart `file` | `{"speech_segments": [{"start", "end"}]}` |
| `POST /full` | multipart `file` | `{"text", "language", "top_emotion", "emotions", "segments": [{"start", "end", "text", "speaker", "emotion", "emotion_scores": [{"label", "score"}]}]}` |
| `POST /predict_text` | JSON `{"text"}` or `{"texts": [...]}` | `{"emotion", "confidence"}` or `{"results": [{"emotion", "confidence"}]}` |
| `POST /embed` | JSON `{"texts": [...]}` | `{"embeddings": [[float]], "model", "dimension": 1024}` |
| `POST /rerank` | JSON `{"query", "documents": [...]}` | `{"scores": [float]}` (same order as `documents`) |
| `POST /parse` | multipart `file` (PDF) | `{"markdown"}` |

| Endpoint | Model |
|---|---|
| ASR | openai-whisper `medium` |
| Diarization | `pyannote/speaker-diarization-3.1` |
| Speech emotion | `iic/emotion2vec_plus_base` (per segment in `/full`) |
| VAD | Silero |
| Text emotion | `j-hartmann/emotion-english-distilroberta-base` |
| Embeddings | `Snowflake/snowflake-arctic-embed-l-v2.0` (same 1024-dim family as Ollama `snowflake-arctic-embed2`) |
| Rerank | `BAAI/bge-reranker-v2-m3` |
| Parse | Docling |

Switching `RAG_MODELS_HOST` changes the embedding model, so re-ingest the docs afterwards with `python main.py --ingest --force` in `services/rag`.

## Run on Kaggle

1. Import `services/kaggle/vocalmind_gpu.ipynb` into Kaggle. Settings: **Accelerator = GPU**, **Internet = on**.
2. Add-ons → Secrets, attach: `HF_TOKEN` (accepted terms for `pyannote/speaker-diarization-3.1` + `pyannote/segmentation-3.0`), `NGROK_TOKEN`, `NGROK_DOMAIN` (static ngrok domain), `BACKEND_URL` (backend public URL + `/api/v1/internal/set-kaggle-url`).
3. Run all. Cell 1 clones the repo (`BRANCH`, default `main`) and installs `requirements.txt` with numpy/torch pinned to Kaggle's preinstalled versions, so no kernel restart is needed. Cell 2 starts `server.py`, which loads all models, opens the ngrok tunnel and POSTs `{"kaggle_url"}` to `BACKEND_URL` (switching the backend to `IS_LOCAL=false`).
4. The last cell blocks while serving; interrupt it to stop. Re-running is safe: the clone is replaced and the same static domain is re-registered. With no `BACKEND_URL`, set `KAGGLE_SERVER_URL` on the backend yourself.

Tests (models mocked): `cd backend && uv run pytest ../services/kaggle/test_server.py`.
