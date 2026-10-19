# Backend Security

This page covers how the backend handles authentication, authorization, tenant isolation, and hardening. Per-route auth is listed in [REST_API_REFERENCE.md](../api/REST_API_REFERENCE.md).

## Authentication

- **Passwords:** hashed with bcrypt (`hashpw`/`checkpw`) in `backend/app/core/security.py`.
- **JWT:** HS256, signed with `SECRET_KEY`. The claim `sub` holds the user id and `exp` comes from `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30). The backend refuses to start while `SECRET_KEY` is the placeholder (`validate_startup_settings` in `backend/app/core/config.py`).
- **Transport:**
  - Login returns the token in the body and also sets the `vocalmind_token` cookie: HttpOnly, `SameSite=lax`, and `secure=False` hardcoded in `routes/auth/router.py`.
  - `get_token` in `backend/app/api/deps.py` checks the cookie first, then `Authorization: Bearer`.
  - The frontend also keeps the token in `sessionStorage` and sends it as a Bearer header for cross-origin use (`frontend/src/app/services/api.ts`).
- **Error codes:** a missing token returns 401; an invalid token returns 403; an inactive user returns 400.
- **Google sign-in:** `POST /auth/google` verifies the ID token against `GOOGLE_CLIENT_ID` and logs in only an existing active user with that email. Unknown emails get 403; it never creates accounts.

## Authorization

There is no global auth dependency. Each handler declares `CurrentUser` and checks the role itself.

- **Manager-only:**
  - `/assistant/*`
  - `/reviews/*`
  - `/feedback/*`
  - `/knowledge/versions*`
- **Agent-only:** creating a dispute (`POST .../dispute`). Agents may retract only their own disputes.
- **Agent self-scoping:**
  - `/interactions*` adds `agent_id = caller` for agents (`_interaction_scope_filters`).
  - `/agents` and `/agents/{id}` return only the calling agent.
- **Tenant isolation:** queries filter on `current_user.organization_id`. This is covered by the `backend/tests/test_*isolation*.py` and `test_assistant_tenant_guard.py` tests.

## Assistant text-to-SQL guard (`backend/app/api/routes/assistant.py`)

1. `_validate_sql_structure` requires:
   - exactly one statement, `SELECT` or `WITH … SELECT`;
   - only tables in the allowlist;
   - only columns in the allowlist.
2. `_is_org_scoped_sql` requires a literal `organization_id = '<caller org id>'` binding.
3. Execution uses a separate engine on `ASSISTANT_DATABASE_URL`. That URL should use the `vocalmind_readonly` role, which has column-level `SELECT` grants only (`infra/db/04_assistant_readonly_role.sql`).

## LLM prompt-injection guard

`INJECTION_GUARD` (`backend/app/llm_trigger/prompt_constants.py`) is appended to the system prompts of the three trigger chains in `backend/app/llm_trigger/prompts.py`. It tells the model to treat all transcript and user text as untrusted data. The RAG service has its own copy in `services/rag/prompt_safety.py`. Do not remove either.

## HTTP hardening (`backend/app/main.py`)

- **Response headers:** every response gets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `X-Request-ID` (echoed from the request or generated).
- **CORS:** allows `FRONTEND_URL` plus `localhost`/`127.0.0.1` on ports 3000 and 5173, with credentials enabled.
- **Rate limiting:** 60 requests/min per IP via slowapi (`backend/app/core/rate_limit.py`). The client IP is the first `X-Forwarded-For` hop, so it is only trustworthy behind a proxy that sets that header.
- **Error masking:** unhandled exceptions return a generic 500 with an `error_id`; the details go only to the logs.

## Known gaps (as of this writing)

- **Unauthenticated routes:**
  - the inference passthroughs (`/vad/*`, `/emotion/process`; `/vad/analyze-local` reads a server-side file path);
  - `/internal/set-kaggle-url`, which reroutes all inference;
  - `/health/circuit-breakers` and `/metrics`.
- **Missing manager checks:**
  - Knowledge policy/SOP/KB create, update, toggle, and delete need only an authenticated user.
  - `/dashboard/stats` returns org-wide data to agents.
- **Rate limits:** `rate_limit.py` describes a tighter 10/min limit for auth endpoints, but no `@limiter.limit` decorator is applied anywhere.
