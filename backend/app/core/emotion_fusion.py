from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings


TEXT_EMOTION_FUSION_MODEL = "hf_transformers_text_acoustic_fusion_v2"


class TextEmotionUnavailable(RuntimeError):
    """The text emotion model could not be reached or returned an error."""


@dataclass
class EmotionFusionResult:
    emotion: str
    confidence: float
    text_emotion: str
    text_confidence: float
    acoustic_emotion: str
    acoustic_confidence: float
    model: str = TEXT_EMOTION_FUSION_MODEL


EMOTION_NORMALIZATION: dict[str, str] = {
    "joy": "happy",
    "calm": "neutral",
    "satisfied": "happy",
    "fear": "frustrated",
    "disgust": "frustrated",
}

TEXT_LABEL_NORMALIZATION: dict[str, str] = {
    "joy": "happy",
    "happiness": "happy",
    "anger": "angry",
    "fear": "frustrated",
    "surprise": "neutral",
    "neutral": "neutral",
    "sadness": "sad",
    "sad": "sad",
    "disgust": "frustrated",
    "annoyance": "frustrated",
}


def _normalize_emotion(label: str) -> str:
    base = (label or "neutral").strip().lower()
    return EMOTION_NORMALIZATION.get(base, base or "neutral")


def _normalize_text_label(label: str) -> str:
    base = (label or "neutral").strip().lower()
    return TEXT_LABEL_NORMALIZATION.get(base, base)


def infer_text_emotion_with_provider(text: str) -> tuple[str, float]:
    """Classify text emotion with the j-hartmann DistilRoBERTa model.

    Calls the local emotion service when ``IS_LOCAL`` else the Kaggle server.
    Raises ``TextEmotionUnavailable`` on any failure — there is no fallback.
    """
    if settings.IS_LOCAL:
        base, headers = settings.EMOTION_API_URL, {}
    else:
        base = settings.KAGGLE_SERVER_URL
        headers = {"ngrok-skip-browser-warning": "true"}
    if not base:
        raise TextEmotionUnavailable("Text emotion service URL is not configured.")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{base.rstrip('/')}/predict_text", json={"text": text}, headers=headers)
        response.raise_for_status()
        data = response.json()
        return _normalize_text_label(str(data["emotion"])), float(data["confidence"])
    except Exception as exc:
        raise TextEmotionUnavailable(f"Text emotion model unavailable: {exc.__class__.__name__}: {exc}") from exc


NON_NEUTRAL_LABELS = frozenset({"happy", "frustrated", "angry", "sad", "surprised"})


def _combined_emotion_scores(
    text: str,
    acoustic_emotion: str,
    acoustic_confidence: float | None,
    text_emotion: str,
    text_confidence: float,
    acoustic_label: str,
    acoustic_score: float,
) -> dict[str, float]:
    text_weight = 0.45
    acoustic_weight = 0.55
    scores: dict[str, float] = {label: 0.0 for label in NON_NEUTRAL_LABELS}
    scores["neutral"] = 0.15
    scores[text_emotion] = scores.get(text_emotion, 0.0) + text_weight * text_confidence
    scores[acoustic_label] = scores.get(acoustic_label, 0.0) + acoustic_weight * acoustic_score
    if not text.strip():
        scores["neutral"] = max(scores["neutral"], 0.30)
    return scores


def _apply_non_neutral_amplification(scores: dict[str, float]) -> tuple[str, float]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_label, top_score = ranked[0]
    if top_label != "neutral" or len(ranked) < 2:
        return top_label, top_score
    second_label, second_score = ranked[1]
    if second_label in NON_NEUTRAL_LABELS and second_score >= 0.38:
        boosted = min(0.95, second_score * 1.4)
        if boosted > top_score:
            return second_label, boosted
    return top_label, top_score


def fuse_emotion_signals(
    text: str,
    acoustic_emotion: str,
    acoustic_confidence: float | None = None,
) -> EmotionFusionResult:
    raw_text_emotion, text_confidence = infer_text_emotion_with_provider(text)
    text_emotion = _normalize_text_label(raw_text_emotion)
    acoustic_label = _normalize_emotion(acoustic_emotion)
    acoustic_score = acoustic_confidence if acoustic_confidence is not None else 0.7
    acoustic_score = max(0.0, min(1.0, acoustic_score))

    text_weight = 0.45
    acoustic_weight = 0.55

    if text_emotion == acoustic_label:
        fused_emotion = acoustic_label
        fused_confidence = min(0.99, (text_confidence * text_weight) + (acoustic_score * acoustic_weight) + 0.08)
    else:
        # Prefer stronger signal but keep confidence conservative when modalities disagree.
        fused_emotion = text_emotion if text_confidence > acoustic_score else acoustic_label
        fused_confidence = max(0.35, (text_confidence * text_weight) + (acoustic_score * acoustic_weight) - 0.12)

    combined_scores = _combined_emotion_scores(
        text,
        acoustic_emotion,
        acoustic_confidence,
        text_emotion,
        text_confidence,
        acoustic_label,
        acoustic_score,
    )
    combined_scores[fused_emotion] = max(combined_scores.get(fused_emotion, 0.0), fused_confidence)
    if fused_confidence >= 0.45:
        fused_emotion, fused_confidence = _apply_non_neutral_amplification(combined_scores)

    return EmotionFusionResult(
        emotion=fused_emotion,
        confidence=round(fused_confidence, 3),
        text_emotion=text_emotion,
        text_confidence=round(text_confidence, 3),
        acoustic_emotion=acoustic_label,
        acoustic_confidence=round(acoustic_score, 3),
        model=TEXT_EMOTION_FUSION_MODEL,
    )
