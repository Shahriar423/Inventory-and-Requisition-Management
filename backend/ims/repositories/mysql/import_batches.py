"""Bulk-import batches (an audit row per import) - MySQL 8."""
from ims.ids import ObjectId
from . import catalog as C
from .engine import require_tables, dispose
from .flat import FlatTable
from .tables import import_batches as T

FT = FlatTable(T, C.IMPORT_BATCH_COLS, C.IMPORT_BATCH_ALWAYS, C.IMPORT_BATCH_COLUMN_OF)


async def startup_check() -> None:
    await require_tables("import_batches")


async def close() -> None:
    await dispose()


async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc)
