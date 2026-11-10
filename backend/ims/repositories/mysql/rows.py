"""Requisition document  <->  MySQL rows.

`doc_to_rows(doc)` splits one requisition document into rows for the four tables in schema.sql.
`rows_to_doc(...)` puts the rows back together into the document shape the application already uses.

Guarantees (checked by tests/test_mysql_conversion.py and by `migrate.py verify`)
  * Nothing is dropped. A key the schema does not know, a value of an unexpected type, or a value that does not
    fit its column goes to the row's JSON `extra` column and comes back unchanged.
  * Timestamps that are not in the application's canonical form (`datetime.now(timezone.utc).isoformat()`) are
    stored in `extra._raw` verbatim, so they come back byte-for-byte - while the DATETIME column still holds a
    usable value for sorting and filtering.
  * A document that cannot be represented at all (missing id/status/number, non-object list entries ...) raises
    ConversionError. The migration puts such documents in a quarantine file for a human to look at.
  * "NULL" means "null or absent" (see normalize_for_compare). Optional keys that are NULL are not emitted.
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

NOT_SET = object()


class ConversionError(Exception):
    """The document cannot be stored faithfully; quarantine it."""


# ------------------------------------------------------------------------------------------ column specs
# (column, kind, max_len). kinds: code = ascii text, str = utf8mb4 VARCHAR, text = TEXT, dt = DATETIME(6), date = DATE,
# bool = TINYINT(1), dec = DECIMAL(14,2), int = INT, json = JSON.
REQ_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("requisition_no", "str", 40), ("requisition_type", "code", 16), ("status", "code", 48),
    ("requisitioner_id", "code", 40), ("requisitioner_name", "str", 150),
    ("requisitioner_department_id", "code", 40), ("requisition_for", "str", 150),
    ("created_at", "dt", None), ("updated_at", "dt", None), ("requisition_date", "date", None),
    ("required_by_date", "date", None), ("closed_at", "dt", None), ("cancelled_at", "dt", None),
    ("service_claimed_at", "dt", None), ("service_completed_at", "dt", None),
    ("requester_note", "text", None), ("overall_business_justification", "text", None),
    ("delivery_location", "str", 255), ("urgency_level", "str", 24), ("total_amount", "dec", None),
    ("edit_count", "int", None), ("attachment_file_id", "code", 64), ("attachment_name", "str", 255),
    ("attachment_path", "str", 512),
    ("pr_flow", "bool", None), ("po_flow", "bool", None), ("pr_needs_refile", "bool", None),
    ("purchase_pr_no", "code", 40), ("pr_filed_by", "str", 150), ("pr_filed_by_id", "code", 40),
    ("pr_cancelled_by", "str", 150), ("pr_cancel_note", "text", None), ("po_id", "code", 40),
    ("fulfillment_type", "code", 32), ("stock_check_at_submission", "code", 24),
    ("procurement_notes", "text", None), ("allocated_by", "str", 150), ("stock_bypassed_by", "str", 150),
    ("handover_id", "code", 40), ("cancelled_by", "str", 150), ("cancel_note", "text", None),
    ("it_team", "str", 40), ("service_assigned_to_id", "code", 40), ("service_assigned_to_name", "str", 150),
    ("service_completed_by", "str", 150),
    ("correction_case_id", "code", 40), ("correction_of_requisition_id", "code", 40),
    ("pr_attachment_file_ids", "json", None), ("allocated_item_details", "json", None),
    ("last_edit", "json", None), ("revision_feedback", "json", None), ("pr_revision_feedback", "json", None),
    ("repair_request", "json", None),
]
REQ_ALWAYS = {"requisition_no", "requisition_type", "status", "created_at", "updated_at", "requisitioner_id",
              "requisitioner_name", "requisitioner_department_id", "requisition_for", "total_amount"}

ITEM_COLS = [
    ("product_type", "code", 24), ("product_name", "str", 255), ("quantity", "int", None), ("rate", "dec", None),
    ("line_total", "dec", None), ("remarks", "text", None), ("category_id", "code", 40),
    ("preferred_specification", "text", None), ("brand_name", "str", 150), ("model", "str", 150),
    ("priority", "code", 16), ("request_type", "code", 64), ("service_category", "code", 64),
    ("request_detail", "text", None), ("category", "str", 64), ("detailed_specs", "text", None),
    ("preferred_brand", "str", 150), ("uom", "str", 24), ("estimated_unit_price", "dec", None),
    ("line_date_required", "date", None), ("justification_remarks", "text", None),
]
ITEM_ALWAYS = {"product_type", "product_name", "quantity", "rate", "remarks", "category_id", "preferred_specification",
               "brand_name", "model", "priority", "request_type", "request_detail", "service_category", "line_total"}

STEP_COLS = [
    ("level", "int", None), ("role", "code", 32), ("label", "str", 120), ("stage", "code", 40),
    ("department_id", "code", 40), ("approver_id", "code", 40), ("approver_name", "str", 150),
    ("status", "code", 24), ("note", "text", None), ("pending_since", "dt", None), ("acted_at", "dt", None),
    ("reminded_at", "dt", None), ("acted_by_id", "code", 40), ("acted_by_name", "str", 150), ("acted_as", "str", 40),
]
STEP_ALWAYS = {"level", "role", "label", "department_id", "approver_id", "approver_name", "status", "note",
               "acted_at", "pending_since"}

HIST_COLS = [("at", "dt", None), ("by", "str", 150), ("action", "code", 64), ("note", "text", None), ("level", "int", None)]
HIST_ALWAYS = {"at", "by", "action", "note"}
HIST_COLUMN_OF = {"by": "by_name"}           # record key -> SQL column when the names differ ("by" is reserved)

TEXT_MAX_BYTES = 65535
DEC_LIMIT = Decimal("999999999999.99")        # DECIMAL(14,2)
INT_LIMIT = 2_147_483_647


# --------------------------------------------------------------------------------------------- value codecs
def _parse_ts(value: str) -> Tuple[Optional[datetime], bool]:
    """(naive-UTC datetime or None, canonical?)  canonical == exactly what datetime.now(utc).isoformat() writes."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None, False
    if dt.tzinfo is None:
        return dt, False                                     # naive: usable for sorting, but not canonical
    utc = dt.astimezone(timezone.utc)
    canonical = dt.utcoffset().total_seconds() == 0 and utc.isoformat() == value
    return utc.replace(tzinfo=None), canonical


