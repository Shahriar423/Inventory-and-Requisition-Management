"""Copy requisitions from MongoDB into MySQL, and prove the copy is complete.

    python -m migration.mysql.migrate schema
    python -m migration.mysql.migrate copy [--dry-run] [--only departments,users,...]
    python -m migration.mysql.migrate verify [--only ...]
    python -m migration.mysql.migrate foreign-keys check | add | drop

Connection settings come from backend/.env (MONGO_URL, DB_NAME, MYSQL_URL); every one can be overridden with
--mongo-url / --mongo-db / --mysql-url. MYSQL_URL looks like  mysql://user:password@127.0.0.1:3307/ims

* `copy` is safe to run again and again (it upserts by the document's ObjectId) and never changes MongoDB.
* `--dry-run` converts everything and reports problems without touching MySQL (no MySQL server needed).
* Documents that cannot be stored faithfully are written to the quarantine file and NOT copied.
* `verify` rebuilds every document from MySQL and compares it with the MongoDB original, then compares totals.
Exit code 0 = everything matched, 1 = differences / quarantined documents, 2 = bad usage.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import unquote, urlparse

from . import convert as cv
from . import foreign_keys as fk
from ims.repositories.mysql import people as P
from ims.repositories.mysql import catalog as Cat

HERE = Path(__file__).parent
REQ_SQL_COLS = ["public_id"] + [c for c, _, _ in cv.REQ_COLS] + ["extra"]
ITEM_SQL_COLS = ["requisition_id", "seq"] + [c for c, _, _ in cv.ITEM_COLS] + ["extra"]
STEP_SQL_COLS = ["requisition_id", "seq"] + [c for c, _, _ in cv.STEP_COLS] + ["extra"]
HIST_SQL_COLS = ["requisition_id"] + [cv.HIST_COLUMN_OF.get(c, c) for c, _, _ in cv.HIST_COLS] + ["extra"]
Q = lambda c: f"`{c}`"          # noqa: E731  (level / role / at / action are keywords)


# ------------------------------------------------------------------------------------------------ connections
def mysql_connect(url: str):
    import pymysql
    from pymysql.constants import CLIENT
    u = urlparse(url)
    conn = pymysql.connect(host=u.hostname or "localhost", port=u.port or 3306, user=unquote(u.username or ""),
                           password=unquote(u.password or ""), database=(u.path or "/").lstrip("/") or None,
                           charset="utf8mb4", autocommit=False, client_flag=CLIENT.FOUND_ROWS)   # rowcount = rows MATCHED
    with conn.cursor() as cur:
        cur.execute("SET SESSION lock_wait_timeout = 60")          # never wait forever for another session's lock
    return conn


def mongo_collection(url: str, db: str, name: str = "requisitions"):
    import pymongo
    return pymongo.MongoClient(url, serverSelectionTimeoutMS=8000)[db][name]


def apply_schema(conn) -> int:
    # drop full-line and trailing "-- comments" (a comment may itself contain a semicolon), then split into statements
    lines = [re.sub(r"\s+--.*$", "", l) for l in (HERE / "schema.sql").read_text().splitlines()]
    text = "\n".join(l for l in lines if not l.strip().startswith("--"))
    stmts = [s.strip() for s in text.split(";") if s.strip()]
    with conn.cursor() as cur:
        for s in stmts:
            cur.execute(s)
    conn.commit()
    return len(stmts)


# ---------------------------------------------------------------------------------------------------- reading
def iter_mongo(coll, batch: int, after: Optional[str] = None) -> Iterable[List[dict]]:
    from bson import ObjectId
    last = ObjectId(after) if after else None
    while True:
        flt = {"_id": {"$gt": last}} if last else {}
        docs = list(coll.find(flt).sort("_id", 1).limit(batch))
        if not docs:
            return
        yield docs
        last = docs[-1]["_id"]


def with_str_id(doc: dict) -> dict:
    return {**doc, "_id": str(doc["_id"])}


# ------------------------------------------------------------------------------------------------------ copy
def _insert_many(cur, table: str, cols: List[str], rows: List[dict]):
    if rows:
        sql = f"INSERT INTO {table} ({', '.join(map(Q, cols))}) VALUES ({', '.join(['%s'] * len(cols))})"
        cur.executemany(sql, [[r.get(c) for c in cols] for r in rows])


def write_doc(cur, rows: dict):
    """Update the row with this document's id, or insert a new one. A collision on requisition_no with ANOTHER document
    raises (and the caller quarantines it) - rows are never merged."""
    req = rows["requisition"]
    cur.execute("SELECT id FROM requisitions WHERE public_id=%s", (req["public_id"],))
    found = cur.fetchone()
    if found:
        rid = found[0]
        sets = ", ".join(f"{Q(c)}=%s" for c in REQ_SQL_COLS if c != "public_id")
        cur.execute(f"UPDATE requisitions SET {sets} WHERE id=%s", [req.get(c) for c in REQ_SQL_COLS if c != "public_id"] + [rid])
    else:
        cur.execute(f"INSERT INTO requisitions ({', '.join(map(Q, REQ_SQL_COLS))}) VALUES ({', '.join(['%s'] * len(REQ_SQL_COLS))})",
                    [req.get(c) for c in REQ_SQL_COLS])
        rid = cur.lastrowid
    for table in ("requisition_items", "approval_steps", "requisition_history"):
        cur.execute(f"DELETE FROM {table} WHERE requisition_id=%s", (rid,))      # children are rewritten as a set
    for key, table, cols in (("items", "requisition_items", ITEM_SQL_COLS), ("steps", "approval_steps", STEP_SQL_COLS),
                             ("history", "requisition_history", HIST_SQL_COLS)):
        for r in rows[key]:
            r["requisition_id"] = rid
        _insert_many(cur, table, cols, rows[key])


def copy(coll, conn, *, batch=200, dry_run=False, after=None, quarantine_path: Optional[Path] = None,
         progress=None) -> dict:
    rep = {"read": 0, "copied": 0, "quarantined": [], "docs_with_raw_timestamps_or_numbers": 0,
           "raw_values_by_field": {}, "docs_with_unmapped_fields": 0, "unmapped_top_level_fields": collections.Counter(),
           "legacy_fields_kept_in_extra": collections.Counter(),
           "known_fields_whose_value_did_not_fit": collections.Counter(), "last_id": None}
    known_cols = {c for c, _, _ in cv.REQ_COLS}
    qfile = open(quarantine_path, "w", encoding="utf-8") if quarantine_path else None
    try:
        for docs in iter_mongo(coll, batch, after):
            cur = None if dry_run else conn.cursor()
            for doc in docs:
                rep["read"] += 1
                rep["last_id"] = str(doc["_id"])
                try:
                    rows = cv.doc_to_rows(with_str_id(doc))
                    extra = json.loads(rows["requisition"]["extra"] or "{}")
                    had_raw = False
                    for table, tr in [("requisitions", [rows["requisition"]])] + [(k, rows[k]) for k in ("items", "steps", "history")]:
                        for r in tr:
                            for fld, orig in json.loads(r["extra"] or "{}").get("_raw", {}).items():
                                had_raw = True
                                slot = rep["raw_values_by_field"].setdefault(f"{table}.{fld}", {"count": 0, "example": orig})
                                slot["count"] += 1
                    rep["docs_with_raw_timestamps_or_numbers"] += int(had_raw)
                    legacy = [k for k in extra if k in cv.LEGACY_FIELDS]
                    rep["legacy_fields_kept_in_extra"].update(legacy)
                    unknown = [k for k in extra if k != "_raw" and k not in known_cols and k not in cv.LEGACY_FIELDS]
                    misfit = [k for k in extra if k in known_cols]
                    if unknown:
                        rep["docs_with_unmapped_fields"] += 1
                        rep["unmapped_top_level_fields"].update(unknown)       # a field the schema has no column for
                    rep["known_fields_whose_value_did_not_fit"].update(misfit)  # e.g. a date that is not a date
                    if cur is not None:
                        cur.execute("SAVEPOINT one_doc")
                        try:
                            write_doc(cur, rows)
                        except Exception as e:                                  # e.g. duplicate requisition_no
                            cur.execute("ROLLBACK TO SAVEPOINT one_doc")
                            raise cv.ConversionError(f"MySQL refused it: {e.__class__.__name__}: {e}")
                    rep["copied"] += 1
                except cv.ConversionError as e:
                    rep["quarantined"].append({"_id": str(doc["_id"]), "requisition_no": doc.get("requisition_no"), "reason": str(e)})
                    if qfile:
                        qfile.write(json.dumps({"reason": str(e), "doc": json.loads(json.dumps(doc, default=str))}, ensure_ascii=False) + "\n")
            if cur is not None:
                conn.commit()
                cur.close()
            if progress:
                progress(rep)
    finally:
        if qfile:
            qfile.close()
    rep["unmapped_top_level_fields"] = dict(rep["unmapped_top_level_fields"])
    rep["legacy_fields_kept_in_extra"] = dict(rep["legacy_fields_kept_in_extra"])
    rep["known_fields_whose_value_did_not_fit"] = dict(rep["known_fields_whose_value_did_not_fit"])
    return rep


# --------------------------------------------------------------------------------------------------- verify
def _fetch_docs(conn, public_ids: List[str]) -> Dict[str, dict]:
    import pymysql.cursors
    out: Dict[str, dict] = {}
    if not public_ids:
        return out
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        ph = ", ".join(["%s"] * len(public_ids))
        cur.execute(f"SELECT * FROM requisitions WHERE public_id IN ({ph})", public_ids)
        reqs = {r["id"]: r for r in cur.fetchall()}
        kids = {"items": collections.defaultdict(list), "steps": collections.defaultdict(list), "history": collections.defaultdict(list)}
        if reqs:
            ids = list(reqs)
            ph2 = ", ".join(["%s"] * len(ids))
            for key, table, order in (("items", "requisition_items", "seq"), ("steps", "approval_steps", "seq"), ("history", "requisition_history", "id")):
                cur.execute(f"SELECT * FROM {table} WHERE requisition_id IN ({ph2}) ORDER BY requisition_id, {order}", ids)
                for r in cur.fetchall():
                    kids[key][r["requisition_id"]].append(r)
        for rid, r in reqs.items():
            out[r["public_id"]] = cv.rows_to_doc(r, kids["items"][rid], kids["steps"][rid], kids["history"][rid])
    return out


def verify(coll, conn, *, batch=200, quarantined_ids: Iterable[str] = ()) -> dict:
    skip = set(quarantined_ids)
    rep = {"checked": 0, "identical": 0, "missing_in_mysql": [], "different": [], "mysql_only": [], "totals": {}}
    mongo_ids = set()
    for docs in iter_mongo(coll, batch):
        docs = [d for d in docs if str(d["_id"]) not in skip]
        rebuilt = _fetch_docs(conn, [str(d["_id"]) for d in docs])
        for d in docs:
            pid = str(d["_id"])
            mongo_ids.add(pid)
            rep["checked"] += 1
            if pid not in rebuilt:
                rep["missing_in_mysql"].append(pid)
            elif cv.normalize_doc(with_str_id(d)) == cv.normalize_doc(rebuilt[pid]):
                rep["identical"] += 1
            else:
                a, b = cv.normalize_doc(with_str_id(d)), cv.normalize_doc(rebuilt[pid])
                rep["different"].append({"_id": pid, "requisition_no": d.get("requisition_no"),
                                         "fields": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))})
    with conn.cursor() as cur:
        cur.execute("SELECT public_id FROM requisitions")
        rep["mysql_only"] = sorted({r[0] for r in cur.fetchall()} - mongo_ids)
    rep["totals"] = _totals(coll, conn, skip)
    return rep


def _totals(coll, conn, skip: set) -> dict:
    mongo = {"requisitions": 0, "by_status": collections.Counter(), "by_type": collections.Counter(), "items": 0, "steps": 0, "history": 0, "sum_total_amount": 0.0}
    for d in coll.find({}):
        if str(d["_id"]) in skip:
            continue
        mongo["requisitions"] += 1
        mongo["by_status"][d.get("status")] += 1
        mongo["by_type"][d.get("requisition_type")] += 1
        mongo["items"] += len(d.get("items") or [])
        mongo["steps"] += len(d.get("approval_chain") or [])
        mongo["history"] += len(d.get("history") or [])
        ta = d.get("total_amount")
        mongo["sum_total_amount"] += ta if isinstance(ta, (int, float)) and not isinstance(ta, bool) else 0
    sql = {}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount),0) FROM requisitions")
        sql["requisitions"], s = cur.fetchone()
        sql["sum_total_amount"] = float(s)
        cur.execute("SELECT status, COUNT(*) FROM requisitions GROUP BY status")
        sql["by_status"] = {k: v for k, v in cur.fetchall()}
        cur.execute("SELECT requisition_type, COUNT(*) FROM requisitions GROUP BY requisition_type")
        sql["by_type"] = {k: v for k, v in cur.fetchall()}
        for key, table in (("items", "requisition_items"), ("steps", "approval_steps"), ("history", "requisition_history")):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            sql[key] = cur.fetchone()[0]
    mongo["by_status"], mongo["by_type"] = dict(mongo["by_status"]), dict(mongo["by_type"])
    mongo["sum_total_amount"] = round(mongo["sum_total_amount"], 2)
    sql["sum_total_amount"] = round(sql["sum_total_amount"], 2)
    # only sections that exist on both sides are comparable; a NULL requisition_type is reported by MySQL as None too
    match = all(mongo[k] == sql[k] for k in ("requisitions", "by_status", "by_type", "items", "steps", "history", "sum_total_amount"))
    return {"mongo": mongo, "mysql": sql, "match": match}



# ----------------------------------------------------------------------------------------- people collections
# departments / users: one document -> one row (upsert by the 24-character id).  sidebar_permissions: one document per role.
# password_resets: an audit log with no natural key, so the table is REPLACED as a whole by each copy.
FLAT = {
    "departments": {"cols": P.DEPT_COLS, "always": P.DEPT_ALWAYS, "must": ("name",)},
    "users": {"cols": P.USER_COLS, "always": P.USER_ALWAYS, "must": tuple(sorted(P.USER_MUST_FIT))},
    "categories": {"cols": Cat.CAT_COLS, "always": Cat.CAT_ALWAYS, "must": tuple(Cat.CAT_MUST_FIT)},
    "products": {"cols": Cat.PRODUCT_COLS, "always": Cat.PRODUCT_ALWAYS, "must": tuple(Cat.PRODUCT_MUST_FIT)},
    "notifications": {"cols": Cat.NOTIF_COLS, "always": Cat.NOTIF_ALWAYS, "must": tuple(Cat.NOTIF_MUST_FIT)},
    "purchase_orders": {"cols": Cat.PO_COLS, "always": Cat.PO_ALWAYS, "must": tuple(Cat.PO_MUST_FIT)},
    "assets": {"cols": Cat.ASSET_COLS, "always": Cat.ASSET_ALWAYS, "must": tuple(Cat.ASSET_MUST_FIT),
               "key_to_col": Cat.ASSET_COLUMN_OF},
    "handovers": {"cols": Cat.HANDOVER_COLS, "always": Cat.HANDOVER_ALWAYS, "must": tuple(Cat.HANDOVER_MUST_FIT)},
    "correction_cases": {"cols": Cat.CORRECTION_COLS, "always": Cat.CORRECTION_ALWAYS, "must": tuple(Cat.CORRECTION_MUST_FIT)},
    "grns": {"cols": Cat.GRN_COLS, "always": Cat.GRN_ALWAYS, "must": tuple(Cat.GRN_MUST_FIT)},
    "asset_history": {"cols": Cat.AH_COLS, "always": Cat.AH_ALWAYS, "must": tuple(Cat.AH_MUST_FIT),
                      "key_to_col": Cat.AH_COLUMN_OF},
    "paper_records": {"cols": Cat.PAPER_COLS, "always": Cat.PAPER_ALWAYS, "must": tuple(Cat.PAPER_MUST_FIT)},
    "saved_reports": {"cols": Cat.SAVED_REPORT_COLS, "always": Cat.SAVED_REPORT_ALWAYS, "must": tuple(Cat.SAVED_REPORT_MUST_FIT)},
    "report_access": {"cols": Cat.REPORT_ACCESS_COLS, "always": Cat.REPORT_ACCESS_ALWAYS, "must": tuple(Cat.REPORT_ACCESS_MUST_FIT)},
    "import_batches": {"cols": Cat.IMPORT_BATCH_COLS, "always": Cat.IMPORT_BATCH_ALWAYS, "must": tuple(Cat.IMPORT_BATCH_MUST_FIT),
                       "key_to_col": Cat.IMPORT_BATCH_COLUMN_OF},
}
ORDER = [
    "departments", "users", "sidebar_permissions", "password_resets", "requisitions",
    "categories", "products", "counters", "files", "notifications", "purchase_orders",
    "assets", "handovers", "correction_cases",
    "grns", "asset_history", "system_settings",
    "paper_records", "saved_reports", "report_access", "import_batches",
]


def _flat_row(name: str, doc: dict) -> dict:
    spec = FLAT[name]
    pid = str(doc.get("_id", ""))
    if len(pid) != 24 or not all(c in "0123456789abcdefABCDEF" for c in pid):
        raise cv.ConversionError("_id is not a 24-character ObjectId")
    row = cv.encode_flat({k: v for k, v in doc.items() if k != "_id"}, spec["cols"], json_text=True,
                         key_to_col=spec.get("key_to_col"))
    for must in spec["must"]:
        col = (spec.get("key_to_col") or {}).get(must, must)
        if col not in row and must not in row:
            raise cv.ConversionError(f"{must} is missing or does not fit its column")
    row["public_id"] = pid.lower()
    return row


def _sidebar_row(doc: dict) -> dict:
    items = doc.get("items")
    if not isinstance(doc.get("role"), str) or not doc["role"].isascii() or not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        raise cv.ConversionError("a saved menu needs a role and a list of menu keys")
    return {"role": doc["role"], "items": json.dumps(items, ensure_ascii=False)}


def _reset_row(doc: dict) -> dict:
    return cv.encode_flat({k: v for k, v in doc.items() if k != "_id"}, P.RESET_COLS, json_text=True)


def _counter_row(doc: dict) -> dict:
    key = doc.get("_id")
    if not isinstance(key, str) or not key:
        raise cv.ConversionError("counter _id must be a non-empty string")
    seq = doc.get("seq", 0)
    if not isinstance(seq, int):
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            raise cv.ConversionError("counter seq must be an integer")
    return {"counter_key": key, "seq": seq}


def _file_row(doc: dict) -> dict:
    fid = doc.get("id") or doc.get("_id")
    if not fid:
        raise cv.ConversionError("file needs an id")
    row = cv.encode_flat({k: v for k, v in doc.items() if k not in ("_id", "id")}, Cat.FILE_COLS, json_text=True)
    if "storage_path" not in row:
        raise cv.ConversionError("storage_path is required")
    row["public_id"] = str(fid)
    if "is_deleted" not in row:
        row["is_deleted"] = 0
    return row


def _settings_row(doc: dict) -> dict:
    import json as _json
    key = doc.get("_id")
    if not isinstance(key, str) or not key:
        raise cv.ConversionError("system_settings _id must be a non-empty string")
    payload = {k: v for k, v in doc.items() if k != "_id"}
    return {"setting_key": key, "payload": _json.dumps(payload, ensure_ascii=False, default=str)}


def copy_people(name: str, coll, conn, *, dry_run=False, quarantine_path: Optional[Path] = None, batch: int = 200) -> dict:
    rep = {"read": 0, "copied": 0, "quarantined": [], "unmapped_fields": collections.Counter()}
    qfile = open(quarantine_path, "a", encoding="utf-8") if quarantine_path else None
    cur = None if dry_run else conn.cursor()
    try:
        if name == "password_resets" and cur is not None:
            cur.execute("DELETE FROM password_resets")
        for docs in iter_mongo(coll, batch):
            for doc in docs:
                rep["read"] += 1
                try:
                    if name in FLAT:
                        row = _flat_row(name, doc)
                        table, key, upsert = name, "public_id", True
                        known = {c for c, _, _ in FLAT[name]["cols"]}
                        rep["unmapped_fields"].update(k for k in json.loads(row.get("extra") or "{}") if k != "_raw" and k not in known)
                    elif name == "sidebar_permissions":
                        row, table, upsert = _sidebar_row(doc), "sidebar_permissions", True
                    elif name == "counters":
                        row, table, upsert = _counter_row(doc), "counters", True
                    elif name == "files":
                        row, table, upsert = _file_row(doc), "files", True
                    elif name == "system_settings":
                        row, table, upsert = _settings_row(doc), "system_settings", True
                    else:
                        row, table, upsert = _reset_row(doc), "password_resets", False
                    if cur is not None:
                        cols = list(row)
                        if table in FLAT or table == "files":
                            keycol = "public_id"
                        elif table == "counters":
                            keycol = "counter_key"
                        elif table == "sidebar_permissions":
                            keycol = "role"
                        elif table == "system_settings":
                            keycol = "setting_key"
                        else:
                            keycol = "id"
                        cur.execute("SAVEPOINT one_doc")
                        try:
                            cur.execute(f"SELECT 1 FROM {table} WHERE {Q(keycol)}=%s", (row[keycol],)) if upsert else None
                            if upsert and cur.fetchone():           # same id: update it; a collision with ANOTHER row's email raises
                                sets = ", ".join(f"{Q(c)}=%s" for c in cols if c != keycol)
                                cur.execute(f"UPDATE {table} SET {sets} WHERE {Q(keycol)}=%s", [row[c] for c in cols if c != keycol] + [row[keycol]])
                            else:
                                cur.execute(f"INSERT INTO {table} ({', '.join(map(Q, cols))}) VALUES ({', '.join(['%s'] * len(cols))})", [row[c] for c in cols])
                        except Exception as e:
                            cur.execute("ROLLBACK TO SAVEPOINT one_doc")
                            raise cv.ConversionError(f"MySQL refused it: {e.__class__.__name__}: {e}")
                    rep["copied"] += 1
                except cv.ConversionError as e:
                    rep["quarantined"].append({"collection": name, "_id": str(doc.get("_id")), "reason": str(e)})
                    if qfile:
                        qfile.write(json.dumps({"collection": name, "reason": str(e), "doc": json.loads(json.dumps(doc, default=str))}, ensure_ascii=False) + "\n")
            if cur is not None:
                conn.commit()
    finally:
        if qfile:
            qfile.close()
        if cur is not None:
            cur.close()
    rep["unmapped_fields"] = dict(rep["unmapped_fields"])
    return rep


def verify_people(name: str, coll, conn, *, skip_ids: Iterable[str] = ()) -> dict:
    import pymysql.cursors
    skip = set(skip_ids)
    mongo_docs = [d for d in coll.find({}) if str(d["_id"]) not in skip]
    rep = {"checked": len(mongo_docs), "identical": 0, "missing_in_mysql": [], "different": [], "mysql_only": []}
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        if name in FLAT:
            spec = FLAT[name]
            cur.execute(f"SELECT * FROM {name}")
            sql_docs = {r["public_id"]: cv.decode_flat(r, spec["cols"], spec["always"], json_text=True,
                                                       key_to_col=spec.get("key_to_col")) for r in cur.fetchall()}
            for d in mongo_docs:
                pid = str(d["_id"])
                if pid not in sql_docs:
                    rep["missing_in_mysql"].append(pid)
                    continue
                a, b = cv.normalize_doc(with_str_id(d)), cv.normalize_doc({**sql_docs[pid], "_id": pid})
                if a == b:
                    rep["identical"] += 1
                else:
                    rep["different"].append({"_id": pid, "fields": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))})
            rep["mysql_only"] = sorted(set(sql_docs) - {str(d["_id"]) for d in mongo_docs})
        elif name == "sidebar_permissions":
            cur.execute("SELECT role, items FROM sidebar_permissions")
            sql = {r["role"]: json.loads(r["items"]) for r in cur.fetchall()}
            mongo = {d["role"]: d["items"] for d in mongo_docs}
            rep["identical"] = sum(1 for r in mongo if sql.get(r) == mongo[r])
            rep["missing_in_mysql"] = sorted(r for r in mongo if r not in sql)
            rep["different"] = sorted(r for r in mongo if r in sql and sql[r] != mongo[r])
            rep["mysql_only"] = sorted(set(sql) - set(mongo))
        elif name == "counters":
            cur.execute("SELECT counter_key, seq FROM counters")
            sql = {r["counter_key"]: r["seq"] for r in cur.fetchall()}
            mongo = {str(d["_id"]): d.get("seq", 0) for d in mongo_docs}
            for key, seq in mongo.items():
                if key not in sql:
                    rep["missing_in_mysql"].append(key)
                elif sql[key] != seq:
                    rep["different"].append({"_id": key, "fields": ["seq"], "mongo": seq, "mysql": sql[key]})
                else:
                    rep["identical"] += 1
            rep["mysql_only"] = sorted(set(sql) - set(mongo))
        elif name == "files":
            # Files use a UUID string as public id (Mongo field is `id`, not always `_id`)
            cur.execute("SELECT * FROM files")
            sql_rows = {r["public_id"]: r for r in cur.fetchall()}
            for d in mongo_docs:
                fid = str(d.get("id") or d.get("_id") or "")
                if fid not in sql_rows:
                    rep["missing_in_mysql"].append(fid)
                    continue
                row = sql_rows[fid]
                rebuilt = cv.decode_flat(row, Cat.FILE_COLS, Cat.FILE_ALWAYS, json_text=True)
                rebuilt["id"] = fid
                # Mongo stores is_deleted as bool; MySQL as 0/1
                a = cv.normalize_doc({k: v for k, v in d.items() if k != "_id"})
                b = cv.normalize_doc(rebuilt)
                # Normalize is_deleted to bool on both sides
                for side in (a, b):
                    if "is_deleted" in side:
                        side["is_deleted"] = bool(side["is_deleted"])
                if a == b:
                    rep["identical"] += 1
                else:
                    rep["different"].append({"_id": fid, "fields": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))})
            mongo_ids = {str(d.get("id") or d.get("_id") or "") for d in mongo_docs}
            rep["mysql_only"] = sorted(set(sql_rows) - mongo_ids)
        elif name == "system_settings":
            cur.execute("SELECT setting_key, payload FROM system_settings")
            sql = {}
            for r in cur.fetchall():
                payload = r["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                sql[r["setting_key"]] = payload or {}
            mongo = {str(d["_id"]): {k: v for k, v in d.items() if k != "_id"} for d in mongo_docs}
            for key, payload in mongo.items():
                if key not in sql:
                    rep["missing_in_mysql"].append(key)
                elif cv.normalize_doc(payload) == cv.normalize_doc(sql[key]):
                    rep["identical"] += 1
                else:
                    a, b = cv.normalize_doc(payload), cv.normalize_doc(sql[key])
                    rep["different"].append({"_id": key, "fields": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))})
            rep["mysql_only"] = sorted(set(sql) - set(mongo))
        else:
            # password_resets (audit log, no natural key - compare as multisets)
            cur.execute("SELECT user_id, user_email, reset_by, reset_by_name, `at` FROM password_resets")
            sql = collections.Counter((r["user_id"], r["user_email"], r["reset_by"], r["reset_by_name"], r["at"].isoformat() if r["at"] else None)
                                      for r in cur.fetchall())

            def norm(d):
                at = d.get("at")
                _dt, _ = cv.parse_ts(at) if isinstance(at, str) else (None, False)
                return (d.get("user_id"), d.get("user_email"), d.get("reset_by"), d.get("reset_by_name"), _dt.isoformat() if _dt else None)
            mongo = collections.Counter(norm(d) for d in mongo_docs)
            rep["identical"] = sum((sql & mongo).values())
            rep["missing_in_mysql"] = [str(k) for k in (mongo - sql)]
            rep["mysql_only"] = [str(k) for k in (sql - mongo)]
    rep["totals"] = {"mongo": len(mongo_docs), "mysql": rep["identical"] + len(rep["mysql_only"]) + len(rep["different"]),
                     "match": not (rep["missing_in_mysql"] or rep["different"] or rep["mysql_only"])}
    return rep


# ------------------------------------------------------------------------------------------------------- CLI
def _load_env() -> None:
    """Read backend/.env so the commands need no long options (values already in the environment win)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE.parent.parent / ".env")
    except ImportError:          # python-dotenv is already a dependency of the backend; just being safe
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="migration.mysql.migrate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["schema", "copy", "verify", "foreign-keys"])
    ap.add_argument("action", nargs="?", choices=["check", "add", "drop"], help="for foreign-keys: check | add | drop")
    _load_env()
    ap.add_argument("--mongo-url", default=os.environ.get("MONGO_URL") or "mongodb://localhost:27017", help="default: MONGO_URL from backend/.env")
    ap.add_argument("--mongo-db", default=os.environ.get("DB_NAME"), help="default: DB_NAME from backend/.env")
    ap.add_argument("--mysql-url", default=os.environ.get("MYSQL_URL"), help="default: MYSQL_URL from backend/.env")
    ap.add_argument("--only", default="all", help="comma-separated: " + ", ".join(ORDER) + "  (default: all, in that order)")
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true", help="convert and report only; do not write to MySQL")
    ap.add_argument("--resume-after", help="requisitions only: continue after this document id (printed as last_id by an earlier run)")
    ap.add_argument("--quarantine", default="quarantine.jsonl")
    ap.add_argument("--report", help="write the JSON report here as well")
    a = ap.parse_args(argv)
    names = ORDER if a.only == "all" else [n.strip() for n in a.only.split(",") if n.strip()]
    if any(n not in ORDER for n in names):
        ap.error(f"--only must be a list of: {', '.join(ORDER)}")
    if a.command == "foreign-keys" and not a.action:
        ap.error("foreign-keys needs an action: check, add or drop")
    if a.command in ("copy", "verify") and not a.mongo_db:
        ap.error("--mongo-db is required (or set DB_NAME in backend/.env)")
    if (a.command != "copy" or not a.dry_run) and not a.mysql_url:
        ap.error("--mysql-url is required (or set MYSQL_URL in backend/.env)")
    conn = mysql_connect(a.mysql_url) if a.mysql_url else None
    try:
        return _run(a, ap, conn, names)
    finally:
        if conn is not None:
            try:
                conn.rollback()                      # a reading command leaves a transaction open: end it, then close
            finally:
                conn.close()


