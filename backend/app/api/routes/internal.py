import logging
from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class KaggleUrlRequest(BaseModel):
    url: str | None = Field(None, description="The remote Kaggle API gateway server URL.")
    kaggle_url: str | None = Field(None, description="Alternative field for the remote Kaggle API gateway server URL.")


@router.post("/set-kaggle-url", responses={400: {"description": "Provide 'url' or 'kaggle_url'."}})
def set_kaggle_url(payload: KaggleUrlRequest):
    """
    Set the active Kaggle inference server URL.
    This dynamically updates settings and switches IS_LOCAL to False so inference is routed to the remote Kaggle server.
    """
    resolved_url = payload.url or payload.kaggle_url
    if not resolved_url:
        return {"status": "error", "detail": "Provide 'url' or 'kaggle_url'."}

    settings.KAGGLE_SERVER_URL = resolved_url
    settings.KAGGLE_NGROK_URL = resolved_url
    settings.IS_LOCAL = False
    logger.info("Kaggle URL set to %s — IS_LOCAL is now False", resolved_url)
    return {"status": "success", "url": resolved_url}
