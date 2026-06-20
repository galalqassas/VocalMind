#!/usr/bin/env python3
import asyncio

import asyncpg

from app.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(settings.SUPABASE_DB_URL)
    tables = await conn.fetch(
        "select table_name from information_schema.tables "
        "where table_schema='public' order by 1"
    )
    print("Remote tables:", [r["table_name"] for r in tables])
    pc_cols = await conn.fetch(
        "select column_name from information_schema.columns "
        "where table_name='policy_compliance' order by 1"
    )
    print("policy_compliance:", [r["column_name"] for r in pc_cols])
    u_cols = await conn.fetch(
        "select column_name from information_schema.columns "
        "where table_name='users' order by 1"
    )
    print("users:", [r["column_name"] for r in u_cols])
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
