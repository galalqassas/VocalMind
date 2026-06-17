"""Locust scenario for VocalMind read-side load testing.

Targets the user-facing dashboard + interaction read endpoints with the
mix a manager generates while triaging calls. Does **not** exercise the
audio-upload / pipeline path — that's GPU-bound and tested separately
via ``infra/scripts/e2e_local_audio.py``.

Run (against a local stack started with ``make up``):

    pip install locust  # one-time, outside the backend venv
    cd infra/loadtest
    locust -f locustfile.py --host http://localhost:8000

Then open http://localhost:8089 to drive RPS / concurrency. Headless run
(scripted):

    locust -f locustfile.py --host http://localhost:8000 \
        --headless --users 50 --spawn-rate 5 --run-time 5m \
        --csv reports/baseline

Targets per ``docs/SLA.md`` §2:

    Dashboard reads   p95 < 800 ms
    Interaction list  p95 < 1.2 s
    Interaction detail p95 < 1.2 s

Env vars (override seeded defaults):

    VM_LOAD_USERNAME   default "manager@nexalink.com"
    VM_LOAD_PASSWORD   default "password123"
"""
from __future__ import annotations

import os
import random
from typing import List, Optional

from locust import HttpUser, between, task, events

API_PREFIX = "/api/v1"
DEFAULT_USERNAME = os.environ.get("VM_LOAD_USERNAME", "manager@nexalink.com")
DEFAULT_PASSWORD = os.environ.get("VM_LOAD_PASSWORD", "password123")


@events.test_start.add_listener
def _on_test_start(environment, **_kwargs) -> None:
    """Surface the seeded creds we'll use so a wrong .env is obvious."""
    print(f"[locust] auth as {DEFAULT_USERNAME!r} against {environment.host}")


class ManagerBrowsingUser(HttpUser):
    """Simulates a manager refreshing dashboards and clicking into calls."""

    wait_time = between(1.0, 3.0)

    interaction_ids: List[str] = []
    auth_header: Optional[dict] = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.auth_header = self._login()
        self.interaction_ids = self._load_interaction_ids()

    def _login(self) -> dict:
        resp = self.client.post(
            f"{API_PREFIX}/auth/login/access-token",
            data={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="POST /auth/login/access-token",
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Login failed ({resp.status_code}). "
                f"Set VM_LOAD_USERNAME/VM_LOAD_PASSWORD to valid seeded creds."
            )
        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError("Login succeeded but no access_token in response.")
        return {"Authorization": f"Bearer {token}"}

    def _load_interaction_ids(self) -> List[str]:
        resp = self.client.get(
            f"{API_PREFIX}/interactions",
            headers=self.auth_header,
            name="GET /interactions (seed list)",
        )
        if resp.status_code != 200:
            return []
        payload = resp.json()
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        # Accept both raw rows and {id, ...} shapes
        return [r["id"] for r in rows if isinstance(r, dict) and "id" in r][:50]

    # ── Tasks (weights mirror real manager click-mix) ────────────────────

    @task(5)
    def dashboard_stats(self) -> None:
        self.client.get(
            f"{API_PREFIX}/dashboard/stats",
            headers=self.auth_header,
            name="GET /dashboard/stats",
        )

    @task(3)
    def interaction_list(self) -> None:
        self.client.get(
            f"{API_PREFIX}/interactions",
            headers=self.auth_header,
            name="GET /interactions",
        )

    @task(4)
    def interaction_detail(self) -> None:
        if not self.interaction_ids:
            return
        iid = random.choice(self.interaction_ids)
        self.client.get(
            f"{API_PREFIX}/interactions/{iid}",
            headers=self.auth_header,
            name="GET /interactions/{id}",
        )

    @task(2)
    def notifications_unread_count(self) -> None:
        # Matches the 30s NotificationBell polling cadence; under load this is
        # the highest-frequency call from the frontend.
        self.client.get(
            f"{API_PREFIX}/notifications/unread-count",
            headers=self.auth_header,
            name="GET /notifications/unread-count",
        )

    @task(1)
    def review_queue(self) -> None:
        self.client.get(
            f"{API_PREFIX}/reviews/queue",
            headers=self.auth_header,
            name="GET /reviews/queue",
        )
