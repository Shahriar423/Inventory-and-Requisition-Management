"""Assets repository - MySQL 8 (the only code that touches the `assets` table)."""
from typing import Dict, Iterable, List, Optional, Sequence

import sqlalchemy as sa

from ims.ids import ObjectId
from . import catalog as C
from .engine import get_engine, require_tables, dispose
from .flat import FlatTable
from .tables import assets as T

FT = FlatTable(T, C.ASSET_COLS, C.ASSET_ALWAYS, C.ASSET_COLUMN_OF)


async def startup_check() -> None:
    await require_tables("assets")


async def close() -> None:
    await dispose()


# ------------------------------------------------------------------------------------------------ helpers
def _name_is(name: str):
    """Case- and whitespace-insensitive match of an item name ('Laptop' finds ' laptop ')."""
    return sa.func.lower(sa.func.trim(T.c.name)) == (name or "").strip().lower()


_AVAILABLE = [T.c.status == "in_stock", sa.or_(T.c.pending_receipt.is_(None), T.c.pending_receipt == 0)]


# ------------------------------------------------------------------------------------------------ reads
async def get(asset_id) -> Optional[dict]:
    return await FT.get(asset_id)


async def get_many(ids: Iterable) -> List[dict]:
    pids = [p for p in (FT.pid(i) for i in set(ids or [])) if p]
    return await FT.select(T.c.public_id.in_(pids)) if pids else []


async def get_map(ids: Iterable) -> Dict[str, dict]:
    return {str(a["_id"]): a for a in await get_many(ids)}


async def list_all(*, status: Optional[str] = None, assigned_to: Optional[str] = None,
                   limit: int = 5000, skip: int = 0) -> List[dict]:
    where = []
    if status:
        where.append(T.c.status == status)
    if assigned_to:
        where.append(T.c.assigned_to == assigned_to)
    return await FT.select(*where, order=[T.c.created_at.desc(), T.c.id.desc()], limit=limit, offset=skip)


async def find(flt: Optional[dict] = None, *, sort: Optional[Sequence] = None, skip: int = 0,
               limit: Optional[int] = None) -> List[dict]:
    """Assets matching a filter dict (see FlatTable.where for what is supported), e.g.
    find({"status": {"$in": [...]}, "assigned_to_user_id": uid}, sort=[("assigned_at", -1)])."""
    return await FT.find(flt, sort=sort, skip=skip, limit=limit)


async def count_filtered(flt: Optional[dict] = None) -> int:
    return await FT.count_filtered(flt)


async def count(*, status: Optional[str] = None, name: Optional[str] = None,
                pending_receipt_ne: bool = False) -> int:
    where = []
    if status:
        where.append(T.c.status == status)
    if name:
        where.append(T.c.name == name)
    if pending_receipt_ne:
        where.append(sa.or_(T.c.pending_receipt.is_(None), T.c.pending_receipt == 0))
    return await FT.count(*where)


async def count_where(*, statuses: Optional[List[str]] = None, assigned_to: Optional[str] = None,
                      assigned_to_in: Optional[List[str]] = None) -> int:
    """Count assets, optionally limited to statuses and/or holder name(s). An empty assigned_to_in matches nothing."""
    where = []
    if statuses:
        where.append(T.c.status.in_(statuses))
    if assigned_to is not None:
        where.append(T.c.assigned_to == assigned_to)
    if assigned_to_in is not None:
        if not assigned_to_in:
            return 0
        where.append(T.c.assigned_to.in_(assigned_to_in))
    return await FT.count(*where)


async def find_by_field(field: str, value: str) -> Optional[dict]:
    """Case-insensitive exact match on serial_no or tag_id."""
    col = {"serial_no": T.c.serial_no, "tag_id": T.c.tag_id}.get(field)
    if col is None:
        return None
    return await FT.first(sa.func.lower(col) == value.lower())


async def tags_and_serials() -> List[tuple]:
    """[(tag_id, serial_no), ...] of every asset (duplicate checks in the bulk import)."""
    async with get_engine().connect() as conn:
        return [tuple(r) for r in (await conn.execute(sa.select(T.c.tag_id, T.c.serial_no))).all()]


