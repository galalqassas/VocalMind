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
