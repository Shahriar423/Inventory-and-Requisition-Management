"""User repository - MySQL 8 implementation (SQLAlchemy Core, async)."""
from typing import Iterable, List, Optional

import sqlalchemy as sa
from ims.ids import ObjectId

from . import people as P
from . import rows as R
from .engine import get_engine, transaction
from .tables import password_resets, users as T


def _pid(user_id) -> Optional[str]:
    if isinstance(user_id, ObjectId):
        return str(user_id)
    if isinstance(user_id, str) and ObjectId.is_valid(user_id):
        return user_id.lower()
    return None


def _doc(row) -> dict:
    d = R.decode_flat(dict(row), P.USER_COLS, P.USER_ALWAYS)
    d["_id"] = ObjectId(row["public_id"])
    return d


def _project(doc: dict, only: Optional[Iterable[str]]) -> dict:
    if only:
        keep = set(only) | {"_id"}
        return {k: v for k, v in doc.items() if k in keep}
    return doc


async def _select(where=None, *, order=None, limit: Optional[int] = None, only_fields=None) -> List[dict]:
    q = sa.select(T)
    if where is not None:
        q = q.where(where)
    q = q.order_by(*(order if order is not None else (T.c.id,)))
    if limit:
        q = q.limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return [_project(_doc(r), only_fields) for r in rows]


async def _one(where) -> Optional[dict]:
    docs = await _select(where, limit=1)
    return docs[0] if docs else None


# ------------------------------------------------------------------------------------------- single lookups
async def get(user_id) -> Optional[dict]:
    pid = _pid(user_id)
    return await _one(T.c.public_id == pid) if pid else None


async def get_by_email(email: str) -> Optional[dict]:
    """Exact match - callers lower-case the address first (the column is case-sensitive)."""
    return await _one(T.c.email == email)


async def get_by_name(name: str) -> Optional[dict]:
    """A user whose full name equals `name`, ignoring case."""
    return await _one(T.c.name == name)


async def find_by_role(role: str, department_id: Optional[str] = None) -> Optional[dict]:
    cond = [T.c.role == role] + ([T.c.department_id == department_id] if department_id else [])
    return await _one(sa.and_(*cond))


async def find_by_roles_in_department(roles: Iterable[str], department_id: str) -> Optional[dict]:
    return await _one(sa.and_(T.c.role.in_(list(roles)), T.c.department_id == department_id))


# ---------------------------------------------------------------------------------------------------- lists
async def list_all(*, only_fields: Optional[Iterable[str]] = None, sort_by_name: bool = False, limit: Optional[int] = None) -> List[dict]:
    order = (T.c.name, T.c.id) if sort_by_name else None
    return await _select(order=order, limit=limit, only_fields=list(only_fields) if only_fields else None)


async def list_by_ids(ids: Iterable) -> List[dict]:
    pids = [p for p in (_pid(i) for i in ids) if p]
    return await _select(T.c.public_id.in_(pids)) if pids else []


async def list_by_department(department_id: Optional[str], limit: int = 500) -> List[dict]:
    where = T.c.department_id.is_(None) if department_id is None else T.c.department_id == department_id
    return await _select(where, limit=limit)


async def list_by_departments(department_ids: Iterable[str]) -> List[dict]:
    ids = list(department_ids)
    return await _select(T.c.department_id.in_(ids)) if ids else []


async def list_delegating_to(user_id: str) -> List[dict]:
    return await _select(T.c.delegate_user_id == str(user_id))


async def list_dept_heads(department_id: str, limit: Optional[int] = None) -> List[dict]:
    return await _select(sa.and_(T.c.role == "dept_head", T.c.department_id == department_id), limit=limit)


async def list_po_stage_holders(stage_role: str, purchase_department_id: Optional[str]) -> List[dict]:
    cond = [T.c.role == stage_role]
    if stage_role == "purchase_head" and purchase_department_id:
        cond.append(sa.and_(T.c.role == "dept_head", T.c.department_id == purchase_department_id))
    return await _select(sa.or_(*cond), limit=50)


