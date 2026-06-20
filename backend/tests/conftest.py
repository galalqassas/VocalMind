"""
Shared pytest fixtures and configuration for the VocalMind Backend.

This module provides common fixtures for testing FastAPI endpoints, including
a pre-configured TestClient and mocked database sessions to ensure tests
remain isolated from production data.
"""

import os

# RAG service Settings() reads GROQ_API_KEY at import time during contract tests.
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("OLLAMA_CLOUD_API_KEY", "test_key_for_tests")
os.environ.setdefault("OLLAMA_API_KEY", "test_key_for_tests")
os.environ.setdefault("LLM_PROVIDER", "ollama_cloud")
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_minimum_x")

import pytest
import importlib
from typing import Generator
from unittest.mock import AsyncMock, MagicMock
from app.api.deps import get_session, get_supabase, get_db
from app.core.config import settings
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel

# Stub startup/lifespan hooks to keep tests isolated and fast.
app_main = importlib.import_module("app.main")
app_main.create_db_and_tables = AsyncMock(return_value=None)
app_main.prewarm_dashboard_cache = AsyncMock(return_value=None)
app_main.seed_nexalink_main = AsyncMock(return_value=None)
app_main.seed_meridian_main = AsyncMock(return_value=None)
app_main.start_processing_worker = AsyncMock(return_value=None)
app_main.stop_processing_worker = AsyncMock(return_value=None)
app_main.start_audio_folder_watcher = AsyncMock(return_value=None)
app_main.stop_audio_folder_watcher = AsyncMock(return_value=None)
app = app_main.app
settings.SECRET_KEY = "test-secret-key-minimum-32-bytes-long"
settings.GROQ_API_KEY = "test-groq-key"
settings.OLLAMA_CLOUD_API_KEY = "test_key_for_tests"
settings.LLM_PROVIDER = "ollama_cloud"

# --- Fixtures ---

@pytest.fixture(autouse=True, scope="session")
def set_test_env():
    """Set minimum required env vars so validate_startup_settings() doesn't raise."""
    os.environ.setdefault("OLLAMA_CLOUD_API_KEY", "test_key_for_tests")
    os.environ.setdefault("OLLAMA_API_KEY", "test_key_for_tests")
    os.environ.setdefault("LLM_PROVIDER", "ollama_cloud")
    os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_minimum_x")
    yield

@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Provides a functional SQLite in-memory Session for testing."""
    # Import ALL models to ensure they are registered with SQLModel.metadata
    # before create_all is called — otherwise tables won't be created.
    import app.models  # noqa: F401 — triggers all sub-imports via __init__.py
    
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client", autouse=True)
def client_fixture(session: Session) -> Generator[TestClient, None, None]:
    """
    Provides a FastAPI TestClient with database and supabase dependencies overriden.
    """
    async def _get_session_override():
        yield session
    
    def _get_supabase_override():
        return MagicMock()

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_db] = _get_session_override
    app.dependency_overrides[get_supabase] = _get_supabase_override
    
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def _mock_health_asyncpg(monkeypatch):
    """Health checks should not require a live Postgres instance in unit tests."""

    class _FakeConn:
        async def execute(self, _sql):
            return None

        async def close(self):
            return None

    async def _fake_connect(**_kwargs):
        return _FakeConn()

    monkeypatch.setattr("app.main.asyncpg.connect", _fake_connect)

@pytest.fixture(name="mock_user")
def mock_user_fixture() -> dict:
    """Provides a sample mock user dictionary for authentication tests."""
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "email": "test@vocalmind.ai",
        "full_name": "Test User",
        "role": "manager"
    }


class AsyncSessionAdapter:
    """
    Wraps a synchronous SQLModel Session in an async interface,
    mimicking AsyncSession for dependency overrides in tests.
    """
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def exec(self, statement):
        return self._session.exec(statement)

    async def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)

    def add(self, instance):
        self._session.add(instance)

    def add_all(self, instances):
        self._session.add_all(instances)

    async def flush(self):
        self._session.flush()

    async def commit(self):
        self._session.commit()

    async def refresh(self, instance):
        self._session.refresh(instance)

    async def rollback(self):
        self._session.rollback()

    async def delete(self, instance):
        self._session.delete(instance)

    async def close(self):
        self._session.close()

