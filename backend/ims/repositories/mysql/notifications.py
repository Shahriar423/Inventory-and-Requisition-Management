"""Notifications repository - MySQL 8."""
from typing import List, Optional

import sqlalchemy as sa

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import notifications as T

FT = FlatTable(T, C.NOTIF_COLS, C.NOTIF_ALWAYS)


async def startup_check() -> None:
    await require_tables("notifications")


async def close() -> None:
    await dispose()


async def get(nid) -> Optional[dict]:
    return await FT.get(nid)


async def list_for_user(user_id: str, statuses: List[str], limit: int = 100) -> List[dict]:
    return await FT.select(T.c.user_id == str(user_id), T.c.status.in_(statuses),
                           order=[T.c.created_at.desc(), T.c.id.desc()], limit=limit)


async def count(query: dict) -> int:
    """Notifications matching a filter dict over its columns (user_id, type, status, handover_id, requisition_id ...)."""
    return await FT.count_filtered(query)


async def exists(query: dict) -> bool:
    return await FT.count_filtered(query) > 0


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc, C.NOTIF_MUST_FIT)


async def update_fields(nid, fields: dict) -> None:
    cond = FT.by_id(nid)
    if cond is None:
        raise ValueError("Invalid notification id")
    await FT.update([cond], fields)


async def update_where(query: dict, fields: dict) -> int:
    """Set fields on EVERY notification matching a filter dict (columns only). Returns how many changed."""
    return await FT.update([FT.where(query)], fields, many=True)


async def resolve_for_correction_case(case_id: str, from_status: str = "correction", to_status: str = "read") -> int:
    """Close the bell entry of a correction case (`correction_case_id` is not a column, so it is checked on the row)."""
    def close_it(d: dict):
        if d.get("correction_case_id") != case_id:
            return False
        d["status"] = to_status
    return await FT.mutate([T.c.status == from_status], close_it, many=True)
