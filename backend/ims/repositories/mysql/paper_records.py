"""Paper records (scanned handover / takeover forms) repository - MySQL 8."""
from typing import List, Optional

import sqlalchemy as sa

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import paper_records as T

FT = FlatTable(T, C.PAPER_COLS, C.PAPER_ALWAYS)


async def startup_check() -> None:
    await require_tables("paper_records")


async def close() -> None:
    await dispose()


async def get(rid) -> Optional[dict]:
    return await FT.get(rid)


async def list_all(limit: int = 5000) -> List[dict]:
    return await FT.select(order=[T.c.created_at.desc(), T.c.id.desc()], limit=limit)


async def search(*, employee_id: Optional[str] = None, asset_id: Optional[str] = None, kind: Optional[str] = None,
                 text: Optional[str] = None, limit: int = 300) -> List[dict]:
    """Newest first. employee / kind are filtered in SQL; the device and the free-text box (which also looks at
    e-mail, form number and remarks, kept outside the columns) on the rows that come back."""
    where = []
    if employee_id:
        where.append(T.c.employee_id == employee_id)
    if kind:
        where.append(T.c.kind == kind)
    docs = await FT.select(*where, order=[T.c.created_at.desc(), T.c.id.desc()])
    if asset_id:
        docs = [d for d in docs if asset_id in (d.get("asset_ids") or [])]
    if text and text.strip():
        needle = text.strip().lower()
        keys = ("employee_name", "employee_email", "form_no", "remarks")
        docs = [d for d in docs if any(needle in str(d.get(k) or "").lower() for k in keys)]
    return docs[:max(1, limit)]


async def any_uses_file(file_id: str) -> bool:
    return any(file_id in (d.get("file_ids") or []) for d in await FT.select())


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc)


async def update_fields(rid, fields: dict) -> None:
    cond = FT.by_id(rid)
    if cond is not None:
        await FT.update([cond], fields)


async def remove_asset(rid, asset_id: str) -> None:
    """Take one asset off a record's asset_ids."""
    cond = FT.by_id(rid)
    if cond is None:
        return

    def drop(d: dict):
        d["asset_ids"] = [a for a in (d.get("asset_ids") or []) if a != asset_id]
    await FT.mutate([cond], drop)


async def delete(rid) -> None:
    cond = FT.by_id(rid)
    if cond is not None:
        await FT.delete(cond)
