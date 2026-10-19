# REST API Route Map

Request/response schemas: the FastAPI OpenAPI docs at http://localhost:8000/docs (spec at `/api/v1/openapi.json`) are the source of truth. This file only maps routes.

- Routers are registered in `backend/app/api/main.py`; handlers live in `backend/app/api/routes/**`. Everything below is under the `/api/v1` prefix unless marked "root".
- Auth: `get_current_user` in `backend/app/api/deps.py` reads the `vocalmind_token` HttpOnly cookie, falling back to `Authorization: Bearer <jwt>`. If no token is found it returns 401. If the token is invalid it returns 403.
- **Auth column:** `public` means no auth dependency. `user` means any authenticated user, with data scoped to the caller's organization. `manager` and `agent` mean the role is checked in the handler (403 otherwise).
- Rate limit: the `SlowAPIMiddleware` default applies to every route (60 req/min per client IP; see `backend/app/core/rate_limit.py`).
- Security and RBAC details: [SECURITY.md](../backend/SECURITY.md).

## Root (no `/api/v1` prefix) — `backend/app/main.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | public | Welcome message |
| GET | `/health` | public | DB connectivity check (200 ok / 503 degraded) |
| GET | `/health/circuit-breakers` | public | LLM circuit-breaker states |
| GET | `/metrics` | public | Prometheus metrics (not in OpenAPI) |

## `/auth` — `routes/auth/router.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/login/access-token` | public | OAuth2 password form login; returns JWT and sets cookie |
| POST | `/auth/google` | public | Login with a Google ID token (`token` query param); existing active users only, 403 for unknown emails |
| POST | `/auth/logout` | public | Delete the `vocalmind_token` cookie |

## `/users` — `routes/users.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/users/me` | user | Current user profile |
| PATCH | `/users/me` | user | Update display name / avatar URL |
| POST | `/users/me/change-password` | user | Change password |

## `/interactions` — `routes/interactions.py`

