from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.emotion_fusion import (
    TextEmotionUnavailable,
    _normalize_text_label,
    fuse_emotion_signals,
    infer_text_emotion_with_provider,
)


def test_fuse_emotion_signals_prefers_agreement():
    with patch("app.core.emotion_fusion.infer_text_emotion_with_provider", return_value=("happy", 0.9)):
        result = fuse_emotion_signals(text="Thanks, this was great.", acoustic_emotion="happy", acoustic_confidence=0.8)
    assert result.emotion == "happy"
    assert 0.0 <= result.confidence <= 1.0
    assert result.model.endswith("_text_acoustic_fusion_v2")


def test_fuse_emotion_signals_handles_disagreement():
    with patch("app.core.emotion_fusion.infer_text_emotion_with_provider", return_value=("angry", 0.9)):
        result = fuse_emotion_signals(text="This is unacceptable.", acoustic_emotion="calm", acoustic_confidence=0.6)
    assert result.emotion in {"angry", "neutral"}
    assert result.text_emotion == "angry"
    assert result.acoustic_emotion == "neutral"


def test_fuse_emotion_signals_propagates_text_emotion_unavailable():
    with patch(
        "app.core.emotion_fusion.infer_text_emotion_with_provider",
        side_effect=TextEmotionUnavailable("down"),
    ), pytest.raises(TextEmotionUnavailable):
        fuse_emotion_signals(text="hello", acoustic_emotion="neutral", acoustic_confidence=0.5)


def test_text_label_normalization_maps_supported_labels():
    assert _normalize_text_label("joy") == "happy"
    assert _normalize_text_label("anger") == "angry"
    assert _normalize_text_label("sadness") == "sad"


def _local_settings():
    return patch.multiple(
        "app.core.emotion_fusion.settings", IS_LOCAL=True, EMOTION_API_URL="http://emotion:8000"
    )


def test_infer_text_emotion_calls_model_endpoint_and_normalizes_label():
    response = MagicMock(status_code=200)
    response.json.return_value = {"emotion": "anger", "confidence": 0.93}
    with _local_settings(), patch("httpx.Client.post", return_value=response) as post:
        assert infer_text_emotion_with_provider("This is unacceptable") == ("angry", 0.93)
    assert post.call_args.args[0] == "http://emotion:8000/predict_text"


def test_infer_text_emotion_raises_on_http_error_status():
    request = httpx.Request("POST", "http://emotion:8000/predict_text")
    response = httpx.Response(503, request=request)
    with _local_settings(), patch("httpx.Client.post", return_value=response):
        with pytest.raises(TextEmotionUnavailable):
            infer_text_emotion_with_provider("hello")


def test_infer_text_emotion_raises_on_connection_error_every_time():
    with _local_settings(), patch("httpx.Client.post", side_effect=httpx.ConnectError("refused")) as post:
        for _ in range(2):
            with pytest.raises(TextEmotionUnavailable):
                infer_text_emotion_with_provider("hello")
    assert post.call_count == 2  # no process-wide disable after the first failure


def test_infer_text_emotion_uses_kaggle_with_ngrok_header():
    response = MagicMock(status_code=200)
    response.json.return_value = {"emotion": "joy", "confidence": 0.8}
    with patch.multiple(
        "app.core.emotion_fusion.settings",
        IS_LOCAL=False,
        KAGGLE_SERVER_URL="https://kaggle.example.com/",
    ), patch("httpx.Client.post", return_value=response) as post:
        assert infer_text_emotion_with_provider("thanks") == ("happy", 0.8)
    assert post.call_args.args[0] == "https://kaggle.example.com/predict_text"
    assert post.call_args.kwargs["headers"] == {"ngrok-skip-browser-warning": "true"}
