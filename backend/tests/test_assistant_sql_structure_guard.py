from uuid import UUID

from app.api.deps import get_current_user
from app.models.enums import UserRole
from app.models.user import User


def _override_manager():
    async def _inner():
        return User(
            id=UUID("b0000000-0000-0000-0000-000000000001"),
            organization_id=UUID("a0000000-0000-0000-0000-000000000001"),
            email="manager@test.local",
            password_hash="hash",
            name="Manager",
            role=UserRole.manager,
            is_active=True,
        )

    return _inner


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement, *_args, **_kwargs):
        return _FakeResult(self._rows)

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _FakeEngine:
    def __init__(self, rows=None):
        self._rows = rows or []

    def connect(self):
        return _FakeConn(self._rows)


def test_assistant_rejects_select_star_exfiltration(client, monkeypatch):
    async def _fake_resolve_sql(_self, _q, _org_id, _conversation_block="", **_kwargs):
        return "SELECT * FROM interactions WHERE organization_id = 'a0000000-0000-0000-0000-000000000001' LIMIT 50"

    monkeypatch.setattr("app.api.routes.assistant.engine", _FakeEngine())
    monkeypatch.setattr("app.api.routes.assistant.IntentResolver.resolve_sql", _fake_resolve_sql)
    client.app.dependency_overrides[get_current_user] = _override_manager()

    response = client.post("/api/v1/assistant/query", json={"query_text": "show all", "mode": "chat"})

    client.app.dependency_overrides.pop(get_current_user, None)
    body = response.json()
    assert response.status_code == 200
    assert body.get("success") is False
    assert "safe analytics queries" in body.get("content", "").lower()
    assert "wildcard projection" in body.get("content", "").lower()


def test_assistant_rejects_multi_statement_injection(client, monkeypatch):
    async def _fake_resolve_sql(_self, _q, _org_id, _conversation_block="", **_kwargs):
        return (
            "SELECT id FROM interactions WHERE organization_id = 'a0000000-0000-0000-0000-000000000001' LIMIT 10; "
            "DROP TABLE users"
        )

    monkeypatch.setattr("app.api.routes.assistant.engine", _FakeEngine())
    monkeypatch.setattr("app.api.routes.assistant.IntentResolver.resolve_sql", _fake_resolve_sql)
    client.app.dependency_overrides[get_current_user] = _override_manager()

    response = client.post("/api/v1/assistant/query", json={"query_text": "do attack", "mode": "chat"})

    client.app.dependency_overrides.pop(get_current_user, None)
    body = response.json()
    assert response.status_code == 200
    assert body.get("success") is False
    assert "safe analytics queries" in body.get("content", "").lower()
    assert "exactly one statement" in body.get("content", "").lower()
