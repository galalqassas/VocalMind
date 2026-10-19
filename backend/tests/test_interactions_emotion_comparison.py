from types import SimpleNamespace
from unittest.mock import patch

from app.api.routes.interactions import _build_emotion_comparison_from_labels, _fuse_utterance_emotions
from app.core.emotion_fusion import TextEmotionUnavailable


def test_emotion_comparison_payload_compact_distribution_and_quality():
    # (acoustic, text, fused) per utterance
    payload = _build_emotion_comparison_from_labels(
        [("happy", "happy", "happy"), ("neutral", "angry", "angry"), ("frustrated", "sad", "sad")]
    )

    assert payload["totalUtterances"] == 3
    assert {row["emotion"] for row in payload["distributions"]["text"]} == {"happy", "angry", "sad"}
    assert {row["emotion"] for row in payload["distributions"]["acoustic"]} == {"happy", "neutral", "frustrated"}
    assert payload["quality"] == {
        "acousticTextAgreementRate": 33.33,
        "fusedMatchesAcousticRate": 33.33,
        "fusedMatchesTextRate": 100.0,
        "disagreementCount": 2,
    }


def test_emotion_comparison_payload_handles_empty_utterances():
    payload = _build_emotion_comparison_from_labels([])

    assert payload["totalUtterances"] == 0
    assert payload["distributions"] == {"acoustic": [], "text": [], "fused": []}
    assert payload["quality"]["disagreementCount"] == 0


def test_fused_emotions_are_none_when_text_emotion_unavailable():
    utterances = [SimpleNamespace(text="hello", emotion="neutral", emotion_confidence=0.6)]
    with patch(
        "app.core.emotion_fusion.infer_text_emotion_with_provider",
        side_effect=TextEmotionUnavailable("down"),
    ):
        assert _fuse_utterance_emotions(utterances) is None
