"""Handovers (issue / return slips) repository - MySQL 8."""
from typing import Iterable, List, Optional

import sqlalchemy as sa

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import handovers as T

FT = FlatTable(T, C.HANDOVER_COLS, C.HANDOVER_ALWAYS)


async def startup_check() -> None:
    await require_tables("handovers")


async def close() -> None:
    await dispose()


async def get(hid) -> Optional[dict]:
    return await FT.get(hid)


async def get_many(ids: Iterable) -> List[dict]:
    pids = [p for p in (FT.pid(i) for i in set(ids or [])) if p]
    return await FT.select(T.c.public_id.in_(pids)) if pids else []


async def list_all(limit: int = 1000) -> List[dict]:
    return await FT.select(order=[T.c.created_at.desc(), T.c.id.desc()], limit=limit)


async def list_for_requisition(requisition_id: str, also_id: Optional[str] = None, limit: int = 20) -> List[dict]:
    """Slips of one requisition (plus one slip by id, e.g. the one linked on the requisition), oldest first."""
    cond = T.c.requisition_id == requisition_id
    pid = FT.pid(also_id) if also_id else None
    if pid:
        cond = sa.or_(cond, T.c.public_id == pid)
    return await FT.select(cond, order=[T.c.created_at.asc(), T.c.id.asc()], limit=limit)


async def count_for_employee(user_id: str) -> int:
    return await FT.count(T.c.employee_user_id == str(user_id))


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc, C.HANDOVER_MUST_FIT)


async def update_fields(hid, fields: dict) -> None:
    cond = FT.by_id(hid)
    if cond is None:
        raise ValueError("Invalid handover id")
    await FT.update([cond], fields)


async def delete(hid) -> None:
    cond = FT.by_id(hid)
    if cond is not None:
        await FT.delete(cond)


async def push_correction_case(hid, case_id: str) -> None:
    """Append a correction case id to the slip's correction_case_ids (once)."""
    cond = FT.by_id(hid)
    if cond is None:
        return

    def add(d: dict):
        ids = list(d.get("correction_case_ids") or [])
        if case_id in ids:
            return False
        ids.append(case_id)
        d["correction_case_ids"] = ids
    await FT.mutate([cond], add)
