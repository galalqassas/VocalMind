from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.routes.transcription.service import transcription_client
from app.core.inference_contracts import is_supported_audio_filename

router = APIRouter()


class AnalyzeLocalRequest(BaseModel):
    file_path: str = Field(..., description="Absolute local filesystem path to the audio file to analyze.")


@router.post("/analyze", summary="Speech Transcription (Upload)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid file upload payload"}})
async def analyze_transcription(file: UploadFile = File(..., description="The audio file to transcribe.")):
    """
    Upload an audio file (WAV/MP3) and run WhisperX transcription and alignment.
    """
    if not is_supported_audio_filename(file.filename):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await transcription_client.analyze_audio(file)


@router.post("/analyze-local", summary="Speech Transcription (Local File)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid JSON request body"}})
async def analyze_local_transcription(request: AnalyzeLocalRequest):
    """
    Perform Speech Transcription on a local filesystem audio file.
    """
    if not is_supported_audio_filename(request.file_path):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await transcription_client.analyze_local_file(request.file_path)
