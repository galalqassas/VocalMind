# Load testing

`locustfile.py` simulates managers browsing read endpoints. Locust is not a backend dependency, so install it in a separate venv.

```bash
python -m venv .venv && .venv/bin/pip install locust
make up                                   # repo root
cd infra/loadtest && locust -f locustfile.py --host http://localhost:8000   # UI on :8089
```

Headless run, writing `reports/baseline_stats.csv` and `reports/baseline_failures.csv`:

```bash
locust -f locustfile.py --host http://localhost:8000 --headless --users 50 --spawn-rate 5 --run-time 5m --csv reports/baseline
```

Credentials come from `VM_LOAD_USERNAME` / `VM_LOAD_PASSWORD` (default: seeded `manager@nexalink.com` / `password123`).

## Task mix (weights)

| Endpoint | Weight | p95 target ([SLA.md](../../docs/SLA.md)) |
|---|---|---|
| `GET /api/v1/dashboard/stats` | 5 | 800 ms |
| `GET /api/v1/interactions/{id}` | 4 | 1.2 s |
| `GET /api/v1/interactions` | 3 | 1.2 s |
| `GET /api/v1/notifications/unread-count` | 2 | 600 ms |
| `GET /api/v1/reviews/queue` | 1 | 600 ms |

## Caveats

- The backend applies a global slowapi limit of 60 requests/minute per client IP (`backend/app/core/rate_limit.py`). A single-host run with many users gets HTTP 429s that measure the limiter, not the endpoints. Either distribute the load across IPs or raise the limit for the test.
- Not covered: audio upload and pipeline runs (see `infra/scripts/e2e_local_audio.py`) and login bursts.
