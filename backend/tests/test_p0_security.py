"""P0 security regression tests."""

from uuid import UUID

import pytest
from sqlalchemy.sql.sqltypes import Uuid
from sqlmodel import SQLModel, Session, create_engine, select

from app.api.deps import get_current_user, get_db, get_session
from app.core.audio_resolver import fetch_audio_bytes, resolve_local_audio_path
from app.core.config import settings
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.policy import CompanyPolicy, OrganizationPolicy
from app.models.user import User

# ── SQLite UUID compatibility shim ───────────────────────
# SQLAlchemy's Uuid bind_processor for SQLite calls value.hex, which fails
# when a string UUID is passed (e.g., from a FastAPI path parameter typed as
# `str`). In production with PostgreSQL this works because PG handles the
# conversion natively. For SQLite tests, we patch the processor to accept
# both UUID objects and UUID strings.

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

# ── Policy cross-org isolation ────────────────────────────

ORG_A_ID = UUID("a0000000-0000-0000-0000-000000000001")
ORG_B_ID = UUID("a0000000-0000-0000-0000-000000000002")
USER_A_ID = UUID("a0000000-0000-0000-0000-0000000000a1")
USER_B_ID = UUID("a0000000-0000-0000-0000-0000000000b1")


@pytest.fixture
def cross_org_client(client, tmp_path, monkeypatch):
    """Set up two orgs and override deps so we can swap the authenticated user."""
    db_path = tmp_path / "cross_org.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    test_session = Session(engine)

    org_a = Organization(id=ORG_A_ID, name="Org A", slug="org-a")
    org_b = Organization(id=ORG_B_ID, name="Org B", slug="org-b")
    user_a = User(
        id=USER_A_ID,
        organization_id=ORG_A_ID,
        email="a@org.local",
        password_hash="hash",
        name="User A",
        role=UserRole.manager,
        is_active=True,
    )
    user_b = User(
        id=USER_B_ID,
        organization_id=ORG_B_ID,
        email="b@org.local",
        password_hash="hash",
        name="User B",
        role=UserRole.manager,
        is_active=True,
    )
    test_session.add_all([org_a, org_b, user_a, user_b])
    test_session.commit()

    from tests.conftest import AsyncSessionAdapter
    adapter = AsyncSessionAdapter(test_session)

    async def _override_get_db():
        yield adapter

    async def _override_get_session():
        yield adapter

    current_user_state = {"user": user_a}

    async def _override_current_user():
        return current_user_state["user"]

    client.app.dependency_overrides[get_current_user] = _override_current_user
    client.app.dependency_overrides[get_db] = _override_get_db
    client.app.dependency_overrides[get_session] = _override_get_session

    async def _noop_invalidate(session, org_filter=None):
        return 0

    monkeypatch.setattr("app.api.routes.knowledge.invalidate_llm_trigger_cache", _noop_invalidate)

    yield client, test_session, current_user_state

    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_db, None)
    client.app.dependency_overrides.pop(get_session, None)
    test_session.close()


def test_cross_org_policy_patch_returns_403(cross_org_client):
    """Org B user must not PATCH a policy owned by Org A."""
    client, test_session, current_user_state = cross_org_client

    response = client.post(
        "/api/v1/knowledge/policies",
        json={"title": "Refund", "category": "Guidelines", "content": "abc"},
    )
    assert response.status_code == 201
    policy_id = response.json()["id"]

    current_user_state["user"] = test_session.exec(
        select(User).where(User.id == USER_B_ID)
    ).first()

    response = client.patch(
        f"/api/v1/knowledge/policies/{policy_id}",
        json={"title": "Evil"},
    )
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"


def test_cross_org_policy_patch_shared_policy_returns_403(cross_org_client):
    """Org B cannot mutate a CompanyPolicy owned by Org A, even with a junction link."""
    client, test_session, current_user_state = cross_org_client

    response = client.post(
        "/api/v1/knowledge/policies",
        json={"title": "Refund", "category": "Guidelines", "content": "abc"},
    )
    assert response.status_code == 201
    policy_id = response.json()["id"]

    shared_policy = test_session.exec(
        select(CompanyPolicy).where(CompanyPolicy.id == UUID(policy_id))
    ).first()
    org_b_link = OrganizationPolicy(
        organization_id=ORG_B_ID,
        policy_id=shared_policy.id,
        is_active=True,
    )
    test_session.add(org_b_link)
    test_session.commit()

    current_user_state["user"] = test_session.exec(
        select(User).where(User.id == USER_B_ID)
    ).first()

    response = client.patch(
        f"/api/v1/knowledge/policies/{policy_id}",
        json={"title": "Evil Overwrite", "category": "Hacked", "content": "pwned"},
    )
    assert response.status_code == 403, (
        f"Expected 403 for cross-org mutation of shared policy, got {response.status_code}"
    )


