# Emotion Fusion

Implementation: `backend/app/core/emotion_fusion.py`. Service labels are normalized by `normalize_emotion_label` (`backend/app/core/inference_contracts.py`).

## Where emotion labels come from

| Signal | Source | Stored? |
|---|---|---|
| Per-utterance acoustic emotion (`Utterance.emotion`, `emotion_confidence`) | emotion2vec per segment: Kaggle `/full` (`IS_LOCAL=false`) or the local Emotion service `/predict` with `segments` (`IS_LOCAL=true`). No result → `unknown`. | Yes |
| Text emotion | `infer_text_emotion_with_provider`: `j-hartmann/emotion-english-distilroberta-base` via `/predict_text` on the Kaggle server (`IS_LOCAL=false`) or `EMOTION_API_URL` (`IS_LOCAL=true`) | No |
| Fused emotion | `fuse_emotion_signals` | No — computed on read |

Text emotion has no fallback: any error raises `TextEmotionUnavailable`.

Fusion runs at read time in:

| Caller | On `TextEmotionUnavailable` |
|---|---|
| `GET /api/v1/interactions/{id}` (per-utterance `textEmotion`, `textConfidence`, `fusedEmotion`, `fusedConfidence`, `fusionModel`) | Those fields are `null` and `emotionComparison` is `null` |
| `GET /api/v1/interactions/{id}/emotion-comparison` | 503 |
| `POST /api/v1/emotion/fuse` | 503 |
| `_derive_llm_inputs` in `llm_trigger/service.py` (customer-level fused label for the emotion-shift chain) | `LLMUnavailableError` → `reasoning` stage fails |

## Fusion rule (`fuse_emotion_signals`)

Weights: acoustic 0.55, text 0.45. Missing acoustic confidence defaults to 0.7.

- Labels agree: label kept, confidence `min(0.99, 0.45·text + 0.55·acoustic + 0.08)`.
- Labels differ: label of the higher-confidence modality, confidence `max(0.35, 0.45·text + 0.55·acoustic − 0.12)`.
- Non-neutral amplification: when fused confidence ≥ 0.45, a combined score map (neutral base 0.15 plus each modality's weighted score) is re-ranked; if `neutral` tops it and the runner-up is non-neutral with score ≥ 0.38, the runner-up wins with `min(0.95, score × 1.4)` when that exceeds neutral.
- `model` = `hf_transformers_text_acoustic_fusion_v2`.

Changing the weights requires re-running `make quality-eval-emotion`.

## Label normalization

| Map | Rules |
|---|---|
| Acoustic (`EMOTION_NORMALIZATION`) | joy, satisfied → happy; calm → neutral; fear, disgust → frustrated |
| Text (`TEXT_LABEL_NORMALIZATION`; mirrored in `services/kaggle/server.py`) | joy, happiness → happy; anger → angry; sadness → sad; fear, disgust, annoyance → frustrated; surprise → neutral |
| Service responses (`normalize_emotion_label`) | as above, but surprise → surprised; other, `<unk>` → unknown |

## Min-duration gate

`apply_emotion_min_duration_gate` (`interaction_processing.py`): segments shorter than `EMOTION_MIN_SEGMENT_SECS` (default 1.0 s) inherit the previous segment's emotion and scores; a replaced label is kept in the segment dict as `_emotion_original` (not persisted).
