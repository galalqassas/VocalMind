# NexaLink Scripted Call Audio Fixtures

These five calls are generated from the annotated scripts in `scripts/` using the
Gemini TTS pipeline under `C:\Users\Mohammed Hassan\Zewail\Senior Project\Data\tts-pipeline`.

The JSON ground truth in `evaluation/` is the source for end-to-end checks:
STT transcript accuracy, speaker role accuracy, emotion label accuracy, RAG
trigger recall, and agent assignment.

## Audio File Index

| File | Scenario | Agent | Escalation Agent(s) | Ground Truth |
|---|---|---|---|---|
| `CALL_01_refund_outage_merged.wav` | Refund request for 48-hour outage | Priya | - | `evaluation/CALL_01_refund_outage.json` |
| `CALL_02_billing_dispute_escalation_merged.wav` | Billing dispute escalated to Tier 2 | Daniel | Sarah Chen | `evaluation/CALL_02_billing_dispute_escalation.json` |
| `CALL_03_tech_support_slow_internet_merged.wav` | Slow internet troubleshooting | Marcus | - | `evaluation/CALL_03_tech_support_slow_internet.json` |
| `CALL_04_access_recovery_fraud_merged.wav` | Account recovery with fraud risk | Aisha | James | `evaluation/CALL_04_access_recovery_fraud.json` |
| `CALL_05_retention_abuse_merged.wav` | Retention/cancellation with abuse protocol | Hannah | Robert | `evaluation/CALL_05_retention_abuse.json` |

## Evaluation Targets

| Capability | Target | Ground Truth Field |
|---|---:|---|
| STT word error rate | <= 0.15 | `turns[].text` |
| Speaker role accuracy | >= 0.90 | `turns[].speaker` |
| Emotion accuracy | >= 0.70 | `turns[].emotion` |
| RAG trigger recall | >= 0.80 | `coverage` |
| Agent assignment | 1.00 | `primary_agent` |

## Notes

- The interaction owner should be the primary agent listed above.
- Secondary escalation speakers are retained in the per-turn JSON as
  `turns[].agent_name`.
- These files replace the previous ten good/bad placeholder calls.
