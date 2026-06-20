from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.routes.emotion.pipeline import process_audio
from app.api.routes.emotion.service import emotion_client
from app.core.emotion_fusion import fuse_emotion_signals

router = APIRouter()


class AnalyzeRequest(BaseModel):
    file_path: str = Field(..., description="Absolute local path to the audio file to analyze on the server.")


class EmotionFusionRequest(BaseModel):
    text: str = Field(..., description="The spoken text content of the utterance to analyze for textual emotion.")
    acoustic_emotion: str = Field(..., description="The detected acoustic emotion label from speech audio (e.g. angry, joy).")
    acoustic_confidence: float | None = Field(None, description="The confidence score of the acoustic emotion model prediction.")


class EmotionFusionResponse(BaseModel):
    emotion: str = Field(..., description="The final fused emotion label resulting from joint acoustic-text modeling.")
    confidence: float = Field(..., description="The confidence score of the final fused emotion verdict.")
    text_emotion: str = Field(..., description="The individual textual emotion label predicted from the text content.")
    text_confidence: float = Field(..., description="Confidence score for the text-based emotion prediction.")
    acoustic_emotion: str = Field(..., description="The individual acoustic emotion label predicted from the audio speech.")
    acoustic_confidence: float = Field(..., description="Confidence score for the acoustic-based emotion prediction.")
    model: str = Field(..., description="Name/version of the fusion algorithm/model applied.")


@router.post("/analyze-local", summary="Local-file Emotion Analysis (Kaggle/Server)", responses={400: {"description": "Unsupported audio format"}, 422: {"description": "Invalid local file path"}})
async def analyze_local_emotion(request: AnalyzeRequest):
    """
    Analyze one audio file from a local path and return the dominant emotion.
    """
    if not (request.file_path.endswith(".wav") or request.file_path.endswith(".mp3")):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await emotion_client.analyze_local_file(request.file_path)


@router.post("/analyze", summary="Single-file Emotion Analysis (Upload)", responses={400: {"description": "Unsupported audio format"}, 422: {"description": "Invalid file upload payload"}})
async def analyze_emotion(file: UploadFile = File(..., description="The audio file to run emotion analysis on.")):
    """
    Upload an audio file (WAV/MP3) and return the dominant emotion.
    """
    if not (file.filename.endswith(".wav") or file.filename.endswith(".mp3")):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")
    return await emotion_client.analyze_audio(file)


@router.post("/fuse", response_model=EmotionFusionResponse, summary="Fuse Text and Acoustic Emotion", responses={422: {"description": "Invalid request parameters"}})
async def fuse_emotion(payload: EmotionFusionRequest):
    """
    Apply dual-emotion fusion logic to combine text and acoustic emotion signals.
    """
    fused = fuse_emotion_signals(
        text=payload.text,
        acoustic_emotion=payload.acoustic_emotion,
        acoustic_confidence=payload.acoustic_confidence,
    )
    return EmotionFusionResponse(
        emotion=fused.emotion,
        confidence=fused.confidence,
        text_emotion=fused.text_emotion,
        text_confidence=fused.text_confidence,
        acoustic_emotion=fused.acoustic_emotion,
        acoustic_confidence=fused.acoustic_confidence,
        model=fused.model,
    )


@router.post("/process", summary="Full Audio Processing Pipeline", responses={400: {"description": "Unsupported audio format"}, 422: {"description": "Invalid interaction ID or file parameters"}})
async def process_emotion(
    file: UploadFile = File(..., description="The call recording audio file to process."),
    interaction_id: UUID = Query(..., description="The unique parent interaction UUID."),
):
    """
    Run full speech processing pipeline: VAD split -> transcribe -> segment emotion -> return utterances list.
    """
    if not (file.filename.endswith(".wav") or file.filename.endswith(".mp3")):
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are supported.")

    audio_bytes = await file.read()

    utterances = await process_audio(audio_bytes, file.filename, interaction_id)

    return {
        "interaction_id": str(interaction_id),
        "total_segments": len(utterances),
        "utterances": utterances,
    }