parse_ts = _parse_ts                       # public name for the tools (underscore names are not star-exported)


def _encode(kind: str, maxlen: Optional[int], value: Any, json_text: bool = True) -> Tuple[Any, Any]:
    """-> (column value, raw) ; raw is NOT_SET when the column value reproduces `value` exactly.
    Raises TypeError/ValueError when the value cannot live in this column at all (caller moves it to `extra`)."""
    if kind in ("code", "str", "text"):
        if not isinstance(value, str):
            raise TypeError("expected text")
        if kind == "code" and not value.isascii():
            raise ValueError("non-ascii value for an ascii column")
        if kind == "text" and len(value.encode("utf-8")) > TEXT_MAX_BYTES:
            raise ValueError("text too long for TEXT")
        if maxlen and len(value) > maxlen:
            raise ValueError("longer than the column")
        return value, NOT_SET
    if kind == "dt":
        if not isinstance(value, str):
            raise TypeError("expected a timestamp string")
        dt, canonical = _parse_ts(value)
        if dt is None:
            raise ValueError("unparseable timestamp")
        return dt, (NOT_SET if canonical else value)
    if kind == "date":
        if not isinstance(value, str):
            raise TypeError("expected a date string")
        try:
            d = date.fromisoformat(value[:10])          # "2026-10-22" or the date part of a full timestamp
        except ValueError:
            raise ValueError("unparseable date")
        return d, (NOT_SET if value == d.isoformat() else value)   # a longer original text is kept as typed in _raw
    if kind == "bool":
        if not isinstance(value, bool):
            raise TypeError("expected true/false")
        return int(value), NOT_SET
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("expected a whole number")
        if abs(value) > INT_LIMIT:
            raise ValueError("outside INT")
        return value, NOT_SET
    if kind == "bigint":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("expected a whole number")
        if abs(value) > 9_000_000_000_000_000_000:
            raise ValueError("outside BIGINT")
        return value, NOT_SET
    if kind == "dec":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("expected a number")
        try:
            exact = Decimal(repr(value))
        except InvalidOperation:
            raise ValueError("not a finite number")
        if not exact.is_finite() or abs(exact) > DEC_LIMIT:
            raise ValueError("outside DECIMAL(14,2)")
        q = exact.quantize(Decimal("0.01"))
        return q, (NOT_SET if q == exact else value)          # more than 2 decimals -> keep the exact number in _raw
    if kind == "json":
        text = json.dumps(value, ensure_ascii=False)           # TypeError for non-JSON values (e.g. ObjectId, datetime)
        return (text if json_text else value), NOT_SET
    raise AssertionError(kind)


