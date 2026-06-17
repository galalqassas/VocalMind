# VocalMind Backend Security Guide

This document outlines the security architecture, authorization mechanisms, and data protection practices implemented in the VocalMind API gateway.

---

## 1. Authentication & Session Management

Authentication is managed via JSON Web Tokens (JWT) and Google OAuth 2.0.

### 1.1 Password Hashing & Encryption
*   **Bcrypt**: User passwords are never stored in plain text. They are hashed using `bcrypt` with a salt round during registration.
*   **Verification**: Password validation is performed using `bcrypt.checkpw()` on login inputs.

### 1.2 JWT Access Tokens
*   **Token Creation**: Upon successful login, `create_access_token` generates a JWT. The subject (`sub`) claim contains the user's UUID.
*   **Expiration**: Access tokens expire after 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`).
*   **Storage**: Access tokens are delivered to the frontend via an **HttpOnly cookie**. This mitigates Cross-Site Scripting (XSS) risks by preventing JavaScript from reading the token.

### 1.3 Google OAuth 2.0
*   Managers and agents can log in via Google OAuth. The gateway validates Google ID tokens via `/auth/google`.
*   If the Google email matches an active user, the gateway issues a session cookie and logs them in.

---

## 2. Authorization & RBAC

VocalMind enforces strict Role-Based Access Control (RBAC) and tenant separation at the endpoint level using dependencies.

### 2.1 Multi-Tenant Data Scoping
All query controllers verify that data is filtered by `organization_id` derived from the active user's DB record. This prevents users from accessing or modifying data belonging to another tenant.

### 2.2 Endpoint Role Guards
FastAPI routes inspect the user's `UserRole` before permitting execution:
*   **Manager Routes**: Enforce that `user.role == UserRole.manager`. Routes like policy ingestion, dispute resolution, settings updates, and AI assistant queries will raise a `403 Forbidden` if executed by an agent.
*   **Agent Routes**: Restrict data returns. When an agent calls `/interactions`, the query injected in `get_db` filters by `agent_id = user.id`. Agents cannot inspect other agents' calls.

---

## 3. Threat Mitigation & Hardening

VocalMind incorporates specialized guards to defend against common attack vectors:

### 3.1 LLM Prompt Injection Guard (`_INJECTION_GUARD`)
All LLM trigger templates in `app/llm_trigger/prompts.py` append an injection guard instruction. This instructs the judging model to treat transcript data as untrusted text rather than instructions.

### 3.2 Read-Only SQL Enforcement
The AI Manager Assistant (`assistant.py`) translates natural language queries into SQL. To prevent SQL Injection or database modifications:
*   The Assistant parses the generated SQL and throws an exception if it contains writing keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`).
*   The query is executed using a read-only database cursor transaction.

### 3.3 Security Headers Middleware
An HTTP middleware in `app/main.py` adds safety headers to all responses:
*   `X-Content-Type-Options: nosniff`: Prevents browsers from MIME-sniffing responses.
*   `X-Frame-Options: DENY`: Mitigates clickjacking attacks by blocking the API from being embedded in frames.
