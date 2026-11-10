"""Translate the filter dicts the application builds (e.g. {"status": {"$in": [...]}, "$or": [...]}) into SQLAlchemy Core expressions.

Only the operators the application really uses are supported - anything else raises UnsupportedFilter instead of guessing:
equality, $in, $nin, $ne, $gt/$gte/$lt/$lte, $exists, $regex (+ $options "i") for a *literal* search text, $and, $or, and
"any approval step has ..." for the dotted paths  approval_chain.<field>  /  approval_chain.<n>.<field>.

NULL policy: "field is null" and "field is absent" are the same thing in MySQL; the translator treats them alike (that is also
how the application uses them: {"x": None} and {"$in": [None, ""]} mean "empty or missing").
"""
import re
from typing import Any

import sqlalchemy as sa

from .tables import approval_steps as steps, requisitions as r


class UnsupportedFilter(ValueError):
    pass


SCALAR_FIELDS = {name: r.c[name] for name in (
    "requisition_no", "requisition_type", "status", "requisitioner_id", "requisitioner_name",
    "requisitioner_department_id", "requisition_for", "total_amount", "created_at", "updated_at", "purchase_pr_no",
    "pr_filed_by_id", "po_id", "handover_id", "it_team", "service_assigned_to_id", "fulfillment_type",
    "correction_case_id", "correction_of_requisition_id", "pr_flow", "po_flow")}
STEP_FIELDS = {name: steps.c[name] for name in ("stage", "approver_id", "status", "role", "level", "department_id", "acted_by_id")}
_ESCAPED_LITERAL = re.compile(r"^(?:[^\\]|\\.)*$")
_REGEX_SYNTAX = re.compile(r"[.^$*+?{}\[\]|()]")


def _like_literal(pattern: str) -> str:
    """The app searches with re.escape(text): turn that back into the plain text and make it LIKE-safe."""
    if not isinstance(pattern, str) or not _ESCAPED_LITERAL.match(pattern) or _REGEX_SYNTAX.search(re.sub(r"\\.", "", pattern)):
        raise UnsupportedFilter("only literal (re.escape'd) search text is supported in $regex")
    text = re.sub(r"\\(.)", r"\1", pattern)
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _condition(col, cond: Any):
    if not isinstance(cond, dict):
        return col.is_(None) if cond is None else col == cond
    opts = cond.get("$options", "")
    parts = []
    for op, val in cond.items():
        if op == "$options":
            continue
        if op in ("$in", "$nin"):
            if not isinstance(val, (list, tuple)):
                raise UnsupportedFilter(f"{op} needs a list")
            nulls = any(v is None for v in val)
            vals = [v for v in val if v is not None]
            if op == "$in":
                inner = ([col.in_(vals)] if vals else []) + ([col.is_(None)] if nulls else [])
                parts.append(sa.or_(*inner) if inner else sa.false())
            else:          # $nin also matches documents where the field is missing
                body = col.not_in(vals) if vals else sa.true()
                parts.append(sa.and_(col.is_not(None), body) if nulls else sa.or_(col.is_(None), body))
        elif op == "$ne":
            parts.append(col.is_not(None) if val is None else sa.or_(col.is_(None), col != val))
        elif op in ("$gt", "$gte", "$lt", "$lte"):
            parts.append({"$gt": col > val, "$gte": col >= val, "$lt": col < val, "$lte": col <= val}[op])
        elif op == "$exists":
            parts.append(col.is_not(None) if val else col.is_(None))
        elif op == "$regex":
            if set(opts) - {"i"}:
                raise UnsupportedFilter(f"unsupported regex option {opts!r}")
            target = col if "i" in opts else col.collate("utf8mb4_0900_as_cs")
            parts.append(target.like(_like_literal(val), escape="\\"))
        else:
            raise UnsupportedFilter(f"unsupported operator {op}")
    return sa.and_(*parts) if parts else sa.true()


def _step_condition(path: str, cond: Any):
    bits = path.split(".")[1:]                      # approval_chain.<field>   or   approval_chain.<n>.<field>
    seq = None
    if len(bits) == 2 and bits[0].isdigit():
        seq, bits = int(bits[0]), bits[1:]
    if len(bits) != 1 or bits[0] not in STEP_FIELDS:
        raise UnsupportedFilter(f"unsupported approval-chain path {path}")
    where = [steps.c.requisition_id == r.c.id, _condition(STEP_FIELDS[bits[0]], cond)]
    if seq is not None:
        where.append(steps.c.seq == seq)
    return sa.exists().where(*where).correlate(r)


def to_clause(flt: dict):
    """-> a SQLAlchemy boolean expression over `requisitions` (and `approval_steps` through EXISTS). {} -> true."""
    clauses = []
    for key, cond in (flt or {}).items():
        if key in ("$and", "$or"):
            subs = [to_clause(x) for x in cond]
            clauses.append((sa.and_ if key == "$and" else sa.or_)(*subs) if subs else (sa.true() if key == "$and" else sa.false()))
        elif key.startswith("approval_chain."):
            clauses.append(_step_condition(key, cond))
        elif key in SCALAR_FIELDS:
            clauses.append(_condition(SCALAR_FIELDS[key], cond))
        else:
            raise UnsupportedFilter(f"field {key!r} is not mapped to a column")
    return sa.and_(*clauses) if clauses else sa.true()
