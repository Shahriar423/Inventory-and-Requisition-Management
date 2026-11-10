"""Saved reports repository - MySQL 8."""
from typing import List, Optional

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import saved_reports as T

FT = FlatTable(T, C.SAVED_REPORT_COLS, C.SAVED_REPORT_ALWAYS)


async def startup_check() -> None:
    await require_tables("saved_reports")


async def close() -> None:
    await dispose()


async def get(rid) -> Optional[dict]:
    return await FT.get(rid)


async def list_all(limit: int = 2000) -> List[dict]:
    return await FT.select(order=[T.c.created_at.desc(), T.c.id.desc()], limit=limit)


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc)


async def update_fields(rid, fields: dict) -> None:
    cond = FT.by_id(rid)
    if cond is not None:
        await FT.update([cond], fields)


async def delete(rid) -> None:
    cond = FT.by_id(rid)
    if cond is not None:
        await FT.delete(cond)
