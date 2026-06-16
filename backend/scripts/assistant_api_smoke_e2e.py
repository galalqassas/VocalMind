import asyncio
import json
import sys
from pathlib import Path

import asyncpg
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.core import security
from app.core.config import settings


MANAGER_ID = "b0000000-0000-0000-0000-000000000001"
ORG_ID = "a0000000-0000-0000-0000-000000000001"


def _pg_dsn_from_sqlalchemy_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _insert_previous_sql(conn: asyncpg.Connection, sql: str) -> None:
    await conn.execute(
        """
        INSERT INTO assistant_queries
        (user_id, organization_id, query_mode, query_text, generated_sql, response_text, execution_time_ms)
        VALUES ($1, $2, 'chat', 'seed previous', $3, 'seed', 1)
        """,
        MANAGER_ID,
        ORG_ID,
        sql,
    )


def _call_api(query_text: str) -> dict:
    token = security.create_access_token(MANAGER_ID)
    response = requests.post(
        "http://host.docker.internal:8000/api/v1/assistant/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"query_text": query_text, "mode": "chat"},
        timeout=90,
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return {
        "request": {"query_text": query_text, "mode": "chat"},
        "status_code": response.status_code,
        "response": body,
    }


async def main() -> None:
    dsn = _pg_dsn_from_sqlalchemy_url(settings.DATABASE_URL)
    conn = await asyncpg.connect(dsn)
    try:
        cases = [
            (
                "safe",
                "SELECT i.id, i.organization_id FROM interactions i "
                "WHERE i.organization_id = 'a0000000-0000-0000-0000-000000000001' "
                "ORDER BY i.id ASC LIMIT 5",
                "second one",
            ),
            (
                "select_star",
                "SELECT * FROM interactions "
                "WHERE organization_id = 'a0000000-0000-0000-0000-000000000001' LIMIT 50",
                "second one",
            ),
            (
                "multi_statement",
                "SELECT id FROM interactions "
                "WHERE organization_id = 'a0000000-0000-0000-0000-000000000001' LIMIT 10; DROP TABLE users",
                "second one",
            ),
            (
                "password_hash",
                "SELECT id, password_hash FROM users "
                "WHERE organization_id = 'a0000000-0000-0000-0000-000000000001' LIMIT 5",
                "second one",
            ),
        ]

        out = []
        for case_name, previous_sql, query_text in cases:
            await _insert_previous_sql(conn, previous_sql)
            api_result = _call_api(query_text)
            out.append(
                {
                    "case": case_name,
                    "seed_previous_sql": previous_sql,
                    **api_result,
                }
            )
        print(json.dumps(out, indent=2))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
