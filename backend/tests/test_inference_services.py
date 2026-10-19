from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.full.service import FullAPIClient
from app.api.routes.transcription.service import TranscriptionAPIClient
from app.api.routes.vad.service import VADAPIClient


@pytest.mark.asyncio
async def test_transcription_service_normalizes_segments_without_top_level_text():
    with patch("app.api.routes.transcription.service.settings") as service_settings, patch(
        "app.core.kaggle_client.settings"
    ) as client_settings:
        service_settings.WHISPERX_API_URL = "http://whisperx:8000"
        client_settings.IS_LOCAL = True
        api = TranscriptionAPIClient()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello"},
                {"start": 1.0, "end": 2.0, "text": "world"},
            ],
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
            result = await api.analyze_bytes(b"audio", "clip.wav")

    assert result["text"] == "hello world"
    assert result["segments"][1]["text"] == "world"


@pytest.mark.asyncio
async def test_transcription_service_preserves_speaker_metadata():
    with patch("app.api.routes.transcription.service.settings") as service_settings, patch(
        "app.core.kaggle_client.settings"
    ) as client_settings:
        service_settings.WHISPERX_API_URL = "http://whisperx:8000"
        client_settings.IS_LOCAL = True
        api = TranscriptionAPIClient()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "language": "en",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello",
                    "speaker": "SPEAKER_00",
                    "speaker_meta": {"source": "diarization", "confidence": 1.0},
                }
            ],
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
            result = await api.analyze_bytes(b"audio", "clip.wav")

    assert result["segments"][0]["speaker_meta"]["source"] == "diarization"


@pytest.mark.asyncio
async def test_vad_service_normalizes_local_split_payload():
    with patch("app.api.routes.vad.service.settings") as service_settings, patch(
        "app.core.kaggle_client.settings"
    ) as client_settings:
        service_settings.VAD_API_URL = "http://vad:8002"
        client_settings.IS_LOCAL = True
        api = VADAPIClient()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "segments": [{"index": 0, "start_time": 0.0, "end_time": 1.25, "audio_base64": "abc"}]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
            result = await api.analyze_bytes(b"audio", "clip.wav")

    assert result == {"speech_segments": [{"start": 0.0, "end": 1.25}]}


_TRANSCRIPTION = {
    "text": "Hello, how can I help? I was charged twice.",
    "language": "en",
    "segments": [
        {"start": 0.0, "end": 1.5, "text": "Hello, how can I help?", "speaker": "SPEAKER_00"},
        {"start": 1.6, "end": 3.0, "text": "I was charged twice.", "speaker": "SPEAKER_01"},
    ],
}


def _local_full_settings():
    return patch.multiple("app.core.kaggle_client.settings", IS_LOCAL=True), patch.multiple(
        "app.api.routes.full.service.settings", IS_LOCAL=True, WHISPERX_API_URL="http://whisperx:8000"
    )


@pytest.mark.asyncio
async def test_full_service_local_passes_transcription_segments_to_emotion_service():
    client_patch, service_patch = _local_full_settings()
    with client_patch, service_patch, patch(
        "app.api.routes.full.service.transcription_client.analyze_bytes",
        new_callable=AsyncMock,
        return_value=_TRANSCRIPTION,
    ), patch(
        "app.api.routes.full.service.emotion_client.analyze_segments",
        new_callable=AsyncMock,
        return_value={
            "top_emotion": "neutral",
            "top_score": 0.9,
            "emotions": [{"label": "neutral", "score": 0.9}],
            "segment_emotions": [
                {"emotion": "neutral", "confidence": 0.8, "emotion_scores": [{"label": "neutral", "score": 0.8}]},
                {"emotion": "angry", "confidence": 0.7, "emotion_scores": [{"label": "angry", "score": 0.7}]},
            ],
        },
    ) as analyze_segments:
        result = await FullAPIClient().analyze_bytes(b"audio", "clip.wav")

    assert analyze_segments.await_args.args[2] == _TRANSCRIPTION["segments"]
    assert [s["emotion"] for s in result["segments"]] == ["neutral", "angry"]
    assert result["segments"][1]["emotion_scores"] == [{"label": "angry", "score": 0.7}]
    assert result["segments"][0]["speaker"] == "SPEAKER_00"


