from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.routes.vad.service import vad_client
from app.core.inference_contracts import is_supported_audio_filename

router = APIRouter()


class AnalyzeLocalRequest(BaseModel):
    file_path: str = Field(..., description="Absolute local filesystem path to the audio file to analyze.")


@router.post("/analyze", summary="Voice Activity Detection (Upload)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid file upload payload"}})
async def analyze_vad(file: UploadFile = File(..., description="The audio file to split using Voice Activity Detection.")):
    """
    Upload an audio file (WAV/MP3) and split it into voice activity segments.
    """
    if not is_supported_audio_filename(file.filename):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await vad_client.analyze_audio(file)


@router.post("/analyze-local", summary="Voice Activity Detection (Local File)", responses={400: {"description": "Unsupported audio format or file type"}, 422: {"description": "Invalid JSON request body"}})
async def analyze_local_vad(request: AnalyzeLocalRequest):
    """
    Perform Voice Activity Detection on a local filesystem audio file.
    """
    if not is_supported_audio_filename(request.file_path):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await vad_client.analyze_local_file(request.file_path)
