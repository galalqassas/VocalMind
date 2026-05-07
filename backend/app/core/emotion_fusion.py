from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.config import settings


logger = logging.getLogger(__name__)
_HF_PROVIDER_DISABLED_REASON: str | None = None


@dataclass
class EmotionFusionResult:
    emotion: str
    confidence: float
    text_emotion: str
    text_confidence: float
    acoustic_emotion: str
    acoustic_confidence: float
    model: str = "text_acoustic_fusion_v2"


TEXT_LEXICON: dict[str, set[str]] = {
    "happy": {"great", "good", "thanks", "thank", "helpful", "happy", "awesome", "perfect"},
    "sad": {"sad", "sorry", "unhappy", "depressed", "down", "disappointed", "regret"},
    "angry": {"angry", "furious", "mad", "unacceptable", "ridiculous", "terrible", "awful", "horrible", "scam"},
    "frustrated": {
        "frustrated",
        "annoyed",
        "upset",
        "still",
        "again",
        "problem",
        "issue",
        "waiting",
        "delay",
        "delayed",
        "late",
        "broken",
        "stuck",
        "unable",
        "cannot",
        "can't",
        "won't",
        "keep",
        "kept",
    },
    "neutral": set(),
}

TEXT_PHRASE_LEXICON: dict[str, tuple[str, ...]] = {
    "happy": ("thank you", "thanks a lot", "really appreciate", "great job", "fixed it", "resolved", "perfect"),
    "sad": ("i'm sorry", "very sorry", "really disappointed", "feel bad", "lost", "regret this"),
    "angry": (
        "not acceptable",
        "waste of time",
        "fed up",
        "this is terrible",
        "absolutely terrible",
        "this is ridiculous",
        "kept me waiting",
        "so angry",
    ),
    "frustrated": (
        "still waiting",
        "kept me waiting",
        "not working",
        "does not work",
        "doesn't work",
        "kept getting",
        "again and again",
        "nothing was fixed",
        "no one helped",
        "no response",
    ),
}

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


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", (text or "").lower())


def infer_text_emotion(text: str) -> tuple[str, float]:
    tokens = _tokenize(text)
    if not tokens:
        return "neutral", 0.2

    scores: dict[str, int] = {label: 0 for label in TEXT_LEXICON.keys()}
    normalized_text = (text or "").lower()
    for token in tokens:
        for label, words in TEXT_LEXICON.items():
            if token in words:
                scores[label] += 1

    for label, phrases in TEXT_PHRASE_LEXICON.items():
        for phrase in phrases:
            if phrase in normalized_text:
                scores[label] += 2

    if any(token in tokens for token in {"waiting", "delay", "delayed", "late", "broken", "stuck", "unable", "cannot", "keep", "kept"}):
        scores["frustrated"] += 1

    if "!" in normalized_text:
        scores["angry"] += 1
        scores["frustrated"] += 1

    best_label = max(scores, key=scores.get)
    best_score = scores[best_label]

    if best_score == 0:
        return "neutral", 0.3

    confidence = min(0.97, 0.42 + (best_score * 0.14))
    return best_label, confidence


def _normalize_text_label(label: str) -> str:
    base = (label or "neutral").strip().lower()
    return TEXT_LABEL_NORMALIZATION.get(base, base)


def _aggregate_text_emotion_scores(scores: list[dict]) -> dict[str, float]:
    aggregated: dict[str, float] = {label: 0.0 for label in TEXT_LEXICON.keys()}
    for item in scores:
        label = _normalize_text_label(str(item.get("label", "neutral")))
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        aggregated[label] = aggregated.get(label, 0.0) + max(0.0, score)
    return aggregated


def _top_text_emotion_from_scores(scores: dict[str, float]) -> tuple[str, float]:
    if not scores:
        return "neutral", 0.3
    label = max(scores, key=scores.get)
    confidence = max(0.0, min(1.0, float(scores.get(label, 0.0))))
    return label, confidence


def infer_text_emotion_with_provider(text: str) -> tuple[str, float]:
    global _HF_PROVIDER_DISABLED_REASON

    provider = settings.TEXT_EMOTION_PROVIDER.strip().lower()
    if provider == "hf_transformers":
        if _HF_PROVIDER_DISABLED_REASON is not None:
            return infer_text_emotion(text)

        import httpx
        try:
            url = f"{settings.EMOTION_API_URL}/predict_text"
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json={"text": text})
                if response.status_code == 200:
                    data = response.json()
                    return data["emotion"], data["confidence"]
                else:
                    raise RuntimeError(f"GPU Service returned {response.status_code}: {response.text}")
        except Exception as exc:
            _HF_PROVIDER_DISABLED_REASON = str(exc)
            logger.warning(
                "GPU text emotion provider disabled for this process, using rule-based fallback: %s",
                exc,
            )

    return infer_text_emotion(text)


def build_deterministic_emotion_analysis(text: str) -> dict[str, object]:
    # Deterministic fallback must remain stable and independent of external model behavior.
    emotion, confidence = infer_text_emotion(text)
    emotion = _normalize_text_label(emotion)
    return {
        "top_emotion": emotion,
        "top_score": round(float(confidence), 3),
        "emotions": [{"label": emotion, "score": round(float(confidence), 3)}],
    }


def fuse_emotion_signals(
    text: str,
    acoustic_emotion: str,
    acoustic_confidence: float | None = None,
) -> EmotionFusionResult:
    text_emotion, text_confidence = infer_text_emotion_with_provider(text)
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

    return EmotionFusionResult(
        emotion=fused_emotion,
        confidence=round(fused_confidence, 3),
        text_emotion=text_emotion,
        text_confidence=round(text_confidence, 3),
        acoustic_emotion=acoustic_label,
        acoustic_confidence=round(acoustic_score, 3),
        model=f"{settings.TEXT_EMOTION_PROVIDER}_text_acoustic_fusion_v2",
    )
