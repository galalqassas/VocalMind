import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _assistant_db_url() -> str:
    return os.getenv("ASSISTANT_DATABASE_URL", "").strip()


async def _run_sql(sql: str):
    db_url = _assistant_db_url()
    if not db_url:
        pytest.skip("ASSISTANT_DATABASE_URL is not configured")
    engine = create_async_engine(
        db_url,
        future=True,
        pool_pre_ping=True,
        connect_args={
            "prepared_statement_cache_size": 0,
            "statement_cache_size": 0,
        },
    )
    try:
        async with engine.connect() as conn:
            return await conn.execute(text(sql))
    finally:
        await engine.dispose()


def _assert_permission_denied(exc: Exception) -> None:
    msg = str(exc).lower()
    assert (
        "permission denied" in msg
        or "insufficient privilege" in msg
        or "must be owner" in msg
    ), msg


@pytest.mark.asyncio
async def test_assistant_readonly_role_allows_realistic_scoped_select():
    result = await _run_sql(
        """
        SELECT
            u.id AS user_id,
            u.organization_id,
            u.name,
            u.email,
            u.role,
            u.agent_type,
            u.is_active,
            i.id AS interaction_id,
            i.duration_seconds,
            i.interaction_date,
            i.processing_status,
            i.language_detected,
            i.has_overlap,
            s.overall_score,
            s.total_silence_seconds,
            s.avg_response_time_seconds,
            pc.compliance_score,
            pc.llm_reasoning,
            cp.organization_id AS policy_organization_id,
            cp.policy_title,
            cp.policy_category,
            cp.policy_text,
            cp.is_active AS policy_is_active,
            ut.speaker_role,
            ut.emotion,
            ut.start_time_seconds,
            ut.end_time_seconds,
            o.id AS org_id,
            o.name AS org_name
        FROM interactions i
        JOIN users u ON u.id = i.agent_id
        JOIN organizations o ON o.id = i.organization_id
        LEFT JOIN interaction_scores s ON s.interaction_id = i.id
        LEFT JOIN policy_compliance pc ON pc.interaction_id = i.id
        LEFT JOIN company_policies cp ON cp.id = pc.policy_id
        LEFT JOIN utterances ut ON ut.interaction_id = i.id
        WHERE i.organization_id = (
            SELECT organization_id
            FROM interactions
            LIMIT 1
        )
        LIMIT 5
        """
    )
    keys = set(result.keys())
    assert "user_id" in keys
    assert "total_silence_seconds" in keys
    assert "llm_reasoning" in keys
    assert "policy_organization_id" in keys


@pytest.mark.asyncio
async def test_assistant_readonly_role_cannot_select_users_password_hash():
    with pytest.raises(Exception) as exc_info:
        await _run_sql("SELECT password_hash FROM users LIMIT 1")
    _assert_permission_denied(exc_info.value)


@pytest.mark.asyncio
async def test_assistant_readonly_role_cannot_select_policy_evidence_text():
    with pytest.raises(Exception) as exc_info:
        await _run_sql("SELECT evidence_text FROM policy_compliance LIMIT 1")
    _assert_permission_denied(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO users (id, organization_id, email, password_hash, name, role, is_active, created_at) "
        "VALUES (gen_random_uuid(), gen_random_uuid(), 'readonly_probe@test.local', 'x', 'Probe', 'agent', true, now())",
        "UPDATE users SET name = 'Probe Update' WHERE 1 = 0",
        "DELETE FROM users WHERE 1 = 0",
        "TRUNCATE TABLE users",
        "CREATE TABLE readonly_probe (id INTEGER)",
    ],
)
async def test_assistant_readonly_role_cannot_execute_mutating_or_ddl_statements(statement: str):
    with pytest.raises(Exception) as exc_info:
        await _run_sql(statement)
    _assert_permission_denied(exc_info.value)
