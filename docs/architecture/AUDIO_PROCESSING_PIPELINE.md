# Audio Processing Pipeline

Core implementation: `backend/app/core/interaction_processing.py`. Inference contracts: `backend/app/core/inference_contracts.py`. Full-analysis client: `backend/app/api/routes/full/service.py`.

## Intake

- `POST /api/v1/interactions` (multipart) and `POST /api/v1/interactions/from-storage` create an `Interaction` (`processing_status=pending`) plus six `ProcessingJob` rows, stages in `STAGE_ORDER`: `diarization`, `stt`, `emotion`, `reasoning`, `scoring`, `rag_eval`.
- `audio_folder_watcher.py` can auto-create interactions from `storage/audio/<org_slug>/` when `AUDIO_FOLDER_WATCHER_ENABLED=true` (Settings default `false`; `backend/.env.example` sets `true`; see [AUDIO_AUTO_INGEST.md](../operations/AUDIO_AUTO_INGEST.md)).
- `POST /api/v1/interactions/{id}/reprocess?priority=true` calls `reset_interaction_for_reprocess` (deletes utterances, emotion events, compliance rows, scores, trigger cache; resets jobs) and enqueues on the priority queue.
- Only `.wav` and `.mp3` are accepted (`SUPPORTED_AUDIO_EXTENSIONS`).

## Worker

One asyncio task (`_worker_loop`) started in the app lifespan. It drains the priority queue first, then waits up to 1 s on the regular queue. On start, interactions stuck in `processing` are reset to `pending` and every `pending` interaction is enqueued.

## `process_interaction` steps

1. **Claim**: skip if already `completed`; mark `diarization`, `stt`, `emotion` jobs `running` and the interaction `processing`; close the DB session before slow I/O.
2. **Fetch audio**: `fetch_audio_bytes()` (`audio_resolver.py`) reads local storage or Supabase Storage.
3. **Analyze** (`full_client.analyze_bytes`):
   - `IS_LOCAL=true`: WhisperX `/transcribe` (transcribe → align → diarize → merge short same-speaker segments → overlap flags), then Emotion `/predict` on the whole file (3 attempts). If the acoustic label is `neutral`/`unknown` and the keyword text heuristic (`build_deterministic_emotion_analysis`) finds a non-neutral label for the whole transcript, the text label replaces it. `build_local_full_response` merges the two. VAD is not called.
   - `IS_LOCAL=false`: Kaggle `/full`, normalized by `normalize_full_response`.
   - If local full analysis raises, a transcription-only retry runs with text-derived emotion; if that also fails the interaction fails ("ASR triple-fallback exhausted").
4. **Per-segment emotion**: the local Emotion service returns one clip-level label, so each segment's `emotion`/`emotion_scores` come from the keyword text heuristic (see [EMOTION_FUSION.md](EMOTION_FUSION.md)).
5. **ASR quality gate**: `is_gibberish()` (`llm_trigger/chains.py`, `fast_classification` stage). Empty text → failed; an LLM error counts as valid.
6. **Min-duration gate**: `apply_emotion_min_duration_gate` — segments shorter than `EMOTION_MIN_SEGMENT_SECS` (default 1.0) inherit the previous segment's emotion and scores.
7. **Speaker roles** (see below), then persist `Transcript`, ordered `Utterance` rows, and an `EmotionEvent` whenever consecutive utterances change emotion label (`emotion_delta=1.0`).
8. **LLM triggers**: `evaluate_interaction_triggers(force_rerun=True)` under `asyncio.wait_for` with `LLM_TRIGGER_EVAL_TIMEOUT_SECONDS` (env, default 600). See [LLM_TRIGGER_FEATURE_GUIDE.md](../llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md).
9. **Scores and violations**: with a report, `compute_scores()` (`llm_trigger/scoring.py`) writes `InteractionScore` (0–1 scale) and `policy_violation_mapping.py` writes `PolicyCompliance` rows. Without a report (timeout/error) every score is `0.7` and `was_resolved=False`.
10. **Complete**: set `language_detected`, `duration_seconds` (max segment end), status `completed`; mark all six jobs `completed`; emit `evaluation_complete` notifications to the agent and managers.

Any uncaught exception calls `mark_interaction_failed`: interaction `failed`, all six jobs `failed` with the error message. The `reasoning`, `scoring`, and `rag_eval` jobs are never individually set to `running`; they flip to `completed`/`failed` with the rest.

## Speaker roles

WhisperX emits `SPEAKER_XX` clusters (pyannote, `DIARIZATION_NUM_SPEAKERS=2` in compose) or, for split-channel stereo with `CHANNEL_DIARIZATION_ENABLED`, `AGENT`/`CUSTOMER` labels from per-segment channel energy. The backend then assigns roles:

- **Multi-cluster** (≥2 distinct `SPEAKER_*`): `assign_cluster_roles_from_text` scores each cluster's joined text. Agent score = LR probability × 3 (`model.pkl` + `vectorizer.pkl`, so at most 3 points) + `_AGENT_PHRASE_WEIGHTS` hits + 15 for any `STRONG_AGENT_PHRASES` + 12 if the agent's name appears + 6 for "my name is/this is <name>" + 4 for a scripted greeting before 15 s + 4 for the earliest cluster if it starts before 8 s. Customer score = (1 − LR probability) × 3 + `_CUSTOMER_PHRASE_WEIGHTS` hits. The cluster with the lowest (agent − customer) net is the customer; all others are agent.
- **Single cluster** (≤1 `SPEAKER_*`): each segment is classified by `classify_segment_speaker_role` with the same weights (greeting bonus only at index 0); segments labelled by text cues keep their label.

## Related

- Reprocess and status endpoints: [REST_API_REFERENCE.md](../api/REST_API_REFERENCE.md)
- Accuracy vs ground truth: [PIPELINE_FINDINGS.md](../eval/PIPELINE_FINDINGS.md)
