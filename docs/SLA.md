# SLA Targets

> **Targets, not measured.** No external uptime monitor, metrics scraper or dashboard is configured in this repo. The "Signal" column says where each number could be observed today.

## Availability

| Target | Signal |
|---|---|
| 99.0 % monthly uptime for `/api/v1/*` | `GET /health` (also the compose healthcheck) |
| 99.5 % monthly uptime for the frontend | none in repo |
| No SLA for pipeline processing (worker, folder watcher) | `processing_jobs` / `interactions.processing_status` |

## Latency (server-side)

Assumed load: ≤ 50 concurrent dashboard sessions and ≤ 5 concurrent uploads, on one backend replica and one model server (Kaggle or local) ([ADR-001](ADR-001-architecture.md)).

| Endpoint class | p50 | p95 | p99 |
|---|---|---|---|
| `GET /api/v1/dashboard/*` (5-min per-org cache) | 200 ms | 800 ms | 2 s |
| `GET /api/v1/interactions`, `/interactions/{id}` | 250 ms | 1.2 s | 3 s |
| Notifications and review queue | 150 ms | 600 ms | 1.5 s |
| LLM trigger evaluation per call | 8 s | 25 s | 60 s |
| End-to-end pipeline, per minute of audio | 45 s | 90 s | 180 s |

Load scenario for the read endpoints: [infra/loadtest/README.md](../infra/loadtest/README.md).

## Error budget

| Metric | Budget | Signal |
|---|---|---|
| API 5xx rate | ≤ 0.5 % per hour | `/metrics` (Prometheus, HTTP only) |
| Reasoning-stage failures (LLM unavailable) | ≤ 5 % per day | `processing_jobs` rows with `stage = 'reasoning'` and `status = 'failed'` |
| Pipeline failures | ≤ 2 % per day | `processing_jobs.status = 'failed'` |

## Rate limits (implemented)

- `slowapi` applies 60 requests/minute per client IP to every route (`backend/app/core/rate_limit.py`, installed in `backend/app/main.py`). The client IP is the first `X-Forwarded-For` hop, or the socket peer if that header is absent. Clients over the limit get HTTP 429.
- No route has a tighter per-route limit, including login and audio upload.

## Data retention (targets; no cleanup job exists)

| Data | Target |
|---|---|
| Raw audio, transcripts, scores | 90 days for audio, 12 months for derived data |
| Notifications | 30 days after read |
| `assistant_queries` | 90 days |
| Feedback rows | Kept indefinitely as training data. `is_used_in_training` marks exported rows. |

## Observability available today

- `GET /health` and `GET /health/circuit-breakers` (Manager Assistant LLM breakers).
- `GET /metrics`: Prometheus text format; `/metrics` and `/health` are excluded.
- `X-Request-ID`: taken from the request or generated, and echoed on the response. Some outbound calls also forward it, via `outbound_request_headers()` in `backend/app/core/request_context.py`.

## Out of scope

Push delivery of notifications (the bell polls every 30 s), multi-region failover, point-in-time recovery, and database-level per-org isolation (all scoping is row-level).
