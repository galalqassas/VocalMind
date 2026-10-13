import json
from typing import Any

import httpx

from app.core.config import settings
from app.core.inference_contracts import audio_content_type, normalize_emotion_analysis
from app.core.kaggle_client import BaseKaggleClient


class EmotionAPIClient(BaseKaggleClient):
    local_endpoint = "/predict"
    remote_endpoint = "/emotion"

    @property
    def local_base_url(self) -> str:
        return settings.EMOTION_API_URL

    def normalize_response(self, data):
        return normalize_emotion_analysis(data)

    async def analyze_segments(
        self,
        audio_bytes: bytes,
        filename: str,
        segments: list[dict[str, Any]],
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Local emotion service: clip-level emotion plus one `segment_emotions` entry per segment."""
        windows = json.dumps([{"start": float(s.get("start") or 0.0), "end": float(s.get("end") or 0.0)} for s in segments])
        async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=10.0)) as client:
            response = await client.post(
                self.url,
                files={"file": (filename, audio_bytes, content_type or audio_content_type(filename))},
                data={"segments": windows},
                headers=self.headers(),
            )
        response.raise_for_status()
        return self.normalize_response(response.json())


emotion_client = EmotionAPIClient()
