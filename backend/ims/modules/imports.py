"""Bulk import and paper records."""

import asyncio
import json
import secrets
from fastapi import Response, HTTPException, Depends, UploadFile, File, Form
from pydantic import EmailStr
from typing import List, Optional
from datetime import datetime, timezone
from ims.ids import ObjectId
import io
import uuid
import re
import csv as _csv
from datetime import date as _date
from ims.repositories import departments as dept_repo
from ims.repositories import users as users_repo
from ims.repositories import files_repo
from ims.repositories import assets as asset_repo
from ims.repositories import asset_history as ah_repo
from ims.repositories import paper_records as paper_repo
from ims.repositories import import_batches as import_batches_repo
from ims.common import (
    APP_NAME,
    MIME_TYPES,
    ROLE_LABELS,
    _is_it_head,
    api_router,
    find_dept_by_type,
    generate_temp_password,
    get_current_user,
    hash_password,
    now_iso,
    put_object,
    require_roles,
)

IMPORT_MAX_ROWS = {"users": 2000, "assets": 5000}


IMPORT_MAX_BYTES = 5 * 1024 * 1024


PAPER_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "pdf"}


PAPER_MAX_BYTES = 15 * 1024 * 1024          # one scan


PAPER_MAX_FILES = 10                        # files in one paper record


PHOTO_MAX_FILES = 150                       # photos in one bulk import


PHOTO_MAX_TOTAL = 90 * 1024 * 1024          # all photos of one bulk import


USER_COLS = [  # (field, header, required)
    ("name", "Name", True), ("email", "Email", True), ("department", "Department", True),
    ("role", "Role", True), ("role_label", "Role Label", False), ("it_team", "IT Team", False),
    ("can_raise_pr", "Can Raise PR", False), ("can_create_po", "Can Create PO", False)]


ASSET_COLS = [
    ("email", "Employee Email", True), ("name", "Product Name", True), ("brand", "Brand", False),
    ("category", "Category", False), ("specification", "Specification", False),
    ("serial_no", "Serial No", False), ("tag_id", "Tag ID", False),
    ("assigned_date", "Assigned Date", False), ("photo", "Document Photo", False), ("remarks", "Remarks", False)]


# Accepted spellings for header cells (after normalising: lower-case, symbols -> spaces).
IMPORT_HEADER_ALIASES = {
    "name": ["name", "full name", "employee name", "product name", "product", "item", "item name", "device"], "email": ["email", "email address", "employee email", "e mail"],
    "department": ["department", "dept"], "role": ["role"], "role_label": ["role label", "designation", "title"],
    "it_team": ["it team", "team"], "can_raise_pr": ["can raise pr", "raise pr"], "can_create_po": ["can create po", "create po"],
    "photo": ["document photo", "photo", "photo file", "document", "document file", "scan", "scanned form", "form photo", "image"],
    "brand": ["brand", "make"],
    "specification": ["specification", "specifications", "specs", "spec", "configuration", "config", "model details"], "category": ["category", "type", "product type"],
    "serial_no": ["serial no", "serial number", "serial", "sl no", "s n"], "tag_id": ["tag id", "tag", "asset tag", "tag no"],
    "assigned_date": ["assigned date", "date", "issue date", "assign date"], "remarks": ["remarks", "note", "notes", "comment"],
}


IMPORT_ROLE_ALIASES = {
    "executive": "executive", "dept head": "dept_head", "department head": "dept_head", "dept_head": "dept_head",
    "head": "dept_head", "accounts": "accounts", "md": "md", "managing director": "md",
    "purchase head": "purchase_head", "purchase_head": "purchase_head"}


IMPORT_TEAM_ALIASES = {
    "application": "Application", "app": "Application", "network infra": "Network_Infra",
    "network and infra": "Network_Infra", "network infra structure": "Network_Infra", "network_infra": "Network_Infra"}


IMPORT_CATEGORY_ALIASES = {
    "asset": "asset", "it asset": "asset", "it assets": "asset", "it accessories": "it_accessories",
    "it_accessories": "it_accessories", "accessories": "it_accessories", "network": "network",
    "consumable": "consumable", "furniture": "furniture"}


