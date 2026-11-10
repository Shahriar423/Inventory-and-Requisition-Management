"""Report access grants (who may open which saved report) - MySQL 8."""
from typing import List, Optional

from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import report_access as T

FT = FlatTable(T, C.REPORT_ACCESS_COLS, C.REPORT_ACCESS_ALWAYS)


async def startup_check() -> None:
    await require_tables("report_access")


async def close() -> None:
    await dispose()


async def get(rid) -> Optional[dict]:
    return await FT.get(rid)


async def list_all(*, user_id=None, report_id=None, status=None, limit=1000) -> List[dict]:
    where = []
    if user_id:
        where.append(T.c.user_id == str(user_id))
    if report_id:
        where.append(T.c.report_id == str(report_id))
    if status:
        where.append(T.c.status == status)
    return await FT.select(*where, limit=limit)


async def find_active(report_id: str, user_id: str) -> Optional[dict]:
    return await FT.first(T.c.report_id == str(report_id), T.c.user_id == str(user_id), T.c.status == "active")


async def count_active(user_id: str) -> int:
    return await FT.count(T.c.user_id == str(user_id), T.c.status == "active")


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc, C.REPORT_ACCESS_MUST_FIT)


async def update_fields(rid, fields: dict) -> None:
    cond = FT.by_id(rid)
    if cond is not None:
        await FT.update([cond], fields)


async def update_by(filter_fields: dict, set_fields: dict) -> int:
    """Set fields on every grant matching a filter dict (columns only). Returns how many changed."""
    if not filter_fields:
        return 0
    return await FT.update([FT.where(filter_fields)], set_fields, many=True)


async def grant(report_id: str, user_id: str, fields: dict) -> None:
    """Create the grant for (report, user) or update the existing one with `fields`."""
    existing = await FT.first(T.c.report_id == str(report_id), T.c.user_id == str(user_id))
    if existing:
        await FT.update([T.c.public_id == str(existing["_id"])], fields)
    else:
        await FT.insert({"report_id": str(report_id), "user_id": str(user_id), "last_opened_at": None, **fields},
                        C.REPORT_ACCESS_MUST_FIT)


async def delete_for_report(report_id: str) -> None:
    await FT.delete(T.c.report_id == str(report_id), many=True)
