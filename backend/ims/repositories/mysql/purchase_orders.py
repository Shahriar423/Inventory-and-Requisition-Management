"""Purchase Order repository - MySQL 8 implementation."""
from typing import Dict, Iterable, List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId

from . import catalog as C
from . import rows as R
from .engine import get_engine, transaction, require_tables, dispose
from .flat import FlatTable
from .tables import purchase_orders as T


_FT = FlatTable(T, C.PO_COLS, C.PO_ALWAYS)


def _pid(po_id) -> Optional[str]:
    if isinstance(po_id, ObjectId):
        return str(po_id)
    if isinstance(po_id, str) and ObjectId.is_valid(po_id):
        return po_id.lower()
    return None


def _doc(row) -> dict:
    d = R.decode_flat(dict(row), C.PO_COLS, C.PO_ALWAYS)
    d["_id"] = ObjectId(row["public_id"])
    return d


async def startup_check() -> None:
    await require_tables("purchase_orders")


async def close() -> None:
    await dispose()


# ----------------------------------------------------------------------------------------- reads
async def get(po_id) -> Optional[dict]:
    pid = _pid(po_id)
    if not pid:
        return None
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.public_id == pid).limit(1))).mappings().first()
    return _doc(row) if row else None


async def list_all(*, created_by: Optional[tuple] = None, limit: int = 1000) -> List[dict]:
    q = sa.select(T)
    if created_by:
        uid, uname = created_by
        q = q.where(sa.or_(T.c.created_by_id == uid, T.c.created_by == uname))
    q = q.order_by(T.c.created_at.desc(), T.c.id.desc()).limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def list_submitted(limit: int = 100000) -> List[dict]:
    q = sa.select(T).where(T.c.status != "draft").limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def list_for_requisition(requisition_id: str, limit: int = 20) -> List[dict]:
    q = (sa.select(T)
         .where(T.c.requisition_id == requisition_id)
         .order_by(T.c.created_at.asc(), T.c.id.asc())
         .limit(limit))
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def group_by_requisition(requisition_ids: Iterable[str]) -> Dict[str, List[dict]]:
    ids = list(requisition_ids)
    if not ids:
        return {}
    q = (sa.select(T)
         .where(T.c.requisition_id.in_(ids))
         .order_by(T.c.created_at.asc(), T.c.id.asc()))
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    grouped: Dict[str, List[dict]] = {}
    for r in rows:
        d = _doc(r)
        grouped.setdefault(d["requisition_id"], []).append(d)
    return grouped


async def list_in_statuses(statuses: Iterable[str]) -> List[dict]:
    q = sa.select(T).where(T.c.status.in_(list(statuses)))
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def list_with_quote_file(file_id: str) -> List[dict]:
    # JSON_CONTAINS for the array of file ids
    q = sa.select(T).where(sa.func.json_contains(T.c.cs_attachment_file_ids, sa.func.json_quote(file_id)))
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def count_in_statuses(statuses: Iterable[str]) -> int:
    q = sa.select(sa.func.count()).select_from(T).where(T.c.status.in_(list(statuses)))
    async with get_engine().connect() as conn:
        return int((await conn.execute(q)).scalar() or 0)


async def count_with_status(status: str) -> int:
    q = sa.select(sa.func.count()).select_from(T).where(T.c.status == status)
    async with get_engine().connect() as conn:
        return int((await conn.execute(q)).scalar() or 0)


async def count_created_by(user_id: str, user_name: str) -> int:
    q = sa.select(sa.func.count()).select_from(T).where(
        sa.or_(T.c.created_by_id == user_id, T.c.created_by == user_name))
    async with get_engine().connect() as conn:
        return int((await conn.execute(q)).scalar() or 0)


# ---------------------------------------------------------------------------------------- writes
async def insert(doc: dict) -> ObjectId:
    oid = doc.get("_id") or ObjectId()
    if not isinstance(oid, ObjectId):
        oid = ObjectId(str(oid))
    row = R.encode_flat({k: v for k, v in doc.items() if k != "_id"}, C.PO_COLS)
    for must in C.PO_MUST_FIT:
        if must not in row:
            raise ValueError(f"{must} is required")
    row["public_id"] = str(oid).lower()
    async with transaction() as conn:
        await conn.execute(sa.insert(T).values(**row))
    return oid


async def update_fields(po_id, fields: dict) -> None:
    pid = _pid(po_id)
    if not pid:
        raise ValueError("Invalid Purchase Order id")
    # read-modify-write under a row lock: None clears a field, fields not mentioned (and `extra`) are kept
    await _FT.update([T.c.public_id == pid], fields)


async def mark_reminded(po_id, status: str, reminded_at: str) -> None:
    await update_fields(po_id, {"reminder": {"status": status, "reminded_at": reminded_at}})
