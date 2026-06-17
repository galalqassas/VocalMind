# Emotion Fusion Architecture

This document describes the dual-signal emotion fusion algorithm that combines acoustic and textual emotion signals to produce a unified sentiment analysis.

---

## 1. Dual-Signal Architecture

Traditional speech classification systems rely solely on acoustic features (which miss conversational context) or text sentiment (which misses vocal inflections). VocalMind implements a **dual-signal fusion framework**:

```text
[Audio Turn segment] ──────────────────────────► emotion2vec (Acoustic) ──┐
                                                                           ├─► [Fusion Algorithm] ──► Fused Emotion
[Segment Transcript] ──► DistilRoBERTa / Lexicon ──► NLP Sentiment (Text) ─┘
```

---

## 2. The Fusion Algorithm

The core fusion logic is implemented in `backend/app/core/emotion_fusion.py` using the following rules:

### 2.1 Weight Allocations
The fused score is calculated by combining normalized confidence scores:
*   **Acoustic Signal Weight**: `0.55`
*   **Text Signal Weight**: `0.45`

### 2.2 Agreement Bonus & Disagreement Penalty
*   **Agreement Bonus**: If the acoustic label and text label agree (e.g. both are classified as `happy`), the fused confidence is rewarded:
    \[C_{\text{fused}} = \text{Min}(0.99, (C_{\text{text}} \times 0.45) + (C_{\text{acoustic}} \times 0.55) + 0.08)\]
*   **Disagreement Penalty**: If the modalities contradict (e.g. text is `happy` but acoustic is `angry`), the confidence is penalized:
    \[C_{\text{fused}} = \text{Max}(0.35, (C_{\text{text}} \times 0.45) + (C_{\text{acoustic}} \times 0.55) - 0.12)\]
    The fused label defaults to the modality that yielded the higher confidence score.

---

## 3. Modality Heuristics & Fallbacks

*   **Acoustic Text Fallback**: Acoustic speech turn classifiers frequently yield `neutral` on flat vocal inflections even when the words are emotionally charged (e.g. *"This is terrible, I'm leaving"*). If the acoustic signal is `neutral` but the text classifier detects active lexical tokens, the text emotion overrides the acoustic neutral.
*   **Min-Duration Gate**: Acoustic classification on segments shorter than 1.0 second is highly unstable. To prevent noise spikes, turns under 1.0 second inherit the classification of the preceding turn.
