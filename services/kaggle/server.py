"""VocalMind Kaggle GPU inference server.

Implements the API contract in README.md. Importing this module has no side
effects: heavy libraries are imported inside ``load_models()``, and ngrok /
uvicorn only start from ``main()``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger("vocalmind.kaggle")

PORT = 8000
SAMPLE_RATE = 16000
MIN_EMOTION_DURATION_S = 0.8
EMBED_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
TEXT_EMOTION_MODEL = "j-hartmann/emotion-english-distilroberta-base"
MODEL_NAMES = ("whisper", "diarization", "emotion", "vad", "text_emotion", "embedder", "reranker", "docling")

# Mirrors backend/app/core/emotion_fusion.py TEXT_LABEL_NORMALIZATION so callers
# receive VocalMind's vocabulary (happy/angry/frustrated/sad/neutral).
TEXT_LABEL_NORMALIZATION = {
    "joy": "happy",
    "happiness": "happy",
    "anger": "angry",
    "fear": "frustrated",
    "surprise": "neutral",
    "neutral": "neutral",
    "sadness": "sad",
    "sad": "sad",
    "disgust": "frustrated",
    "annoyance": "frustrated",
}

models: dict[str, Any] = {}
device = "cpu"
gpu_lock = asyncio.Lock()
app = FastAPI(title="VocalMind Kaggle GPU server")


# ── Config ───────────────────────────────────────────────────────────────────


def get_secret(name: str) -> str:
    """Kaggle Secret first, then environment variable. Never hard-code secrets."""
    try:
        from kaggle_secrets import UserSecretsClient

        value = UserSecretsClient().get_secret(name)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(name, "")


# ── Model loading ────────────────────────────────────────────────────────────


def load_models() -> None:
    """Load every model; a failure leaves that model out (endpoint returns 503)."""
    global device
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    hf_token = get_secret("HF_TOKEN")

    def whisper_model():
        import whisper

        return whisper.load_model("medium", device=device)

    def diarization():
        from pyannote.audio import Pipeline

        name = "pyannote/speaker-diarization-3.1"
        try:  # pyannote.audio 4.x
            pipe = Pipeline.from_pretrained(name, token=hf_token)
        except TypeError:  # pyannote.audio 3.x
            pipe = Pipeline.from_pretrained(name, use_auth_token=hf_token)
        return pipe.to(torch.device(device))

    def emotion():
        from funasr import AutoModel

        # CPU keeps the GPU free for whisper/pyannote; emotion2vec base is fast enough.
        return AutoModel(model="iic/emotion2vec_plus_base", hub="ms", disable_update=True, device="cpu")

    def vad():
        model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
        return model, utils[0]  # (model, get_speech_timestamps)

    def text_emotion():
        from transformers import pipeline

        return pipeline("text-classification", model=TEXT_EMOTION_MODEL, top_k=None, device=0 if device == "cuda" else -1)

    def embedder():
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(EMBED_MODEL, device=device)

    def reranker():
        from sentence_transformers import CrossEncoder

        return CrossEncoder(RERANK_MODEL, device=device)

    def docling():
        from docling.document_converter import DocumentConverter

        return DocumentConverter()  # same default options as services/rag/ingest.py

    loaders = {
        "whisper": whisper_model, "diarization": diarization, "emotion": emotion, "vad": vad,
        "text_emotion": text_emotion, "embedder": embedder, "reranker": reranker, "docling": docling,
    }
    for name, loader in loaders.items():
        try:
            logger.info("Loading %s on %s...", name, device)
            models[name] = loader()
        except Exception:
            logger.exception("Failed to load %s", name)


def _model(name: str) -> Any:
    if name not in models:
        raise HTTPException(status_code=503, detail=f"Model '{name}' is not loaded")
    return models[name]


# ── Audio helpers ────────────────────────────────────────────────────────────


def _ffmpeg_to_wav(src: str, dst: str, start: float | None = None, duration: float | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}"]
    cmd += ["-i", src, "-ac", "1", "-ar", str(SAMPLE_RATE), dst]
    subprocess.run(cmd, check=True, capture_output=True)


def _read_mono_16k(path: str):
    """Decode any audio to a float32 mono 16 kHz numpy array via ffmpeg."""
    import soundfile as sf

    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "audio.wav")
        _ffmpeg_to_wav(path, wav)
        audio, _ = sf.read(wav, dtype="float32")
    return audio


def _emotion_window(start: float, end: float) -> tuple[float, float]:
    """(start, duration) for an emotion clip, padded around its centre to MIN_EMOTION_DURATION_S."""
    start, end = sorted((max(0.0, start), max(0.0, end)))
    if end - start >= MIN_EMOTION_DURATION_S:
        return start, end - start
    window_start = max(0.0, (start + end) / 2 - MIN_EMOTION_DURATION_S / 2)
    return window_start, MIN_EMOTION_DURATION_S


def _assign_speakers(segments: list[dict], turns: list[dict]) -> list[dict]:
    """Label each transcript segment with the diarization turn covering its midpoint."""
    for seg in segments:
        mid = (seg["start"] + seg["end"]) / 2
        seg["speaker"] = next((t["speaker"] for t in turns if t["start"] <= mid <= t["end"]), "UNKNOWN")
    return segments


# ── Inference (sync; always called under gpu_lock) ──────────────────────────


def _transcribe(path: str) -> dict:
    result = _model("whisper").transcribe(path, language="en", fp16=device == "cuda")
    return {
        "text": result["text"].strip(),
        "language": result.get("language", "en"),
        "segments": [
            {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
            for s in result["segments"]
        ],
    }


def _emotion(path: str) -> dict:
    res = _model("emotion").generate(path, output_dir=None, granularity="utterance", extract_embedding=False)
    if not res or not res[0].get("labels"):
        return {"top_emotion": "unknown", "emotions": []}
    emotions = sorted(
        ({"label": label.split("/")[-1], "score": round(float(score), 4)} for label, score in zip(res[0]["labels"], res[0]["scores"])),
        key=lambda e: e["score"],
        reverse=True,
    )
    return {"top_emotion": emotions[0]["label"], "emotions": emotions}


def _diarize(path: str) -> dict:
    import torch

    waveform = torch.from_numpy(_read_mono_16k(path)).unsqueeze(0)
    output = _model("diarization")({"waveform": waveform, "sample_rate": SAMPLE_RATE}, min_speakers=1)
    annotation = getattr(output, "speaker_diarization", output)  # pyannote 4 wraps the Annotation
    return {
        "segments": [
            {"start": round(turn.start, 2), "end": round(turn.end, 2), "speaker": speaker}
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]
    }


def _vad(path: str) -> dict:
    import torch

    model, get_speech_timestamps = _model("vad")
    audio = torch.from_numpy(_read_mono_16k(path))
    stamps = get_speech_timestamps(audio, model, sampling_rate=SAMPLE_RATE, return_seconds=True)
    return {"speech_segments": [{"start": s["start"], "end": s["end"]} for s in stamps]}


def _full(path: str) -> dict:
    asr = _transcribe(path)
    segments = _assign_speakers(asr["segments"], _diarize(path)["segments"])
    with tempfile.TemporaryDirectory() as tmp:
        for i, seg in enumerate(segments):
            clip = os.path.join(tmp, f"seg_{i}.wav")
            try:
                _ffmpeg_to_wav(path, clip, *_emotion_window(seg["start"], seg["end"]))
                emo = _emotion(clip)
            except Exception:
                logger.exception("Segment %d emotion failed", i)
                emo = {"top_emotion": "unknown", "emotions": []}
            seg["emotion"], seg["emotion_scores"] = emo["top_emotion"], emo["emotions"]
    return {**asr, "segments": segments, **_emotion(path)}


def _text_result(scores: list[dict]) -> dict:
    totals: dict[str, float] = {}
    for item in scores:
        raw = str(item["label"]).strip().lower()
        label = TEXT_LABEL_NORMALIZATION.get(raw, raw)
        totals[label] = totals.get(label, 0.0) + float(item["score"])
    if not totals:
        return {"emotion": "neutral", "confidence": 0.3}
    top = max(totals, key=totals.get)
    return {"emotion": top, "confidence": round(totals[top], 4)}


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _locked(fn, *args):
    async with gpu_lock:
        return await asyncio.to_thread(fn, *args)


async def _run_with_lock(fn, file: UploadFile) -> dict:
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        return await _locked(fn, tmp.name)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("%s failed", fn.__name__)
        raise HTTPException(status_code=500, detail=f"{fn.__name__.strip('_')} failed: {exc}") from exc
    finally:
        os.unlink(tmp.name)


class TextRequest(BaseModel):
    text: str | None = None
    texts: list[str] | None = None


class EmbedRequest(BaseModel):
    texts: list[str]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]


@app.get("/health")
async def health():
    return {"status": "ok", "models": {name: name in models for name in MODEL_NAMES}}


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    return await _run_with_lock(_transcribe, file)


@app.post("/emotion")
async def emotion(file: UploadFile = File(...)):
    return await _run_with_lock(_emotion, file)


@app.post("/diarize")
async def diarize(file: UploadFile = File(...)):
    return await _run_with_lock(_diarize, file)


@app.post("/vad")
async def vad(file: UploadFile = File(...)):
    return await _run_with_lock(_vad, file)


@app.post("/full")
async def full(file: UploadFile = File(...)):
    return await _run_with_lock(_full, file)


@app.post("/parse")
async def parse(file: UploadFile = File(...)):
    def _parse(path: str) -> dict:
        return {"markdown": _model("docling").convert(path).document.export_to_markdown()}

    return await _run_with_lock(_parse, file)


@app.post("/predict_text")
async def predict_text(request: TextRequest):
    texts = request.texts if request.texts is not None else [request.text or ""]
    classifier = _model("text_emotion")
    non_empty = [t for t in texts if t and t.strip()]
    raw = await _locked(lambda: classifier(non_empty, truncation=True)) if non_empty else []
    by_text = dict(zip(non_empty, raw))
    results = [_text_result(by_text[t]) if t in by_text else {"emotion": "neutral", "confidence": 0.2} for t in texts]
    return {"results": results} if request.texts is not None else results[0]


@app.post("/embed")
async def embed(request: EmbedRequest):
    embedder = _model("embedder")
    # Qdrant collections use cosine distance and Ollama's /api/embed returns
    # unit vectors, so normalize; no query prefix, matching the Ollama path.
    vectors = await _locked(lambda: embedder.encode(request.texts, normalize_embeddings=True, batch_size=32))
    return {
        "embeddings": [[float(x) for x in v] for v in vectors],
        "model": EMBED_MODEL,
        "dimension": embedder.get_sentence_embedding_dimension(),
    }


@app.post("/rerank")
async def rerank(request: RerankRequest):
    reranker = _model("reranker")
    if not request.documents:
        return {"scores": []}
    # Same call as services/rag/reranker.py so scores share its scale.
    scores = await _locked(lambda: reranker.predict([(request.query, d) for d in request.documents]))
    return {"scores": [float(s) for s in scores]}


# ── Startup ──────────────────────────────────────────────────────────────────


def _register_with_backend(public_url: str, server) -> None:
    backend_url = get_secret("BACKEND_URL")
    if not backend_url:
        logger.warning("BACKEND_URL not set; register %s with the backend manually", public_url)
        return
    while not server.started:
        time.sleep(1)
    try:
        import requests

        resp = requests.post(
            backend_url, json={"kaggle_url": public_url}, headers={"ngrok-skip-browser-warning": "true"}, timeout=30
        )
        logger.info("Registered with backend: %s %s", resp.status_code, resp.text[:200])
    except Exception:
        logger.exception("Failed to register %s with %s", public_url, backend_url)


def main() -> None:
    import uvicorn
    from pyngrok import ngrok

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_models()
    logger.info("Models: %s", {name: name in models for name in MODEL_NAMES})

    ngrok.set_auth_token(get_secret("NGROK_TOKEN"))
    domain = get_secret("NGROK_DOMAIN")
    public_url = ngrok.connect(PORT, **({"domain": domain} if domain else {})).public_url
    logger.info("Public URL: %s", public_url)

    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info"))
    threading.Thread(target=_register_with_backend, args=(public_url, server), daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
