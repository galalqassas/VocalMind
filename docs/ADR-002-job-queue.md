# ADR-002 — Move the Processing Queue from in-process `asyncio.Queue` to Postgres `LISTEN/NOTIFY`

**Status:** Proposed (target: own branch, after the LLM-trigger model swap lands)
**Date:** 2026-06-16
**Owners:** backend
**Supersedes:** none
**Related:** [ADR-001](ADR-001-architecture.md) §"Trade-offs accepted" (single-replica constraint), [MATURITY_GAP_ANALYSIS.md](MATURITY_GAP_ANALYSIS.md) §11.

## Why this isn't in the current branch

The notifications + HITL branch had a self-imposed rule: no edits to
`backend/app/llm_trigger/` and no large edits to files the LLM-trigger
refactor will touch. The job-queue worker
([`backend/app/core/interaction_processing.py`](../backend/app/core/interaction_processing.py),
848 lines) is exactly that file — it calls
`evaluate_interaction_triggers` and is the most likely conflict surface.
Doing this migration here would cost a painful three-way merge for no
gain. It belongs in its own branch, started **after** the LLM-trigger
swap merges.

## Context

The audio-ingestion → scoring pipeline runs out of an **in-process
`asyncio.Queue`**:

```
audio_folder_watcher  ─┐
POST /interactions     ├──►  enqueue_interaction_processing(id)
POST /reprocess        ─┘            │
                                     ▼
                       _processing_queue: asyncio.Queue
                                     │
                                     ▼
                       _worker_task: single asyncio task
                                     │
                                     ▼
                  WhisperX → Emotion → LLM trigger → score
```

The queue object itself lives at module scope in
[`interaction_processing.py:43`](../backend/app/core/interaction_processing.py)
and is created in `start_processing_worker()` at backend startup. Three
callers enqueue:

- [`interactions.py:404`](../backend/app/api/routes/interactions.py) (POST `/interactions`)
- [`interactions.py:471`](../backend/app/api/routes/interactions.py) (POST `/interactions/from-storage`)
- [`interactions.py:554`](../backend/app/api/routes/interactions.py) (POST `/interactions/{id}/reprocess`)
- [`audio_folder_watcher.py:174`](../backend/app/core/audio_folder_watcher.py) (watched-folder ingest)

On startup, `_enqueue_pending_interactions_backlog()` scans
`processing_jobs` for rows still marked pending and re-enqueues them —
that's our crash-recovery story today.

### What works

- Zero infra dependencies; queue is "free."
- FIFO ordering inside a single backend process.
- Crash recovery via the backlog scan at startup.

### What breaks

- **One backend replica only.** Two replicas means two independent
  in-process queues. They can't see each other's enqueues; the same job
  can be picked up twice; HTTP-tier autoscaling is not safe.
- **Cross-process ingest doesn't notify the worker.** The watched-folder
  ingest in `audio_folder_watcher` only works because it's in the same
  process. A separate watcher container can't enqueue.
- **No durability between enqueue and pickup.** A backend crash between
  `enqueue(...)` and the worker actually getting the message loses the
  signal — only the backlog scan at next startup recovers it, and only
  because the `processing_jobs` row exists. The queue is structurally
  a notification, not durable state.

## Decision

Replace the in-process `asyncio.Queue` with **Postgres `LISTEN/NOTIFY`
on a dedicated channel**, backed by the existing `processing_jobs` table
as the durable work record.

```
enqueuer (any process) ──► INSERT/UPDATE processing_jobs
                                  │
                                  ▼
                          NOTIFY vm_jobs, '<interaction_id>'
                                  │
                                  ▼
                  worker (LISTEN vm_jobs, dedicated connection)
                                  │
                                  ▼
              SELECT FOR UPDATE SKIP LOCKED first pending row
                                  │
                                  ▼
                          run pipeline as today
```

### What changes

| Surface | Before | After |
|---|---|---|
| Module-level `_processing_queue` | `asyncio.Queue` | None — removed |
| `enqueue_interaction_processing(id)` | `await queue.put(id)` | After the `processing_jobs` row is committed, fire `NOTIFY vm_jobs, '<id>'` via the same transaction. |
| `start_processing_worker` | Spawns one task draining the queue | Opens a dedicated asyncpg connection, runs `LISTEN vm_jobs`, plus a fallback poll loop (every 30 s) for missed notifications. |
| Worker pickup | `await queue.get()` | `SELECT … FROM processing_jobs WHERE status='pending' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1` |
| Backlog scan | At startup only | Becomes the fallback poll loop — same query, every 30 s, plus on `LISTEN` reconnect. |

### What stays exactly the same

