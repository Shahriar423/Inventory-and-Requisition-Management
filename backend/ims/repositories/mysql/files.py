"""Files repository - MySQL 8. A file's public id is a UUID string called `id` (not an ObjectId)."""
from typing import Dict, Iterable, List, Optional

import sqlalchemy as sa

from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import files as T

FT = FlatTable(T, C.FILE_COLS, C.FILE_ALWAYS, str_id=True)


async def startup_check() -> None:
    await require_tables("files")


async def close() -> None:
    await dispose()


async def get(file_id: str, *, include_deleted: bool = False) -> Optional[dict]:
    where = [T.c.public_id == file_id]
    if not include_deleted:
        where.append(T.c.is_deleted == 0)
    return await FT.first(*where)


async def get_map(file_ids: Iterable[str]) -> Dict[str, dict]:
    """{file id: record} for the live (not deleted) files among `file_ids`."""
    ids = list({str(i) for i in (file_ids or []) if i})
    if not ids:
        return {}
    return {d["id"]: d for d in await FT.select(T.c.public_id.in_(ids), T.c.is_deleted == 0)}


async def insert(doc: dict) -> str:
    if not (doc.get("id") or doc.get("_id")):
        raise ValueError("file id is required")
    return str(await FT.insert(doc, C.FILE_MUST_FIT))


async def mark_deleted(file_id: str) -> None:
    await FT.update([T.c.public_id == file_id], {"is_deleted": True})


async def mark_deleted_many(file_ids: Iterable[str]) -> None:
    ids = list({str(i) for i in (file_ids or []) if i})
    if ids:
        await FT.update([T.c.public_id.in_(ids)], {"is_deleted": True}, many=True)
