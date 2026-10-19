# LLM Trigger Engine

Per-interaction reasoning that produces the emotion-shift, process-adherence, and NLI-policy verdicts, the explainability cards, and the inputs to scoring.

| File (`backend/app/llm_trigger/`) | Role |
|---|---|
| `service.py` | Orchestration (`evaluate_interaction_triggers`), `classify_topic`, evidence gates, explainability builders, cache |
| `chains.py` | LLM construction (`build_llm`, `get_model_for_stage`), the topic-classification chain and the three judgment chains, retry, `is_gibberish` |
| `prompts.py` / `prompt_constants.py` | Prompt templates, output schemas, few-shots, `INJECTION_GUARD`, and `RESOLUTION_GRAPHS` (the single source of expected SOP steps for the 11 topics) |
| `retrieval.py` | `SOPRetriever`, `PolicyRetriever`, `KBRetriever`, SOP context resolution |
| `schemas.py` | `TopicClassification`, `EmotionShiftAnalysis`, `ProcessAdherenceReport`, `NLIEvaluation`, `InteractionLLMTriggerReport`, explainability models |
| `scoring.py` | `compute_scores()` — policy / empathy / resolution / overall (0–1) |

## Entry points

- Processing worker: `evaluate_interaction_triggers(force_rerun=True)` after utterances are saved (see [AUDIO_PROCESSING_PIPELINE.md](../architecture/AUDIO_PROCESSING_PIPELINE.md)).
- `GET /api/v1/interactions/{id}?include_llm_triggers=true` returns the cached report as `emotionTriggers`, `ragCompliance`, `llmTriggers`, plus `knowledgeVersion` / `activeKnowledgeVersion` / `isStale`. Add `llm_force_rerun=true` to recompute and commit. Without a cache entry it returns `available: false`; while the interaction is processing it does not run.
- `POST /api/v1/llm-trigger/interaction/{id}/run` — body `retrieved_sop_from_pinecone`, `ground_truth_policy`, `org_filter`, `force_rerun`. Pass the org slug as `org_filter`; without it retrieval is empty.
- `POST /api/v1/knowledge/versions/reprocess` with `target=original` re-judges against a past knowledge snapshot ([KNOWLEDGE_BASE_MANAGEMENT.md](../operations/KNOWLEDGE_BASE_MANAGEMENT.md)).
- `GET /api/v1/llm-trigger/health`: Qdrant and embedding-host check.
- The run endpoint returns **503** when an LLM (or the text-emotion model) is unavailable (`LLMUnavailableError`).

## Providers and models

`LLM_PROVIDER` (`backend/app/core/config.py`; startup fails if the matching key is missing):

- `ollama_cloud` (compose default): `ChatOpenAI` against `OLLAMA_CLOUD_BASE_URL`. Model per stage: `OLLAMA_MODEL_<STAGE>`, else the class default. Heavy (`OLLAMA_CLOUD_HEAVY_MODEL`, default `kimi-k2.6:cloud`): `emotion_shift`, `process_adherence`, `text_to_sql`. Fast (`OLLAMA_CLOUD_FAST_MODEL`, default `ministral-3:8b`): `nli_policy`, `rag_judge`, `fast_classification`, `rag_synthesis`.
- `groq` (Settings default): `ChatGroq` with `LLM_MODEL` (default `llama-3.3-70b-versatile`) for every stage.

Chains bind JSON-object mode and parse with `PydanticOutputParser`. `_invoke_chain_with_retry` makes 3 attempts with exponential backoff on rate-limit/timeout/connection errors; after that `_run_chain` raises `LLMUnavailableError`.

LLM calls per interaction: `is_gibberish` (ASR gate, in the worker), then 4 in the trigger engine — topic classification, emotion shift, process adherence, NLI policy — plus the supplemental `PolicyComplianceEvaluator` judge.

## Orchestration (`evaluate_interaction_triggers`)

