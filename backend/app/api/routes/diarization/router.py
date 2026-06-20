from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.routes.diarization.service import diarization_client

router = APIRouter()


class AnalyzeLocalRequest(BaseModel):
    file_path: str = Field(..., description="Absolute local filesystem path to the audio file to analyze.")


@router.post("/analyze", summary="Speaker Diarization (Upload)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid file upload payload"}})
async def analyze_diarization(file: UploadFile = File(..., description="The audio file to split using Speaker Diarization.")):
    """
    Upload an audio file (WAV/MP3) and run pyannote speaker diarization to discover who spoke when.
    """
    if not (file.filename.endswith(".wav") or file.filename.endswith(".mp3")):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await diarization_client.analyze_audio(file)


@router.post("/analyze-local", summary="Speaker Diarization (Local File)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid JSON request body"}})
async def analyze_local_diarization(request: AnalyzeLocalRequest):
    """
    Analyze a local audio file on the backend filesystem and return speaker-timestamped segments.
    """
    return await diarization_client.analyze_local_file(request.file_path)
