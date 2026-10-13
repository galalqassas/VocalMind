# Manager Guide

What a user with the **manager** role can see and do. All data is scoped to the manager's organization. Route and component map: [FRONTEND_ARCHITECTURE.md](../frontend/FRONTEND_ARCHITECTURE.md).

The sidebar has Dashboard, Session Inspector, Review Queue, Knowledge Base, Manager Assistant and Settings. Notifications are under the header bell (`/manager/notifications`).

## Dashboard (`/manager`)

- KPI cards: Average Score, Calls Processed, Resolution Rate and Policy Violations.
- Weekly Score Trends, Emotion Distribution, Agent Leaderboard and Recent Interactions.
- The backend caches dashboard stats per organization for 5 minutes (`dashboard_cache` in `backend/app/core/cache.py`). New or reprocessed calls can take up to 5 minutes to show up.

## Session Inspector (`/manager/inspector`)

- Search by agent name, date or interaction ID. Sort by score, date or duration. Results are paginated.
- **Upload audio** creates an interaction (`POST /api/v1/interactions`), optionally assigned to an agent, and queues it for processing.
- The row menu has **View details**, **Reprocess** and **Delete session** (asks for confirmation).

## Session detail (`/manager/inspector/:id`)

- Audio player synced with the diarized transcript. Click a turn to seek the audio.
- Analysis tabs: Emotion, Process (SOP adherence), Policy (NLI verdicts and violations) and Quality (agreement between audio, text and fused emotion).
- Evidence panel: each trigger links to transcript spans and to the retrieved policy or SOP chunk, with jump-to-timestamp buttons. See [EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md](../explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md).
- **Correct** on an emotion event or compliance verdict opens a correction sheet. It writes a `reviewed` feedback row and notifies the agent; no agent flag is needed (`backend/app/api/routes/feedback.py`).
- **Reprocess**: the header shows the knowledge version the call was judged against (e.g. `KB v3 · stale`). Reprocessing lets you choose that original version or the active one.

## Review Queue (`/manager/reviews`)

Lists AI findings that agents flagged, with tabs for All, Emotion and Compliance.

- **Accept flag** records a correction: a corrected emotion and justification, or a corrected compliance verdict and an optional 0–1 score. It writes a `reviewed` feedback row.
- **Reject** clears the flag and keeps the AI verdict. No feedback row is written.
- Both actions notify the agent (`backend/app/api/routes/reviews.py`).

## Knowledge Base (`/manager/knowledge`)

- Tabs: **Policies**, **SOPs**, **Knowledge Base** and **Versions**.
- Upload, replace, toggle (active/inactive) or delete PDFs. Uploads are saved under `storage/docs/<org>/` for the ingestion service to index. See [KNOWLEDGE_BASE_MANAGEMENT.md](../operations/KNOWLEDGE_BASE_MANAGEMENT.md).
- **Versions**: every knowledge change creates a version. **Activate** an older version to roll back. **Reprocess stale results** re-judges calls that were scored against an older version.

## Manager Assistant (`/manager/assistant`)

- Ask questions in plain English. The backend turns each question into one `SELECT` (or `WITH … SELECT`), validates it, and runs it on a read-only database connection (`ASSISTANT_DATABASE_URL`).
- Suggested questions appear on an empty chat. Follow-ups such as "the second one" reuse the previous result.
- Chats are saved per user and can be renamed or deleted. Details: [MANAGER_ASSISTANT.md](../llm_trigger/MANAGER_ASSISTANT.md).
