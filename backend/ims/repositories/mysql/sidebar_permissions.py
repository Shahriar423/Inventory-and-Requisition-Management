"""Sidebar-permission repository - MySQL 8 implementation. One saved menu list per role (absent = use the defaults)."""
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import insert as mysql_insert

from .engine import get_engine, transaction
from .tables import sidebar_permissions as T


async def get_items(role: str) -> Optional[List[str]]:
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T.c["items"]).where(T.c.role == role))).first()
    return list(row[0]) if row else None


async def set_items(role: str, items: List[str]) -> None:
    async with transaction() as conn:
        stmt = mysql_insert(T).values(role=role, items=items)
        await conn.execute(stmt.on_duplicate_key_update(items=stmt.inserted["items"]))


async def startup_check() -> None:
    from .engine import require_tables
    await require_tables("sidebar_permissions")


async def close() -> None:
    from .engine import dispose
    await dispose()


__all__ = ["startup_check", "close", "get_items", "set_items"]