1. **Cache**: without `force_rerun` and overrides, return the `interaction_llm_trigger_cache` row if `_schema_version >= CACHE_SCHEMA_VERSION` (5) and its `org_filter` matches.
2. **Load** interaction (org-scoped), transcript, utterances, agent. Build rolling windows of 8 utterances, stride 4 (`ROLLING_WINDOW_TURNS`, `ROLLING_WINDOW_STRIDE`). The emotion focus window has the largest sum of customer negative-emotion confidences (stored acoustic labels); process windows are first/middle/last (`MAX_PROCESS_WINDOWS=3`).
3. **Inputs** (`_derive_llm_inputs`): customer and agent text from role-labelled utterances (≤2400 chars each; the LLM input falls back to the first 900 transcript chars when roles are missing). Customer emotion = confidence- and recency-weighted utterance emotions, fused with text via `fuse_emotion_signals` (text-emotion failure → `LLMUnavailableError`).
4. **SOP context** (`resolve_retrieved_sop_context`): caller override → manual org files → Qdrant `vocalmind_sop_parents` (`doc_type=sop`, top `SOP_RETRIEVAL_TOP_K`), ranked to 2 chunks. Manual files are PDFs in `storage/docs/{org}/sop-procedures|faq-docs/` resolved to `parsed-docs/sops/{stem}.md` (then `parsed-docs/{stem}.md`, then legacy `services/rag/parsed_docs/`), else raw `.md`/`.txt` there. When manual files exist, this step does not query Qdrant; a Qdrant error yields empty context.
5. **Topic** (`classify_topic`): one fast-LLM call (`build_topic_classification_chain`, `fast_classification` stage) on the full transcript (≤6000 chars) returns one `RESOLUTION_GRAPHS` key or `unknown`. Computed once and passed to process adherence.
6. **Topic-aware SOP filter** (`_ensure_on_topic_sop_chunks`): if no chunk's `source_file` matches `_TOPIC_TO_SOP_FILE_TOKENS[topic]`, re-query Qdrant (top `max(5, 2×SOP_RETRIEVAL_TOP_K)`); keep only on-topic chunks when any exist.
7. **Policy context** (`_resolve_active_policy_context`): `ground_truth_policy` override → Qdrant `vocalmind_parents` (`doc_type=policy`, top 2, chunks from the top hit's source) → active DB policies for the org (regulatory/legal first, then newest) → SOP text.
8. **Run in parallel**: emotion shift, process adherence + NLI, and the transcript-level `PolicyComplianceEvaluator` (`services/rag/evaluator.py`, loaded from `/app/rag` or `services/`). The evaluator's report is only logged, and its errors are swallowed.
9. **Evidence gates**: transcript citations are back-filled with utterance indices. No mapped transcript citation → `insufficient_evidence` for emotion shift / process adherence; no policy citation → NLI `insufficient_evidence`.
10. **Explainability**: see [EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md](../explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md).
11. **Persist** to the cache (unless overrides were passed without `force_persist`), tagged with the org's active knowledge version.

Any LLM or text-emotion failure in steps 3–8 raises `LLMUnavailableError`; nothing is cached and the worker marks the `reasoning` stage failed ([failure semantics](../architecture/AUDIO_PROCESSING_PIPELINE.md#failure-semantics)).

## Stage 1 — Emotion shift (agent friction)

`analyze_emotion_shift`. The prompt diagnoses which agent behaviour caused the customer's state; `dissonance_type` is one of `interruption`, `dismissive_tone`, `missing_acknowledgment`, `none` (sarcasm/cross-modal labels are explicitly excluded).

- Conversations under 8 words skip the LLM (`insufficient_evidence`).
- The LLM sees the full speaker-labelled conversation (≤7000 chars) plus the focus window.
- Friction whose evidence quotes align better with customer turns than agent turns is reset to `none` (`_friction_grounded_in_agent_turns`).

## Stage 2 — Process adherence

`evaluate_process_adherence` (one heavy-LLM call; topic from `classify_topic`, or classified here when the single-stage endpoint is called without one):

- **Topic hint**: the classified topic; when it is `unknown`, the topic implied by the retrieved SOP file names/headers (`_detect_topic_from_sop_chunks`), else none. Off-topic SOP chunks are dropped (`_filter_chunks_by_topic`). The hint becomes `detected_topic`.
- **Expected steps**: bullet/numbered lines extracted from the SOP context (≤5); if none, `RESOLUTION_GRAPHS[topic]` (`prompt_constants.py`). Bullet, prose (>12 words), and other-topic steps are filtered out.
- **From the LLM only**: `is_resolved` and `efficiency_score` (1–10) are required fields; `missing_sop_steps` (step keys mapped back to labels by `_resolve_step_labels`, then filtered as above) and evidence quotes/citations come from the same response. There is no keyword or heuristic adjustment.
- A `[Reference SOP] <file> — <headers>` citation is appended when SOP chunks exist and the model cited none.

## Stage 3 — NLI policy

`run_single_claim_nli_policy_check`: one call classifying the concatenated agent statement against the policy context as `Entailment`, `Benign Deviation`, `Contradiction`, or `Policy Hallucination`, with `severity` (`critical`/`major`/`minor`/`none`) and `policy_alignment_score`. A `Contradiction` whose model-supplied quotes are not anchored in the policy text (verbatim or ≥50% token overlap) is downgraded to `Benign Deviation` (severity `none`, alignment score at least 0.45).

## Scoring (`scoring.py`)

- **Policy**: NLI base (Entailment 0.95, Benign Deviation 0.85; violations graded by severity, e.g. Contradiction critical 0.25 / major 0.45 / minor 0.65), blended 80/20 with `policy_alignment_score`, multiplied by `0.85 + 0.15 × efficiency/10`; floored at 0.6 when NLI evidence is insufficient.
- **Empathy**: `1 − penalty` (missing_acknowledgment 0.15, interruption 0.25, dismissive_tone 0.35) × confidence; no penalty below confidence 0.5; 0.8 when emotion evidence is insufficient.
- **Resolution**: 0.94 resolved with no missing steps, 0.84 resolved with missing steps, 0.42 unresolved.
- **Overall**: 0.4 policy + 0.3 empathy + 0.3 resolution.

## Prompt safety

Every system prompt ends with `INJECTION_GUARD` (`prompt_constants.py`); never remove it. User data is passed through `_sanitize_for_prompt` (neutralizes `system:`/`assistant:`/`human:`/`user:` prefixes and code fences, truncates).

## Frontend

`frontend/src/app/services/api.ts` (types), `components/manager/SessionDetail.tsx`, `components/agent/AgentCallDetail.tsx`, `components/manager/EvidenceAnchoredExplainabilityPanel.tsx`.

## Tests

`make llm-trigger-test` runs `backend/tests/test_llm_trigger_service.py`, `test_interactions_llm_triggers.py`, `test_sop_retrieval.py`, `services/rag/tests/test_ingest.py`, and `frontend/src/tests/AgentCallDetail.test.tsx`. Related: `test_llm_trigger_prompts.py`, `test_llm_trigger_scoring.py`, `test_llm_trigger_isolation.py`, `test_interactions_llm_org_filter_isolation.py`, `frontend/src/tests/LLMTriggerSections.test.tsx`.

## Known issues

- The `PolicyComplianceEvaluator` report costs an extra LLM call per run but is discarded after logging.
- Toggling a policy off in the Knowledge Base only changes DB flags; Qdrant retrieval (tried first for policy context) still returns its chunks.
- The single-stage `/llm-trigger/*` endpoints and `/llm-trigger/health` have no authentication dependency.
