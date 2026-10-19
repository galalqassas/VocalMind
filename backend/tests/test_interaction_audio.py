"""GET /interactions/{id}/audio returns 404 when the audio is missing (never a generated stand-in)."""

from uuid import UUID

import pytest

from app.api.deps import get_current_user, get_db, get_session
from app.models.enums import UserRole
from app.models.user import User

INTERACTION_ID = UUID("c0000000-0000-0000-0000-000000000001")


@pytest.fixture
def audio_client(client):
    """Return a factory that makes the interaction lookup yield `audio_path`."""

    def _make(audio_path: str | None):
        class _Result:
            def first(self):
                return (INTERACTION_ID, audio_path)

        class _Session:
            async def exec(self, _statement):
                return _Result()

        async def _db():
            yield _Session()

        async def _user():
            return User(
                id=UUID("b0000000-0000-0000-0000-000000000001"),
                organization_id=UUID("a0000000-0000-0000-0000-000000000001"),
                email="manager@orga.local",
                password_hash="hash",
                name="Manager A",
                role=UserRole.manager,
                is_active=True,
            )

        client.app.dependency_overrides[get_db] = _db
        client.app.dependency_overrides[get_session] = _db
        client.app.dependency_overrides[get_current_user] = _user
        return client

    yield _make
    for dep in (get_current_user, get_db, get_session):
        client.app.dependency_overrides.pop(dep, None)


def test_audio_returns_404_when_interaction_has_no_audio_path(audio_client):
    response = audio_client(None).get(f"/api/v1/interactions/{INTERACTION_ID}/audio")
    assert response.status_code == 404
    assert response.json()["detail"] == "Audio file not found"


def test_audio_returns_404_when_audio_file_is_missing(audio_client, monkeypatch):
    async def _missing(*_args, **_kwargs):
        raise FileNotFoundError("org/call.wav")

    monkeypatch.setattr("app.api.routes.interactions.fetch_audio_bytes", _missing)
    response = audio_client("org/call.wav").get(f"/api/v1/interactions/{INTERACTION_ID}/audio")
    assert response.status_code == 404
    assert response.json()["detail"] == "Audio file not found"