def _imp_norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


def _imp_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, _date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))          # Excel stores 12345 as 12345.0
    return " ".join(str(v).split())


def _imp_parse_date(v: str) -> Optional[str]:
    """Accepts YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY. Returns an ISO UTC string or None."""
    v = (v or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v[:10], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    raise ValueError("Date must look like 2025-03-31 or 31/03/2025")


def _imp_bool(v: str) -> bool:
    n = _imp_norm(v)
    if n in ("", "no", "n", "false", "0"):
        return False
    if n in ("yes", "y", "true", "1", "x"):
        return True
    raise ValueError("use Yes or No")


def _imp_read_table(filename: str, data: bytes, kind: str) -> List[tuple]:
    """Returns [(sheet_row_number, {field: value})]. Empty rows are skipped."""
    wanted = USER_COLS if kind == "users" else ASSET_COLS
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(status_code=501, detail="Excel support needs the 'openpyxl' package on the server (pip install openpyxl). Upload a .csv file instead.")
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not read this Excel file. Use the downloaded template.")
        ws = next((wb[s] for s in wb.sheetnames if s.lower() == kind), wb[wb.sheetnames[0]])
        raw = [[_imp_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
    elif name.endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        raw = [[_imp_cell(c) for c in row] for row in _csv.reader(io.StringIO(text))]
    else:
        raise HTTPException(status_code=400, detail="Upload an .xlsx or .csv file")

    # Header row = the first row that contains the required column names.
    hdr_idx, colmap = None, {}
    for i, row in enumerate(raw[:15]):
        cm = {}
        for j, cell in enumerate(row):
            n = _imp_norm(cell)
            for field, aliases in IMPORT_HEADER_ALIASES.items():
                if n in aliases and field in [w[0] for w in wanted] and field not in cm:
                    cm[field] = j
        if all(f in cm for f, _h, req in wanted if req):
            hdr_idx, colmap = i, cm
            break
    if hdr_idx is None:
        need = ", ".join(h for _f, h, req in wanted if req)
        raise HTTPException(status_code=400, detail=f"Column headings not found. The first row must contain: {need}. Use the downloaded template.")
    rows = []
    for i in range(hdr_idx + 1, len(raw)):
        row = raw[i]
        rec = {f: (row[j] if j < len(row) else "") for f, j in colmap.items()}
        if not any(rec.values()):
            continue
        rows.append((i + 1, rec))
    if len(rows) > IMPORT_MAX_ROWS[kind]:
        raise HTTPException(status_code=400, detail=f"Too many rows ({len(rows)}). Split the file into batches of {IMPORT_MAX_ROWS[kind]} or fewer.")
    if not rows:
        raise HTTPException(status_code=400, detail="The file has no data rows")
    return rows


async def _imp_validate_users(rows: List[tuple]) -> List[dict]:
    from pydantic import TypeAdapter
    email_ta = TypeAdapter(EmailStr)
    depts = {_imp_norm(d["name"]): d for d in await dept_repo.list_all()}
    it_dept = await find_dept_by_type("it")
    purchase_dept = await find_dept_by_type("purchase")
    it_id = str(it_dept["_id"]) if it_dept else None
    po_id = str(purchase_dept["_id"]) if purchase_dept else None
    existing = {(u.get("email") or "").lower() for u in await users_repo.list_all(only_fields=["email"])}
    seen, out = set(), []
    for rno, r in rows:
        errs, warn = [], []
        name = r.get("name", "")
        email = r.get("email", "").lower()
        if not name:
            errs.append("Name is required")
        if not email:
            errs.append("Email is required")
        else:
            try:
                email = str(email_ta.validate_python(email)).lower()
            except Exception:
                errs.append(f"'{email}' is not a valid email address")
        dept = depts.get(_imp_norm(r.get("department", "")))
        if not r.get("department"):
            errs.append("Department is required")
        elif not dept:
            errs.append(f"Department '{r['department']}' not found (check Organization > Departments)")
        role = IMPORT_ROLE_ALIASES.get(_imp_norm(r.get("role", "")))
        if not r.get("role"):
            errs.append("Role is required")
        elif not role:
            errs.append(f"Role '{r['role']}' is not valid (Executive, Dept Head, Accounts, Managing Director, Purchase Head)")
        dept_id = str(dept["_id"]) if dept else None
        team = None
        if r.get("it_team"):
            team = IMPORT_TEAM_ALIASES.get(_imp_norm(r["it_team"]))
            if not team:
                errs.append(f"IT Team '{r['it_team']}' is not valid (Application or Network & Infra)")
            elif dept_id != it_id:
                errs.append("IT Team is only for the IT department")
        flags = {}
        for f, label, only_id, only_name in (("can_raise_pr", "Can Raise PR", it_id, "IT"), ("can_create_po", "Can Create PO", po_id, "Purchase")):
            try:
                flags[f] = _imp_bool(r.get(f, ""))
            except ValueError:
                flags[f] = False
                errs.append(f"{label}: use Yes or No")
                continue
            if flags[f] and dept_id != only_id:
                errs.append(f"{label} is only for the {only_name} department")
        status = "ok"
        if email and email in existing:
            status = "skip"
            warn.append("A user with this email already exists - will be skipped")
        elif email and email in seen:
            errs.append("Email appears more than once in this file")
        if email:
            seen.add(email)
        if errs:
            status = "error"
        out.append({"row": rno, "status": status, "summary": f"{name or '—'} · {email or '—'}",
                    "messages": errs + warn,
                    "data": {"name": name, "email": email, "department_id": dept_id, "department_name": dept["name"] if dept else None,
                             "role": role, "role_label": r.get("role_label") or (ROLE_LABELS.get(role) if role else None),
                             "it_team": team, **flags}})
    return out


async def _imp_validate_assets(rows: List[tuple], photo_names: Optional[set] = None) -> List[dict]:
    users = {(u.get("email") or "").lower(): u for u in await users_repo.list_all()}
    tags, serials = set(), set()
    for tag_id, serial_no in await asset_repo.tags_and_serials():
        a = {"tag_id": tag_id, "serial_no": serial_no}
        if a.get("tag_id"):
            tags.add(str(a["tag_id"]).strip().lower())
        if a.get("serial_no"):
            serials.add(str(a["serial_no"]).strip().lower())
    seen_t, seen_s, out = set(), set(), []
    for rno, r in rows:
        errs = []
        email = r.get("email", "").lower()
        emp = users.get(email)
        if not email:
            errs.append("Employee Email is required")
        elif not emp:
            errs.append(f"No employee with email '{email}' - import the users first")
        if not r.get("name"):
            errs.append("Product Name is required")
        cat = None
        if r.get("category"):
            cat = IMPORT_CATEGORY_ALIASES.get(_imp_norm(r["category"]))
            if not cat:
                errs.append(f"Category '{r['category']}' is not valid (IT Asset, IT Accessories, Network, Consumable, Furniture)")
        when = None
        try:
            when = _imp_parse_date(r.get("assigned_date", ""))
        except ValueError as e:
            errs.append(f"Assigned Date: {e}")
        photos = [p.strip() for p in re.split(r"[;|\n]+", r.get("photo", "") or "") if p.strip()]
        for pn in photos:
            if pn.rsplit(".", 1)[-1].lower() not in PAPER_EXTS or "." not in pn:
                errs.append(f"Document Photo '{pn}': only JPG, PNG, WEBP, GIF or PDF")
            elif pn.lower() not in (photo_names or set()):
                errs.append(f"Document Photo '{pn}' was not selected - add it in the photo step")
        for val, field, label, in_db, seen in ((r.get("tag_id", ""), "tag_id", "Tag ID", tags, seen_t), (r.get("serial_no", ""), "serial_no", "Serial No", serials, seen_s)):
            k = val.strip().lower()
            if not k:
                continue
            if k in in_db:
                errs.append(f"{label} '{val}' already exists in the system")
            elif k in seen:
                errs.append(f"{label} '{val}' appears more than once in this file")
            seen.add(k)
        out.append({"row": rno, "status": "error" if errs else "ok",
                    "summary": f"{r.get('name') or '—'} → {(emp or {}).get('name') or email or '—'}",
                    "messages": errs, "photos": photos,
                    "data": {"photos": photos, "emp_id": str(emp["_id"]) if emp else None, "name": r.get("name", ""), "brand": r.get("brand") or None,
                             "category_id": cat, "specification": r.get("specification") or None,
                             "tag_id": r.get("tag_id") or None, "serial_no": r.get("serial_no") or None,
                             "assigned_date": when, "remarks": r.get("remarks") or None}})
    return out


@api_router.post("/import/{kind}")
async def bulk_import(kind: str, file: UploadFile = File(...), dry_run: bool = Form(True), allow_partial: bool = Form(False),
                      photos: List[UploadFile] = File([]), photo_names: Optional[str] = Form(None),
                      user: dict = Depends(require_roles("super_admin"))):
    if kind not in ("users", "assets"):
        raise HTTPException(status_code=404, detail="Unknown import type")
    data = await file.read()
    if len(data) > IMPORT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (5 MB maximum)")
    rows = _imp_read_table(file.filename or "", data, kind)
    # Photos of the paper forms (assets import only). The preview sends just the file NAMES; the real import sends the files.
    photo_bytes: dict = {}
    names_lc: set = set()
    if kind == "assets":
        if photos:
            if len(photos) > PHOTO_MAX_FILES:
                raise HTTPException(status_code=400, detail=f"Too many photos ({len(photos)}). Import at most {PHOTO_MAX_FILES} per batch.")
            for f in photos:
                photo_bytes[(f.filename or "").strip().lower()] = ((f.filename or "").strip(), await f.read())
            names_lc = set(photo_bytes)
        elif photo_names:
            try:
                names_lc = {str(n).strip().lower() for n in json.loads(photo_names)}
            except Exception:
                names_lc = set()
    result = await (_imp_validate_users(rows) if kind == "users" else _imp_validate_assets(rows, names_lc))
    counts = {"total": len(result), "ok": sum(r["status"] == "ok" for r in result),
              "skipped": sum(r["status"] == "skip" for r in result), "errors": sum(r["status"] == "error" for r in result)}
    resp = {"kind": kind, "filename": file.filename, "dry_run": dry_run, **counts, "created": 0, "credentials": [], "batch_id": None,
            "photos_saved": 0}

    if not dry_run:
        if counts["errors"] and not allow_partial:
            raise HTTPException(status_code=400, detail=f"{counts['errors']} row(s) have errors. Fix the file, or choose to import only the valid rows.")
        good = [r for r in result if r["status"] == "ok"]
        if not good:
            raise HTTPException(status_code=400, detail="There are no valid rows to import")
        batch_id = secrets.token_hex(6)
        stamp = now_iso()
        if kind == "assets":
            used = {p.lower() for r in good for p in r["data"]["photos"]}
            if sum(len(b) for _n, b in photo_bytes.values()) > PHOTO_MAX_TOTAL:
                raise HTTPException(status_code=400, detail="The photos are too large in total (90 MB maximum per import). Import in smaller batches.")
            for key in used:
                _paper_check(*photo_bytes[key])        # nothing is saved if any photo is bad
        if kind == "users":
            temps = [generate_temp_password() for _ in good]
            hashes = []
            for i in range(0, len(temps), 16):       # bcrypt is slow: hash in worker threads, not on the event loop
                hashes += await asyncio.gather(*[asyncio.to_thread(hash_password, t) for t in temps[i:i + 16]])
            docs = []
            for r, h in zip(good, hashes):
                d = r["data"]
                docs.append({"name": d["name"], "email": d["email"], "password_hash": h, "department_id": d["department_id"],
                             "role": d["role"], "role_label": d["role_label"], "can_raise_pr": d["can_raise_pr"],
                             "can_create_po": d["can_create_po"], "it_team": d["it_team"], "created_at": stamp,
                             "must_change_password": True, "password_changed_at": stamp, "import_batch": batch_id})
            try:
                await users_repo.insert_many(docs)
            except Exception as e:                    # e.g. someone created the same email between preview and import
                raise HTTPException(status_code=409, detail=f"Import stopped: {str(e)[:200]}. Run the check again.")
            resp["credentials"] = [{"name": d["name"], "email": d["email"], "temporary_password": t} for d, t in zip(docs, temps)]
            resp["created"] = len(docs)
        else:
            emps = {str(u["_id"]): u for u in await users_repo.list_by_ids([r["data"]["emp_id"] for r in good])}
            docs = []
            for r in good:
                d = r["data"]
                emp = emps[d["emp_id"]]
                when = d["assigned_date"] or stamp
                docs.append({"name": d["name"], "brand": d["brand"], "serial_no": d["serial_no"], "tag_id": d["tag_id"],
                             "category_id": d["category_id"], "specification": d["specification"],
                             "status": "assigned", "assigned_to": emp["name"],
                             "assigned_to_user_id": str(emp["_id"]), "assigned_department_id": emp.get("department_id"),
                             "assigned_at": when, "receipt_confirmed": True, "receipt_confirmed_at": when,
                             "pending_receipt": False, "pending_handover_id": None, "assigned_slip_no": None,
                             "remarks": d["remarks"], "source": "existing_entry", "added_by": user["name"],
                             "created_at": stamp, "import_batch": batch_id})
            inserted_ids = await asset_repo.insert_many(docs)
            # One paper record per (employee, photo): a single scanned form can cover several devices.
            groups: dict = {}
            for r, aid in zip(good, inserted_ids):
                for pn in r["data"]["photos"]:
                    g = groups.setdefault((r["data"]["emp_id"], pn.lower()), {"asset_ids": [], "dates": []})
                    g["asset_ids"].append(str(aid))
                    if r["data"]["assigned_date"]:
                        g["dates"].append(r["data"]["assigned_date"])
            for (emp_id, key), g in groups.items():
                emp = emps[emp_id]
                orig, data_b = photo_bytes[key]
                fid = await _store_paper_file(emp_id, orig, data_b, user)
                await paper_repo.insert({
                    "employee_id": emp_id, "employee_name": emp.get("name"), "employee_email": emp.get("email"),
                    "department_id": emp.get("department_id"), "kind": "handover", "doc_date": min(g["dates"]) if g["dates"] else None,
                    "form_no": None, "remarks": f"Added by bulk import {batch_id}", "file_ids": [fid], "asset_ids": g["asset_ids"],
                    "created_by": user["name"], "created_by_id": str(user["_id"]), "created_at": stamp})
            resp["photos_saved"] = len(groups)
            await ah_repo.insert_many([{
                "asset_id": str(aid), "asset_name": a["name"], "tag_id": a["tag_id"], "serial_no": a["serial_no"],
                "event": "issued", "employee_user_id": a["assigned_to_user_id"], "employee_name": a["assigned_to"],
                "slip_no": None, "handover_id": None, "by": user["name"], "at": a["assigned_at"],
                "source": "existing_entry", "import_batch": batch_id} for aid, a in zip(inserted_ids, docs)])
            resp["created"] = len(docs)
        await import_batches_repo.insert({"batch_id": batch_id, "kind": kind, "filename": file.filename, "by": user["name"],
                                            "by_id": str(user["_id"]), "at": stamp, "created": resp["created"], **counts})
        resp["batch_id"] = batch_id

    resp["rows"] = [{k: v for k, v in r.items() if k != "data"} for r in result]
    return resp


@api_router.get("/import/template/{kind}")
async def import_template(kind: str, fmt: str = "xlsx", user: dict = Depends(require_roles("super_admin"))):
    if kind not in ("users", "assets"):
        raise HTTPException(status_code=404, detail="Unknown import type")
    cols = USER_COLS if kind == "users" else ASSET_COLS
    headers = [f"{h} *" if req else h for _f, h, req in cols]
    if fmt == "csv":
        buf = io.StringIO()
        _csv.writer(buf).writerow(headers)
        return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{kind}_import_template.csv"'})
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:
        raise HTTPException(status_code=501, detail="Excel templates need the 'openpyxl' package (pip install openpyxl). Download the CSV template instead.")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users" if kind == "users" else "Assets"
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="B45309" if "*" in c.value else "475569")
        c.alignment = Alignment(vertical="center")
    for i, (_f, h, _r) in enumerate(cols, start=1):
        ws.column_dimensions[chr(64 + i)].width = max(16, len(h) + 6)
    ws.freeze_panes = "A2"
    lists = wb.create_sheet("Lists")
    def add_list(col_letter, title, values):
        lists[f"{col_letter}1"] = title
        for i, v in enumerate(values, start=2):
            lists[f"{col_letter}{i}"] = v
        return f"Lists!${col_letter}$2:${col_letter}${max(len(values), 1) + 1}"
    def dropdown(col_idx, ref):
        dv = DataValidation(type="list", formula1=f"={ref}", allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{chr(64 + col_idx)}2:{chr(64 + col_idx)}3000")
    if kind == "users":
        dept_names = [d["name"] for d in await dept_repo.list_all()]
        dropdown(3, add_list("A", "Departments", dept_names))
        dropdown(4, add_list("B", "Roles", ["Executive", "Dept Head", "Accounts", "Managing Director", "Purchase Head"]))
        dropdown(6, add_list("C", "IT Team", ["Application", "Network & Infra"]))
        yn = add_list("D", "Yes/No", ["Yes", "No"])
        dropdown(7, yn); dropdown(8, yn)
    else:
        dropdown(4, add_list("A", "Categories", ["IT Asset", "IT Accessories", "Network", "Consumable", "Furniture"]))
    info = wb.create_sheet("Instructions")
    notes = (["Fill the 'Users' sheet - one employee per row. Columns marked * are required.",
              "Department and Role must match the drop-down values. Users start with a generated temporary password and choose their own at first login.",
              "IT Team, Can Raise PR (IT department) and Can Create PO (Purchase department) are optional.",
              "Emails that already exist are skipped. Super Admin accounts cannot be imported."] if kind == "users" else
             ["Fill the 'Assets' sheet - one device per row. Columns marked * are required.",
              "Employee Email must belong to an existing user - import users first.",
              "Specification: processor / RAM / storage / screen size or any detail that identifies the device (optional).",
              "Tag ID and Serial No must be unique across the whole system (leave blank if the device has none).",
              "Assigned Date: 2025-03-31 or 31/03/2025. Blank = today.",
              "Document Photo: the file name of the scanned handover form for that row (for example rahim_form.jpg). Several names: separate with ;  One photo may be used on several rows. Select the photo files in the 'Photos' step of Bulk Import.",
              "Assets are recorded as already assigned to the employee and do not change stock counts."])
    for n in notes:
        info.append([n])
    info.column_dimensions["A"].width = 120
    out = io.BytesIO()
    wb.save(out)
    return Response(content=out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{kind}_import_template.xlsx"'})


def _sniff_kind(data: bytes) -> Optional[str]:
    """What the bytes really are (a renamed .exe is not an image)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:5] == b"%PDF-":
        return "pdf"
    return None


def _paper_check(name: str, data: bytes) -> str:
    """Validate one uploaded scan; returns the detected file type."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in PAPER_EXTS:
        raise HTTPException(status_code=400, detail=f"'{name}': only JPG, PNG, WEBP, GIF or PDF files are allowed")
    if not data:
        raise HTTPException(status_code=400, detail=f"'{name}' is empty")
    if len(data) > PAPER_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"'{name}' is larger than 15 MB")
    kind = _sniff_kind(data)
    if not kind:
        raise HTTPException(status_code=400, detail=f"'{name}' is not a valid image or PDF file")
    return kind


async def _store_paper_file(emp_id: str, name: str, data: bytes, user: dict) -> str:
    kind = _sniff_kind(data) or "bin"
    fid = str(uuid.uuid4())
    path = f"{APP_NAME}/paper-records/{emp_id}/{fid}.{kind}"
    ct = MIME_TYPES.get(kind, "application/octet-stream")
    result = put_object(path, data, ct)
    await files_repo.insert({"id": fid, "storage_path": result["path"], "original_filename": name, "content_type": ct,
                               "size": result.get("size", len(data)), "is_deleted": False,
                               "uploaded_by": str(user["_id"]), "created_at": now_iso(), "purpose": "paper_record"})
    return fid


async def _require_paper_access(user: dict):
    if user.get("role") != "super_admin" and not await _is_it_head(user):
        raise HTTPException(status_code=403, detail="Only the IT Head or Super Admin can manage paper records")


def _paper_rec_out(d: dict, fmap: dict) -> dict:
    return {"id": str(d["_id"]), "kind": d.get("kind"), "doc_date": d.get("doc_date"), "form_no": d.get("form_no"),
            "remarks": d.get("remarks"),
            "files": [{"id": i, "name": fmap[i]["original_filename"], "content_type": fmap[i]["content_type"]}
                      for i in d.get("file_ids", []) if i in fmap]}


@api_router.post("/paper-records")
async def create_paper_record(
    employee_id: str = Form(...), kind: str = Form(...), doc_date: Optional[str] = Form(None),
    form_no: Optional[str] = Form(None), remarks: Optional[str] = Form(None), asset_ids: Optional[str] = Form(None),
    files: List[UploadFile] = File(...), user: dict = Depends(get_current_user)):
    await _require_paper_access(user)
    if kind not in ("handover", "takeover", "swap"):
        raise HTTPException(status_code=400, detail="Type must be handover, takeover or swap")
    if not ObjectId.is_valid(employee_id):
        raise HTTPException(status_code=400, detail="Choose an employee")
    emp = await users_repo.get(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not files or len(files) > PAPER_MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Attach between 1 and {PAPER_MAX_FILES} files")
    when = None
    if doc_date and doc_date.strip():
        try:
            when = _imp_parse_date(doc_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Form date: {e}")
    linked = [i for i in re.split(r"[,\s]+", asset_ids or "") if i]
    if linked:
        if not all(ObjectId.is_valid(i) for i in linked):
            raise HTTPException(status_code=400, detail="Invalid asset selected")
        found = set(await asset_repo.get_map(linked))
        if found != set(linked):
            raise HTTPException(status_code=404, detail="One of the selected assets no longer exists")

    stored = []
    for f in files:
        name = f.filename or "scan"
        data = await f.read()
        _paper_check(name, data)
        stored.append((name, data))
    file_ids = [await _store_paper_file(str(emp["_id"]), n, d, user) for n, d in stored]
    doc = {"employee_id": str(emp["_id"]), "employee_name": emp.get("name"), "employee_email": emp.get("email"),
           "department_id": emp.get("department_id"), "kind": kind, "doc_date": when,
           "form_no": (form_no or "").strip() or None, "remarks": (remarks or "").strip() or None,
           "file_ids": file_ids, "asset_ids": linked,
           "created_by": user["name"], "created_by_id": str(user["_id"]), "created_at": now_iso()}
    res = await paper_repo.insert(doc)
    return {"id": str(res), "files": len(file_ids)}


@api_router.get("/paper-records/asset-map")
async def paper_asset_map(user: dict = Depends(get_current_user)):
    """Every scanned form grouped by the asset it covers; forms not linked to any asset are grouped by employee."""
    await _require_paper_access(user)
    docs = await paper_repo.list_all()
    fids = [i for d in docs for i in d.get("file_ids", [])]
    fmap = await files_repo.get_map(fids)
    by_asset, by_employee = {}, {}
    for d in docs:
        rec = _paper_rec_out(d, fmap)
        if not rec["files"]:
            continue
        ids = d.get("asset_ids") or []
        rec["asset_count"] = len(ids)          # lets the UI warn when a form is shared by several devices
        if ids:
            for aid in ids:
                by_asset.setdefault(aid, []).append(rec)
        else:
            by_employee.setdefault(d.get("employee_id"), []).append(rec)
    return {"by_asset": by_asset, "by_employee": by_employee}


@api_router.get("/paper-records/employee-assets/{employee_id}")
async def paper_employee_assets(employee_id: str, user: dict = Depends(get_current_user)):
    await _require_paper_access(user)
    docs = await asset_repo.find({"assigned_to_user_id": employee_id, "status": {"$in": ["assigned", "return_pending"]}}, limit=500)
    return [{"id": str(a["_id"]), "name": a.get("name"), "brand": a.get("brand"), "tag_id": a.get("tag_id"),
             "serial_no": a.get("serial_no"), "specification": a.get("specification")} for a in docs]


@api_router.get("/paper-records")
async def list_paper_records(employee_id: Optional[str] = None, asset_id: Optional[str] = None, kind: Optional[str] = None,
                             q: Optional[str] = None, limit: int = 300, user: dict = Depends(get_current_user)):
    await _require_paper_access(user)
    docs = await paper_repo.search(employee_id=employee_id, asset_id=asset_id,
                                   kind=kind if kind in ("handover", "takeover", "swap") else None,
                                   text=q, limit=max(1, min(limit, 1000)))
    dept_ids = {d.get("department_id") for d in docs if d.get("department_id")}
    depts = {str(x["_id"]): x["name"] for x in await dept_repo.list_by_ids(dept_ids)}
    fmap = await files_repo.get_map([i for d in docs for i in d.get("file_ids", [])])
    aids = {i for d in docs for i in d.get("asset_ids", []) if ObjectId.is_valid(i)}
    amap = await asset_repo.get_map(aids)
    out = []
    for d in docs:
        r = _paper_rec_out(d, fmap)
        r.update({"employee_id": d.get("employee_id"), "employee_name": d.get("employee_name"), "employee_email": d.get("employee_email"),
                  "department_name": depts.get(d.get("department_id")), "created_by": d.get("created_by"), "created_at": d.get("created_at"),
                  "assets": [{"id": i, "name": amap[i].get("name"), "tag_id": amap[i].get("tag_id"), "serial_no": amap[i].get("serial_no")}
                             for i in d.get("asset_ids", []) if i in amap]})
        out.append(r)
    return out


@api_router.delete("/paper-records/{rec_id}/files/{file_id}")
async def remove_paper_record_file(rec_id: str, file_id: str, asset_id: Optional[str] = None,
                                   user: dict = Depends(get_current_user)):
    """Remove ONE scanned photo / PDF from a paper record (IT Head or Super Admin - the same people who can add one).
    - Photo only used for this device (or not linked to a device): the file is removed from the record, and the
      record itself is deleted when no file is left.
    - Form shared by several devices (asset_id given): it is taken off THIS device only; the other devices keep it."""
    await _require_paper_access(user)
    if not ObjectId.is_valid(rec_id):
        raise HTTPException(status_code=404, detail="Record not found")
    d = await paper_repo.get(rec_id)
    if not d or file_id not in (d.get("file_ids") or []):
        raise HTTPException(status_code=404, detail="Photo not found")
    file_ids = d.get("file_ids") or []
    asset_ids = d.get("asset_ids") or []
    if asset_id and asset_id in asset_ids and len(asset_ids) > 1:
        others = [f for f in file_ids if f != file_id]
        await paper_repo.remove_asset(d["_id"], asset_id)
        if others:                                   # this device keeps the form's other pages
            clone = {k: v for k, v in d.items() if k != "_id"}
            clone.update({"asset_ids": [asset_id], "file_ids": others})
            await paper_repo.insert(clone)
        return {"ok": True, "scope": "device"}
    remaining = [f for f in file_ids if f != file_id]
    if remaining:
        await paper_repo.update_fields(d["_id"], {"file_ids": remaining})
    else:
        await paper_repo.delete(d["_id"])
    if not await paper_repo.any_uses_file(file_id):     # nobody else uses this file
        await files_repo.mark_deleted(file_id)
    return {"ok": True, "scope": "photo"}


@api_router.delete("/paper-records/{rec_id}")
async def delete_paper_record(rec_id: str, user: dict = Depends(require_roles("super_admin"))):
    if not ObjectId.is_valid(rec_id):
        raise HTTPException(status_code=404, detail="Record not found")
    d = await paper_repo.get(rec_id)
    if not d:
        raise HTTPException(status_code=404, detail="Record not found")
    await files_repo.mark_deleted_many(d.get("file_ids", []))
    await paper_repo.delete(d["_id"])
    return {"ok": True}