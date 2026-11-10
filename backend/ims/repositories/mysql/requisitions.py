"""Requisition repository - MySQL 8 implementation (SQLAlchemy Core, async).

Documents come back as the dicts the application already uses
(`_id` is an ObjectId, timestamps are ISO strings, items / approval_chain / history are lists).

How writes work
  * Every write is ONE transaction at READ COMMITTED: lock the requisition row (SELECT ... FOR UPDATE), check the guard,
    change the row and its child rows, commit. Because every writer takes that lock first, two people acting at once are
    serialised and the second one sees the first one's result.
  * A "guarded" function (apply_requester_edit, cancel_by_requester, transition_service_ticket) returns whether it won.
  * history is append-only: only entries that are new are inserted (a rewritten earlier entry makes it replace the set).
"""
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId
from sqlalchemy.exc import IntegrityError

from ims.repositories import requisition_fields as F

from . import rows as R
from .clauses import to_clause
from .engine import get_engine, ping, transaction
from .tables import CHILD_TABLES, approval_steps, requisition_history, requisition_items, requisitions as T

_ORDER = {"items": requisition_items.c.seq, "steps": approval_steps.c.seq, "history": requisition_history.c.id}
_KEY_OF = {"items": "items", "steps": "approval_chain", "history": "history"}
_CHUNK = 500


class DuplicateRequisition(Exception):
    """requisition_no is already used by another requisition."""


def _pid(req_id) -> Optional[str]:
    if isinstance(req_id, ObjectId):
        return str(req_id)
    if isinstance(req_id, str) and ObjectId.is_valid(req_id):
        return req_id.lower()
    return None


_tx = transaction


# ------------------------------------------------------------------------------------------------ reading
async def _children(conn, ids: List[int], want: Iterable[str]) -> Dict[str, Dict[int, list]]:
    out: Dict[str, Dict[int, list]] = {k: defaultdict(list) for k in CHILD_TABLES}
    for key in want:
        table = CHILD_TABLES[key]
        for i in range(0, len(ids), _CHUNK):
            res = await conn.execute(sa.select(table).where(table.c.requisition_id.in_(ids[i:i + _CHUNK]))
                                     .order_by(table.c.requisition_id, _ORDER[key]))
            for m in res.mappings():
                out[key][m["requisition_id"]].append(dict(m))
    return out


def _project(doc: dict, only: Optional[Iterable[str]], exclude: Optional[Iterable[str]]) -> dict:
    if only:
        keep = set(only) | {"_id"}
        return {k: v for k, v in doc.items() if k in keep}
    if exclude:
        drop = set(exclude)
        return {k: v for k, v in doc.items() if k not in drop}
    return doc


async def _select_docs(conn, where=None, *, order=None, skip: int = 0, limit: Optional[int] = None,
                       only_fields=None, exclude_fields=None) -> List[dict]:
    q = sa.select(T)
    if where is not None:
        q = q.where(where)
    q = q.order_by(*(order if order is not None else (T.c.id,)))
    if skip:
        q = q.offset(skip)
    if limit:
        q = q.limit(limit)
    req_rows = [dict(m) for m in (await conn.execute(q)).mappings()]
    if not req_rows:
        return []
    want = set(CHILD_TABLES)
    if only_fields:
        want = {k for k in want if _KEY_OF[k] in set(only_fields)}
    elif exclude_fields:
        want = {k for k in want if _KEY_OF[k] not in set(exclude_fields)}
    kids = await _children(conn, [r["id"] for r in req_rows], want)
    docs = []
    for r in req_rows:
        doc = R.rows_to_doc(r, kids["items"][r["id"]], kids["steps"][r["id"]], kids["history"][r["id"]], json_text=False)
        doc["_id"] = ObjectId(doc["_id"])
        docs.append(_project(doc, only_fields, exclude_fields))
    return docs


async def _one(conn, where) -> Optional[dict]:
    docs = await _select_docs(conn, where, limit=1)
    return docs[0] if docs else None


async def get(req_id) -> Optional[dict]:
    """One requisition by id (string or ObjectId); None if the id is malformed or nothing matches."""
    pid = _pid(req_id)
    if pid is None:
        return None
    async with get_engine().connect() as conn:
        return await _one(conn, T.c.public_id == pid)


async def find_by_reference(ref: str) -> Optional[dict]:
    """A requisition whose number OR PR number equals `ref` (exact match, case-insensitive)."""
    low = ref.lower()
    async with get_engine().connect() as conn:
        return await _one(conn, sa.or_(sa.func.lower(T.c.requisition_no) == low, sa.func.lower(T.c.purchase_pr_no) == low))


