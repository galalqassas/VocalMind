import logging
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class KaggleUrlRequest(BaseModel):
    url: str | None = None
    kaggle_url: str | None = None


@router.post("/set-kaggle-url")
def set_kaggle_url(payload: KaggleUrlRequest):
    resolved_url = payload.url or payload.kaggle_url
    if not resolved_url:
        return {"status": "error", "detail": "Provide 'url' or 'kaggle_url'."}

    settings.KAGGLE_NGROK_URL = resolved_url
    settings.IS_LOCAL = False
    logger.info("Kaggle URL set to %s — IS_LOCAL is now False", resolved_url)
    return {"status": "success", "url": resolved_url}