Agents only see their own interactions (`_interaction_scope_filters`); managers see the whole org.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/interactions` | user | Multipart audio upload; creates the interaction and enqueues processing |
| POST | `/interactions/from-storage` | user | Create an interaction from an existing Supabase Storage object |
| GET | `/interactions` | user | List interactions with agent name and scores |
| GET | `/interactions/{interaction_id}` | user | Detail: utterances, emotion events, triggers, explainability, `scores`. When the text-emotion model is unavailable, per-utterance text/fused fields and `emotionComparison` are `null`. |
| GET | `/interactions/{interaction_id}/processing-status` | user | Per-stage `ProcessingJob` status |
| GET | `/interactions/{interaction_id}/audio` | user | Stream audio (local FS or Supabase Storage); 404 when the file is missing |
| POST | `/interactions/{interaction_id}/reprocess` | user | Reset and re-run the pipeline (`?force=`, `?priority=`) |
| DELETE | `/interactions/{interaction_id}` | user | Delete the interaction and all dependent rows |

## Disputes — `routes/emotion/dispute_router.py`, `routes/compliance_disputes.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/interactions/emotion-events/{event_id}/dispute` | agent | Dispute an emotion event; notifies org managers |
| DELETE | `/interactions/emotion-events/{event_id}/dispute` | user | Retract (agents: own disputes only) |
| POST | `/policy-compliance/{compliance_id}/dispute` | agent | Dispute a compliance verdict; notifies org managers |
| DELETE | `/policy-compliance/{compliance_id}/dispute` | user | Retract (agents: own disputes only) |

## `/reviews` and `/feedback` — `routes/reviews.py`, `routes/feedback.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/reviews/queue` | manager | Disputed emotion and compliance items for the org |
| POST | `/reviews/emotion/{event_id}` | manager | Accept/reject an emotion dispute |
| POST | `/reviews/compliance/{compliance_id}` | manager | Accept/reject a compliance dispute |
| POST | `/feedback/emotion` | manager | Direct manager correction of an emotion event |
| POST | `/feedback/compliance` | manager | Direct manager correction of a compliance result |

## `/notifications` — `routes/notifications.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/notifications` | user | Paginated notifications for the caller |
| GET | `/notifications/unread-count` | user | Unread count |
| POST | `/notifications/{notification_id}/read` | user | Mark one as read (recipient only) |
| POST | `/notifications/read-all` | user | Mark all as read |

## `/dashboard` and `/agents` — `routes/dashboard.py`, `routes/agents.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/dashboard/stats` | user | Org KPIs, trends, emotion distribution, leaderboard (5-min in-memory TTL cache) |
| GET | `/agents` | user | Active agents in the org (an agent only gets themselves) |
| GET | `/agents/{agent_id}` | user | Agent profile and performance (an agent can only read their own) |

## `/assistant` — `routes/assistant.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/assistant/query` | manager | NL → read-only SQL → answer; creates or continues a session |
| GET | `/assistant/history` | manager | Recent assistant sessions |
| PATCH | `/assistant/session/{session_id}` | manager | Rename a session |
| DELETE | `/assistant/session/{session_id}` | manager | Soft-delete a session |

## `/knowledge` — `routes/knowledge.py`

"FAQ" routes manage SOP documents. FAQs and KB articles are both `faq_articles` rows; KB rows use a `kb:` category prefix. Every mutation records a new knowledge version.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/knowledge/policies` | user | List org policies |
| POST | `/knowledge/policies` | user | Create a policy from text |
| POST | `/knowledge/policies/upload` | user | Create a policy from a PDF |
| PATCH | `/knowledge/policies/{policy_id}` | user | Edit policy fields |
| PATCH | `/knowledge/policies/{policy_id}/upload` | user | Replace the policy PDF |
| POST | `/knowledge/policies/{policy_id}/toggle` | user | Toggle active for the org |
| DELETE | `/knowledge/policies/{policy_id}` | user | Remove the policy from the org |
| GET | `/knowledge/faqs` | user | List SOPs |
| POST | `/knowledge/faqs` | user | Create an SOP from text |
| POST | `/knowledge/faqs/upload` | user | Create an SOP from a PDF |
| PATCH | `/knowledge/faqs/{faq_id}` | user | Edit an SOP |
| PATCH | `/knowledge/faqs/{faq_id}/upload` | user | Replace the SOP PDF |
| POST | `/knowledge/faqs/{faq_id}/toggle` | user | Toggle active |
| DELETE | `/knowledge/faqs/{faq_id}` | user | Remove the SOP |
| GET | `/knowledge/kb` | user | List KB articles |
| POST | `/knowledge/kb/upload` | user | Create a KB article from a PDF |
| PATCH | `/knowledge/kb/{kb_id}/upload` | user | Replace the KB PDF |
| POST | `/knowledge/kb/{kb_id}/toggle` | user | Toggle active |
| DELETE | `/knowledge/kb/{kb_id}` | user | Remove the KB article |
| GET | `/knowledge/versions` | manager | List knowledge versions (newest first) |
| GET | `/knowledge/versions/active` | manager | Currently active version |
| POST | `/knowledge/versions/{version_id}/activate` | manager | Restore that version's snapshot and make it active |
| POST | `/knowledge/versions/reprocess` | manager | Re-judge interactions' LLM analysis against a version |

## `/llm-trigger` — `routes/llm_trigger/router.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/llm-trigger/health` | public | Qdrant and embedding-host check (Kaggle `/health`, Ollama Cloud, or local Ollama); only Qdrant affects `status` |
| POST | `/llm-trigger/interaction/{interaction_id}/run` | user | Run all trigger checks for one org-scoped interaction |

The run endpoint returns 503 when an LLM or the text-emotion model is unavailable (no heuristic fallback).

## `/rag` — `routes/rag.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/rag/health` | public | Qdrant / local Ollama dependency check |
| POST | `/rag/query` | user | Org-filtered retrieval with provenance |

## Inference passthroughs — `routes/{vad,emotion}/router.py`

These call the local microservices, or Kaggle when `IS_LOCAL=false`. `*-local` variants take a server-side file path instead of an upload.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/vad/analyze`, `/vad/analyze-local` | public | Silero VAD segments |
| POST | `/emotion/process` | public | VAD split → transcribe → per-segment emotion |

## `/internal` — `routes/internal.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/internal/set-kaggle-url` | public | Set `KAGGLE_SERVER_URL` and switch `IS_LOCAL=false` in memory (lost on restart) |
