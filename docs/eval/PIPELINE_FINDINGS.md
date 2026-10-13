# Pipeline Evaluation vs Ground Truth (results record, 2026-05-25)

This records two evaluation runs and the changes they drove. The numbers are as measured on 2026-05-25. The "Current location" notes point to where each mechanism lives now. Harness and axis definitions: [tools/README.md](../../tools/README.md).

**Caveat for both runs:** the Groq daily token quota ran out during the runs, so most LLM-trigger verdicts came from the deterministic fallback path rather than full LLM grading.

## Run 1: 6 calls (nexalink CALL_01/07/15, meridian CALL_21/24/30)

| Axis | Baseline | After | Δ |
|---|---|---|---|
| agent_match | 100% | 100% | 0 |
| topic_match | 33.3% | 100.0% | +66.7pp |
| resolution_match | 33.3% | 83.3% | +50.0pp |
| sop_retrieval_match | 33.3% | 100.0% | +66.7pp |
| avg_turn_ratio (1.0 ideal) | 2.17 | 0.94 | −1.23 |
| avg_emotion_cosine_fused (1 ideal) | 0.894 | 0.948 | +0.054 |
| avg_diar_share_delta (0 ideal) | 0.28 | 0.26 | −0.02 |
| avg_coverage_recall (1 ideal) | 0.32 | 0.43 | +0.11 |

The remaining resolution miss (CALL_07) came from the evaluator's `infer_gt_resolved` wording heuristic, not from the pipeline. It was fixed in Run 2.

## Run 2: 9 calls (adds nexalink CALL_06, meridian CALL_22/35)

| Axis | Run 1 | Run 2 |
|---|---|---|
| agent_match | 100.0% | 100.0% |
| topic_match | 100.0% | 100.0% |
| resolution_match | 83.3% | 100.0% |
| sop_retrieval_match | 100.0% | 100.0% |
| avg_turn_ratio | 0.94 | 0.93 |
| avg_emotion_cosine_fused | 0.948 | 0.957 |
| avg_diar_share_delta | 0.26 | 0.272 |
| avg_coverage_recall | 0.43 | 0.434 |

`evaluate_pipeline.py` still uses this 9-call set.

## Changes behind the numbers

**LLM trigger (`backend/app/llm_trigger/service.py`)**
- Topic detection: `_TOPIC_KEYWORDS` and `RESOLUTION_GRAPHS` gained topics beyond refund/billing/tech/access, e.g. `account_opening`, `fraud_dispute`, `fee_adjustment`, `aml_review`, `retention`. `_score_topic` returns `(topic, score)`. Topics are detected from the full transcript, and a strong keyword hit (score ≥ 6) overrides the LLM's `detected_topic`.
- SOP retrieval: `_TOPIC_TO_SOP_FILE_TOKENS` maps each topic to SOP file names. When a strong-signal topic has no matching chunk, a targeted Qdrant re-retrieval runs, and `_filter_chunks_by_topic` drops off-topic chunks (keeping the original list if nothing matches).
- Resolution: `_is_resolved_heuristic` runs on the full transcript. Hard-negative markers (escalation, freeze, fraud hand-off) always win. Otherwise a concrete strong-positive outcome marker is required, and a polite closing alone no longer counts as resolved.
- Citations: policy references read `"<source_file> — <section>"`, and process adherence always carries a `[Reference SOP] <file> — <section>` citation.

**Segmentation and diarization (`services/whisperx/app.py`)**
- `merge_short_same_speaker_segments()` merges same-speaker segments with gaps ≤ 1.2 s and absorbs fragments < 1.5 s. Turn ratio went from 2.17 to 0.94, and fused emotion cosine improved because emotion runs on longer segments.
- Stereo channel diarization: `detect_stereo_layout()` and `assign_speakers_by_channel()` label genuine 2-channel audio by channel energy and bypass PyAnnote. Controlled by `CHANNEL_DIARIZATION_ENABLED` (default true) and `CHANNEL_DIARIZATION_MAX_CORR` (default 0.92). Responses include `diarization_strategy` (`channel`/`cluster`). This is a no-op on the mono eval set.

**Emotion and speaker roles (`backend/app/core/interaction_processing.py`)**
- `apply_emotion_min_duration_gate()`: segments shorter than `EMOTION_MIN_SEGMENT_SECS` (default 1.0) inherit the previous segment's emotion.
- Speaker roles: `assign_cluster_roles_from_text()` scores each diarization cluster. The score combines the LR+TF-IDF classifier (`backend/app/core/model.pkl` + `vectorizer.pkl`), the `_AGENT_PHRASE_WEIGHTS` / `_CUSTOMER_PHRASE_WEIGHTS` phrase lists, agent-name and greeting boosts, and a first-speaker prior (+4 for the cluster that speaks first within 8 s). When diarization collapses to a single cluster, `classify_segment_speaker_role()` labels each segment instead. The earlier `speaker_role_classifier.py` cue lists no longer exist.

**Evaluator (`tools/evaluate_pipeline.py`)**
- `infer_gt_resolved` uses hard-negative and strong-positive phrase lists. `resolution_match` prefers `processAdherence.isResolved`. SOP matching accepts several expected tokens for calls that cover two SOPs. Coverage recall counts a verbatim GT rule ID as covered.

## Open gaps (as of this record)

- **diar_share_delta about 0.27.** PyAnnote splits one agent voice across clusters on long calls. The first-speaker prior anchors one cluster but does not merge the fragments.
- **Fused emotion is about equal to acoustic** (both 0.948 in Run 1). The text path mostly agrees with acoustic, so fusion adds little on this set.
- **Eval audio is clean 16 kHz mono TTS.** There is no 8 kHz telephony split yet.
- **No PII redaction** before persistence.
- **Two-speaker assumption.** Warm transfers are covered only by `test_assign_cluster_roles_handles_three_clusters_warm_transfer` in `backend/tests/test_interaction_processing_quality.py`.

## Reproducing

Run infra in Docker and the GPU services plus the backend natively. The conda env needs CUDA torch, `whisperx`, `pyannote`, `funasr`, `silero_vad` and the backend deps.

```bash
docker compose up -d db qdrant ollama        # not `frontend`: it depends on the compose backend
cd services/vad      && python -m uvicorn app:app --port 8002
cd services/emotion  && python -m uvicorn app:app --port 8001
cd services/whisperx && WHISPER_MODEL_SIZE=medium WHISPER_COMPUTE_TYPE=float16 python -m uvicorn app:app --port 8003
cd backend && IS_LOCAL=true AUDIO_FOLDER_WATCHER_ENABLED=false python -m uvicorn app.main:app --port 8000
make fe-dev                                   # optional UI; VITE_API_URL unset → http://localhost:8000
python tools/reprocess_and_compare.py --org nexalink --calls CALL_01,CALL_06,CALL_07,CALL_15
python tools/reprocess_and_compare.py --org meridian --calls CALL_21,CALL_22,CALL_24,CALL_30,CALL_35
python tools/evaluate_pipeline.py
```

Set `EXTRA_AUDIO_ROOTS` if the backend's checkout does not contain `storage/audio`. `WHISPER_MODEL_SIZE` defaults to `large-v2`; this recipe overrides it to `medium`.
