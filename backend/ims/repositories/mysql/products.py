"""Products repository - MySQL 8 implementation."""
from typing import List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId

from . import catalog as C
from . import rows as R
from .engine import get_engine, transaction, require_tables, dispose
from .flat import FlatTable
from .tables import products as T


_FT = FlatTable(T, C.PRODUCT_COLS, C.PRODUCT_ALWAYS)


def _pid(pid) -> Optional[str]:
    if isinstance(pid, ObjectId):
        return str(pid)
    if isinstance(pid, str) and ObjectId.is_valid(pid):
        return pid.lower()
    return None


def _doc(row) -> dict:
    d = R.decode_flat(dict(row), C.PRODUCT_COLS, C.PRODUCT_ALWAYS)
    d["_id"] = ObjectId(row["public_id"])
    return d


async def startup_check() -> None:
    await require_tables("products")


async def close() -> None:
    await dispose()


async def get(product_id) -> Optional[dict]:
    pid = _pid(product_id)
    if not pid:
        return None
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.public_id == pid).limit(1))).mappings().first()
    return _doc(row) if row else None


async def get_by_name_key(name_key: str) -> Optional[dict]:
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.name_key == name_key).limit(1))).mappings().first()
    return _doc(row) if row else None


async def list_all(*, product_type: Optional[str] = None, limit: int = 5000) -> List[dict]:
    q = sa.select(T)
    if product_type:
        q = q.where(T.c.product_type == product_type)
    q = q.order_by(T.c.name_key, T.c.id).limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_doc(r) for r in rows]


async def insert(doc: dict) -> ObjectId:
    oid = doc.get("_id") or ObjectId()
    if not isinstance(oid, ObjectId):
        oid = ObjectId(str(oid))
    row = R.encode_flat({k: v for k, v in doc.items() if k != "_id"}, C.PRODUCT_COLS)
    for must in C.PRODUCT_MUST_FIT:
        if must not in row:
            raise ValueError(f"{must} is required")
    row["public_id"] = str(oid).lower()
    async with transaction() as conn:
        await conn.execute(sa.insert(T).values(**row))
    return oid


async def update_fields(product_id, fields: dict) -> None:
    pid = _pid(product_id)
    if not pid:
        raise ValueError("Invalid product id")
    # read-modify-write under a row lock: None clears a field, fields not mentioned (and `extra`) are kept
    await _FT.update([T.c.public_id == pid], fields)


async def delete(product_id) -> None:
    pid = _pid(product_id)
    if not pid:
        return
    async with transaction() as conn:
        await conn.execute(sa.delete(T).where(T.c.public_id == pid))
