"""Correction cases repository - MySQL 8."""
from typing import List, Optional

import sqlalchemy as sa

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import correction_cases as T

FT = FlatTable(T, C.CORRECTION_COLS, C.CORRECTION_ALWAYS)


async def startup_check() -> None:
    await require_tables("correction_cases")


async def close() -> None:
    await dispose()


async def get(case_id) -> Optional[dict]:
    return await FT.get(case_id)


async def list_all(*, status_in: Optional[List[str]] = None, limit: int = 2000) -> List[dict]:
    where = [T.c.status.in_(status_in)] if status_in else []
    return await FT.select(*where, order=[T.c.created_at.desc(), T.c.id.desc()], limit=limit)


async def list_for_requisition(requisition_id: str, limit: int = 50) -> List[dict]:
    """Cases raised on a requisition, or whose replacement purchase is that requisition; oldest first."""
    in_procurement = sa.func.json_unquote(sa.func.json_extract(T.c.procurement, "$.requisition_id")) == requisition_id
    return await FT.select(sa.or_(T.c.requisition_id == requisition_id, in_procurement),
                           order=[T.c.created_at.asc(), T.c.id.asc()], limit=limit)


async def find_open_for_notification(notification_id: str, open_statuses: List[str]) -> Optional[dict]:
    return await FT.first(T.c.notification_id == notification_id, T.c.status.in_(open_statuses))


async def count_open_for_handover(handover_id: str, open_statuses: List[str]) -> int:
    return await FT.count(T.c.original_handover_id == handover_id, T.c.status.in_(open_statuses))


async def count_open_for_requisition(requisition_id: str, open_statuses: List[str]) -> int:
    return await FT.count(T.c.requisition_id == requisition_id, T.c.status.in_(open_statuses))


async def count_for_employee(user_id: str) -> int:
    return await FT.count(T.c.employee_user_id == str(user_id))


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc, C.CORRECTION_MUST_FIT)


async def update_fields(case_id, fields: dict) -> None:
    cond = FT.by_id(case_id)
    if cond is None:
        raise ValueError("Invalid correction case id")
    await FT.update([cond], fields)


async def save(doc: dict) -> None:
    """Replace the stored case with this dict (used after the case was edited in memory)."""
    cond = FT.by_id(doc.get("_id"))
    if cond is None:
        raise ValueError("Invalid correction case id")
    body = {k: v for k, v in doc.items() if k != "_id"}

    def replace(d: dict):
        d.clear()
        d.update({k: v for k, v in body.items() if v is not None})
    await FT.mutate([cond], replace)


async def save_if_version(case: dict, expected_version: int, body: dict) -> bool:
    """Version-guarded save: stores `body` only if the case is still at `expected_version`.
    False means someone else changed it first (nothing is written)."""
    cond = FT.by_id(case.get("_id"))
    if cond is None:
        return False

    def replace(d: dict):
        if (d.get("version") or 0) != expected_version:
            return False
        d.clear()
        d.update({k: v for k, v in body.items() if v is not None and k != "_id"})
    return await FT.mutate([cond], replace) > 0
