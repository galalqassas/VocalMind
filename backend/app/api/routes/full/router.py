from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.routes.full.service import full_client
from app.core.inference_contracts import is_supported_audio_filename

router = APIRouter()


class AnalyzeLocalRequest(BaseModel):
    file_path: str = Field(..., description="Absolute local filesystem path to the audio file to analyze.")


@router.post("/analyze", summary="Full Audio Analysis (Upload)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid file upload payload"}})
async def analyze_full(file: UploadFile = File(..., description="The audio file to perform full pipeline analysis (VAD + ASR + Emotion) on.")):
    """
    Upload an audio file (WAV/MP3) and run the unified speech processing pipeline.
    This includes VAD splitting, WhisperX transcription/diarization, and FunASR emotion detection.
    """
    if not is_supported_audio_filename(file.filename):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await full_client.analyze_audio(file)


@router.post("/analyze-local", summary="Full Audio Analysis (Local File)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid JSON request body"}})
async def analyze_local_full(request: AnalyzeLocalRequest):
    """
    Perform full unified pipeline analysis on a local filesystem audio file.
    """
    if not is_supported_audio_filename(request.file_path):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await full_client.analyze_local_file(request.file_path)