async def list_in_stock_by_name(name: str, limit: int = 5000) -> List[dict]:
    return await FT.select(T.c.name == name, *_AVAILABLE, order=[T.c.created_at.asc(), T.c.id.asc()], limit=limit)


# ---- stock that can be issued right now: in_stock and not reserved by another slip
async def count_available(name: str) -> int:
    return await FT.count(_name_is(name), *_AVAILABLE)


async def list_available(name: str, limit: int = 5000) -> List[dict]:
    return await FT.select(_name_is(name), *_AVAILABLE, order=[T.c.created_at.asc(), T.c.id.asc()], limit=limit)


async def list_all_available(limit: int = 5000) -> List[dict]:
    """Every available unit, by product name then oldest first."""
    return await FT.select(*_AVAILABLE, order=[T.c.name.asc(), T.c.created_at.asc(), T.c.id.asc()], limit=limit)


async def available_counts() -> Dict[str, int]:
    """Available units per asset name (as stored; callers normalise the key)."""
    out: Dict[str, int] = {}
    for name, n in await FT.group_count([T.c.name], *_AVAILABLE):
        out[name] = out.get(name, 0) + n
    return out


async def stock_summary() -> List[dict]:
    """In-stock units per (name, category), name order: [{name, category_id, available_stock}]."""
    rows = await FT.group_count([T.c.name, T.c.category_id], T.c.status == "in_stock")
    return [{"name": n, "category_id": c, "available_stock": k}
            for n, c, k in sorted(rows, key=lambda r: ((r[0] or "").lower(), r[1] or ""))]


async def find_reservable(name: str, *, handover_id: Optional[str] = None,
                          exclude_ids: Iterable[str] = ()) -> Optional[dict]:
    """One in-stock unit called `name`. With handover_id: only a unit already reserved for that slip.
    Without: only a free one (not reserved by anything)."""
    where = [_name_is(name), T.c.status == "in_stock"]
    if handover_id:
        where.append(T.c.pending_handover_id == handover_id)
    else:
        where.append(sa.or_(T.c.pending_receipt.is_(None), T.c.pending_receipt == 0))
    skip = [p for p in (FT.pid(i) for i in exclude_ids) if p]
    if skip:
        where.append(T.c.public_id.not_in(skip))
    return await FT.first(*where)


# ------------------------------------------------------------------------------------------------ writes
async def insert(doc: dict) -> ObjectId:
    return await FT.insert(doc, C.ASSET_MUST_FIT)


async def insert_many(docs: List[dict]) -> List[ObjectId]:
    return await FT.insert_many(docs, C.ASSET_MUST_FIT)


async def update_fields(asset_id, fields: dict) -> None:
    """Set fields on one asset; a value of None clears the field."""
    cond = FT.by_id(asset_id)
    if cond is None:
        raise ValueError("Invalid asset id")
    await FT.update([cond], fields)


async def update_if(asset_id, guard: dict, fields: dict) -> int:
    """Guarded update: apply `fields` only if the asset still satisfies `guard` ({key: value | {"$ne": value}}),
    checked on the locked row. Returns 1 when applied, 0 when the asset is gone or the guard failed."""
    cond = FT.by_id(asset_id)
    if cond is None:
        return 0
    return await FT.update([cond], fields, guard=guard)


async def release_reservations(handover_id: str) -> None:
    """Undo what a not-yet-completed slip locked: reserved stock goes back to in_stock, units waiting to be
    returned go back to 'assigned'."""
    await FT.update([T.c.pending_handover_id == handover_id, T.c.status == "in_stock"],
                    {"pending_receipt": False, "pending_handover_id": None,
                     "assigned_to_tentative": None, "assigned_department_id": None}, many=True)
    await FT.update([T.c.pending_return_handover_id == handover_id, T.c.status == "return_pending"],
                    {"status": "assigned", "pending_return_handover_id": None, "pending_return_slip_no": None}, many=True)
