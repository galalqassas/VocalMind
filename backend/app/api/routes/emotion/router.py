from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.routes.emotion.pipeline import process_audio

router = APIRouter()


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
