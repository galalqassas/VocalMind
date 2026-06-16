from uuid import UUID

from sqlalchemy.sql.sqltypes import Uuid

from app.api.deps import get_current_user
from app.models.enums import UserRole
from app.models.user import User

_original_uuid_bind_processor = Uuid.bind_processor


def _sqlite_safe_uuid_bind_processor(self, dialect):
    processor = _original_uuid_bind_processor(self, dialect)
    if processor is None:
        return None

    def safe_process(value):
        if value is not None and isinstance(value, str):
            try:
                value = UUID(value)
            except ValueError:
                pass
        return processor(value)

    return safe_process


Uuid.bind_processor = _sqlite_safe_uuid_bind_processor


def test_assistant_rejects_sql_without_org_tenant_filter(client, monkeypatch):
    async def _override_current_user():
        return User(
            id=UUID("b0000000-0000-0000-0000-000000000001"),
            organization_id=UUID("a0000000-0000-0000-0000-000000000001"),
            email="manager@test.local",
            password_hash="hash",
            name="Manager",
            role=UserRole.manager,
            is_active=True,
        )

    class _FakeResult:
        def all(self):
            return []

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _statement, *_args, **_kwargs):
            return _FakeResult()

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class _FakeEngine:
        def connect(self):
            return _FakeConn()

    async def _fake_resolve_sql(_self, _q, _org_id, _conversation_block="", **_kwargs):
        return "SELECT id, email FROM users LIMIT 10"

    monkeypatch.setattr("app.api.routes.assistant.engine", _FakeEngine())
    monkeypatch.setattr("app.api.routes.assistant.IntentResolver.resolve_sql", _fake_resolve_sql)
    monkeypatch.setattr("app.api.routes.assistant.IntentResolver.synthesize_answer", lambda *_a, **_k: "ok")

    client.app.dependency_overrides[get_current_user] = _override_current_user

    response = client.post(
        "/api/v1/assistant/query",
        json={"query_text": "list users", "mode": "chat"},
    )

    client.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is False
    assert "organization-scoped" in body.get("content", "").lower()
