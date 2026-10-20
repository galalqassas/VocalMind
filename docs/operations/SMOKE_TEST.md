# Smoke test: real audio through Kaggle + backend

Checks the Kaggle GPU server (VAD → Whisper → pyannote → emotion) and the full pipeline on real audio. Takes about 1 hour and uses ~1 hour of Kaggle GPU quota. Write each check's result in the table at the end.

## 0. Prepare

- **Kaggle:** phone-verified account (needed for GPU + Internet). Secrets: `HF_TOKEN` (with the `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` terms accepted), `NGROK_TOKEN` and `NGROK_DOMAIN`. Leave `BACKEND_URL` unset when the backend runs on your laptop.
- **Laptop:** Docker, an `OLLAMA_API_KEY`, `ffmpeg`.
- **Audio:**
  - A real call recording: your `CALL_<NN>_<agent>_<scenario>.wav` files (they're gitignored). If you have none, recover the old sample: `git show archive/pre-cleanup-2026-10-13:research/voice-gen/telecom_call.mp3 > telecom_call.mp3`.
  - A silent file: `ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 10 silence.wav`.
  - Reference transcripts are in `storage/audio/nexalink/scripts/`, and labels are in `storage/audio/nexalink/evaluation/`.

## 1. Start the Kaggle server

1. Import `services/kaggle/vocalmind_gpu.ipynb`. Set **Accelerator = GPU** and **Internet = on**, and attach the secrets.
2. In cell 1, set `BRANCH` to the branch under test (until it's merged: `feat/vad-in-full-pipeline`). Then run all cells.
3. Set `URL=https://<NGROK_DOMAIN>` and `H='ngrok-skip-browser-warning: true'`, then run `curl -H "$H" $URL/health`.

**Pass:** every entry in `models` is `true`. If one is `false`, the notebook log says why (usually an install or HF-token problem).

## 2. Test the server directly

```bash
curl -s -H "$H" -F file=@CALL_04.wav $URL/vad  > vad.json
curl -s -H "$H" -F file=@CALL_04.wav $URL/full > full.json
curl -s -H "$H" -F file=@silence.wav $URL/full > silence.json
```

| Check | Pass when |
|---|---|
| VAD | `vad.json` has several `speech_segments`; the gaps match pauses in the call |
| Transcript | `full.json` text matches the reference script closely; nothing is invented in the silent parts |
| Timestamps | Every segment falls inside a `speech_segments` region |
| Speakers | Two labels (`SPEAKER_00`/`01`) that alternate with the turns; few `UNKNOWN` |
| Emotion | Per-segment `emotion` varies and is mostly not `unknown` |
| Silence | `silence.json` has `text: ""`, `segments: []` and `top_emotion: "unknown"` |
| Other models | `/predict_text` (`{"text":"this is terrible"}` → negative label), `/embed` (`dimension: 1024`), `/rerank`, and `/parse` on `storage/docs/nexalink/policy-docs/POLICY_01_call_conduct.pdf` (markdown with headings) |

Keep the JSON files, so later runs can be compared.

## 3. End-to-end through the app

1. In `.env`, set `OLLAMA_API_KEY` and `KAGGLE_SERVER_URL=$URL`. In `backend/.env`, point `DATABASE_URL` and `ASSISTANT_DATABASE_URL` at `db:5432`, and set `AUDIO_FOLDER_WATCHER_ENABLED=false` for this test.
2. Run `make build && make up`.
3. Index the policy docs with the Kaggle embeddings: `docker compose exec ingestion /opt/venv/bin/python main.py --ingest --force`. Check retrieval with `docker compose exec ingestion /opt/venv/bin/python main.py -q "refund policy" --org nexalink`.
4. Copy the call to `storage/audio/nexalink/CALL_04_aisha_access_recovery_fraud.wav`, then run `python infra/scripts/e2e_local_audio.py --include-llm`. It logs in as the NexaLink manager, processes the file and polls until done.
5. Open http://localhost:3000 as `manager@nexalink.com` / `password123`, then open the call.

**Pass:**
- The script exits 0, and all 6 processing jobs are `completed`.
- Agent and customer roles are right for most turns.
- Scores exist, and each trigger shows evidence quotes from the transcript.

## 4. Failure path (nothing should be guessed)

| Action | Expected |
|---|---|
| Stop the notebook, then process another call | The interaction is `failed`; `diarization`/`stt`/`emotion` show "Audio analysis failed"; there are no scores |
| Restart the notebook, then `POST /api/v1/interactions/{id}/reprocess?priority=true` | It completes normally |
| Process `silence.wav` | `stt` fails with "no speech detected or transcript is gibberish" |
| Set `OLLAMA_API_KEY=invalid`, restart the backend and reprocess | `stt` fails with "ASR quality check failed" (the first LLM call); there are no scores. Removing the key entirely stops the backend at startup instead |

## 5. Quality vs ground truth (later, more calls)

Process the labelled calls, then run `python tools/reprocess_and_compare.py --org nexalink --calls CALL_01,CALL_04,CALL_07` and `python tools/evaluate_pipeline.py` ([tools/README.md](../../tools/README.md)). Compare against the numbers in [PIPELINE_FINDINGS.md](../eval/PIPELINE_FINDINGS.md), especially speaker roles (now LR-only) and emotion (now per segment).

## 6. Optional: local models (no Kaggle)

Run `make up-local` (or `make up-gpu`) and `make ollama-pull-embed`, then repeat steps 3–4 with `IS_LOCAL=true` and `RAG_MODELS_HOST=local`. This checks WhisperX with `vad_method="silero"`.

## Results

| Step | Check | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Health: all models loaded | | |
| 2 | VAD / transcript / speakers / emotion / silence / other models | | |
| 3 | End-to-end call completed with sensible roles and evidence | | |
| 4 | Failure path and reprocess | | |
| 5 | Ground-truth comparison | | |
