"""System settings - MySQL 8. Key is a string , payload is the rest of the document as JSON."""
import json
from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import insert as mysql_insert

from .engine import get_engine, transaction, require_tables, dispose
from .tables import system_settings as T


async def startup_check() -> None:
    await require_tables("system_settings")


async def close() -> None:
    await dispose()


async def get(key: str) -> Optional[dict]:
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.setting_key == key).limit(1))).mappings().first()
    if not row:
        return None
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {"_id": key, **(payload or {})}


async def upsert(key: str, fields: dict) -> None:
    """Merge fields into the settings document (upsert)."""
    existing = await get(key) or {}
    payload = {k: v for k, v in {**existing, **fields}.items() if k != "_id"}
    async with transaction() as conn:
        stmt = mysql_insert(T).values(setting_key=key, payload=payload)
        stmt = stmt.on_duplicate_key_update(payload=payload)
        await conn.execute(stmt)
