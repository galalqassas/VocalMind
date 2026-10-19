"""
Tests for auth routes and logic.

Covers password login and Google ID-token login (existing users only)
using an injected Mock AsyncSession.
"""

from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_password_hash
from app.models.user import User as UserModel


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db_session(client: TestClient):
    """Overrides get_db with an AsyncMock session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    # Default: select().where() returns empty result
    session.exec.return_value.first.return_value = None
    
    from app.api.deps import get_db, get_session
    async def _override_get_db():
        yield session

    client.app.dependency_overrides[get_db] = _override_get_db
    client.app.dependency_overrides[get_session] = _override_get_db
    yield session
    client.app.dependency_overrides.pop(get_db, None)
    client.app.dependency_overrides.pop(get_session, None)


def _fake_user(email="agent@test.com", password="correct", is_active=True) -> UserModel:
    return UserModel(
        id=uuid4(),
        organization_id=uuid4(),
        email=email,
        password_hash=get_password_hash(password) if password else None,
        name="Test",
        role="agent",
        is_active=is_active,
    )


def _mock_exec_results(mock_session, *results):
    """Queue up fetch results for sequential session.exec() calls."""
    mock_results = []
    for res in results:
        m = MagicMock()
        m.first.return_value = res
        mock_results.append(m)
    mock_session.exec.side_effect = mock_results


# ── Password Login Tests ─────────────────────────────────────────────────────

def test_login_valid_credentials(client: TestClient, mock_db_session: AsyncMock):
    _mock_exec_results(mock_db_session, _fake_user(password="right"))
    response = client.post("/api/v1/auth/login/access-token", data={"username": "agent@test.com", "password": "right"})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password(client: TestClient, mock_db_session: AsyncMock):
    _mock_exec_results(mock_db_session, _fake_user(password="right"))
    response = client.post("/api/v1/auth/login/access-token", data={"username": "agent@test.com", "password": "wrong"})
    assert response.status_code == 400


def test_login_nonexistent_user(client: TestClient, mock_db_session: AsyncMock):
    _mock_exec_results(mock_db_session, None)
    response = client.post("/api/v1/auth/login/access-token", data={"username": "ghost@test.com", "password": "any"})
    assert response.status_code == 400


def test_login_inactive_user(client: TestClient, mock_db_session: AsyncMock):
    _mock_exec_results(mock_db_session, _fake_user(is_active=False))
    response = client.post("/api/v1/auth/login/access-token", data={"username": "inactive@test.com", "password": "pw"})
    assert response.status_code == 400


# ── Google Direct Auth ───────────────────────────────────────────────────────

@patch("app.api.routes.auth.router.verify_google_token")
def test_google_direct_auth_existing_user(mock_verify, client: TestClient, mock_db_session: AsyncMock):
    mock_verify.return_value = MagicMock(email="test@google.com", name="G")
    _mock_exec_results(mock_db_session, _fake_user(email="test@google.com"))
    response = client.post("/api/v1/auth/google?token=good")
    assert response.status_code == 200
    assert "access_token" in response.json()


@patch("app.api.routes.auth.router.verify_google_token")
def test_google_direct_auth_rejects_unknown_email(mock_verify, client: TestClient, mock_db_session: AsyncMock):
    mock_verify.return_value = MagicMock(email="new@google.com", name="New")
    _mock_exec_results(mock_db_session, None)

    response = client.post("/api/v1/auth/google?token=good")
    assert response.status_code == 403
    assert response.json()["detail"] == "No VocalMind account for this email; ask your manager to add you."
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()


@patch("app.api.routes.auth.router.verify_google_token")
def test_google_direct_auth_rejects_inactive_user(mock_verify, client: TestClient, mock_db_session: AsyncMock):
    mock_verify.return_value = MagicMock(email="test@google.com", name="G")
    _mock_exec_results(mock_db_session, _fake_user(email="test@google.com", is_active=False))
    response = client.post("/api/v1/auth/google?token=good")
    assert response.status_code == 400


def test_google_direct_invalid_token(client: TestClient):
    with patch("app.api.routes.auth.router.verify_google_token", return_value=None):
        response = client.post("/api/v1/auth/google?token=bad-token")
    assert response.status_code == 400


def test_token_validation_no_auth(client: TestClient):
    # /reviews/queue is the new manager-only entry point that replaces the
    # retired /emotion-events/flagged endpoint. Without a cookie or bearer
    # header, the standard auth dep rejects with 401.
    response = client.get("/api/v1/reviews/queue")
    assert response.status_code == 401
