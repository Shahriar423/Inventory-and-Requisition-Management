"""Categories repository - MySQL 8 implementation."""
from typing import List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId

from . import catalog as C
from . import rows as R
from .engine import get_engine, transaction, require_tables, dispose
from .flat import FlatTable
from .tables import categories as T


_FT = FlatTable(T, C.CAT_COLS, C.CAT_ALWAYS)


def _pid(cat_id) -> Optional[str]:
    if isinstance(cat_id, ObjectId):
        return str(cat_id)
    if isinstance(cat_id, str) and ObjectId.is_valid(cat_id):
        return cat_id.lower()
    return None


def _doc(row) -> dict:
    d = R.decode_flat(dict(row), C.CAT_COLS, C.CAT_ALWAYS)
    d["_id"] = ObjectId(row["public_id"])
    return d


async def startup_check() -> None:
    await require_tables("categories")


async def close() -> None:
    await dispose()


async def get(cat_id) -> Optional[dict]:
    pid = _pid(cat_id)
    if not pid:
        return None
    async with get_engine().connect() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.public_id == pid).limit(1))).mappings().first()
    return _doc(row) if row else None


async def list_all(limit: int = 500) -> List[dict]:
    async with get_engine().connect() as conn:
        rows = (await conn.execute(sa.select(T).order_by(T.c.name, T.c.id).limit(limit))).mappings().all()
    return [_doc(r) for r in rows]


async def insert(doc: dict) -> ObjectId:
    oid = doc.get("_id") or ObjectId()
    if not isinstance(oid, ObjectId):
        oid = ObjectId(str(oid))
    row = R.encode_flat({k: v for k, v in doc.items() if k != "_id"}, C.CAT_COLS)
    for must in C.CAT_MUST_FIT:
        if must not in row:
            raise ValueError(f"{must} is required")
    row["public_id"] = str(oid).lower()
    async with transaction() as conn:
        await conn.execute(sa.insert(T).values(**row))
    return oid


async def update_fields(cat_id, fields: dict) -> None:
    pid = _pid(cat_id)
    if not pid:
        raise ValueError("Invalid category id")
    # read-modify-write under a row lock: None clears a field, fields not mentioned (and `extra`) are kept
    await _FT.update([T.c.public_id == pid], fields)


async def delete(cat_id) -> None:
    pid = _pid(cat_id)
    if not pid:
        return
    async with transaction() as conn:
        await conn.execute(sa.delete(T).where(T.c.public_id == pid))