def _run(a, ap, conn, names) -> int:
    if a.command == "schema":
        print(f"applied {apply_schema(conn)} statements")
        return 0
    if a.command == "foreign-keys":
        rep = {"check": fk.check, "add": fk.add, "drop": fk.drop}[a.action](conn)
        print(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
        ok = rep.get("clean", True) and not rep.get("refused")
        print("RESULT:", "OK" if ok else "NEEDS ATTENTION")
        return 0 if ok else 1
    qpath = Path(a.quarantine)
    if a.command == "copy" and qpath.exists():
        qpath.unlink()                                     # one fresh quarantine file per run (each collection appends to it)
    reports, ok = {}, True
    for n in names:
        coll = mongo_collection(a.mongo_url, a.mongo_db, n) if n != "requisitions" else mongo_collection(a.mongo_url, a.mongo_db)
        if a.command == "copy":
            if n == "requisitions":
                rep = copy(coll, conn, batch=a.batch, dry_run=a.dry_run, after=a.resume_after, quarantine_path=qpath,
                           progress=lambda r: print(f"  ... {r['read']} read, {r['copied']} copied", file=sys.stderr))
            else:
                rep = copy_people(n, coll, conn, dry_run=a.dry_run, quarantine_path=qpath, batch=a.batch)
            ok = ok and not rep["quarantined"]
        else:
            q = []
            if qpath.exists():
                for line in qpath.read_text().splitlines():
                    rec = json.loads(line)
                    if rec.get("collection", "requisitions") == n:
                        q.append(str(rec["doc"].get("_id")))
            if n == "requisitions":
                rep = verify(coll, conn, batch=a.batch, quarantined_ids=q)
                ok = ok and not (rep["missing_in_mysql"] or rep["different"] or rep["mysql_only"]) and rep["totals"]["match"]
            else:
                rep = verify_people(n, coll, conn, skip_ids=q)
                ok = ok and rep["totals"]["match"]
        reports[n] = rep
    out_obj = reports[names[0]] if len(names) == 1 else reports
    out = json.dumps(out_obj, indent=1, ensure_ascii=False, default=str)
    if a.report:
        Path(a.report).write_text(out)
    print(out)
    print("RESULT:", "OK" if ok else "NEEDS ATTENTION")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