async def get_service_ticket(ticket_id, it_teams: Iterable[str]) -> Optional[dict]:
    """An IT service ticket (a requisition of type "service") that belongs to one of the given IT teams."""
    pid = _pid(ticket_id)
    if pid is None:
        return None
    async with get_engine().connect() as conn:
        return await _one(conn, sa.and_(T.c.public_id == pid, T.c.requisition_type == "service", T.c.it_team.in_(list(it_teams))))


async def list_with_status(status: str, *, oldest_first: bool = True) -> List[dict]:
    order = (T.c.created_at.asc(), T.c.id.asc()) if oldest_first else (T.c.created_at.desc(), T.c.id.desc())
    async with get_engine().connect() as conn:
        return await _select_docs(conn, T.c.status == status, order=order)


async def list_not_in_statuses(statuses: Iterable[str], *, only_fields: Optional[Iterable[str]] = None,
                               newest_first: Optional[bool] = None, limit: Optional[int] = None) -> List[dict]:
    order = None if newest_first is None else ((T.c.created_at.desc(), T.c.id.desc()) if newest_first else (T.c.created_at.asc(), T.c.id.asc()))
    async with get_engine().connect() as conn:
        return await _select_docs(conn, to_clause({"status": {"$nin": list(statuses)}}), order=order, limit=limit,
                                  only_fields=list(only_fields) if only_fields else None)


async def list_product_items() -> List[dict]:
    """The `items` of every product requisition (used to learn which product names are in use)."""
    async with get_engine().connect() as conn:
        return await _select_docs(conn, T.c.requisition_type == "product", only_fields=["items"])


async def find_handover_candidates(status: str, employee_name: str, department_id: Optional[str] = None,
                                   limit: int = 20) -> List[dict]:
    """Requisitions in `status` raised by / for an employee of exactly this name (case-insensitive),
    optionally narrowed to the requester's department."""
    name = employee_name.strip()
    cond = [T.c.status == status, sa.or_(T.c.requisitioner_name == name, T.c.requisition_for == name)]
    if department_id:
        cond.append(T.c.requisitioner_department_id == department_id)
    async with get_engine().connect() as conn:
        return await _select_docs(conn, sa.and_(*cond), limit=limit)


async def find_filtered(query: Optional[dict] = None, *, only_fields: Optional[Iterable[str]] = None,
                        exclude_fields: Optional[Iterable[str]] = None, newest_first: Optional[bool] = True,
                        skip: int = 0, limit: Optional[int] = 1000) -> List[dict]:
    """Requisitions matching a caller-built filter. Newest first by default; `skip`/`limit` page the result."""
    if newest_first is None:
        order = None
    else:
        order = (T.c.created_at.desc(), T.c.id.desc()) if newest_first else (T.c.created_at.asc(), T.c.id.asc())
    async with get_engine().connect() as conn:
        return await _select_docs(conn, to_clause(query or {}), order=order, skip=skip, limit=limit,
                                  only_fields=list(only_fields) if only_fields else None,
                                  exclude_fields=list(exclude_fields) if exclude_fields else None)


async def count_filtered(query: Optional[dict] = None) -> int:
    async with get_engine().connect() as conn:
        return (await conn.execute(sa.select(sa.func.count()).select_from(T).where(to_clause(query or {})))).scalar_one()


# ------------------------------------------------------------------------------------------------- writing
async def _lock(conn, public_id: str, where=None) -> Optional[dict]:
    q = sa.select(T).where(T.c.public_id == public_id)
    if where is not None:
        q = q.where(where)
    row = (await conn.execute(q.with_for_update())).mappings().first()
    return dict(row) if row else None


async def _insert_children(conn, rid: int, key: str, new_rows: List[dict]) -> None:
    """Insert child rows. Every row is padded to the full column set: SQLAlchemy builds an executemany INSERT from the FIRST
    row's keys, so rows that carry extra fields (e.g. a `stage` only some steps have) would silently lose them otherwise."""
    if not new_rows:
        return
    table = CHILD_TABLES[key]
    cols = [c.name for c in table.columns if c.name != "id"]
    await conn.execute(sa.insert(table), [{c: ({**r, "requisition_id": rid}).get(c) for c in cols} for r in new_rows])


async def _replace_children(conn, rid: int, key: str, new_rows: List[dict]) -> None:
    table = CHILD_TABLES[key]
    await conn.execute(sa.delete(table).where(table.c.requisition_id == rid))
    await _insert_children(conn, rid, key, new_rows)