- `processing_jobs` table schema (already the right shape).
- Stage progression / scoring logic / LLM trigger call site
  (`evaluate_interaction_triggers` invocation is untouched).
- The watched-folder ingester. It just calls
  `enqueue_interaction_processing` like everyone else; only the
  implementation of that function changes.
- API route signatures.

## Why `LISTEN/NOTIFY` instead of Redis / Celery / SQS

| Option | Pro | Con | Verdict |
|---|---|---|---|
| Postgres `LISTEN/NOTIFY` + `SKIP LOCKED` | Zero new infra. Atomic with the INSERT. Already have a Postgres dependency. | NOTIFY payload size is 8 kB max (fine — we send a UUID). Listener needs a long-lived connection outside the pool. | **Pick.** |
| Redis Streams / RQ | Battle-tested. | Adds a Redis dep + ops + secret. Doesn't solve durability — still need `processing_jobs` as source of truth. | No — extra infra for no incremental durability. |
| Celery + RabbitMQ | "The default." | Heavy. Operational overhead disproportionate to one queue. | No. |
| AWS SQS / GCP Pub/Sub | Managed. | Vendor lock-in. Local dev needs emulator. Crosses a billing surface. | Reconsider if we ever multi-region. |

## Migration steps (in the future branch)

1. **Schema** — no change. `processing_jobs` is already authoritative.
2. **DB function + trigger** — write a `notify_pending_job()` trigger on
   `processing_jobs` AFTER INSERT or AFTER UPDATE OF status WHEN status
   = 'pending'. Ships in `infra/db/01_schema.sql`. This is the seam
   that makes the enqueue/notify atomic: every commit that creates a
   pending job emits exactly one notification with the interaction id
   payload.
3. **Listener** — `app/core/job_listener.py`:
   - Acquires a dedicated asyncpg connection (NOT from the SQLModel pool —
     `LISTEN` ties up the connection for its lifetime).
   - Runs `add_listener('vm_jobs', handler)`.
   - On notification, dispatches via an `asyncio.Queue` to the worker
     coroutine. The asyncio.Queue stays — it's now an in-process **fan-out
     buffer**, not the source of truth.
   - On disconnect, reconnect with exponential backoff + immediately scan
     `processing_jobs` for anything pending that was missed during the
     gap.
4. **Worker pickup** — replace `await queue.get()` with a function that:
   ```sql
   SELECT id, interaction_id FROM processing_jobs
   WHERE status = 'pending'
   ORDER BY created_at
   FOR UPDATE SKIP LOCKED LIMIT 1;
   ```
   then transitions the row to `running` in the same transaction.
   `SKIP LOCKED` is what makes N workers safe.
5. **Remove** the `_enqueue_pending_interactions_backlog` startup scan
   (the fallback poll subsumes it).
6. **Tests** — new pytest in `backend/tests/test_job_queue.py`:
   - 2 workers + 5 jobs → each job processed exactly once
   - NOTIFY missed → next poll picks it up within 30 s
   - Worker crash mid-job → row stays `running` until timeout, then
     resets to `pending` (also new — a janitor query that resets
     `running` jobs older than N minutes; specify N=15)
7. **Rollout** — feature-flag via env var `JOB_QUEUE_BACKEND` with
   values `inproc` (default) and `pg_notify`. Run side-by-side in a
   staging deploy for a week before flipping production.

## Backwards compatibility

- API contracts unchanged. The frontend, audio watcher, and pipeline
  internals don't notice the swap.
- A single deploy can transition by running both implementations
  simultaneously behind the env var; rollback is one variable flip.
- No data migration. `processing_jobs` already has all the state we
  need.

## Cost

- **Engineering** — estimated 2–3 days for one engineer, plus a week
  of side-by-side observation.
- **Infra** — $0. Postgres already deployed.
- **Operational** — one new long-lived Postgres connection per backend
  replica. Negligible against the existing pool.

## When to do this

- **Trigger:** the first time we need to run two backend replicas (HA
  or horizontal scale). Today's single-replica works; this is the work
  that unblocks the second replica.
- **Blocker:** must land **after** the LLM-trigger model swap. Both
  changes touch `interaction_processing.py`; sequencing avoids a
  three-way merge.

## Rejected alternatives in the same problem space

- **Move the watched-folder ingester to a sidecar that posts to the
  HTTP API.** Solves cross-process enqueue but leaves the single-worker
  bottleneck and doesn't fix HA. Worth doing eventually but doesn't
  obviate `LISTEN/NOTIFY`.
- **Keep `asyncio.Queue` and add a Redis distributed lock instead.**
  Strictly worse — adds Redis without any of the durability the
  `processing_jobs` + NOTIFY combination already gives us.
