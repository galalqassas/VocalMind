# ADR-002: Move the Processing Queue to Postgres `LISTEN/NOTIFY`

**Status:** Proposed. Not implemented: the backend has no `LISTEN`/`NOTIFY` or `SKIP LOCKED` code.
**Date:** 2026-06-16
**Related:** [ADR-001](ADR-001-architecture.md) (single-replica trade-off)

## Current state

The queue lives in-process in `backend/app/core/interaction_processing.py`:

- `start_processing_worker()` creates two `asyncio.Queue`s (`_priority_queue`, `_processing_queue`) and one worker task. `_worker_loop` drains the priority queue first.
- These callers enqueue through `enqueue_interaction_processing(id, priority=...)`:
  - `POST /interactions`, `POST /interactions/from-storage` and `POST /interactions/{id}/reprocess` (`?priority=true`) in `backend/app/api/routes/interactions.py`
  - `POST /knowledge/versions/reprocess` in `backend/app/api/routes/knowledge.py`
  - the folder watcher in `backend/app/core/audio_folder_watcher.py`
- Crash recovery: at startup, `_enqueue_pending_interactions_backlog()` resets interactions stuck in `processing` to `pending` and enqueues every `pending` interaction. It reads `interactions.processing_status`, not `processing_jobs`.

Limits of this design:

- Only one backend replica is possible. Two replicas would have separate queues and could process the same interaction twice.
- Only code in the same process can enqueue, so a separate watcher container could not.
- If the backend crashes after an enqueue, the work is not picked up until the next startup scan.

## Proposal

Keep Postgres as the source of truth and use `NOTIFY` only as a wake-up signal:

1. An enqueuer commits the pending state, and a trigger (or explicit statement) fires `NOTIFY vm_jobs, '<interaction_id>'`.
2. Each worker holds a dedicated asyncpg connection (outside the SQLModel pool) running `LISTEN vm_jobs`. It also polls about every 30 s and after a reconnect, to catch missed notifications.
3. Pickup claims work with `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1`, which makes N workers safe.
4. A janitor resets claims left in `processing`/`running` past a timeout, e.g. 15 min.
5. Roll out behind an env flag such as `JOB_QUEUE_BACKEND=inproc|pg_notify`. API contracts stay unchanged.

The schema needs work first:

- `processing_jobs` has one row per stage (6 per interaction) and no `created_at` column. Pickup should claim interactions (e.g. `interactions.processing_status = 'pending'`), or a per-interaction queue column or table must be added.
- `JobStatus` uses `running`, but `ProcessingStatus` uses `processing`. Pick one claim state.
- The priority path (`?priority=true`) needs an ordering column, such as a priority flag plus an enqueue timestamp.

## Alternatives considered

| Option | Verdict |
|---|---|
| Postgres `LISTEN/NOTIFY` + `SKIP LOCKED` | Preferred: no new infrastructure, and Postgres already holds the state |
| Redis Streams / RQ | Adds a service and still needs Postgres as the source of truth |
| Celery + RabbitMQ | Too heavy for one queue |
| Managed queues (SQS, Pub/Sub) | Vendor lock-in, and local dev needs an emulator |
| Watcher as a sidecar posting to the HTTP API | Fixes cross-process enqueue only. Still a single worker and no HA. |

## Trigger

Do this the first time more than one backend replica is needed.
