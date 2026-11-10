"""Asset history (append-only life log of each asset) - MySQL 8."""
from typing import List, Optional, Sequence

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import asset_history as T

FT = FlatTable(T, C.AH_COLS, C.AH_ALWAYS, C.AH_COLUMN_OF)


async def startup_check() -> None:
    await require_tables("asset_history")


async def close() -> None:
    await dispose()


async def list_for_asset(asset_id: str, limit: int = 500) -> List[dict]:
    return await FT.select(T.c.asset_id == str(asset_id), order=[T.c.at.desc(), T.c.id.desc()], limit=limit)


async def find(flt: Optional[dict] = None, *, sort: Optional[Sequence] = None, limit: Optional[int] = None) -> List[dict]:
    """Events matching a filter dict, e.g. {"employee_user_id": {"$in": [...]}, "event": "returned"}."""
    return await FT.find(flt, sort=sort, limit=limit)


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc, C.AH_MUST_FIT)


async def insert_many(docs: List[dict]) -> List[ObjectId]:
    return await FT.insert_many(docs, C.AH_MUST_FIT)
