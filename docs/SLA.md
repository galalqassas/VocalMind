# VocalMind SLA Targets

> Aspirational targets for the graduation-project deployment. They are
> the contract the system *aims* to honour, not numbers we've measured
> in production. Each target lists the current observation method so
> we can replace "aspirational" with "measured" as monitoring lands.

## 1. Availability

| Target | Window | Method |
|---|---|---|
| **99.0 %** monthly uptime for the user-facing API (`/api/v1/*`) | 30-day rolling | `GET /health` polled externally every 60 s; downtime counted only after 3 consecutive failures |
| **99.5 %** monthly uptime for the frontend (static SPA) | 30-day rolling | CDN-level monitor |
| **No SLA** for offline pipeline replay (`audio_folder_watcher`, `processing_worker`) — best-effort, jobs are durable in `processing_jobs` |

Planned maintenance is excluded with ≥ 24 h notice on a status page.

## 2. Latency

Measured **server-side** (excludes client network). Numbers under expected
production load (≤ 50 concurrent dashboard sessions, ≤ 5 concurrent
audio uploads).

| Endpoint class | p50 | p95 | p99 | Notes |
|---|---|---|---|---|
| Dashboard reads (`/api/v1/dashboard/*`) | 200 ms | 800 ms | 2 s | Cached for the manager's org; cold cache may hit p95 |
| Interaction list / detail (`/api/v1/interactions*`) | 250 ms | 1.2 s | 3 s | |
| Notifications + review queue | 150 ms | 600 ms | 1.5 s | Bounded by the polling cadence on the bell (30 s) |
| LLM trigger inference | 8 s | 25 s | 60 s | Bounded by Groq; degraded fallback returns ≤ 1 s |
| End-to-end pipeline (audio → scored) | 45 s / minute of audio | 90 s / minute | 180 s / minute | WhisperX is the long pole |

These targets are conditional on the
[Architecture ADR](ADR-001-architecture.md) infrastructure assumptions:
single backend replica, single WhisperX worker, Groq as LLM provider.

## 3. Error budget

| Metric | Budget |
|---|---|
| API 5xx rate | ≤ 0.5 % over any 1-hour window |
| LLM trigger fallback rate | ≤ 5 % over any 24-hour window (rises = Groq incident / quota / prompt regression) |
| Pipeline failures (`processing_jobs.status=failed`) | ≤ 2 % over any 24-hour window |

A breached budget is a halt-and-investigate signal — no new merges to
`main` until the cause is identified.

## 4. Rate limits

Enforced by `slowapi` middleware (see `app/core/rate_limit.py`).

| Surface | Limit |
|---|---|
| All `/api/v1/*` | 60 req / minute / IP (default) |
| `/api/v1/auth/login`, `/api/v1/auth/register` | 10 req / minute / IP (tighter — apply with route-level decorator) |
| Audio upload (`POST /api/v1/interactions`) | 5 req / minute / IP — protects the GPU queue |

Clients hitting the limit receive HTTP 429 with `Retry-After`.

## 5. Data retention & deletion

| Class | Retention | Notes |
|---|---|---|
| Raw audio | 90 days | Deletable on org request; PII-redaction is a TODO before extending |
| Transcripts + scores | 12 months | Same as audio |
| Notifications | 30 days after `is_read=TRUE`, indefinite while unread | Cleanup is a TODO job |
| Feedback rows (emotion / compliance) | Indefinite — they are training data | `is_used_in_training=TRUE` marks rows already exported |
| `assistant_queries` | 90 days | |

## 6. Out-of-scope (no SLA — known)

- Real-time WebSocket / SSE delivery — notifications are 30 s polling today.
- Multi-region failover.
- Backups: nightly Postgres dump only; no PITR.
- Per-org isolation at the database level — currently row-level only.

## 7. How we'll know

| Signal | Where today | Where it should be |
|---|---|---|
| Uptime | manual / `make logs` + `GET /health` | external monitor + Grafana board |
| Latency p50/p95/p99 | `GET /metrics` (Prometheus text format) — exposed by `prometheus_fastapi_instrumentator` | Prometheus scraping + Grafana board |
| Per-request correlation | `X-Request-ID` request/response header (see `app/core/request_id.py`); accepted from upstream proxy if set, otherwise UUID4 | Same id stamped into every log line once structured logging lands |
| Error rate | `logger.error` calls only, no aggregation | structured logs → log aggregator |
| LLM fallback rate | `llm_trigger.service` logs | counter into Prometheus |
| Pipeline failure rate | `processing_jobs.status=failed` rows | Grafana panel on the same table |

Adding the rest of the observability stack (log aggregation, dashboards)
is tracked in [`docs/MATURITY_GAP_ANALYSIS.md`](MATURITY_GAP_ANALYSIS.md) §6.