async def search_by_name(name: str, department_id: Optional[str] = None, exact: bool = True) -> List[dict]:
    cond = []
    nm = (name or "").strip()
    if nm:
        if exact:
            cond.append(T.c.name == nm)
        else:
            cond.append(T.c.name.like("%" + nm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
    if department_id:
        cond.append(T.c.department_id == department_id)
    return await _select(sa.and_(*cond) if cond else None, order=(T.c.name, T.c.id), limit=50)


async def list_it_ticket_recipients(department_id: str, team: str) -> List[dict]:
    return await _select(sa.and_(T.c.department_id == department_id, sa.or_(T.c.it_team == team, T.c.role == "dept_head")))


async def list_pr_processors() -> List[dict]:
    return await _select(sa.or_(T.c.can_raise_pr == 1, T.c.can_process_requisition == 1), limit=50)


# --------------------------------------------------------------------------------------------------- writes
def _row_for(doc: dict, public_id: str) -> dict:
    src = {k: v for k, v in doc.items() if k != "_id"}
    try:
        row = R.encode_flat(src, P.USER_COLS)
    except R.ConversionError:
        raise
    for must in P.USER_MUST_FIT:
        if must not in row:
            raise R.ConversionError(f"user {must} is missing or does not fit its column")
    row["public_id"] = public_id
    return row


async def insert(doc: dict) -> ObjectId:
    oid = doc.get("_id") or ObjectId()
    row = _row_for(doc, str(oid))
    async with transaction() as conn:
        await conn.execute(sa.insert(T).values(**row))
    return ObjectId(str(oid))


async def insert_many(docs: List[dict]) -> None:
    """Bulk insert; a document that cannot be stored (e.g. a duplicate email) does not stop the others.
    The first failure is re-raised at the end."""
    first_error = None
    for d in docs:
        try:
            await insert(d)
        except Exception as e:           # noqa: BLE001 - keep going, report the first problem afterwards
            first_error = first_error or e
    if first_error:
        raise first_error


async def _update(user_id, fields: dict) -> None:
    pid = _pid(user_id)
    if pid is None:
        raise ValueError("Invalid user id")
    async with transaction() as conn:
        row = (await conn.execute(sa.select(T).where(T.c.public_id == pid).with_for_update())).mappings().first()
        if row is None:
            return
        columns, extra = R.plan_update(dict(row), fields, P.USER_COLS, P.USER_ALWAYS, must_fit=P.USER_MUST_FIT)
        await conn.execute(sa.update(T).where(T.c.id == row["id"]).values(**columns, extra=extra))


async def update_fields(user_id, fields: dict) -> None:
    await _update(user_id, fields)


async def unset_fields(user_id, names: Iterable[str]) -> None:
    await _update(user_id, {n: None for n in names})


async def delete(user_id) -> None:
    pid = _pid(user_id)
    if pid is not None:
        async with transaction() as conn:
            await conn.execute(sa.delete(T).where(T.c.public_id == pid))


async def log_password_reset(record: dict) -> None:
    row = R.encode_flat(record, P.RESET_COLS)
    async with transaction() as conn:
        await conn.execute(sa.insert(password_resets).values(**row))


async def list_password_resets(limit: int = 100) -> List[dict]:
    """The latest password resets, newest first."""
    async with get_engine().connect() as conn:
        rows = (await conn.execute(sa.select(password_resets).order_by(password_resets.c.at.desc(), password_resets.c.id.desc()).limit(limit))).mappings().all()
    return [R.decode_flat(dict(r), P.RESET_COLS, P.RESET_ALWAYS) | {"_id": r["id"]} for r in rows]


async def startup_check() -> None:
    from .engine import require_tables
    await require_tables("users", "password_resets")


async def close() -> None:
    from .engine import dispose
    await dispose()


__all__ = ["startup_check", "close", "list_password_resets", "get", "get_by_email", "get_by_name", "find_by_role", "find_by_roles_in_department", "list_all", "list_by_ids",
           "list_by_department", "list_by_departments", "list_delegating_to", "list_dept_heads", "list_po_stage_holders",
           "search_by_name", "list_it_ticket_recipients", "list_pr_processors", "insert", "insert_many", "update_fields",
           "unset_fields", "delete", "log_password_reset"]
