# Audio Processing Pipeline

Core implementation: `backend/app/core/interaction_processing.py`. Inference contracts: `backend/app/core/inference_contracts.py`. Full-analysis client: `backend/app/api/routes/full/service.py`.

## Intake

- `POST /api/v1/interactions` (multipart) and `POST /api/v1/interactions/from-storage` create an `Interaction` (`processing_status=pending`) plus six `ProcessingJob` rows, stages in `STAGE_ORDER`: `diarization`, `stt`, `emotion`, `reasoning`, `scoring`, `rag_eval`.
- `audio_folder_watcher.py` can auto-create interactions from `storage/audio/<org_slug>/` when `AUDIO_FOLDER_WATCHER_ENABLED=true` (Settings default `false`; `backend/.env.example` sets `true`; see [AUDIO_AUTO_INGEST.md](../operations/AUDIO_AUTO_INGEST.md)).
- `POST /api/v1/interactions/{id}/reprocess?priority=true` calls `reset_interaction_for_reprocess` (deletes utterances, emotion events, compliance rows, scores, trigger cache; resets every job to `pending`) and enqueues on the priority queue. This is also how a failed interaction is retried.
- Only `.wav` and `.mp3` are accepted (`SUPPORTED_AUDIO_EXTENSIONS`).

## Worker

One asyncio task (`_worker_loop`) started in the app lifespan. It drains the priority queue first, then waits up to 1 s on the regular queue. On start, interactions stuck in `processing` are reset to `pending` and every `pending` interaction is enqueued.

## `process_interaction` steps

1. **Claim**: skip if already `completed`; mark `diarization`, `stt`, `emotion` jobs `running` and the interaction `processing`; close the DB session before slow I/O.
2. **Fetch audio**: `fetch_audio_bytes()` (`audio_resolver.py`) reads local storage or Supabase Storage.
3. **Analyze** (`full_client.analyze_bytes`), routed by `IS_LOCAL`:
   - `false` (compose default): Kaggle `/full` (Whisper ASR → pyannote diarization → emotion2vec per segment), normalized by `normalize_full_response`.
   - `true`: WhisperX `/transcribe` (transcribe → align → diarize → merge short same-speaker segments → overlap flags), then Emotion `/predict` with the segment windows (`emotion_client.analyze_segments`), merged by `build_local_full_response`. VAD is not called.
   - Each segment's `emotion` / `emotion_scores` come only from the speech-emotion model; a segment with no result stays `unknown`.
4. **ASR quality gate**: `is_gibberish()` (`llm_trigger/chains.py`, `fast_classification` stage). Empty or gibberish text fails `stt`; an LLM error also fails `stt`.
5. **Min-duration gate**: `apply_emotion_min_duration_gate` — segments shorter than `EMOTION_MIN_SEGMENT_SECS` (default 1.0) inherit the previous segment's emotion and scores.
6. **Speaker roles** (`assign_speaker_roles`, below).
7. **Persist**: `Transcript` (`overall_confidence=None`, see TODOs), ordered `Utterance` rows (acoustic emotion + confidence of the top score), and an `EmotionEvent` whenever consecutive non-`unknown` utterance emotions change (`emotion_delta=1.0`). Set `language_detected` and `duration_seconds` (max segment end); mark `diarization`, `stt`, `emotion` `completed` and `reasoning` `running`.
8. **Reasoning**: `evaluate_interaction_triggers(force_rerun=True)` under `asyncio.wait_for` with `LLM_TRIGGER_EVAL_TIMEOUT_SECONDS` (env, default 600). See [LLM_TRIGGER_FEATURE_GUIDE.md](../llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md).
9. **Scoring**: `compute_scores()` (`llm_trigger/scoring.py`) writes one `InteractionScore` (0–1 scale); `policy_violation_mapping.py` writes `PolicyCompliance` rows.
10. **Complete**: mark `scoring` and `rag_eval` `completed`, interaction `completed`; emit `evaluation_complete` notifications to the agent and managers.

Text emotion and fusion are not stored; they are computed at read time ([EMOTION_FUSION.md](EMOTION_FUSION.md)).

## Failure semantics

There is no keyword or default-score fallback. A failing step raises `StageFailed(stages, message)`, and `mark_interaction_failed` sets the interaction `failed`, the failing stage(s) `failed` with the error, and every stage not yet completed `failed` with `Not run: <stage> stage failed.` No `InteractionScore` row is written. Reprocess to retry.

| Failure | Failed stage(s) |
|---|---|
| Speech inference (Kaggle or local services) | `diarization`, `stt`, `emotion` |
| `is_gibberish` LLM error or gibberish transcript | `stt` |
| Speaker-role model cannot load (`SpeakerRoleModelUnavailable`) | `diarization` |
| Any trigger LLM call, the text-emotion model, or the timeout | `reasoning` |
| Scoring or violation persistence | `scoring` |

Any other exception fails all unfinished stages with the formatted error.

## Speaker roles

WhisperX emits `SPEAKER_XX` clusters (pyannote, `DIARIZATION_NUM_SPEAKERS=2` in compose) or, for split-channel stereo with `CHANNEL_DIARIZATION_ENABLED`, `AGENT`/`CUSTOMER` labels from per-segment channel energy. Kaggle `/full` emits pyannote `SPEAKER_XX` labels (or `UNKNOWN`).

`assign_speaker_roles` uses only the LR + TF-IDF classifier (`backend/app/core/model.pkl` + `vectorizer.pkl`, P(agent) per utterance text):

1. Explicit `AGENT`/`CUSTOMER` labels (stereo channel diarization) are kept as-is.
2. Two or more `SPEAKER_*` clusters: the cluster with the highest mean P(agent) is the agent; all other clusters are the customer.
3. Otherwise (one cluster or none): each segment is the agent when P(agent) ≥ 0.5.

## TODOs in code

- `Transcript.overall_confidence` is `None` until WhisperX / Kaggle return a real ASR confidence.
- `InteractionScore.total_silence_seconds` and `avg_response_time_seconds` are `None` until computed from utterance timestamps.

## Related

- Reprocess and status endpoints: [REST_API_REFERENCE.md](../api/REST_API_REFERENCE.md)
- Accuracy vs ground truth: [PIPELINE_FINDINGS.md](../eval/PIPELINE_FINDINGS.md)
