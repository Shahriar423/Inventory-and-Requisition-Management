"""GRNs repository - MySQL 8."""
from typing import List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId

from . import catalog as C
from . import rows as R
from .engine import get_engine, transaction, require_tables, dispose
from .tables import grns as T


def _pid(gid) -> Optional[str]:
    if isinstance(gid, ObjectId):
        return str(gid)
    if isinstance(gid, str) and ObjectId.is_valid(gid):
        return gid.lower()
    return None


def _doc(row) -> dict:
    d = R.decode_flat(dict(row), C.GRN_COLS, C.GRN_ALWAYS)
    d["_id"] = ObjectId(row["public_id"])
    return d


async def startup_check() -> None:
    await require_tables("grns")


async def close() -> None:
    await dispose()


async def get(gid) -> Optional[dict]:
    pid = _pid(gid)
    if not pid:
        return None
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.public_id == pid).limit(1))).mappings().first()
    return _doc(row) if row else None


async def list_all(limit: int = 1000) -> List[dict]:
    q = sa.select(T).order_by(T.c.created_at.desc(), T.c.id.desc()).limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def list_for_requisition(rid) -> List[dict]:
    """GRNs that were received against this requisition (oldest first)."""
    pid = _pid(rid)
    if not pid:
        return []
    q = sa.select(T).where(T.c.requisition_id == pid).order_by(T.c.created_at.asc(), T.c.id.asc())
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def insert(doc: dict) -> ObjectId:
    oid = doc.get("_id") or ObjectId()
    if not isinstance(oid, ObjectId):
        oid = ObjectId(str(oid))
    row = R.encode_flat({k: v for k, v in doc.items() if k != "_id"}, C.GRN_COLS)
    for must in C.GRN_MUST_FIT:
        if must not in row:
            raise ValueError(f"{must} is required")
    row["public_id"] = str(oid).lower()
    async with transaction() as conn:
        await conn.execute(sa.insert(T).values(**row))
    return oid