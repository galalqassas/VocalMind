from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
import uvicorn
import json
import os
import shutil
import tempfile
import subprocess
import numpy as np
import torch
from funasr import AutoModel
from transformers import pipeline
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
import asyncio
import logging
from fastapi import Request

# Global dictionary to hold the loaded model
ml_models = {}
inference_lock = asyncio.Lock()
MAX_INFERENCE_SECONDS = int(os.getenv("EMOTION_MAX_AUDIO_SECONDS", "30"))
SAMPLE_RATE = 16000
MIN_SEGMENT_WINDOW_SECONDS = 0.8
logger = logging.getLogger(__name__)

class TextPredictRequest(BaseModel):
    text: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check if CUDA is available
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Using device: {device}")

    # Initialize the audio model
    logger.info("Loading model iic/emotion2vec_plus_base inside worker...")
    # SECURITY NOTE: trust_remote_code=True allows arbitrary code execution from the
    # model repository. This is intentional for this model but means the security
    # posture of this service depends on the integrity of the upstream HF repo.
    # Model should be pinned to a specific commit hash in production, not a tag.
    # Reviewed and accepted: 2026-06-16 — revisit if model source changes.
    ml_models["emotion2vec"] = AutoModel(model="iic/emotion2vec_plus_base", trust_remote_code=True, disable_update=True, device=device)
    logger.info("Audio model loaded successfully.")

    # Initialize the text model. Failure to load must NOT break the container —
    # /predict_text returns 503 and the backend marks the text-emotion stage failed.
    try:
        logger.info("Loading text emotion model j-hartmann/emotion-english-distilroberta-base...")
        hf_device = 0 if device == "cuda" else -1
        ml_models["text_emotion"] = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            device=hf_device,
            top_k=None,
        )
        logger.info("Text emotion model loaded successfully.")
    except Exception as exc:
        logger.warning(f"WARNING: text emotion model failed to load: {exc}. /predict_text will return 503.")

    yield
    # Clean up the ML models and release the resources
    ml_models.clear()

app = FastAPI(title="Emotion Recognition API", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        logger.info("[request_id=%s] Emotion request %s %s", request_id, request.method, request.url.path)
    response = await call_next(request)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def _run_inference(audio_input):
    return ml_models["emotion2vec"].generate(input=audio_input, extract_embedding=False)


def _parse_result(res: dict) -> dict:
    labels = [lbl.split('/')[-1] if '/' in lbl else lbl for lbl in res['labels']]
    scores = [float(s) for s in res['scores']]
    best = int(np.argmax(scores))
    return {"emotion": labels[best], "confidence": scores[best], "labels": labels, "scores": scores}


def segment_windows(segments: list[dict], total_samples: int, sr: int = SAMPLE_RATE) -> list[tuple[int, int]]:
    """Sample ranges per segment: centered window of at least MIN_SEGMENT_WINDOW_SECONDS, capped at MAX_INFERENCE_SECONDS."""
    total = total_samples / sr
    windows = []
    for seg in segments:
        start, end = float(seg["start"]), float(seg["end"])
        duration = min(max(end - start, MIN_SEGMENT_WINDOW_SECONDS), MAX_INFERENCE_SECONDS, total)
        lo = max(0.0, min((start + end) / 2 - duration / 2, total - duration))
        windows.append((int(lo * sr), int(min(total, lo + duration) * sr)))
    return windows


def _ffmpeg(args: list[str]) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-y", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout


def _decode_mono_16k(path: str) -> np.ndarray:
    pcm = _ffmpeg(["-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"])
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


@app.post("/predict")
async def predict(file: UploadFile = File(...), segments: str | None = Form(None)):
    """Clip-level emotion; with `segments` (JSON list of {start, end}) also returns `segment_emotions`."""
    filename = (file.filename or "").lower()
    if not (filename.endswith('.wav') or filename.endswith('.mp3')):
        raise HTTPException(status_code=400, detail="Only .wav or .mp3 files are supported.")
    try:
        segment_list = json.loads(segments) if segments else []
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid segments JSON: {e}")

    suffix = '.wav' if filename.endswith('.wav') else '.mp3'

    # Save the uploaded file temporarily
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    normalized_wav_path = None
    try:
        with os.fdopen(fd, 'wb') as f:
            shutil.copyfileobj(file.file, f)

        # Normalize all inputs to a bounded mono 16k wav to avoid unstable inference on long/raw files.
        fd_wav, normalized_wav_path = tempfile.mkstemp(suffix='.wav')
        os.close(fd_wav)
        _ffmpeg(["-i", temp_path, "-ac", "1", "-ar", str(SAMPLE_RATE), "-t", str(MAX_INFERENCE_SECONDS), normalized_wav_path])

        # Run inference using the pre-loaded FunaSR model via threadpool
        async with inference_lock:
            results = await run_in_threadpool(_run_inference, normalized_wav_path)
        if not results:
            raise HTTPException(status_code=500, detail="Model inference returned empty results.")
        clip = _parse_result(results[0])

        segment_emotions = []
        if segment_list:
            audio = _decode_mono_16k(temp_path)
            for lo, hi in segment_windows(segment_list, len(audio)):
                if hi <= lo:
                    segment_emotions.append({"emotion": "unknown", "confidence": 0.0, "emotion_scores": []})
                    continue
                async with inference_lock:
                    seg_results = await run_in_threadpool(_run_inference, audio[lo:hi])
                if not seg_results:
                    raise HTTPException(status_code=500, detail="Model inference returned empty segment results.")
                parsed = _parse_result(seg_results[0])
                segment_emotions.append({
                    "emotion": parsed["emotion"],
                    "confidence": parsed["confidence"],
                    "emotion_scores": [{"label": lbl, "score": sc} for lbl, sc in zip(parsed["labels"], parsed["scores"])],
                })

        response = {
            "emotion": clip["emotion"],
            "confidence": clip["confidence"],
            "raw_result": {"labels": clip["labels"], "scores": clip["scores"]},
        }
        if segment_list:
            response["segment_emotions"] = segment_emotions
        return response

    except HTTPException:
        raise
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="ignore")
        raise HTTPException(status_code=400, detail=f"Failed to decode/convert audio: {stderr[:400]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing audio: {str(e)}")
    finally:
        # Clean up the temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if normalized_wav_path and os.path.exists(normalized_wav_path):
            os.remove(normalized_wav_path)

@app.get("/health")
async def health():
    return {
        "status": "ok", 
        "audio_model_loaded": "emotion2vec" in ml_models,
        "text_model_loaded": "text_emotion" in ml_models
    }

@app.post("/predict_text")
async def predict_text(request: TextPredictRequest):
    if not request.text or not request.text.strip():
        return {"emotion": "neutral", "confidence": 0.2}

    if "text_emotion" not in ml_models:
        raise HTTPException(
            status_code=503,
            detail="Text emotion model unavailable.",
        )

    try:
        # Run inference using the pre-loaded HF pipeline
        raw_result = ml_models["text_emotion"](request.text)
        
        # top_k=None returns [[{'label', 'score'}, ...]] or a flat list depending on the transformers version.
        scores = raw_result[0] if raw_result and isinstance(raw_result[0], list) else raw_result
        
        if not scores:
            raise HTTPException(status_code=500, detail="Text emotion model returned empty results.")

        # Get the top score
        top_emotion = max(scores, key=lambda x: x["score"])
        
        return {
            "emotion": top_emotion["label"],
            "confidence": float(top_emotion["score"]),
            "raw_result": scores
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text emotion inference failed: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
