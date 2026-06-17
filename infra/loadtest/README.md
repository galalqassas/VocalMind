# Load testing

Locust scenario exercising the user-facing read endpoints. Lives outside
the backend venv so installing Locust doesn't pollute the runtime image.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install locust
```

## Run against a local stack

```bash
make up                                  # in repo root
cd infra/loadtest
locust -f locustfile.py --host http://localhost:8000
# open http://localhost:8089
```

## Headless run (CI / baseline capture)

```bash
mkdir -p reports
locust -f locustfile.py --host http://localhost:8000 \
    --headless --users 50 --spawn-rate 5 --run-time 5m \
    --csv reports/baseline
```

Produces `reports/baseline_stats.csv` + `reports/baseline_failures.csv`.
Commit the CSVs alongside a `reports/<date>_<sha>.md` summary noting
which commit / environment they came from.

## Targets

From [`docs/SLA.md`](../../docs/SLA.md) §2:

| Endpoint | p95 budget |
|---|---|
| `GET /dashboard/stats` | 800 ms |
| `GET /interactions` | 1.2 s |
| `GET /interactions/{id}` | 1.2 s |
| `GET /notifications/unread-count` | 600 ms |
| `GET /reviews/queue` | 600 ms |

A run is a regression if any p95 doubles vs. the last committed baseline.

## What's deliberately out of scope

- **Audio uploads + pipeline runs** — GPU-bound, tested separately via
  [`infra/scripts/e2e_local_audio.py`](../scripts/e2e_local_audio.py).
- **Auth burst tests** — `/auth/login/access-token` has its own rate
  limit; load-testing it is a separate scenario.
- **Realtime delivery** — there isn't any yet; the bell polls at 30 s.
