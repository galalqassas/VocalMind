# Evidence-Anchored Explainability

Every LLM-trigger verdict is returned as a card that links a transcript span, the SOP/policy clause used, and the verdict. Built during `evaluate_interaction_triggers` (see [LLM_TRIGGER_FEATURE_GUIDE.md](../llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)) and cached with the trigger report.

| Layer | File |
|---|---|
| Models | `backend/app/llm_trigger/schemas.py` — `EvidenceAnchoredExplainability`, `TriggerAttribution`, `ClaimProvenance`, `EvidenceSpan`, `PolicyReference`, `EvidenceCitation` |
| Builders | `backend/app/llm_trigger/service.py` — `_build_explainability_layer` and helpers |
| API mapping | `backend/app/api/routes/interactions.py` — `_map_emotion_trigger_report`, `_map_rag_compliance_report`, `_map_llm_trigger_report` |
| UI | `frontend/src/app/components/manager/EvidenceAnchoredExplainabilityPanel.tsx` (used by `SessionDetail.tsx` and `AgentCallDetail.tsx`) |

## Cards produced

`trigger_attributions` (in order):

1. **Agent friction** — exactly one, `attribution_id="emotion-dissonance"`, family `emotion`, `trigger_type="Acoustic-Transcript Dissonance"`, title from the diagnosed friction ("Agent Interruption", "Dismissive Agent Tone", "Missing Acknowledgment", "No Agent Friction"). Verdict: `Insufficient Evidence` if the stage lacked evidence, `Cross-Modal Mismatch` if friction was detected, else `No Trigger`. Span = best customer transcript citation.
2. **Emotion polarity shifts** — up to 3 (`EMOTION_TRANSITION_MAX_CARDS`), family `emotion`, `trigger_type="Emotion Polarity Shift"`. Emitted only when a speaker's consecutive utterances cross positive↔negative (neutral excluded) with utterance confidence ≥ 0.55; the highest-confidence ones are kept. Verdict `Cross-Modal Mismatch` when deteriorating, `Neutral` when improving.
3. **SOP violations** — one per missing SOP step, family `sop`, `trigger_type="SOP Violation"`, title = step. Verdict `Partial Attempt` if the closest transcript citation has Jaccard token overlap ≥ 0.18 with the step, else `Contradiction`. `policy_reference` comes from the best-matching retrieved SOP chunk.

No builder emits family `policy`; policy judgments appear only as claim cards.

`claim_provenance`: up to 2 cards from the NLI result's agent/unknown transcript citations (if none, one card for the agent statement truncated to 220 chars). Each claim re-queries `PolicyRetriever` (top 2), keeps chunks from the same source document as the retrieved policy context (if any), and picks the highest-scoring chunk; `semantic_similarity` is that chunk's Qdrant score. Verdict mapping (`_map_nli_verdict`): Entailment → `Supported`; Contradiction and Policy Hallucination → `Contradiction`; Benign Deviation → `Neutral`; insufficient evidence → `Insufficient Evidence`. Confidence = NLI `confidence_score` (may be `null`; no estimate is substituted). When retrieval fails, a placeholder policy reference is built from the policy context or NLI justification so the deck is never empty.

Allowed verdicts (`ExplainabilityVerdict`): `Supported`, `Partial Attempt`, `Neutral`, `Contradiction`, `Cross-Modal Mismatch`, `No Trigger`, `Insufficient Evidence`.

## API surface

`GET /api/v1/interactions/{id}?include_llm_triggers=true` (camelCase):

| Field | Contents |
|---|---|
| `utterances[].sequenceIndex`, `startTime`, `endTime`, `timestamp` | Anchors for span jump-to-audio |
| `emotionTriggers.explainability` | `triggerAttributions` with family `emotion`; `claimProvenance` is empty |
| `ragCompliance.explainability` | `triggerAttributions` with family `sop`/`policy`, plus `claimProvenance` |
| `llmTriggers.explainability` | All trigger attributions plus `claimProvenance` |

Card fields:

- Trigger: `attributionId`, `family`, `triggerType`, `title`, `verdict`, `confidence`, `evidenceSpan`, `policyReference`, `reasoning`, `evidenceChain`, `supportingQuotes`.
- Claim: `claimId`, `claimText`, `claimSpan`, `retrievedPolicy`, `semanticSimilarity`, `nliVerdict`, `confidence`, `reasoning`, `provenance`, `supportingQuotes`.
- `evidenceSpan` / `claimSpan`: `utteranceIndex`, `speaker`, `quote`, `timestamp`, `startSeconds`, `endSeconds`.
- `policyReference` / `retrievedPolicy`: `source`, `reference`, `clause`, `docType`, `policyRef`, `version`, `category`, `provenance`. The internal `PolicyReference` also has `doc_id`, `rule_id`, `step_number`, `severity`; the interaction mappers do not emit them.

`POST /api/v1/rag/query` returns a lighter `retrieval_provenance` list built in `backend/app/api/routes/rag.py`: `claim` (the query), `chunkRank`, `semanticSimilarity`, `verdict` (`supported` ≥ `RAG_SUPPORTED_THRESHOLD` 0.82, `neutral` ≥ `RAG_NEUTRAL_THRESHOLD` 0.55, else `insufficient_evidence` — a retrieval-support label, not an NLI verdict), `docType`, `policyRef`, `reference`, `excerpt` (220 chars), `provenance` {`docId`, `sourceFile`, `headerPath`}.

## UI behaviour

`EvidenceAnchoredExplainabilityPanel` groups cards into tabs: "SOP Violations" (family `sop`), "Policy Findings" (family `policy`), "Span-Level Trigger Attribution" (family `emotion`), "Retrieval Provenance Scoring" (claims). Empty groups are hidden. KB references use indigo styling, policy/SOP orange. Missing numbers render as `N/A`. Timestamps call `onJumpTo` to seek the audio.

`SessionDetail.tsx` prefers `llmTriggers.explainability`; `AgentCallDetail.tsx` prefers `emotionTriggers.explainability`, so agents normally see only emotion cards.

## Tests

`backend/tests/test_interactions_llm_triggers.py` (payload mapping), `backend/tests/test_sop_retrieval.py`, `frontend/src/tests/SessionDetail.test.tsx`, `frontend/src/tests/LLMTriggerSections.test.tsx`.

## Changing the contract

Update together: `schemas.py` → mappers in `interactions.py` → types in `frontend/src/app/services/api.ts` → the panel component → the tests above. Bump `CACHE_SCHEMA_VERSION` in `service.py` when cached payloads become incompatible.