def _decode(kind: str, value: Any, json_text: bool = True) -> Any:
    if value is None:
        return None
    if kind == "dt":
        return value.replace(tzinfo=timezone.utc).isoformat()
    if kind == "date":
        return value.isoformat()
    if kind == "bool":
        return bool(value)
    if kind == "dec":
        return float(value)
    if kind == "json":
        return json.loads(value) if (json_text and isinstance(value, (str, bytes))) else value
    return value


# ---------------------------------------------------------------------------------------------- row builders
def _to_row(src: dict, cols, key_to_col=None, json_text: bool = True) -> Tuple[dict, dict]:
    """Split a mapping into (column values, extra). Unknown keys / unusable values go to extra, untouched."""
    key_to_col = key_to_col or {}
    row, extra, raw = {}, {}, {}
    known = {name for name, _, _ in cols}
    for name, kind, maxlen in cols:
        col = key_to_col.get(name, name)
        if name not in src or src[name] is None:
            continue
        try:
            val, rawval = _encode(kind, maxlen, src[name], json_text)
        except (TypeError, ValueError):
            extra[name] = src[name]
            continue
        row[col] = val
        if rawval is not NOT_SET:
            raw[name] = rawval
    for k, v in src.items():
        if k not in known:
            extra[k] = v
    if raw:
        extra["_raw"] = raw
    return row, extra


def _from_row(row: dict, cols, always, key_to_col=None, json_text: bool = True) -> dict:
    key_to_col = key_to_col or {}
    out = {}
    extra = row.get("extra")
    extra = json.loads(extra) if (json_text and isinstance(extra, (str, bytes))) else (extra or {})
    raw = extra.get("_raw", {})
    for name, kind, _ in cols:
        col = key_to_col.get(name, name)
        val = row.get(col)
        if name in raw:
            out[name] = raw[name]                      # exact original text/number
        elif name in extra:
            out[name] = extra[name]                    # the value did not fit the column: it is kept here, unchanged
        elif val is not None:
            out[name] = _decode(kind, val, json_text)
        elif name in always:
            out[name] = None
    for k, v in extra.items():
        if k != "_raw" and k not in out:
            out[k] = v
    return out


def _extra_json(extra: dict, json_text: bool = True) -> Any:
    try:
        text = json.dumps(extra, ensure_ascii=False) if extra else None
        return text if json_text else (extra or None)
    except (TypeError, ValueError) as e:       # e.g. a native date or id object sitting in an unexpected place
        raise ConversionError(f"contains a value that is not plain JSON ({e})")


def _list_of_dicts(doc: dict, key: str) -> List[dict]:
    v = doc.get(key)
    if v is None:
        return []
    if not isinstance(v, list) or any(not isinstance(x, dict) for x in v):
        raise ConversionError(f"{key} is not a list of objects")
    return v


# -------------------------------------------------------------------------------------------------- public API
LIST_KEYS = ("items", "approval_chain", "history")
LEGACY_FIELDS = {"pr_void_reason", "voided_pr_numbers"}      # written by an older version of the app; kept in `extra`
REQ_SPEC = {name: (kind, maxlen) for name, kind, maxlen in REQ_COLS}
MUST_FIT = {"requisition_no", "status"}                       # NOT NULL, indexed: refuse instead of parking them in extra