async def _write_history(conn, rid: int, entries: list) -> None:
    """Keep what is already stored and insert only the new tail; if an old entry itself changed, replace the set."""
    new_rows = R.history_to_rows(entries, json_text=False)
    old = (await conn.execute(sa.select(requisition_history).where(requisition_history.c.requisition_id == rid)
                              .order_by(requisition_history.c.id))).mappings().all()
    old_entries = [R._from_row(dict(o), R.HIST_COLS, R.HIST_ALWAYS, R.HIST_COLUMN_OF, json_text=False) for o in old]
    n = len(old_entries)
    same_prefix = len(entries) >= n and all(
        R.normalize_for_compare(a) == R.normalize_for_compare(b) for a, b in zip(old_entries, entries[:n]))
    if not same_prefix:
        await conn.execute(sa.delete(requisition_history).where(requisition_history.c.requisition_id == rid))
        n = 0
    await _insert_children(conn, rid, "history", new_rows[n:])


async def _apply(conn, row: dict, fields: dict) -> None:
    """Apply a {key: value} update to a LOCKED row: scalar/JSON columns, `extra`, and the three child lists."""
    fields = dict(fields)
    lists = {k: fields.pop(k) for k in R.LIST_KEYS if k in fields}
    if fields:
        columns, extra = R.plan_scalar_update(row, fields, json_text=False)
        values = {**columns, "extra": extra}
        await conn.execute(sa.update(T).where(T.c.id == row["id"]).values(**values))
    if "items" in lists:
        await _replace_children(conn, row["id"], "items", R.items_to_rows(lists["items"], json_text=False))
    if "approval_chain" in lists:
        await _replace_children(conn, row["id"], "steps", R.steps_to_rows(lists["approval_chain"], json_text=False))
    if "history" in lists:
        await _write_history(conn, row["id"], lists["history"])


async def update_fields(req_id, fields: dict) -> None:
    """Set the given top-level fields on a requisition (a {key: value} update; "a.b" paths and None are understood)."""
    pid = _pid(req_id)
    if pid is None:
        raise ValueError("Invalid requisition id")
    async with _tx() as conn:
        row = await _lock(conn, pid)
        if row is not None:
            await _apply(conn, row, fields)


async def save_progress(req_id, *, status: str, history: list, updated_at: str, extra: Optional[dict] = None, **fields) -> None:
    await update_fields(req_id, F.progress(status, history, updated_at, extra, fields))


async def save_approval_chain(req_id, chain: list) -> None:
    await update_fields(req_id, F.approval_chain(chain))


async def set_pr_number(req_id, pr_no: str) -> None:
    await update_fields(req_id, F.pr_number(pr_no))


async def link_handover(req_id, handover_id: str, status: str) -> None:
    await update_fields(req_id, F.handover_link(handover_id, status))


async def save_decision(req_id, *, approval_chain: list, status: str, history: list, updated_at: str, extra: Optional[dict] = None) -> None:
    await update_fields(req_id, F.decision(approval_chain, status, history, updated_at, extra))


async def save_resubmission(req_id, changes: dict) -> None:
    await update_fields(req_id, changes)


async def save_pr_filing(req_id, *, items: list, approval_chain: list, status: str, history: list, updated_at: str,
                         overall_business_justification, required_by_date, urgency_level, delivery_location,
                         pr_attachment_file_ids: list, pr_filed_by: str, pr_filed_by_id: str) -> None:
    await update_fields(req_id, F.pr_filing(items, approval_chain, status, history, updated_at, overall_business_justification,
                                            required_by_date, urgency_level, delivery_location, pr_attachment_file_ids,
                                            pr_filed_by, pr_filed_by_id))


async def save_stock_allocation(req_id, *, status: str, approval_chain: list, fulfillment_type: str, allocated_item_details: list,
                                procurement_notes: Optional[str], allocated_by: str, history: list, updated_at: str) -> None:
    await update_fields(req_id, F.stock_allocation(status, approval_chain, fulfillment_type, allocated_item_details,
                                                   procurement_notes, allocated_by, history, updated_at))


async def save_stock_bypass(req_id, *, fulfillment_type: str, reason: str, bypassed_by: str, history: list, updated_at: str) -> None:
    await update_fields(req_id, F.stock_bypass(fulfillment_type, reason, bypassed_by, history, updated_at))


async def save_pr_cancellation(req_id, *, history: list, updated_at: str, closed_at: str, note: str, cancelled_by: str) -> None:
    await update_fields(req_id, F.pr_cancellation(history, updated_at, closed_at, note, cancelled_by))


