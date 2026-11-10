"""Department repository - MySQL 8 implementation (SQLAlchemy Core, async)."""
from typing import Iterable, List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId

from . import people as P
from . import rows as R
from .engine import get_engine, transaction
from .tables import departments as T


def _pid(dept_id) -> Optional[str]:
    if isinstance(dept_id, ObjectId):
        return str(dept_id)
    if isinstance(dept_id, str) and ObjectId.is_valid(dept_id):
        return dept_id.lower()
    return None


def _doc(row) -> dict:
    d = R.decode_flat(dict(row), P.DEPT_COLS, P.DEPT_ALWAYS)
    d["_id"] = ObjectId(row["public_id"])
    return d


async def _select(where=None, *, order=None, limit: Optional[int] = None) -> List[dict]:
    q = sa.select(T)
    if where is not None:
        q = q.where(where)
    q = q.order_by(*(order if order is not None else (T.c.id,)))
    if limit:
        q = q.limit(limit)
    async with get_engine().connect() as conn:
        return [_doc(r) for r in (await conn.execute(q)).mappings().all()]


async def get(dept_id) -> Optional[dict]:
    pid = _pid(dept_id)
    docs = await _select(T.c.public_id == pid, limit=1) if pid else []
    return docs[0] if docs else None


async def get_by_name(name: str) -> Optional[dict]:
    """Exact, case-sensitive name match (the app looks up "IT", "Purchase", "Primitek Group" ...)."""
    docs = await _select(T.c.name == name, limit=1)
    return docs[0] if docs else None


async def list_all() -> List[dict]:
    return await _select(order=(T.c.name, T.c.id), limit=500)


async def list_by_ids(ids: Iterable) -> List[dict]:
    pids = [p for p in (_pid(i) for i in ids) if p]
    return await _select(T.c.public_id.in_(pids)) if pids else []


async def insert(doc: dict) -> ObjectId:
    oid = doc.get("_id") or ObjectId()
    row = R.encode_flat({k: v for k, v in doc.items() if k != "_id"}, P.DEPT_COLS)
    if "name" not in row:
        raise R.ConversionError("department name is missing or does not fit its column")
    row["public_id"] = str(oid)
    async with transaction() as conn:
        await conn.execute(sa.insert(T).values(**row))
    return ObjectId(str(oid))


async def update_fields(dept_id, fields: dict) -> None:
    pid = _pid(dept_id)
    if pid is None:
        raise ValueError("Invalid department id")
    async with transaction() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.public_id == pid).with_for_update())).mappings().first()
        if row is None:
            return
        columns, extra = R.plan_update(dict(row), fields, P.DEPT_COLS, P.DEPT_ALWAYS, must_fit={"name"})
        await conn.execute(sa.update(T).where(T.c.id == row["id"]).values(**columns, extra=extra))


async def delete(dept_id) -> None:
    pid = _pid(dept_id)
    if pid is not None:
        async with transaction() as conn:
            await conn.execute(sa.delete(T).where(T.c.public_id == pid))


async def startup_check() -> None:
    from .engine import require_tables
    await require_tables("departments")


async def close() -> None:
    from .engine import dispose
    await dispose()


__all__ = ["startup_check", "close", "get", "get_by_name", "list_all", "list_by_ids", "insert", "update_fields", "delete"]