def test_delete_linked_policy_removes_only_caller_link(cross_org_client):
    """An org can delete a policy it is linked to (the visibility boundary), and
    doing so removes only its own junction link — the underlying CompanyPolicy is
    preserved while another org still links it."""
    client, test_session, current_user_state = cross_org_client

    # Org A creates and owns the policy.
    response = client.post(
        "/api/v1/knowledge/policies",
        json={"title": "Refund", "category": "Guidelines", "content": "abc"},
    )
    assert response.status_code == 200
    policy_id = response.json()["id"]

    # Org B is granted a link to the same policy (e.g. a shared/seeded policy).
    test_session.add(
        OrganizationPolicy(organization_id=ORG_B_ID, policy_id=UUID(policy_id), is_active=True)
    )
    test_session.commit()

    # Org B deletes it from its own knowledge base — previously this 403'd.
    current_user_state["user"] = test_session.exec(
        select(User).where(User.id == USER_B_ID)
    ).first()
    response = client.delete(f"/api/v1/knowledge/policies/{policy_id}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    # Org B's link is gone; Org A's link and the policy itself are preserved.
    test_session.expire_all()
    links = test_session.exec(
        select(OrganizationPolicy).where(OrganizationPolicy.policy_id == UUID(policy_id))
    ).all()
    assert {link.organization_id for link in links} == {ORG_A_ID}
    assert test_session.exec(
        select(CompanyPolicy).where(CompanyPolicy.id == UUID(policy_id))
    ).first() is not None


# ── Audio resolver path traversal ───────────────────────────

@pytest.mark.asyncio
async def test_fetch_audio_bytes_rejects_relative_traversal(monkeypatch):
    """Relative path traversal via ../../ must not escape storage root.

    Clear Supabase config so the test runs offline-stable: with no Supabase
    credentials the fallback returns FileNotFoundError instead of attempting a
    network call against a configured URL.
    """
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    with pytest.raises(FileNotFoundError):
        await fetch_audio_bytes("../../etc/passwd")


@pytest.mark.asyncio
async def test_fetch_audio_bytes_rejects_absolute_path(monkeypatch):
    """Absolute paths outside the storage root must be rejected."""
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    with pytest.raises(FileNotFoundError):
        await fetch_audio_bytes("/etc/passwd")


@pytest.mark.asyncio
async def test_fetch_audio_bytes_rejects_null_byte_injection():
    """Null bytes in paths must not trick resolution (e.g. audio.wav%00../../etc/passwd)."""
    with pytest.raises(FileNotFoundError):
        await fetch_audio_bytes("audio.wav\x00../../etc/passwd")


def test_resolve_local_audio_path_rejects_path_traversal(tmp_path, monkeypatch):
    """resolve_local_audio_path must never return a path outside allowed roots."""
    storage_dir = tmp_path / "storage" / "uploads"
    storage_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "LOCAL_AUDIO_STORAGE_DIR", str(storage_dir))

    dangerous_paths = [
        "../../etc/passwd",
        "/etc/passwd",
        "../../../etc/shadow",
        "audio.wav\x00../../etc/passwd",
    ]
    for path in dangerous_paths:
        result = resolve_local_audio_path(path)
        assert result is None, f"Expected None for {path!r}, got {result}"


def test_resolve_local_audio_path_allows_valid_path(tmp_path, monkeypatch):
    """A legitimate relative path inside the storage root should be resolved."""
    storage_dir = tmp_path / "storage" / "uploads"
    sub_dir = storage_dir / "org-a"
    sub_dir.mkdir(parents=True, exist_ok=True)
    test_file = sub_dir / "call.wav"
    test_file.write_bytes(b"RIFFfakeaudio")

    monkeypatch.setattr(settings, "LOCAL_AUDIO_STORAGE_DIR", str(storage_dir))
    monkeypatch.chdir(tmp_path)

    result = resolve_local_audio_path("storage/uploads/org-a/call.wav")
    assert result is not None
    assert result == test_file.resolve()


def test_resolve_local_audio_path_symlink_escape(tmp_path, monkeypatch):
    """A symlink inside the storage dir pointing outside must not be followed out."""
    storage_dir = tmp_path / "storage" / "uploads"
    storage_dir.mkdir(parents=True)

    outside_dir = tmp_path / "secret"
    outside_dir.mkdir()
    secret_file = outside_dir / "passwd"
    secret_file.write_text("root:x:0:0::/root:/bin/bash")

    symlink = storage_dir / "escape.wav"
    try:
        symlink.symlink_to(secret_file)
    except OSError:
        pytest.skip("Platform does not support symlinks")

    monkeypatch.setattr(settings, "LOCAL_AUDIO_STORAGE_DIR", str(storage_dir))

    result = resolve_local_audio_path("escape.wav")
    assert result is None, (
        f"Symlink escape returned {result}; must not resolve symlinks that point outside storage root"
    )