async def insert(doc: dict) -> ObjectId:
    """Insert a new requisition document (with its items / chain / history) and return its id."""
    oid = doc.get("_id") or ObjectId()
    rows = R.doc_to_rows({**doc, "_id": str(oid)}, json_text=False)
    try:
        async with _tx() as conn:
            rid = (await conn.execute(sa.insert(T).values(**rows["requisition"]))).inserted_primary_key[0]
            for key in ("items", "steps", "history"):
                await _insert_children(conn, rid, key, rows[key])
    except IntegrityError as e:
        raise DuplicateRequisition(str(e.orig)) from e
    return ObjectId(str(oid))


async def save_creation_routing(req_id, *, status: str, approval_chain: list, extra: Optional[dict] = None) -> None:
    await update_fields(req_id, F.creation_routing(status, approval_chain, extra))


async def apply_requester_edit(req_id, changes: dict) -> bool:
    """Apply the requester's edit - but only while the requisition is still waiting on its FIRST approver.
    Atomic: returns False (and writes nothing) if the approver acted in the meantime."""
    pid = _pid(req_id)
    if pid is None:
        return False
    async with _tx() as conn:
        row = await _lock(conn, pid)
        if row is None or row["status"] != "pending_dept":
            return False
        first = (await conn.execute(sa.select(approval_steps.c.status).where(
            approval_steps.c.requisition_id == row["id"], approval_steps.c.seq == 0))).first()
        if first is None or first[0] != "pending":
            return False
        await _apply(conn, row, changes)
        return True


async def cancel_by_requester(req_id, *, approval_chain: list, history: list, cancelled_by: str, note: str, at: str) -> bool:
    """Withdraw the requisition - but only while it is still 'pending_dept'. Atomic; False if too late."""
    pid = _pid(req_id)
    if pid is None:
        return False
    async with _tx() as conn:
        row = await _lock(conn, pid)
        if row is None or row["status"] != "pending_dept":
            return False
        await _apply(conn, row, F.requester_cancellation(approval_chain, history, cancelled_by, note, at))
        return True


async def transition_service_ticket(ticket_id, expected: dict, changes: dict, history_entry: dict, updated_at: str) -> Optional[dict]:
    """Move an IT service ticket on ONLY if it still matches `expected` (status / assignee / team ...).
    One locked transaction, so of several simultaneous callers exactly one wins. Returns the updated ticket or None."""
    pid = _pid(ticket_id)
    if pid is None:
        return None
    async with _tx() as conn:
        row = await _lock(conn, pid, sa.and_(T.c.requisition_type == "service", to_clause(expected)))
        if row is None:
            return None
        await _apply(conn, row, {**changes, "updated_at": updated_at})
        await _insert_children(conn, row["id"], "history", R.history_to_rows([history_entry], json_text=False))
        return await _one(conn, T.c.id == row["id"])


async def clear_handover(req_id, status: str) -> None:
    """Move a requisition to `status` and remove its handover link (the handover slip was cancelled)."""
    await update_fields(req_id, {"status": status, "handover_id": None})


async def append_history(req_id, entry: dict) -> None:
    """Add one entry to the end of a requisition's history without touching anything else."""
    pid = _pid(req_id)
    if pid is None:
        raise ValueError("Invalid requisition id")
    async with _tx() as conn:
        rid = (await conn.execute(sa.select(T.c.id).where(T.c.public_id == pid))).scalar()
        if rid is not None:
            await _insert_children(conn, rid, "history", R.history_to_rows([entry], json_text=False))


# --------------------------------------------------------------------------------------------- start / stop
async def startup_check() -> None:
    """Fail early, with instructions, when MySQL is unreachable or the tables have not been created."""
    await ping()
    async with get_engine().connect() as conn:
        have = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
    missing = {t.name for t in (T, requisition_items, approval_steps, requisition_history)} - have
    if missing:
        raise RuntimeError(f"MySQL is reachable but these tables are missing: {sorted(missing)}. "
                           "Create them with:  python -m migration.mysql.migrate schema --mysql-url <MYSQL_URL>")


async def close() -> None:
    await get_engine().dispose()


__all__ = sorted(n for n in (
    "append_history apply_requester_edit cancel_by_requester clear_handover close count_filtered find_by_reference find_filtered "
    "find_handover_candidates get get_service_ticket insert link_handover list_not_in_statuses list_product_items list_with_status "
    "save_approval_chain save_creation_routing save_decision save_pr_cancellation save_pr_filing save_progress save_resubmission "
    "save_stock_allocation save_stock_bypass set_pr_number startup_check transition_service_ticket update_fields").split())
