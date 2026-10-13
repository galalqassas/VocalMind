# Emotion Fusion

Implementation: `backend/app/core/emotion_fusion.py`. Labels are normalized by `normalize_emotion_label` (`backend/app/core/inference_contracts.py`).

## Where emotion labels come from

| Signal | Source | Stored? |
|---|---|---|
| Per-utterance `Utterance.emotion` | Local mode: keyword heuristic `build_deterministic_emotion_analysis` on the segment text (the Emotion service returns one clip-level label, which never reaches segments). Remote mode: per-segment scores from Kaggle `/full`, same heuristic for missing ones. | Yes |
| Clip-level acoustic label | Emotion service `/predict` (emotion2vec, first 30 s, mono 16 kHz) | Only `top_score`, written to `Transcript.overall_confidence` |
| Text emotion | `infer_text_emotion_with_provider` (below) | No |
| Fused emotion | `fuse_emotion_signals` | No — computed on read |

Fusion runs at read time in: `GET /api/v1/interactions/{id}` (per-utterance `textEmotion`, `fusedEmotion`, `fusedConfidence`, `fusionModel`), `GET /api/v1/interactions/{id}/emotion-comparison`, `POST /api/v1/emotion/fuse`, and `_derive_llm_inputs` in `llm_trigger/service.py` (customer-level fused label fed to the emotion-shift chain).

## Text emotion provider (`TEXT_EMOTION_PROVIDER`)

- `rule_based` (Settings default): `infer_text_emotion` — lexicon tokens +1, phrases +2, frustration cues +1, `!` adds +1 to angry and frustrated; confidence `min(0.97, 0.42 + 0.14 × score)`; no hit → `neutral` 0.3; empty → `neutral` 0.2.
- `hf_transformers` (compose default): POST `{EMOTION_API_URL}/predict_text` (or Kaggle `/predict_text` when `IS_LOCAL=false`), model `j-hartmann/emotion-english-distilroberta-base`. The first failure sets `_HF_PROVIDER_DISABLED_REASON` and the process uses `rule_based` until restart.

## Fusion rule (`fuse_emotion_signals`)

Weights: acoustic 0.55, text 0.45. Missing acoustic confidence defaults to 0.7.

- Labels agree: label kept, confidence `min(0.99, 0.45·text + 0.55·acoustic + 0.08)`.
- Labels differ: label of the higher-confidence modality, confidence `max(0.35, 0.45·text + 0.55·acoustic − 0.12)`.
- Non-neutral amplification: when fused confidence ≥ 0.45, a combined score map (neutral base 0.15 plus each modality's weighted score) is re-ranked; if `neutral` tops it and the runner-up is non-neutral with score ≥ 0.38, the runner-up wins with `min(0.95, score × 1.4)` when that exceeds neutral.
- `model` = `<TEXT_EMOTION_PROVIDER>_text_acoustic_fusion_v2`.

Changing the weights requires re-running `make quality-eval-emotion`.

## Label normalization

| Map | Rules |
|---|---|
| Acoustic (`EMOTION_NORMALIZATION`) | joy, satisfied → happy; calm → neutral; fear, disgust → frustrated |
| Text (`TEXT_LABEL_NORMALIZATION`) | joy, happiness → happy; anger → angry; sadness → sad; fear, disgust, annoyance → frustrated; surprise → neutral |
| Service responses (`normalize_emotion_label`) | as above, but surprise → surprised; other, `<unk>` → unknown |

## Min-duration gate

`apply_emotion_min_duration_gate` (`interaction_processing.py`): segments shorter than `EMOTION_MIN_SEGMENT_SECS` (default 1.0 s) inherit the previous segment's emotion and scores; a replaced label is kept in the segment dict as `_emotion_original` (not persisted).
