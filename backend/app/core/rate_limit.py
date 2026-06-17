"""Shared slowapi limiter.

Default budget: 60 req / minute / IP for the whole `/api/v1` surface.
Auth endpoints are tighter (10 req / minute / IP) — apply via
`@limiter.limit("10/minute")` on the route function.

The limiter is installed as middleware in `app/main.py`; per-route
overrides only need the decorator. Read the IP from `X-Forwarded-For`
first (we run behind a proxy in production) and fall back to the peer
address otherwise.
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter

_DEFAULT_LIMIT = "60/minute"


def _client_ip(request: Request) -> str:
    """Prefer the first hop in X-Forwarded-For; fall back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


limiter = Limiter(key_func=_client_ip, default_limits=[_DEFAULT_LIMIT])
