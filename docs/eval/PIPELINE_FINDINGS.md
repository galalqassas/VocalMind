# Pipeline Evaluation vs Ground Truth (results record, 2026-05-25)

This records two evaluation runs (numbers as measured on 2026-05-25). Harness and axis definitions: [tools/README.md](../../tools/README.md).

**These numbers do not describe the current pipeline.** During both runs the Groq daily token quota ran out, so most verdicts came from keyword fallbacks, and topic, resolution and speaker roles were partly keyword-driven. Those heuristics no longer exist: topic, resolution, missing steps and evidence now come only from the LLM, speaker roles only from the LR model, and a model failure fails the stage instead of producing a fallback verdict. Re-run the harness before quoting any figure.

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

## Mechanisms from these runs that are still in the code

- **SOP retrieval** (`backend/app/llm_trigger/service.py`): `_TOPIC_TO_SOP_FILE_TOKENS` maps each topic to SOP file names; `_ensure_on_topic_sop_chunks` re-queries Qdrant when no retrieved chunk matches the topic and drops off-topic chunks. Process adherence always names the grounding SOP with a `[Reference SOP] <file> — <section>` citation.
- **Topic set**: the 11 `RESOLUTION_GRAPHS` topics in `backend/app/llm_trigger/prompt_constants.py` (`refund_request`, `billing_issue`, `technical_support`, `account_access`, `account_opening`, `fraud_dispute`, `fee_adjustment`, `aml_review`, `retention`, `wire_transfer`, `account_signers`).
- **Segmentation** (`services/whisperx/app.py`): `merge_short_same_speaker_segments()` merges same-speaker segments with gaps ≤ 1.2 s and absorbs fragments < 1.5 s (turn ratio 2.17 → 0.94).
- **Stereo channel diarization** (`services/whisperx/app.py`): `detect_stereo_layout()` and `assign_speakers_by_channel()` label genuine 2-channel audio by channel energy (`CHANNEL_DIARIZATION_ENABLED`, `CHANNEL_DIARIZATION_MAX_CORR`). No-op on the mono eval set.
- **Emotion min-duration gate** (`backend/app/core/interaction_processing.py`): `apply_emotion_min_duration_gate()`.
- **Evaluator** (`tools/evaluate_pipeline.py`): `infer_gt_resolved` uses hard-negative and strong-positive phrase lists; `resolution_match` prefers `processAdherence.isResolved`; SOP matching accepts several expected tokens; coverage recall counts a verbatim GT rule ID as covered.

## Open gaps (as of this record)

- **diar_share_delta about 0.27.** PyAnnote splits one agent voice across clusters on long calls; role assignment does not merge the fragments.
- **Fused emotion is about equal to acoustic** (both 0.948 in Run 1). The text path mostly agrees with acoustic, so fusion adds little on this set.
- **Eval audio is clean 16 kHz mono TTS.** There is no 8 kHz telephony split yet.
- **No PII redaction** before persistence.
- **Two-speaker assumption.** With three or more clusters, only the highest-P(agent) cluster becomes the agent, so a warm-transfer second agent is labelled customer.

## Reproducing

Default setup (models on Kaggle): start the Kaggle notebook ([services/kaggle/README.md](../../services/kaggle/README.md)), then `make up` (or `make support-up` + `make be-dev`). For fully local GPU inference, run infra in Docker and the model services plus the backend natively; the conda env needs CUDA torch, `whisperx`, `pyannote`, `funasr`, `silero_vad` and the backend deps.

```bash
docker compose --profile local-ml up -d db qdrant ollama   # not `frontend`: it depends on the compose backend
cd services/vad      && python -m uvicorn app:app --port 8002
cd services/emotion  && python -m uvicorn app:app --port 8001
cd services/whisperx && WHISPER_MODEL_SIZE=medium WHISPER_COMPUTE_TYPE=float16 python -m uvicorn app:app --port 8003
cd backend && IS_LOCAL=true RAG_MODELS_HOST=local AUDIO_FOLDER_WATCHER_ENABLED=false python -m uvicorn app.main:app --port 8000
make fe-dev                                   # optional UI; VITE_API_URL unset → http://localhost:8000
python tools/reprocess_and_compare.py --org nexalink --calls CALL_01,CALL_06,CALL_07,CALL_15
python tools/reprocess_and_compare.py --org meridian --calls CALL_21,CALL_22,CALL_24,CALL_30,CALL_35
python tools/evaluate_pipeline.py
```

With `RAG_MODELS_HOST=local`, the Qdrant collections must have been ingested with Ollama embeddings (`cd services/rag && uv run python main.py --ingest --force`). Set `EXTRA_AUDIO_ROOTS` if the backend's checkout does not contain `storage/audio`. `WHISPER_MODEL_SIZE` defaults to `large-v2`; this recipe overrides it to `medium`.
