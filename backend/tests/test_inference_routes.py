from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


@patch("app.api.routes.vad.router.vad_client.analyze_audio", new_callable=AsyncMock)
def test_vad_analyze_success(mock_analyze, client: TestClient):
    mock_analyze.return_value = {"speech_segments": [{"start": 0.0, "end": 1.0}]}
    response = client.post(
        "/api/v1/vad/analyze",
        files={"file": ("sample.wav", b"fake audio", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["speech_segments"][0]["end"] == 1.0


@patch("app.api.routes.vad.router.vad_client.analyze_local_file", new_callable=AsyncMock)
def test_vad_analyze_local_success(mock_analyze, client: TestClient):
    mock_analyze.return_value = {"speech_segments": [{"start": 0.0, "end": 1.0}]}
    response = client.post("/api/v1/vad/analyze-local", json={"file_path": "sample.wav"})
    assert response.status_code == 200
    assert response.json()["speech_segments"][0]["start"] == 0.0


def test_vad_analyze_rejects_invalid_extension(client: TestClient):
    response = client.post("/api/v1/vad/analyze", files={"file": ("notes.txt", b"nope", "text/plain")})
    assert response.status_code == 400
