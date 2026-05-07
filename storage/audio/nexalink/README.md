# NexaLink Scripted Call Audio Fixtures

These five calls are generated from the annotated scripts in `scripts/` using the
Gemini TTS pipeline.

The JSON ground truth in `evaluation/` is the source for end-to-end checks:
STT transcript accuracy, speaker role accuracy, emotion label accuracy, RAG
trigger recall, and agent assignment.

## Filename Convention

`CALL_<NN>_<agent_lowercase>_<scenario>.wav`

The agent token embedded in the filename is the **primary agent** for the call
and is used by the auto-ingest watcher (`backend/app/core/audio_folder_watcher.py`)
to assign the interaction to the correct seeded agent on first detection.

## Audio File Index

| File | Scenario | Primary Agent | Escalation Speaker(s) | Ground Truth |
|---|---|---|---|---|
| `CALL_01_priya_refund_outage.wav` | Refund request for 48-hour outage | Priya | - | `evaluation/CALL_01_refund_outage.json` |
| `CALL_02_daniel_billing_dispute.wav` | Billing dispute escalated to Tier 2 | Daniel | Sarah Chen (Tier 2 lead, voice only) | `evaluation/CALL_02_billing_dispute_escalation.json` |
| `CALL_03_marcus_tech_support.wav` | Slow internet troubleshooting | Marcus | - | `evaluation/CALL_03_tech_support_slow_internet.json` |
| `CALL_04_aisha_access_recovery.wav` | Account recovery with fraud risk | Aisha | James (Tier 2 fraud, voice only) | `evaluation/CALL_04_access_recovery_fraud.json` |
| `CALL_05_hannah_retention.wav` | Retention/cancellation with abuse protocol | Hannah | Robert (Tier 3 lead, voice only) | `evaluation/CALL_05_retention_abuse.json` |

The five primary agents — Priya, Daniel, Marcus, Aisha, Hannah — are the only
agents seeded into the NexaLink organization. Escalation speakers appear in
the audio for realism but are not modeled as separate users.

## Evaluation Targets

| Capability | Target | Ground Truth Field |
|---|---:|---|
| STT word error rate | <= 0.15 | `turns[].text` |
| Speaker role accuracy | >= 0.90 | `turns[].speaker` |
| Emotion accuracy | >= 0.70 | `turns[].emotion` |
| RAG trigger recall | >= 0.80 | `coverage` |
| Agent assignment | 1.00 | `primary_agent` |

## Notes

- `.wav` files in this folder are **not committed to git**; they are processed
  locally by the auto-ingest watcher and their filename encodes the agent.
- Drop a new audio file matching the naming convention into this folder while
  the backend is running and it will be auto-queued for the full processing
  pipeline (transcribe → diarize → emotion → trigger evaluation).
- Secondary escalation speakers are retained in the per-turn ground-truth JSON
  as `turns[].agent_name` but do not get their own seeded user account.
