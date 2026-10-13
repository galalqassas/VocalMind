# WhisperX Service

`services/whisperx/app.py` — FastAPI wrapper for WhisperX ASR, wav2vec2 alignment, and pyannote diarization. Compose service `whisperx`, host port 8003 → container 8000; backend uses `WHISPERX_API_URL` (`http://whisperx:8000` in compose). Models load at startup (`start_period: 300s` health grace).

## Configuration

| Variable | Default in code | Compose | Notes |
|---|---|---|---|
| `WHISPER_MODEL_SIZE` | `large-v2` | `tiny` (GPU overlay: `large-v3`) | |
| `WHISPER_COMPUTE_TYPE` | `float16` on CUDA, `int8` on CPU | GPU overlay: `int8_float16` | |
| `WHISPER_BATCH_SIZE` | `8` | — | |
| `HF_TOKEN` | — | from `.env` | Needed for pyannote; without it diarization is disabled |
| `STRICT_DIARIZATION` | `false` | — | `true` makes startup fail when diarization cannot load |
| `DIARIZATION_NUM_SPEAKERS` | `2` | `2` | Exact speaker count; `0` disables the hint |
| `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS` | unset | — | Override `NUM` when set |
| `CHANNEL_DIARIZATION_ENABLED` | `true` | `true` | Channel-based roles for split-channel stereo |
| `CHANNEL_DIARIZATION_MAX_CORR` | `0.92` | `0.92` | At or above this abs(correlation) the file is treated as mono |
| `AGENT_CHANNEL` | unset | unset | Force agent channel `0`/`1`; otherwise the louder channel in the first 8 s |

## Endpoints

`POST /transcribe` — multipart `file`, optional form field `language`. Steps:

1. **Stereo check** (`detect_stereo_layout`): 2 channels with abs(correlation) over the first 30 s below `CHANNEL_DIARIZATION_MAX_CORR` → strategy `channel`, else `cluster`.
2. **Transcribe** (batched), then **align** (on a corrupted alignment checkpoint the file is deleted and loading retried once; alignment errors are logged and skipped).
3. **Diarize**:
   - `channel`: each segment is labelled `AGENT` or `CUSTOMER` by RMS energy per channel; `speaker_meta.source="channel"`.
   - `cluster` with pyannote: `assign_word_speakers`, then segments are split where word speakers change; `speaker_meta` gets `diarization_speaker`, `source="diarization"`, `strategy="cluster"`.
   - No diarization model: `speaker="UNKNOWN"`, `speaker_meta.fallback_reason="diarization_unavailable"`.
4. **Merge** (`merge_short_same_speaker_segments`): joins consecutive same-speaker segments with gap ≤ 1.2 s while the merged span stays ≤ 22 s.
5. **Overlap flags** (`detect_overlaps`).

Response: `{language, segments: [{start, end, text, speaker, overlap, speaker_meta}], processing_time_s, diarization_strategy, stereo_layout}`. 503 before models load; 500 on internal errors.

`GET /health` — `{status, device, model, models_loaded, diarization_enabled, diarization_reason}`.

## Backend use

`transcription_client` (`backend/app/api/routes/transcription/service.py`) calls `/transcribe`; agent/customer roles are assigned in the backend — see [AUDIO_PROCESSING_PIPELINE.md](../architecture/AUDIO_PROCESSING_PIPELINE.md#speaker-roles). The backend counts only `SPEAKER_*` labels as clusters, so channel-mode `AGENT`/`CUSTOMER` labels are re-classified per segment from text.
