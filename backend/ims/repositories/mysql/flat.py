"""Shared row <-> document mechanics for the "flat" tables (one row per record: assets, handovers, notifications,
correction_cases, files, asset_history, paper_records, saved_reports, report_access, import_batches).

A record is a plain dict (the shape the application always used). Known keys live in typed columns, everything
else in the JSON `extra` column. The repositories build their SQL conditions with SQLAlchemy and hand them to a
FlatTable; every write is one transaction with a locking read (SELECT ... FOR UPDATE), so a guarded update such as
"set status=assigned only if status is still in_stock" cannot be beaten by a concurrent request.

Update rule: the record is read, the changes applied to the decoded dict, and the WHOLE record written back.
A field set to None is cleared (column NULL / key removed from `extra`); fields not mentioned are untouched.
"""
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import sqlalchemy as sa

from ims.ids import ObjectId
from . import rows as R
from .clauses import UnsupportedFilter, _condition, _like_literal  # noqa: F401
from .engine import get_engine, transaction


def public_id(value) -> Optional[str]:
    """A record id (ObjectId or 24-hex string) -> the stored lowercase string; None when it is not a valid id."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, str) and ObjectId.is_valid(value):
        return value.lower()
    return None


_ANCHORED = re.compile(r"^\^(\\s\*)?((?:[^\\]|\\.)*?)(\\s\*)?\$$")


def _anchored_literal(pattern) -> Optional[tuple]:
    """'^literal$' / '^\\s*literal\\s*$' (what the app builds with re.escape) -> (text, trims_spaces); else None."""
    if not isinstance(pattern, str):
        return None
    m = _ANCHORED.match(pattern)
    if not m:
        return None
    body = m.group(2)
    if re.search(r"(?<!\\)[.^$*+?{}\[\]|()]", body):
        return None
    return re.sub(r"\\(.)", r"\1", body), bool(m.group(1) or m.group(3))


def _column_condition(col, cond):
    """_condition() plus anchored literal regexes, which become exact (case-insensitive) matches."""
    if isinstance(cond, dict) and "$regex" in cond:
        lit = _anchored_literal(cond["$regex"])
        if lit is not None:
            text, trim = lit
            left = sa.func.lower(sa.func.trim(col) if trim else col)
            rest = {k: v for k, v in cond.items() if k not in ("$regex", "$options")}
            exact = left == text.lower() if "i" in cond.get("$options", "") else (sa.func.trim(col) if trim else col) == text
            return sa.and_(exact, _condition(col, rest)) if rest else exact
    return _condition(col, cond)


def set_path(doc: dict, dotted: str, value: Any) -> None:
    *parents, last = dotted.split(".")
    cur = doc
    for p in parents:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = cur[p] = {}
        cur = nxt
    if value is None:
        cur.pop(last, None)
    else:
        cur[last] = value


class FlatTable:
    def __init__(self, table: sa.Table, cols, always, key_to_col: Optional[dict] = None, str_id: bool = False):
        self.T, self.cols, self.always = table, cols, always
        self.key_to_col = key_to_col or {}
        self.str_id = str_id                     # files: the public id is a UUID string and the key is `id`

    # ---- conversion
    def col(self, key: str):
        return self.T.c[self.key_to_col.get(key, key)]

    def doc(self, row) -> dict:
        d = R.decode_flat(dict(row), self.cols, self.always, key_to_col=self.key_to_col)
        if self.str_id:
            d["id"] = d["_id"] = row["public_id"]
        else:
            d["_id"] = ObjectId(row["public_id"])
        return d

    def _row(self, doc: dict) -> dict:
        body = {k: v for k, v in doc.items() if k not in ("_id", "id")}
        row = R.encode_flat(body, self.cols, key_to_col=self.key_to_col)
        full = {self.key_to_col.get(n, n): None for n, _, _ in self.cols}      # a key that is absent is NULL
        full.update(row)
        return full

    def pid(self, value) -> Optional[str]:
        if self.str_id:
            return str(value) if value else None
        return public_id(value)

    def by_id(self, value):
        pid = self.pid(value)
        return None if pid is None else (self.T.c.public_id == pid)

    # ---- filters
    def where(self, flt: Optional[dict]):
        """Translate a filter dict ({"status": "in_stock", "$or": [...], "name": {"$in": [...]}}) into SQL.

        Only plain columns can be filtered on (a key stored in the JSON `extra` column raises UnsupportedFilter instead of
        silently matching nothing). Operators: equality, $in $nin $ne $gt $gte $lt $lte $exists, $regex for literal search
        text (+ $options "i"), $and $or. `_id` / `id` match the record's public id; {"_id": None} matches nothing."""
        parts = []
        for key, cond in (flt or {}).items():
            if key == "$and":
                parts.append(sa.and_(*[self.where(f) for f in cond]) if cond else sa.true())
            elif key == "$or":
                parts.append(sa.or_(*[self.where(f) for f in cond]) if cond else sa.false())
            elif key in ("_id", "id"):
                if cond is None:
                    parts.append(sa.false())
                elif isinstance(cond, dict) and set(cond) <= {"$in", "$nin"}:
                    ids = [self.pid(v) for v in next(iter(cond.values())) if v is not None]
                    ids = [i for i in ids if i]
                    col = self.T.c.public_id
                    if "$in" in cond:
                        parts.append(col.in_(ids) if ids else sa.false())
                    else:
                        parts.append(col.not_in(ids) if ids else sa.true())
                else:
                    pid = self.pid(cond)
                    parts.append(self.T.c.public_id == pid if pid else sa.false())
            elif key.startswith("$"):
                raise UnsupportedFilter(f"unsupported operator {key}")
            else:
                name = self.key_to_col.get(key, key)
                if name not in self.T.c:
                    raise UnsupportedFilter(f"{self.T.name}.{key} is not a column and cannot be filtered on")
                parts.append(_column_condition(self.T.c[name], cond))
        return sa.and_(*parts) if parts else sa.true()

    def split(self, flt: Optional[dict]):
        """(SQL clause, residual) for a filter. Keys that are not columns can only be tested by equality / $in; those go
        into `residual` and are checked in Python on the rows SQL returns. Anything fancier on such a key raises."""
        clauses, residual = [], {}

        def walk(f: dict):
            for key, cond in (f or {}).items():
                if key == "$and":
                    for sub in cond:
                        walk(sub)
                elif key.startswith("$"):
                    clauses.append(self.where({key: cond}))
                elif key in ("_id", "id") or self.key_to_col.get(key, key) in self.T.c:
                    clauses.append(self.where({key: cond}))
                elif not isinstance(cond, dict) or set(cond) == {"$in"}:
                    residual[key] = cond
                else:
                    raise UnsupportedFilter(f"{self.T.name}.{key} is not a column; only equality / $in can be used on it")
        walk(flt or {})
        return (sa.and_(*clauses) if clauses else sa.true()), residual

    @staticmethod
    def _residual_ok(doc: dict, residual: dict) -> bool:
        for k, cond in residual.items():
            v = doc.get(k)
            if isinstance(cond, dict):
                if v not in cond["$in"] and not (v is None and any(c in (None, "") for c in cond["$in"])):
                    return False
            elif (v if v not in ("",) else None) != (cond if cond != "" else None):
                return False
        return True

    async def find(self, flt: Optional[dict] = None, *, sort: Optional[Sequence] = None, skip: int = 0,
                   limit: Optional[int] = None) -> List[dict]:
        clause, residual = self.split(flt)
        if not residual:
            return await self.select(clause, order=self.order(sort), limit=limit, offset=skip)
        docs = [d for d in await self.select(clause, order=self.order(sort)) if self._residual_ok(d, residual)]
        docs = docs[skip:]
        return docs[:limit] if limit else docs

    async def count_filtered(self, flt: Optional[dict] = None) -> int:
        clause, residual = self.split(flt)
        if not residual:
            return await self.count(clause)
        return len([d for d in await self.select(clause) if self._residual_ok(d, residual)])

    def order(self, spec: Optional[Sequence]) -> list:
        """[("created_at", -1), ("_id", 1)] -> ORDER BY expressions (`_id` = insertion order)."""
        out = []
        for key, direction in (spec or []):
            col = self.T.c.id if key in ("_id", "id") else self.col(key)
            out.append(col.desc() if direction < 0 else col.asc())
        out.append(self.T.c.id.desc() if spec and spec[-1][1] < 0 else self.T.c.id.asc())
        return out

    # ---- reads
    async def select(self, *where, order: Sequence = (), limit: Optional[int] = None, offset: int = 0) -> List[dict]:
        q = sa.select(self.T)
        for w in where:
            q = q.where(w)
        q = q.order_by(*(order or (self.T.c.id,)))
        if offset:
            q = q.offset(offset)
        if limit:
            q = q.limit(limit)
        async with get_engine().connect() as conn:
            rows = (await conn.execute(q)).mappings().all()
        return [self.doc(r) for r in rows]

    async def first(self, *where, order: Sequence = ()) -> Optional[dict]:
        docs = await self.select(*where, order=order, limit=1)
        return docs[0] if docs else None

    async def get(self, value) -> Optional[dict]:
        cond = self.by_id(value)
        return None if cond is None else await self.first(cond)

    async def count(self, *where) -> int:
        q = sa.select(sa.func.count()).select_from(self.T)
        for w in where:
            q = q.where(w)
        async with get_engine().connect() as conn:
            return int((await conn.execute(q)).scalar() or 0)

    async def group_count(self, key_cols: Sequence, *where) -> List[tuple]:
        """SELECT <key_cols>, COUNT(*) ... GROUP BY <key_cols>  ->  [(k1, k2, ..., n), ...]"""
        q = sa.select(*key_cols, sa.func.count()).select_from(self.T).group_by(*key_cols)
        for w in where:
            q = q.where(w)
        async with get_engine().connect() as conn:
            return [tuple(r) for r in (await conn.execute(q)).all()]

    # ---- writes
    def _new_id(self, doc: dict):
        if self.str_id:
            return str(doc.get("id") or doc.get("_id") or ObjectId())
        oid = doc.get("_id") or ObjectId()
        return oid if isinstance(oid, ObjectId) else ObjectId(str(oid))

    async def _insert(self, conn, doc: dict, must_fit: Iterable[str] = ()):
        oid = self._new_id(doc)
        row = self._row(doc)
        for must in must_fit:
            if row.get(self.key_to_col.get(must, must)) is None:
                raise ValueError(f"{must} is required")
        row = {k: v for k, v in row.items() if v is not None}                 # NULL / column defaults on insert
        row["public_id"] = str(oid) if self.str_id else str(oid).lower()
        if self.str_id:
            row.setdefault("is_deleted", 0)
        await conn.execute(sa.insert(self.T).values(**row))
        return oid

    async def insert(self, doc: dict, must_fit: Iterable[str] = ()):
        async with transaction() as conn:
            return await self._insert(conn, doc, must_fit)

    async def insert_many(self, docs: Iterable[dict], must_fit: Iterable[str] = ()) -> list:
        async with transaction() as conn:
            return [await self._insert(conn, d, must_fit) for d in docs]

    async def mutate(self, where: Sequence, fn: Callable[[dict], Any], *, many: bool = False) -> int:
        """Lock the matching row(s), run fn(doc) on each decoded record (it edits the dict in place; returning False
        skips that record) and save. Returns how many records were changed (matched and not skipped)."""
        n = 0
        async with transaction() as conn:
            q = sa.select(self.T).order_by(self.T.c.id).with_for_update()
            for w in where:
                q = q.where(w)
            if not many:
                q = q.limit(1)
            for r in (await conn.execute(q)).mappings().all():
                d = self.doc(r)
                if fn(d) is False:
                    continue
                n += 1
                await conn.execute(sa.update(self.T).where(self.T.c.id == r["id"]).values(**self._row(d)))
        return n

    async def update(self, where: Sequence, fields: dict, *, many: bool = False,
                     guard: Optional[dict] = None, unset: Iterable[str] = ()) -> int:
        """Apply {key: value} to the matching record(s); None clears a key, dotted keys reach into objects.
        `guard` = {key: expected | {"$ne": x}} is checked on the LOCKED record (columns or extra keys alike); a record
        that fails it is left alone. Returns how many records were changed - 0 means nothing matched / a guard failed."""
        def apply(d: dict):
            for k, want in (guard or {}).items():
                have = d.get(k)
                if isinstance(want, dict) and set(want) == {"$ne"}:
                    if have == want["$ne"] or (want["$ne"] is None and have is None):
                        return False
                elif (have or None) != (want or None) if want in (None, "", False) else have != want:
                    return False
            for k in unset:
                d.pop(k, None)
            for k, v in fields.items():
                if "." in k:
                    set_path(d, k, v)
                elif v is None:
                    d.pop(k, None)
                else:
                    d[k] = v
        return await self.mutate(where, apply, many=many)

    async def delete(self, *where, many: bool = False) -> int:
        async with transaction() as conn:
            q = sa.select(self.T.c.id).where(*where).with_for_update()
            ids = [r[0] for r in (await conn.execute(q)).all()]
            if not many:
                ids = ids[:1]
            if ids:
                await conn.execute(sa.delete(self.T).where(self.T.c.id.in_(ids)))
        return len(ids)
