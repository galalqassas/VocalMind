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
            if not settings.IS_LOCAL:
                base = settings.KAGGLE_SERVER_URL or settings.KAGGLE_NGROK_URL
                if not base:
                    return infer_text_emotion(text)
                url = f"{base.rstrip('/')}/predict_text"
                headers = {"ngrok-skip-browser-warning": "true"}
            else:
                url = f"{settings.EMOTION_API_URL}/predict_text"
                headers = {}
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json={"text": text}, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return data["emotion"], data["confidence"]
                else:
                    raise RuntimeError(f"Text emotion service returned {response.status_code}: {response.text}")
        except Exception as exc:
            _HF_PROVIDER_DISABLED_REASON = str(exc)
            logger.warning(
                "Text emotion provider disabled for this process, using rule-based fallback: %s",
                exc,
            )

    return infer_text_emotion(text)


def build_deterministic_emotion_analysis(text: str) -> dict[str, object]:
    normalized = (text or "").lower()
    scores: dict[str, float] = {
        "neutral": 0.30,
        "happy": 0.0,
        "frustrated": 0.0,
        "angry": 0.0,
        "sad": 0.0,
        "surprised": 0.0,
    }

    happy_keywords = (
        "great", "perfect", "awesome", "wonderful", "thank you so much", "appreciate",
        "fantastic", "excellent", "glad", "happy", "relieved", "that works",
    )
    frustrated_keywords = (
        "unacceptable", "ridiculous", "this is crazy", "been waiting", "keep getting",
        "never works", "fed up", "seriously", "come on", "not good enough", "this is not",
        "every time",
    )
    angry_keywords = (
        "i'm done", "cancel", "this is a joke", "outrageous", "furious", "demand",
        "immediately", "escalate", "supervisor", "lawyer", "threatening", "abuse", "hang up",
    )
    sad_keywords = (
        "worried", "scared", "afraid", "stressed", "really need", "please help",
        "desperate", "lost", "don't know what to do",
    )

    for label, keywords in (
        ("happy", happy_keywords),
        ("frustrated", frustrated_keywords),
        ("angry", angry_keywords),
        ("sad", sad_keywords),
    ):
        hits = sum(1 for kw in keywords if kw in normalized)
        if hits:
            scores[label] = min(0.70, 0.35 * hits)

    # Preserve legacy lexicon signal as a small boost.
    legacy_label, legacy_conf = infer_text_emotion(text)
    legacy_label = _normalize_text_label(legacy_label)
    if legacy_label in scores and legacy_label != "neutral":
        scores[legacy_label] = max(scores[legacy_label], float(legacy_conf) * 0.5)

    emotion = max(scores, key=scores.get)
    confidence = max(scores.values())
    if confidence <= 0.30 and emotion == "neutral":
        confidence = 0.30
    return {
        "top_emotion": emotion,
        "top_score": round(float(confidence), 3),
        "emotions": [{"label": emotion, "score": round(float(confidence), 3)}],
    }


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
        model=f"{settings.TEXT_EMOTION_PROVIDER}_text_acoustic_fusion_v2",
    )
