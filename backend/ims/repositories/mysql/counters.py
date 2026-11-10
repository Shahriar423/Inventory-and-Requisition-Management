"""Counters repository - MySQL 8 implementation (atomic sequence numbers for PR/PO)."""
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import insert as mysql_insert

from .engine import get_engine, transaction, require_tables, dispose
from .tables import counters as T


async def startup_check() -> None:
    await require_tables("counters")


async def close() -> None:
    await dispose()


async def get(counter_key: str) -> Optional[dict]:
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.counter_key == counter_key).limit(1))).mappings().first()
    if not row:
        return None
    return {"_id": row["counter_key"], "seq": row["seq"]}


async def find_one_and_inc(counter_key: str) -> dict:
    """Atomically increment seq and return the new document."""
    async with transaction() as conn:
        # Upsert: insert with seq=1 if missing, else increment
        stmt = mysql_insert(T).values(counter_key=counter_key, seq=1)
        stmt = stmt.on_duplicate_key_update(seq=T.c.seq + 1)
        await conn.execute(stmt)
        row = (await conn.execute(sa.select(T).where(T.c.counter_key == counter_key).limit(1))).mappings().first()
    return {"_id": row["counter_key"], "seq": row["seq"]}