@pytest.mark.asyncio
async def test_full_service_local_segment_without_emotion_stays_unknown():
    client_patch, service_patch = _local_full_settings()
    with client_patch, service_patch, patch(
        "app.api.routes.full.service.transcription_client.analyze_bytes",
        new_callable=AsyncMock,
        return_value=_TRANSCRIPTION,
    ), patch(
        "app.api.routes.full.service.emotion_client.analyze_segments",
        new_callable=AsyncMock,
        return_value={"top_emotion": "happy", "top_score": 0.97, "emotions": [{"label": "happy", "score": 0.97}]},
    ):
        result = await FullAPIClient().analyze_bytes(b"audio", "clip.wav")

    assert [s["emotion"] for s in result["segments"]] == ["unknown", "unknown"]
    assert all(s["emotion_scores"] == [] for s in result["segments"])


@pytest.mark.asyncio
async def test_full_service_local_raises_when_emotion_service_fails():
    client_patch, service_patch = _local_full_settings()
    with client_patch, service_patch, patch(
        "app.api.routes.full.service.transcription_client.analyze_bytes",
        new_callable=AsyncMock,
        return_value=_TRANSCRIPTION,
    ), patch(
        "app.api.routes.full.service.emotion_client.analyze_segments",
        new_callable=AsyncMock,
        side_effect=RuntimeError("emotion service unreachable"),
    ), pytest.raises(RuntimeError, match="emotion service unreachable"):
        await FullAPIClient().analyze_bytes(b"audio", "clip.wav")


@pytest.mark.asyncio
async def test_emotion_client_analyze_segments_posts_segments_form_field():
    from app.api.routes.emotion.service import EmotionAPIClient

    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "emotion": "angry",
        "confidence": 0.9,
        "raw_result": {"labels": ["angry"], "scores": [0.9]},
        "segment_emotions": [{"emotion": "sad", "confidence": 0.6, "emotion_scores": [{"label": "sad", "score": 0.6}]}],
    }
    with patch.multiple("app.core.kaggle_client.settings", IS_LOCAL=True), patch.multiple(
        "app.api.routes.emotion.service.settings", EMOTION_API_URL="http://emotion:8000"
    ), patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp) as post:
        result = await EmotionAPIClient().analyze_segments(b"a", "clip.wav", [{"start": 0, "end": 1.5, "text": "x"}])

    assert post.await_args.args[0] == "http://emotion:8000/predict"
    assert post.await_args.kwargs["data"] == {"segments": '[{"start": 0.0, "end": 1.5}]'}
    assert result["segment_emotions"][0]["emotion"] == "sad"


@pytest.mark.asyncio
async def test_full_service_normalizes_remote_payload():
    with patch("app.api.routes.full.service.settings") as service_settings, patch(
        "app.core.kaggle_client.settings"
    ) as client_settings:
        service_settings.WHISPERX_API_URL = "http://whisperx:8000"
        client_settings.IS_LOCAL = False
        client_settings.KAGGLE_SERVER_URL = "https://kaggle.example.com"
        api = FullAPIClient()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "text": "hello",
            "language": "en",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello",
                    "speaker": "UNKNOWN",
                    "emotion": "中立/neutral",
                    "emotion_scores": [{"label": "中立/neutral", "score": 0.95}],
                }
            ],
            "top_emotion": "中立/neutral",
            "emotions": [{"label": "中立/neutral", "score": 0.95}],
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
            result = await api.analyze_bytes(b"audio", "clip.wav")

    assert result["top_emotion"] == "neutral"
    assert result["segments"][0]["emotion"] == "neutral"