def _check_list(value, key: str) -> List[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise ConversionError(f"{key} is not a list of objects")
    return value


def items_to_rows(items, json_text: bool = True) -> List[dict]:
    out = []
    for i, it in enumerate(_check_list(items, "items")):
        row, ex = _to_row(it, ITEM_COLS, None, json_text)
        row["seq"], row["extra"] = i, _extra_json(ex, json_text)
        out.append(row)
    return out


def steps_to_rows(chain, json_text: bool = True) -> List[dict]:
    out = []
    for i, st in enumerate(_check_list(chain, "approval_chain")):
        row, ex = _to_row(st, STEP_COLS, None, json_text)
        if "status" not in row:
            raise ConversionError(f"approval step {i} has no usable status")
        row["seq"], row["extra"] = i, _extra_json(ex, json_text)
        out.append(row)
    return out


def history_to_rows(history, json_text: bool = True) -> List[dict]:
    out = []
    for h in _check_list(history, "history"):
        row, ex = _to_row(h, HIST_COLS, HIST_COLUMN_OF, json_text)
        row["extra"] = _extra_json(ex, json_text)
        out.append(row)
    return out


def doc_to_rows(doc: dict, json_text: bool = True) -> dict:
    """-> {"requisition": {...}, "items": [...], "steps": [...], "history": [...]}   (column -> value dicts).

    json_text=True gives JSON columns as text (PyMySQL); False gives Python objects (SQLAlchemy's JSON type)."""
    pid = str(doc.get("_id", ""))
    if len(pid) != 24 or not all(c in "0123456789abcdefABCDEF" for c in pid):
        raise ConversionError("_id is not a 24-character ObjectId")
    if not isinstance(doc.get("requisition_no"), str) or not doc["requisition_no"]:
        raise ConversionError("missing requisition_no")
    if not isinstance(doc.get("status"), str) or not doc["status"].isascii():
        raise ConversionError("missing or unusable status")
    for k in LIST_KEYS:
        _check_list(doc.get(k), k)

    top = {k: v for k, v in doc.items() if k != "_id" and k not in LIST_KEYS}
    req, extra = _to_row(top, REQ_COLS, None, json_text)
    if "requisition_no" not in req or "status" not in req:
        raise ConversionError("requisition_no / status does not fit its column")
    req["public_id"] = pid.lower()
    req.setdefault("total_amount", Decimal("0"))
    req["extra"] = _extra_json(extra, json_text)
    return {"requisition": req, "items": items_to_rows(doc.get("items"), json_text),
            "steps": steps_to_rows(doc.get("approval_chain"), json_text),
            "history": history_to_rows(doc.get("history"), json_text)}


def rows_to_doc(req: dict, items: List[dict], steps: List[dict], history: List[dict], json_text: bool = True) -> dict:
    """Rebuild the application's document from the rows (rows already ordered: items/steps by seq, history by id)."""
    doc = _from_row(req, REQ_COLS, REQ_ALWAYS, None, json_text)
    doc["_id"] = req["public_id"]
    doc["items"] = [_from_row(r, ITEM_COLS, ITEM_ALWAYS, None, json_text) for r in items]
    doc["approval_chain"] = [_from_row(r, STEP_COLS, STEP_ALWAYS, None, json_text) for r in steps]
    doc["history"] = [_from_row(r, HIST_COLS, HIST_ALWAYS, HIST_COLUMN_OF, json_text) for r in history]
    return doc


def _set_path(obj: dict, dotted: str, value: Any) -> None:
    """dotted-path set {"a.b.c": v}  on a plain dict (creating missing levels)."""
    *parents, last = dotted.split(".")
    for p in parents:
        nxt = obj.get(p)
        if not isinstance(nxt, dict):
            nxt = obj[p] = {}
        obj = nxt
    obj[last] = value


def plan_update(current: dict, fields: dict, cols, always, *, must_fit=(), zero_default=(), skip_dotted=(),
                json_text: bool = False) -> Tuple[dict, Any]:
    """What to write when `fields` (top-level keys, for a partial update) are applied to a stored row.

    `current` is the row as read (all columns + extra). Returns (column values to SET, new `extra`).
    * `None` clears the field (null and absent are the same).
    * A value that does not fit its column is parked in `extra` - never dropped, never rounded.
    * "a.b" keys (dotted paths, e.g. repair_request.status) are applied inside the stored object first.
    `must_fit` columns (NOT NULL) refuse instead of parking; `zero_default` columns fall back to 0 instead of NULL."""
    spec = {name: (kind, maxlen) for name, kind, maxlen in cols}
    fields = dict(fields)
    dotted = {k: fields.pop(k) for k in list(fields) if "." in k}
    if dotted:
        view = _from_row(current, cols, always, None, json_text)
        for k, v in dotted.items():
            base = k.split(".", 1)[0]
            if base in skip_dotted:
                raise ConversionError(f"dotted update of {base} is not supported")
            clone = json.loads(json.dumps(view.get(base))) if isinstance(view.get(base), (dict, list)) else view.get(base)
            holder = {base: clone if isinstance(clone, dict) else {}}
            _set_path(holder, k, v)
            view[base] = fields[base] = holder[base]
    extra = current.get("extra")
    extra = json.loads(extra) if (json_text and isinstance(extra, (str, bytes))) else dict(extra or {})
    raw = dict(extra.pop("_raw", {}))
    columns: dict = {}
    for key, value in fields.items():
        extra.pop(key, None)
        raw.pop(key, None)
        if key not in spec:
            if value is not None:
                extra[key] = value
            continue
        kind, maxlen = spec[key]
        zero = Decimal("0") if key in zero_default else None
        if value is None:
            if key in must_fit:
                raise ConversionError(f"{key} cannot be cleared")
            columns[key] = zero
            continue
        try:
            val, rawval = _encode(kind, maxlen, value, json_text)
        except (TypeError, ValueError):
            if key in must_fit:
                raise ConversionError(f"{key} does not fit its column")
            columns[key] = zero
            extra[key] = value
            continue
        columns[key] = val
        if rawval is not NOT_SET:
            raw[key] = rawval
    if raw:
        extra["_raw"] = raw
    return columns, _extra_json(extra, json_text)


def plan_scalar_update(current: dict, fields: dict, json_text: bool = False) -> Tuple[dict, Any]:
    """plan_update for a requisition row (the three lists items / approval_chain / history are handled by the caller)."""
    return plan_update(current, fields, REQ_COLS, REQ_ALWAYS, must_fit=MUST_FIT, zero_default=("total_amount",),
                       skip_dotted=LIST_KEYS, json_text=json_text)


def encode_flat(src: dict, cols, json_text: bool = False, key_to_col=None) -> dict:
    """A whole stored document -> one row (known keys as columns, everything else in `extra`)."""
    row, extra = _to_row(src, cols, key_to_col, json_text)
    row["extra"] = _extra_json(extra, json_text)
    return row


def decode_flat(row: dict, cols, always, json_text: bool = False, key_to_col=None) -> dict:
    """One row -> the document the application uses."""
    return _from_row(row, cols, always, key_to_col, json_text)


# --------------------------------------------------------------------------------------------- verification
def normalize_doc(doc: dict) -> dict:
    """normalize_for_compare for a whole requisition: also "no total_amount" == 0 (the column defaults to 0)
    and the id is compared as text."""
    d = normalize_for_compare(dict(doc))
    if d.get("total_amount") == 0:
        d.pop("total_amount", None)
    if "_id" in d:
        d["_id"] = str(d["_id"])
    return d


def normalize_for_compare(value: Any) -> Any:
    """What "the same document" means: null == absent, a missing list == [], 0 == 0.0, key order irrelevant."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            n = normalize_for_compare(v)
            if n is None or (n == [] and k in ("items", "approval_chain", "history")):
                continue
            out[k] = n
        return out
    if isinstance(value, list):
        return [normalize_for_compare(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
