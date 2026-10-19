"""
Unit tests for the Emotion Analysis endpoints.

Covers /process (success, invalid extension).
"""

from uuid import uuid4
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


# ── /process ─────────────────────────────────────────────────────────────────

@patch("app.api.routes.emotion.router.process_audio", new_callable=AsyncMock)
def test_process_endpoint_success(mock_pipeline, client: TestClient):
    interaction_id = uuid4()
    mock_pipeline.return_value = [
        {"emotion": "angry", "start_time_seconds": 0.0, "end_time_seconds": 2.0},
    ]
    response = client.post(
        f"/api/v1/emotion/process?interaction_id={interaction_id}",
        files={"file": ("call.wav", b"audio-bytes", "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_segments"] == 1
    assert data["interaction_id"] == str(interaction_id)


def test_process_invalid_extension(client: TestClient):
    interaction_id = uuid4()
    response = client.post(
        f"/api/v1/emotion/process?interaction_id={interaction_id}",
        files={"file": ("notes.pdf", b"not audio", "application/pdf")},
    )
    assert response.status_code == 400
    assert "Only .wav and .mp3 files are supported" in response.json()["detail"]
