"""Reports and audit log."""

from fastapi import Response, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal, Dict
from datetime import datetime
from ims.ids import ObjectId
import io
import re
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from xml.sax.saxutils import escape as _xml_escape
from ims.repositories import departments as dept_repo
from ims.repositories import users as users_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import products as prod_repo
from ims.repositories import categories as cat_repo
from ims.repositories import grns as grn_repo
from ims.repositories import assets as asset_repo
from ims.repositories import handovers as handover_repo
from ims.repositories import asset_history as ah_repo
from ims.repositories import saved_reports as saved_reports_repo
from ims.repositories import report_access as report_access_repo
from ims.common import (
    ASSET_HELD_STATUSES,
    grn_line_for_asset,
    CONDITION_LABELS,
    IT_TEAM_LABELS,
    PRODUCT_TYPE_LABELS,
    RP_UNIT_STATUS_LABEL,
    audit_tz,
    _a_dt,
    _held_filter,
    _notify,
    _parse_iso,
    _pkey,
    _rp_and,
    api_router,
    audit_can_view,
    build_audit_timeline,
    collect_audit_data,
    find_requisition_for_audit,
    get_current_user,
    now_iso,
    require_roles,
    resolve_category_name,
)

def audit_request_type(d: dict) -> str:
    return "SR" if d.get("requisition_type") == "service" else "PR"


@api_router.get("/audit/requisitions/{req_no}")
async def audit_summary(req_no: str, user: dict = Depends(get_current_user)):
    """Summary card for the Audit Search page (JSON)."""
    d = await find_requisition_for_audit(req_no)
    if not d:
        raise HTTPException(status_code=404, detail=f"No requisition found for '{req_no.strip()}'")
    data = await collect_audit_data(d)
    if not await audit_can_view(user, d, data["pos"]):
        raise HTTPException(status_code=403, detail="Audit reports are available to the IT Head and Super Admin only")
    tl = build_audit_timeline(d, data["pos"])
    return {
        "requisition_no": d["requisition_no"], "request_type": audit_request_type(d),
        "status": d.get("status"), "created_at": d.get("created_at"),
        "requisitioner_name": d.get("requisitioner_name"), "requisition_for": d.get("requisition_for"),
        "department_name": data["department_name"],
        "items": [{"name": it.get("product_name"), "quantity": it.get("quantity")} for it in d.get("items") or []],
        "it_team": IT_TEAM_LABELS.get(d.get("it_team")) if d.get("it_team") else None,
        "handled_by": d.get("service_assigned_to_name"),
        "po_numbers": [po.get("po_number") for po in data["pos"]],
        "slip_numbers": [h.get("slip_no") for h in data["handovers"]],
        "event_count": len(tl), "last_event_at": tl[-1]["at"] if tl else None,
    }


RP_MAX_ROWS = 5000


RP_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


RP_PAGE_SIZES = (10, 25, 50, 100)


RP_SCOPE_LABELS = {
    "all": "All Inventory",
    "own_assets": "Own Assets Only",
    "own_employee_records": "Own Employee Records",
    "own_performed": "Movements Performed by Me",
    "own_department": "Own Department",
    "selected_departments": "Selected Departments",
}


RP_PERSONAL_SCOPES = ("own_assets", "own_employee_records", "own_performed")


RP_DEPT_SCOPES = ("own_department", "selected_departments")


# The Unit Status choices offered by the Report Center's master filter panel.
RP_MASTER_STATUS_OPTIONS = [
    {"value": "available", "label": "Available"}, {"value": "assigned", "label": "Assigned"},
    {"value": "damaged", "label": "Damaged"}, {"value": "lost", "label": "Lost"},
    {"value": "under_repair", "label": "Under Repair"},
]


def _rp_asset_status_q(v: str) -> dict:
    """Filter dict for a Unit Status choice (also accepts the raw asset statuses older saved reports hold)."""
    if v == "available": return {"status": "in_stock", "pending_receipt": {"$ne": True}}
    if v == "assigned": return {"status": {"$in": ["assigned", "return_pending"]}}
    if v == "damaged": return {"status": {"$in": ["under_repair", "scrapped"]}, "condition": {"$in": ["damaged", "missing_parts"]}}
    return {"status": v}


def _rp_ms_ok(f: dict, *vals) -> bool:
    """Model / Serial Number box: matches the model, specification, serial number or tag (any one)."""
    ms = f.get("model_serial")
    return not ms or any(_rp_has(v, ms) for v in vals)


RP_UNIT_STATUS_TONE = {"in_stock": "ok", "assigned": "info", "return_pending": "warn", "under_repair": "warn",
                       "scrapped": "danger", "lost": "danger"}


def _rp_col(key, label, typ="text"):
    return {"key": key, "label": label, "type": typ}


RP_DEFS = {
    "all_inventory": {
        "label": "All Inventory Report", "icon": "Boxes", "short": "Every unit in the inventory, serial by serial",
        "scopes": ["all", "selected_departments", "own_department", "own_assets"],
        "fields": [], "columns": [], "default_sort": ("product", "asc"),
    },
    "stock": {
        "label": "Stock Report", "icon": "Boxes", "short": "Current inventory and quantities by product",
        "scopes": ["all", "selected_departments", "own_department", "own_assets"],
        "fields": [
            {"key": "product", "label": "Product Name", "type": "text"},
            {"key": "brand", "label": "Brand", "type": "text"},
            {"key": "category_id", "label": "Category", "type": "category"},
            {"key": "model_serial", "label": "Model / Serial Number", "type": "text"},
            {"key": "model", "label": "Model", "type": "text", "hidden": True},
            {"key": "serial_no", "label": "Serial Number", "type": "text", "hidden": True},
            {"key": "department_id", "label": "Department", "type": "department"},
            {"key": "employee_user_id", "label": "Employee", "type": "employee"},
            {"key": "status", "label": "Unit Status", "type": "select", "options": RP_MASTER_STATUS_OPTIONS, "legacy": ["in_stock", "return_pending", "scrapped"]},
            {"key": "date_from", "label": "From Date", "type": "date"},
            {"key": "date_to", "label": "To Date", "type": "date"},
            {"key": "view", "label": "View", "type": "select", "empty_label": "Summary by product",
             "options": [{"value": "units", "label": "Every unit (serial-level detail)"}]},
        ],
        "columns": [_rp_col("product", "Product Name"), _rp_col("brand", "Brand"), _rp_col("category", "Category"),
                    _rp_col("model", "Model"), _rp_col("specification", "Specification"), _rp_col("serial_no", "Serial Number"),
                    _rp_col("total_qty", "Total Qty", "number"), _rp_col("available_qty", "Available", "number"),
                    _rp_col("assigned_qty", "Assigned", "number"), _rp_col("under_repair_qty", "Under Repair", "number"),
                    _rp_col("damaged_lost_qty", "Damaged / Lost", "number"),
                    _rp_col("status", "Current Status", "status")],
        "default_sort": ("product", "asc"),
    },
    "employee_assets": {
        "label": "Employee Asset Report", "icon": "Users", "short": "Products currently assigned to employees",
        "scopes": ["all", "selected_departments", "own_department", "own_assets", "own_employee_records"],
        "fields": [
            {"key": "employee_user_id", "label": "Employee", "type": "employee"},
            {"key": "employee_text", "label": "Employee Name / ID", "type": "text"},
            {"key": "department_id", "label": "Department", "type": "department"},
            {"key": "product", "label": "Product Name", "type": "text"},
            {"key": "brand", "label": "Brand", "type": "text"},
            {"key": "category_id", "label": "Category", "type": "category"},
            {"key": "model_serial", "label": "Model / Serial Number", "type": "text"},
            {"key": "model", "label": "Model", "type": "text", "hidden": True},
            {"key": "serial_no", "label": "Serial Number", "type": "text", "hidden": True},
            {"key": "date_from", "label": "Assigned From", "type": "date"},
            {"key": "date_to", "label": "Assigned To", "type": "date"},
        ],
        "columns": [_rp_col("employee_name", "Employee Name"), _rp_col("employee_code", "Employee ID"),
                    _rp_col("department", "Department"), _rp_col("product", "Product Name"), _rp_col("brand", "Brand"),
                    _rp_col("model", "Model"), _rp_col("specification", "Specification"), _rp_col("serial_no", "Serial Number"),
                    _rp_col("assigned_at", "Assignment Date", "date"), _rp_col("status", "Assignment Status", "status"),
                    _rp_col("return_date", "Return Date", "date")],
        "default_sort": ("employee_name", "asc"),
    },
    "department": {
        "label": "Department-wise Report", "icon": "Building2", "short": "Assets by department and employee",
        "scopes": ["all", "selected_departments", "own_department"],
        "fields": [
            {"key": "department_id", "label": "Department", "type": "department"},
            {"key": "employee_user_id", "label": "Employee", "type": "employee"},
            {"key": "product", "label": "Product Name", "type": "text"},
            {"key": "brand", "label": "Brand", "type": "text"},
            {"key": "category_id", "label": "Category", "type": "category"},
            {"key": "model_serial", "label": "Model / Serial Number", "type": "text"},
            {"key": "model", "label": "Model", "type": "text", "hidden": True},
            {"key": "serial_no", "label": "Serial Number", "type": "text", "hidden": True},
            {"key": "status", "label": "Unit Status", "type": "select", "options": RP_MASTER_STATUS_OPTIONS, "legacy": ["in_stock", "return_pending", "scrapped"]},
            {"key": "date_from", "label": "From Date", "type": "date"},
            {"key": "date_to", "label": "To Date", "type": "date"},
        ],
        "columns": [_rp_col("department", "Department"), _rp_col("employee_name", "Employee Name"),
                    _rp_col("employee_code", "Employee ID"), _rp_col("product", "Product Name"), _rp_col("brand", "Brand"),
                    _rp_col("model", "Model"), _rp_col("specification", "Specification"), _rp_col("serial_no", "Serial Number"),
                    _rp_col("assigned_at", "Assignment Date", "date"), _rp_col("assignment", "Assignment"),
                    _rp_col("status", "Status", "status")],
        "default_sort": ("department", "asc"),
    },
    "movement": {
        "label": "Stock Movement Report", "icon": "ArrowLeftRight", "short": "Stock in, assignments and returns",
        "scopes": ["all", "selected_departments", "own_department", "own_assets", "own_performed"],
        "fields": [
            {"key": "txn_type", "label": "Transaction Type", "type": "select", "options": [
                {"value": "added", "label": "Added to Stock"}, {"value": "assigned", "label": "Assigned"},
                {"value": "returned", "label": "Returned"}]},
            {"key": "product", "label": "Product", "type": "text"},
            {"key": "employee_user_id", "label": "Employee", "type": "employee"},
            {"key": "department_id", "label": "Department", "type": "department"},
            {"key": "brand", "label": "Brand", "type": "text"},
            {"key": "category_id", "label": "Category", "type": "category"},
            {"key": "model_serial", "label": "Model / Serial Number", "type": "text"},
            {"key": "serial_no", "label": "Serial Number", "type": "text", "hidden": True},
            {"key": "date_from", "label": "From Date", "type": "date"},
            {"key": "date_to", "label": "To Date", "type": "date"},
        ],
        "columns": [_rp_col("product", "Product Name"), _rp_col("brand_model", "Brand / Model"),
                    _rp_col("serial_no", "Serial Number"), _rp_col("txn_label", "Transaction", "status"),
                    _rp_col("prev_status", "Previous Status"), _rp_col("new_status", "New Status"),
                    _rp_col("prev_party", "Previous Employee / Dept"), _rp_col("new_party", "New Employee / Dept"),
                    _rp_col("at", "Date", "date"), _rp_col("performed_by", "Performed By"), _rp_col("remarks", "Remarks")],
        "default_sort": ("at", "desc"),
    },
    "return_damage_lost": {
        "label": "Return, Damage & Lost Report", "icon": "PackageX", "short": "Returned, damaged, lost and repair items",
        "scopes": ["all", "selected_departments", "own_department", "own_assets"],
        "fields": [
            {"key": "product", "label": "Product", "type": "text"},
            {"key": "employee_user_id", "label": "Employee", "type": "employee"},
            {"key": "department_id", "label": "Department", "type": "department"},
            {"key": "brand", "label": "Brand", "type": "text"},
            {"key": "category_id", "label": "Category", "type": "category"},
            {"key": "model_serial", "label": "Model / Serial Number", "type": "text"},
            {"key": "serial_no", "label": "Serial Number", "type": "text", "hidden": True},
            {"key": "status", "label": "Unit Status", "type": "select", "options": RP_MASTER_STATUS_OPTIONS,
             "legacy": ["returned", "scrapped"]},
            {"key": "date_from", "label": "From Date", "type": "date"},
            {"key": "date_to", "label": "To Date", "type": "date"},
        ],
        "columns": [_rp_col("product", "Product Name"), _rp_col("brand", "Brand"), _rp_col("model", "Model"),
                    _rp_col("serial_no", "Serial Number"), _rp_col("employee_name", "Employee"),
                    _rp_col("department", "Department"), _rp_col("return_date", "Return Date", "date"),
                    _rp_col("damage_date", "Damage / Loss Date", "date"), _rp_col("status", "Current Status", "status"),
                    _rp_col("repair_status", "Repair Status"), _rp_col("remarks", "Remarks / Reason")],
        "default_sort": ("return_date", "desc"),
    },
    "purchase": {
        "label": "Purchase Report", "icon": "ShoppingCart", "short": "Purchase orders, vendors and costs",
        "scopes": ["all"],
        "fields": [
            {"key": "product", "label": "Product", "type": "text"},
            {"key": "brand", "label": "Brand", "type": "text"},
            {"key": "vendor", "label": "Supplier / Vendor", "type": "text"},
            {"key": "po_number", "label": "PO Number", "type": "text"},
            {"key": "category_id", "label": "Category", "type": "category"},
            {"key": "model_serial", "label": "Model / Serial Number", "type": "text"},
            {"key": "date_from", "label": "Purchase From", "type": "date"},
            {"key": "date_to", "label": "Purchase To", "type": "date"},
        ],
        "columns": [_rp_col("product", "Product Name"), _rp_col("brand_model", "Brand / Model"),
                    _rp_col("vendor", "Supplier / Vendor"), _rp_col("po_number", "PO Number"),
                    _rp_col("po_date", "Purchase Date", "date"), _rp_col("invoice_no", "Invoice / Challan No."),
                    _rp_col("quantity", "Qty", "number"), _rp_col("unit_price", "Unit Price (BDT)", "money"),
                    _rp_col("total_cost", "Total Cost (BDT)", "money"), _rp_col("warranty_period", "Warranty Period"),
                    _rp_col("warranty_expiry", "Warranty Expiry"), _rp_col("status", "Purchase Status", "status")],
        "default_sort": ("po_date", "desc"),
    },
}


RP_DEFS["all_inventory"]["fields"] = [f for f in RP_DEFS["stock"]["fields"] if f["key"] != "view"]


RP_DEFS["all_inventory"]["columns"] = RP_DEFS["stock"]["columns"]


# Serial-level view of the Stock Report: one row per physical unit, with everything known about it.
RP_STOCK_UNIT_COLS = [
    _rp_col("product", "Product Name"), _rp_col("brand", "Brand"), _rp_col("category", "Category"),
    _rp_col("model", "Model"), _rp_col("specification", "Specification"), _rp_col("serial_no", "Serial Number"),
    _rp_col("tag_id", "Tag / Asset ID"), _rp_col("status", "Status", "status"), _rp_col("assigned_to", "Assigned To"),
    _rp_col("department", "Department"), _rp_col("assigned_at", "Assigned On", "date"),
    _rp_col("received_at", "Received On", "date"), _rp_col("grn_no", "GRN No."), _rp_col("vendor", "Vendor"),
    _rp_col("unit_price", "Unit Price (BDT)", "money"), _rp_col("remarks", "Remarks"),
]


# Purchase details are shown only in the unrestricted scope - a user with a limited scope
# (for example "own assets") never sees what the company paid or who the vendor was.
RP_UNIT_PRIVATE = ("grn_no", "vendor", "unit_price", "received_at")


def _rp_columns(rtype: str, filters: dict, ctx: dict) -> List[dict]:
    if rtype == "all_inventory" or (rtype == "stock" and filters.get("view") == "units"):
        return RP_STOCK_UNIT_COLS if ctx["type"] == "all" else [c for c in RP_STOCK_UNIT_COLS if c["key"] not in RP_UNIT_PRIVATE]
    return RP_DEFS[rtype]["columns"]


def _rp_has(val, needle: str) -> bool:
    return needle.strip().lower() in str(val or "").lower()


def _rp_local_date(iso) -> str:
    dt = _parse_iso(iso) if isinstance(iso, str) else None
    return dt.astimezone(audit_tz()).strftime("%Y-%m-%d") if dt else ""


def _rp_in_range(iso, f: dict) -> bool:
    if not (f.get("date_from") or f.get("date_to")):
        return True
    d = _rp_local_date(iso)
    if not d:
        return False
    return not ((f.get("date_from") and d < f["date_from"]) or (f.get("date_to") and d > f["date_to"]))


def _rp_clean_filters(rtype: str, raw: Optional[dict]) -> dict:
    """Keep only the filter keys this report type knows; drop empty values (empty = ignored)."""
    defs = {f["key"]: f for f in RP_DEFS[rtype]["fields"]}
    out: dict = {}
    for k, v in (raw or {}).items():
        if k not in defs or v is None:
            continue
        v = str(v).strip()
        if not v:
            continue
        ftype = defs[k]["type"]
        if ftype == "date" and not RP_DATE_RE.match(v):
            raise HTTPException(status_code=400, detail=f"{defs[k]['label']}: use the YYYY-MM-DD date format")
        if ftype == "select" and v not in ({o["value"] for o in defs[k]["options"]} | set(defs[k].get("legacy", []))):
            raise HTTPException(status_code=400, detail=f"{defs[k]['label']}: invalid option")
        if ftype in ("employee", "department") and not ObjectId.is_valid(v):
            raise HTTPException(status_code=400, detail=f"{defs[k]['label']}: invalid selection")
        out[k] = v[:120]
    if out.get("date_from") and out.get("date_to") and out["date_from"] > out["date_to"]:
        raise HTTPException(status_code=400, detail="The start date is after the end date")
    return out


def _rp_emp_code(u: dict) -> str:
    return u.get("employee_id") or u.get("emp_code") or ("EMP-" + str(u["_id"])[-6:].upper())


class _RpRef:
    """Per-request lookup tables (users, departments, categories) so rows carry names, not ids."""
    def __init__(self):
        self.users: Dict[str, dict] = {}
        self.depts: Dict[str, str] = {}
        self.by_name: Dict[str, List[str]] = {}
        self._cat: Dict[str, Optional[str]] = {}

    @classmethod
    async def load(cls):
        r = cls()
        for u in await users_repo.list_all():
            uid = str(u["_id"])
            r.users[uid] = u
            r.by_name.setdefault((u.get("name") or "").strip().lower(), []).append(uid)
        for d in await dept_repo.list_all():
            r.depts[str(d["_id"])] = d.get("name")
        return r

    async def category(self, cid) -> Optional[str]:
        if not cid:
            return None
        if cid not in self._cat:
            self._cat[cid] = await resolve_category_name(cid)
        return self._cat[cid]

    def person(self, uid: Optional[str], name: Optional[str] = None, dept_id: Optional[str] = None):
        """-> (user_id, display name, employee code, department name, dept id). Falls back to a unique
        exact-name match for records written before user ids were stored."""
        u = self.users.get(uid) if uid else None
        if not u and name:
            ids = self.by_name.get(name.strip().lower(), [])
            if dept_id:
                narrowed = [i for i in ids if self.users[i].get("department_id") == dept_id]
                ids = narrowed or ids
            if len(ids) == 1:
                u = self.users[ids[0]]
        if u:
            did = dept_id or u.get("department_id")
            return (str(u["_id"]), u.get("name"), _rp_emp_code(u), self.depts.get(did), did)
        return (uid, name, None, self.depts.get(dept_id) if dept_id else None, dept_id)


async def _rp_scope_ctx(scope: dict, subject: dict) -> dict:
    """Turn a saved scope into concrete ids, evaluated LIVE for the user the report runs for.
    Personal scopes use the authenticated user's own record - never an id taken from the request."""
    st = (scope or {}).get("type", "all")
    ctx: dict = {"type": st}
    if st in RP_PERSONAL_SCOPES:
        ctx.update({"user": subject, "user_id": str(subject["_id"]), "user_name": subject.get("name")})
    elif st in RP_DEPT_SCOPES:
        ids = [subject.get("department_id")] if st == "own_department" else list(scope.get("department_ids") or [])
        ids = [i for i in ids if i]
        ctx["department_ids"] = ids
        ctx["dept_user_ids"] = [str(u["_id"]) for u in await users_repo.list_by_departments(ids)]
    return ctx


def _rp_asset_scope_q(ctx: dict) -> dict:
    t = ctx["type"]
    if t == "all":
        return {}
    if t in ("own_assets", "own_employee_records"):
        return _held_filter(ctx["user"])
    if t in RP_DEPT_SCOPES:
        if not ctx["department_ids"]:
            return {"_id": None}                       # no department -> matches nothing
        return {"$or": [{"assigned_department_id": {"$in": ctx["department_ids"]}},
                        {"assigned_to_user_id": {"$in": ctx["dept_user_ids"] or ["__none__"]}}]}
    return {"_id": None}


def _rp_history_scope_q(ctx: dict) -> dict:
    t = ctx["type"]
    if t == "all":
        return {}
    if t in ("own_assets", "own_employee_records"):
        return {"employee_user_id": ctx["user_id"]}
    if t == "own_performed":
        return {"by": ctx["user_name"]}
    if t in RP_DEPT_SCOPES:
        return {"employee_user_id": {"$in": ctx["dept_user_ids"] or ["__none__"]}}
    return {"_id": None}


def _rp_serial(a: dict) -> Optional[str]:
    return a.get("serial_no") or a.get("tag_id")


def _rp_model(a: dict) -> Optional[str]:
    return a.get("model") or a.get("specification")


async def _rp_assets(ctx: dict, extra: Optional[dict] = None) -> List[dict]:
    return await asset_repo.find(_rp_and(_rp_asset_scope_q(ctx), extra or {}), limit=100000)


async def _rp_build_stock(ctx, f, ref):
    extra = _rp_asset_status_q(f["status"]) if f.get("status") else {}
    matched = []
    for a in await _rp_assets(ctx, extra):
        name = (a.get("name") or "").strip()
        brand = (a.get("brand") or "").strip()
        model = _rp_model(a) or ""
        cat = await ref.category(a.get("category_id")) or ""
        if f.get("product") and not _rp_has(name, f["product"]): continue
        if f.get("brand") and not _rp_has(brand, f["brand"]): continue
        if f.get("model") and not (_rp_has(model, f["model"]) or _rp_has(a.get("specification"), f["model"])): continue
        if f.get("serial_no") and not (_rp_has(a.get("serial_no"), f["serial_no"]) or _rp_has(a.get("tag_id"), f["serial_no"])): continue
        if f.get("category_id") and (cat or "").lower() != ((await ref.category(f["category_id"])) or "").lower(): continue
        if not _rp_ms_ok(f, a.get("model"), a.get("specification"), a.get("serial_no"), a.get("tag_id")): continue
        if f.get("department_id") or f.get("employee_user_id"):
            if a.get("status") not in ASSET_HELD_STATUSES: continue
            hid_, _n, _c, _d, hdid = ref.person(a.get("assigned_to_user_id"), a.get("assigned_to"), a.get("assigned_department_id"))
            if f.get("employee_user_id") and hid_ != f["employee_user_id"]: continue
            if f.get("department_id") and hdid != f["department_id"]: continue
        if (f.get("date_from") or f.get("date_to")) and not _rp_in_range(a.get("created_at"), f): continue
        matched.append((a, name, brand, model, cat))

    if f.get("view") == "units":
        show_buy = ctx["type"] == "all"
        grns = {str(g["_id"]): g for g in await grn_repo.list_all(limit=100000)} if show_buy else {}
        rows = []
        for a, name, brand, model, cat in matched:
            held = a.get("status") in ASSET_HELD_STATUSES
            _, ename, _, dname, _ = ref.person(a.get("assigned_to_user_id"), a.get("assigned_to"), a.get("assigned_department_id")) if held else (None, None, None, None, None)
            g = grns.get(a.get("source_grn_id") or "")
            price = None
            if g:
                gi = grn_line_for_asset(g, a, name)
                price = float(gi.get("rate") or 0) if gi is not None else None
            st = a.get("status")
            rows.append({"product": name, "brand": brand or None, "category": cat or None, "model": model or None,
                         "specification": a.get("specification"), "serial_no": a.get("serial_no"), "tag_id": a.get("tag_id"),
                         "status": RP_UNIT_STATUS_LABEL.get(st, st), "status_tone": RP_UNIT_STATUS_TONE.get(st, "neutral"),
                         "assigned_to": ename or (a.get("assigned_to") if held else None), "department": dname,
                         "assigned_at": a.get("assigned_at") if held else None,
                         "received_at": (g or {}).get("received_date") or a.get("created_at") if show_buy else None,
                         "grn_no": (g or {}).get("grn_no"), "vendor": (g or {}).get("vendor_name"), "unit_price": price,
                         "remarks": a.get("remarks")})
        return rows

    groups: Dict[tuple, dict] = {}
    for a, name, brand, model, cat in matched:
        spec = (a.get("specification") or "").strip()
        serial = _rp_serial(a) or ""
        key = (name.lower(), brand.lower(), model.lower(), spec.lower(), cat.lower())
        g = groups.setdefault(key, {"product": name, "brand": brand or None, "category": cat or None, "model": model or None,
                                    "specification": spec or None, "serials": [], "total_qty": 0, "available_qty": 0,
                                    "assigned_qty": 0, "under_repair_qty": 0, "damaged_lost_qty": 0})
        st = a.get("status")
        g["total_qty"] += 1
        if serial: g["serials"].append(serial)
        if st == "in_stock" and not a.get("pending_receipt"): g["available_qty"] += 1
        elif st in ("assigned", "return_pending"): g["assigned_qty"] += 1
        elif st == "under_repair": g["under_repair_qty"] += 1
        elif st == "lost": g["damaged_lost_qty"] += 1
        if st in ("under_repair", "scrapped") and a.get("condition") in ("damaged", "missing_parts"): g["damaged_lost_qty"] += 1
    rows = []
    for g in groups.values():
        ser = g.pop("serials")
        g["serial_no"] = ser[0] if len(ser) == 1 else (f"{len(ser)} units" if ser else None)
        if g["available_qty"] > 0: g["status"], g["status_tone"] = "In Stock", "ok"
        elif g["assigned_qty"] > 0: g["status"], g["status_tone"] = "All Assigned", "info"
        elif g["under_repair_qty"] or g["damaged_lost_qty"]: g["status"], g["status_tone"] = "Unavailable", "warn"
        else: g["status"], g["status_tone"] = "Out of Stock", "danger"
        rows.append(g)
    return rows


async def _rp_build_employee_assets(ctx, f, ref):
    q: dict = {"status": {"$in": ASSET_HELD_STATUSES}}
    if f.get("employee_user_id"):
        q["assigned_to_user_id"] = f["employee_user_id"]
    assets = await _rp_assets(ctx, q)
    hids = [a["pending_return_handover_id"] for a in assets if a.get("pending_return_handover_id") and ObjectId.is_valid(a["pending_return_handover_id"])]
    ret_dates = {str(h["_id"]): h.get("created_at") for h in await handover_repo.get_many(hids)} if hids else {}
    rows = []
    for a in assets:
        uid, ename, ecode, dname, did = ref.person(a.get("assigned_to_user_id"), a.get("assigned_to"), a.get("assigned_department_id"))
        if f.get("employee_user_id") and uid != f["employee_user_id"]: continue
        if f.get("employee_text") and not (_rp_has(ename, f["employee_text"]) or _rp_has(ecode, f["employee_text"])): continue
        if f.get("department_id") and did != f["department_id"]: continue
        if f.get("product") and not _rp_has(a.get("name"), f["product"]): continue
        if f.get("brand") and not _rp_has(a.get("brand"), f["brand"]): continue
        if f.get("model") and not _rp_has(_rp_model(a), f["model"]): continue
        if f.get("serial_no") and not (_rp_has(a.get("serial_no"), f["serial_no"]) or _rp_has(a.get("tag_id"), f["serial_no"])): continue
        if not _rp_ms_ok(f, a.get("model"), a.get("specification"), a.get("serial_no"), a.get("tag_id")): continue
        if f.get("category_id") and ((await ref.category(a.get("category_id"))) or "").lower() != ((await ref.category(f["category_id"])) or "").lower(): continue
        if not _rp_in_range(a.get("assigned_at"), f): continue
        st = a.get("status")
        rows.append({"employee_name": ename, "employee_code": ecode, "department": dname, "product": a.get("name"),
                     "brand": a.get("brand"), "model": _rp_model(a), "specification": a.get("specification"), "serial_no": _rp_serial(a),
                     "assigned_at": a.get("assigned_at"), "status": RP_UNIT_STATUS_LABEL.get(st, st),
                     "status_tone": RP_UNIT_STATUS_TONE.get(st, "neutral"),
                     "return_date": ret_dates.get(a.get("pending_return_handover_id")) if st == "return_pending" else None})
    return rows


async def _rp_build_department(ctx, f, ref):
    extra: dict = _rp_asset_status_q(f["status"]) if f.get("status") else {}
    if f.get("employee_user_id"): extra = _rp_and(extra, {"assigned_to_user_id": f["employee_user_id"]})
    rows = []
    for a in await _rp_assets(ctx, extra):
        held = a.get("status") in ASSET_HELD_STATUSES
        if held:
            uid, ename, ecode, dname, did = ref.person(a.get("assigned_to_user_id"), a.get("assigned_to"), a.get("assigned_department_id"))
        else:
            uid, ename, ecode, dname, did = None, None, None, None, None
        if f.get("employee_user_id") and uid != f["employee_user_id"]: continue
        if f.get("department_id") and did != f["department_id"]: continue
        if f.get("product") and not _rp_has(a.get("name"), f["product"]): continue
        if f.get("brand") and not _rp_has(a.get("brand"), f["brand"]): continue
        if f.get("model") and not _rp_has(_rp_model(a), f["model"]): continue
        if f.get("serial_no") and not (_rp_has(a.get("serial_no"), f["serial_no"]) or _rp_has(a.get("tag_id"), f["serial_no"])): continue
        if f.get("category_id") and ((await ref.category(a.get("category_id"))) or "").lower() != ((await ref.category(f["category_id"])) or "").lower(): continue
        if not _rp_ms_ok(f, a.get("model"), a.get("specification"), a.get("serial_no"), a.get("tag_id")): continue
        if (f.get("date_from") or f.get("date_to")) and not (held and _rp_in_range(a.get("assigned_at"), f)): continue
        st = a.get("status")
        rows.append({"department": dname or "Unassigned stock", "employee_name": ename, "employee_code": ecode,
                     "product": a.get("name"), "brand": a.get("brand"), "model": _rp_model(a), "specification": a.get("specification"), "serial_no": _rp_serial(a),
                     "assigned_at": a.get("assigned_at") if held else None,
                     "assignment": "Assigned" if held else "Unassigned stock",
                     "status": RP_UNIT_STATUS_LABEL.get(st, st), "status_tone": RP_UNIT_STATUS_TONE.get(st, "neutral")})
    return rows


_RP_TXN = {"added": ("Added to Stock", "ok"), "assigned": ("Assigned", "info"), "returned": ("Returned", "warn")}


async def _rp_assets_by_id(ids) -> Dict[str, dict]:
    return await asset_repo.get_map(i for i in ids if i and ObjectId.is_valid(i))


async def _rp_build_movement(ctx, f, ref):
    hq: dict = {}
    if f.get("employee_user_id"): hq["employee_user_id"] = f["employee_user_id"]
    events = await ah_repo.find(_rp_and(_rp_history_scope_q(ctx), hq), limit=200000)
    assets = await _rp_assets_by_id(e.get("asset_id") for e in events)
    rows = []
    for e in events:
        kind = {"issued": "assigned", "returned": "returned"}.get(e.get("event"))
        if not kind: continue
        if f.get("txn_type") and f["txn_type"] != kind: continue
        a = assets.get(e.get("asset_id")) or {}
        uid, ename, ecode, dname, did = ref.person(e.get("employee_user_id"), e.get("employee_name"))
        if f.get("department_id") and did != f["department_id"]: continue
        if f.get("product") and not _rp_has(e.get("asset_name") or a.get("name"), f["product"]): continue
        if f.get("serial_no") and not (_rp_has(e.get("serial_no"), f["serial_no"]) or _rp_has(e.get("tag_id"), f["serial_no"])): continue
        if f.get("brand") and not _rp_has(a.get("brand"), f["brand"]): continue
        if f.get("category_id") and ((await ref.category(a.get("category_id"))) or "").lower() != ((await ref.category(f["category_id"])) or "").lower(): continue
        if not _rp_ms_ok(f, e.get("serial_no"), e.get("tag_id"), a.get("model"), a.get("specification")): continue
        if not _rp_in_range(e.get("at"), f): continue
        who = f"{ename} ({dname})" if ename and dname else (ename or "-")
        if kind == "assigned":
            prev_s, new_s, prev_p, new_p = "In Stock", "Assigned", "Stock", who
        else:
            nxt = e.get("next_status") or "in_stock"
            prev_s, new_s = "Assigned", RP_UNIT_STATUS_LABEL.get(nxt, nxt)
            prev_p, new_p = who, {"in_stock": "Stock", "under_repair": "Repair", "scrapped": "Scrapped"}.get(nxt, "Stock")
        bits = [x for x in (f"Slip {e['slip_no']}" if e.get("slip_no") else None,
                            CONDITION_LABELS.get(e.get("condition")) if e.get("condition") and e.get("condition") != "good" else None,
                            e.get("remarks")) if x]
        rows.append({"product": e.get("asset_name") or a.get("name"),
                     "brand_model": " ".join(x for x in (a.get("brand"), _rp_model(a)) if x) or None,
                     "serial_no": e.get("serial_no") or e.get("tag_id"), "txn_label": _RP_TXN[kind][0],
                     "txn_label_tone": _RP_TXN[kind][1], "txn_kind": kind, "prev_status": prev_s, "new_status": new_s,
                     "prev_party": prev_p, "new_party": new_p, "at": e.get("at"), "performed_by": e.get("by"),
                     "remarks": "; ".join(bits) or None})
    # "Added to stock": stock receipts are not employee records, so they only appear in the
    # unrestricted (All Inventory) scope.
    if ctx["type"] == "all" and not (f.get("employee_user_id") or f.get("department_id")) and f.get("txn_type") in (None, "added"):
        grns = {str(g["_id"]): g for g in await grn_repo.list_all(limit=100000)}
        for a in await asset_repo.find({"source": {"$ne": "existing_entry"}}, limit=100000):
            if f.get("product") and not _rp_has(a.get("name"), f["product"]): continue
            if f.get("serial_no") and not (_rp_has(a.get("serial_no"), f["serial_no"]) or _rp_has(a.get("tag_id"), f["serial_no"])): continue
            if f.get("brand") and not _rp_has(a.get("brand"), f["brand"]): continue
            if f.get("category_id") and ((await ref.category(a.get("category_id"))) or "").lower() != ((await ref.category(f["category_id"])) or "").lower(): continue
            if not _rp_ms_ok(f, a.get("serial_no"), a.get("tag_id"), a.get("model"), a.get("specification")): continue
            if not _rp_in_range(a.get("created_at"), f): continue
            g = grns.get(a.get("source_grn_id") or "")
            rows.append({"product": a.get("name"), "brand_model": " ".join(x for x in (a.get("brand"), _rp_model(a)) if x) or None,
                         "serial_no": _rp_serial(a), "txn_label": "Added to Stock", "txn_label_tone": "ok", "txn_kind": "added",
                         "prev_status": "-", "new_status": "In Stock", "prev_party": "-", "new_party": "Stock",
                         "at": a.get("created_at"), "performed_by": (g or {}).get("received_by") or a.get("added_by"),
                         "remarks": (f"GRN {g['grn_no']} (challan {g.get('challan_no')})" if g else None)})
    return rows


async def _rp_build_rdl(ctx, f, ref):
    hq: dict = {"event": "returned"}
    if f.get("employee_user_id"): hq["employee_user_id"] = f["employee_user_id"]
    events = await ah_repo.find(_rp_and(_rp_history_scope_q(ctx), hq), limit=200000)
    assets = await _rp_assets_by_id(e.get("asset_id") for e in events)
    rows = []
    for e in events:
        a = assets.get(e.get("asset_id")) or {}
        uid, ename, ecode, dname, did = ref.person(e.get("employee_user_id"), e.get("employee_name"))
        if f.get("department_id") and did != f["department_id"]: continue
        if f.get("product") and not _rp_has(e.get("asset_name") or a.get("name"), f["product"]): continue
        if f.get("brand") and not _rp_has(a.get("brand"), f["brand"]): continue
        if f.get("serial_no") and not (_rp_has(e.get("serial_no"), f["serial_no"]) or _rp_has(e.get("tag_id"), f["serial_no"])): continue
        if f.get("category_id") and ((await ref.category(a.get("category_id"))) or "").lower() != ((await ref.category(f["category_id"])) or "").lower(): continue
        if not _rp_ms_ok(f, e.get("serial_no"), e.get("tag_id"), a.get("model"), a.get("specification")): continue
        if not _rp_in_range(e.get("at"), f): continue
        cond, nxt, cur = e.get("condition") or "good", e.get("next_status") or "in_stock", a.get("status")
        if cur == "lost": kind, label, tone = "lost", "Lost", "danger"
        elif nxt == "under_repair": kind, label, tone = "under_repair", "Under Repair", "warn"
        elif nxt == "scrapped": kind, label, tone = "scrapped", "Scrapped", "danger"
        elif cond != "good": kind, label, tone = "damaged", "Damaged", "danger"
        else: kind, label, tone = "returned", "Returned", "ok"
        if f.get("status") and {"available": "returned"}.get(f["status"], f["status"]) != kind: continue
        if nxt == "under_repair":
            repair = "Under repair" if cur == "under_repair" else "Repair finished"
        else:
            repair = None
        bits = [x for x in (CONDITION_LABELS.get(cond) if cond != "good" else None, e.get("remarks")) if x]
        rows.append({"product": e.get("asset_name") or a.get("name"), "brand": a.get("brand"), "model": _rp_model(a),
                     "serial_no": e.get("serial_no") or e.get("tag_id"), "employee_name": ename, "department": dname,
                     "return_date": e.get("at"), "damage_date": e.get("at") if cond != "good" else None,
                     "status": label, "status_tone": tone, "repair_status": repair, "remarks": "; ".join(bits) or None})
    if ctx["type"] == "all" and not f.get("employee_user_id") and f.get("status") in (None, "lost"):
        for a in await asset_repo.find({"status": "lost"}, limit=100000):      # future-proof: only when the app records lost units
            if f.get("product") and not _rp_has(a.get("name"), f["product"]): continue
            rows.append({"product": a.get("name"), "brand": a.get("brand"), "model": _rp_model(a), "serial_no": _rp_serial(a),
                         "employee_name": a.get("last_returned_by"), "department": None, "return_date": None,
                         "damage_date": a.get("lost_at"), "status": "Lost", "status_tone": "danger",
                         "repair_status": None, "remarks": a.get("remarks")})
    return rows


async def _rp_build_purchase(ctx, f, ref):
    if ctx["type"] != "all":
        return []
    prods = {(p.get("name") or "").strip().lower(): PRODUCT_TYPE_LABELS.get(p.get("product_type"), p.get("product_type"))
             for p in await prod_repo.list_all(limit=20000)}
    invoices: Dict[str, str] = {}
    for g in await grn_repo.list_all(limit=100000):
        if g.get("requisition_id") and g.get("challan_no"):
            invoices.setdefault(g["requisition_id"], g["challan_no"])
    want_cat = ((await ref.category(f["category_id"])) or "").lower() if f.get("category_id") else None
    rows = []
    for po in await po_repo.list_submitted():
        if f.get("po_number") and not _rp_has(po.get("po_number"), f["po_number"]): continue
        if f.get("vendor") and not _rp_has(po.get("vendor_name"), f["vendor"]): continue
        if not _rp_in_range(po.get("po_date") or po.get("created_at"), f): continue
        st = po.get("status") or ""
        tone = "ok" if st == "approved" else ("danger" if "reject" in st else "warn")
        for it in po.get("items") or []:
            name = it.get("product_name") or it.get("item_description")
            if f.get("product") and not (_rp_has(name, f["product"]) or _rp_has(it.get("item_description"), f["product"])): continue
            if f.get("brand") and not _rp_has(it.get("brand_model"), f["brand"]): continue
            if not _rp_ms_ok(f, it.get("brand_model"), it.get("item_description")): continue
            if want_cat is not None and (prods.get((name or "").strip().lower()) or "").lower() != want_cat: continue
            q, up = int(it.get("quantity") or 0), float(it.get("unit_price") or 0)
            rows.append({"product": name, "brand_model": it.get("brand_model"), "vendor": po.get("vendor_name"),
                         "po_number": po.get("po_number"), "po_date": po.get("po_date") or po.get("created_at"),
                         "invoice_no": invoices.get(po.get("requisition_id")), "quantity": q, "unit_price": up,
                         "total_cost": round(q * up, 2), "warranty_period": None, "warranty_expiry": None,
                         "status": st.replace("_", " ").title(), "status_tone": tone})
    return rows


async def _rp_build_all_inventory(ctx, f, ref):
    return await _rp_build_stock(ctx, {**f, "view": "units"}, ref)


RP_BUILDERS = {"all_inventory": _rp_build_all_inventory, "stock": _rp_build_stock, "employee_assets": _rp_build_employee_assets, "department": _rp_build_department,
               "movement": _rp_build_movement, "return_damage_lost": _rp_build_rdl, "purchase": _rp_build_purchase}


def _rp_sort_key(col_type: str, v):
    if v is None or v == "":
        return (1, 0, "")
    if col_type in ("number", "money"):
        return (0, float(v), "")
    return (0, 0, str(v).lower())


async def _rp_run(rtype: str, filters: dict, scope: dict, subject: dict, sort_by: Optional[str], sort_dir: str,
                  page: int, page_size: int, purpose: str = "view") -> dict:
    d = RP_DEFS[rtype]
    ref = await _RpRef.load()
    ctx = await _rp_scope_ctx(scope, subject)
    rows = await RP_BUILDERS[rtype](ctx, filters, ref)
    columns = _rp_columns(rtype, filters, ctx)
    cols = {c["key"]: c for c in columns}
    sb, sd = (sort_by, sort_dir) if sort_by in cols else d["default_sort"]
    rows.sort(key=lambda r: _rp_sort_key(cols[sb]["type"], r.get(sb)), reverse=(sd == "desc"))
    # rows with an empty sort value always sink to the bottom, in either direction
    if sd == "desc":
        rows.sort(key=lambda r: 1 if r.get(sb) in (None, "") else 0)
    total = len(rows)
    warnings: List[str] = []
    if purpose in ("print", "export"):
        if total > RP_MAX_ROWS:
            warnings.append(f"Only the first {RP_MAX_ROWS} of {total} records are included.")
        rows, page, page_size = rows[:RP_MAX_ROWS], 1, max(min(total, RP_MAX_ROWS), 1)
    else:
        page_size = page_size if page_size in RP_PAGE_SIZES else 25
        pages = max((total + page_size - 1) // page_size, 1)
        page = min(max(page, 1), pages)
        rows = rows[(page - 1) * page_size: page * page_size]
    for k in ("employee_user_id", "department_id"):
        if filters.get(k) and k == "employee_user_id" and filters[k] not in ref.users:
            warnings.append("The employee selected for this report no longer exists.")
        if filters.get(k) and k == "department_id" and filters[k] not in ref.depts:
            warnings.append("The department selected for this report no longer exists.")
    return {"report_type": rtype, "columns": columns, "rows": rows, "total": total, "page": page,
            "page_size": page_size, "sort_by": sb, "sort_dir": sd, "generated_at": now_iso(), "warnings": warnings,
            "filters_applied": await _rp_filter_summary(rtype, filters, ref)}


async def _rp_filter_summary(rtype: str, filters: dict, ref: "_RpRef") -> List[dict]:
    out = []
    for fld in RP_DEFS[rtype]["fields"]:
        v = filters.get(fld["key"])
        if not v:
            continue
        if fld["type"] == "employee": v = (ref.users.get(v) or {}).get("name") or "(removed employee)"
        elif fld["type"] == "department": v = ref.depts.get(v) or "(removed department)"
        elif fld["type"] == "category": v = (await ref.category(v)) or v
        elif fld["type"] == "select": v = next((o["label"] for o in fld["options"] if o["value"] == v), v)
        out.append({"label": fld["label"], "value": v})
    return out


def _rp_cell(col: dict, row: dict):
    v = row.get(col["key"])
    if v is None or v == "":
        return "-" if col["type"] not in ("number", "money") else 0
    if col["type"] == "date":
        return _a_dt(v)
    return v


def _rp_xlsx_bytes(title: str, columns: List[dict], rows: List[dict], info: List[tuple]) -> bytes:
    """Minimal .xlsx writer (zip + XML) so Excel export needs no extra dependency."""
    import zipfile
    def ref_(r, c):
        s, c = "", c + 1
        while c:
            c, rem = divmod(c - 1, 26)
            s = chr(65 + rem) + s
        return f"{s}{r}"
    def cell(r, c, v, style=0):
        a = f' s="{style}"' if style else ""
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref_(r, c)}"{a}><v>{v}</v></c>'
        txt = _xml_escape(str(v if v is not None else ""))
        return f'<c r="{ref_(r, c)}" t="inlineStr"{a}><is><t xml:space="preserve">{txt}</t></is></c>'
    def sheet(rws, widths=None):
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths or []))
        body = "".join(f'<row r="{i + 1}">{"".join(cs)}</row>' for i, cs in enumerate(rws))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'{("<cols>" + cols + "</cols>") if cols else ""}<sheetData>{body}</sheetData></worksheet>')
    data = [[cell(1, i, c["label"], 1) for i, c in enumerate(columns)]]
    for r_i, row in enumerate(rows, start=2):
        data.append([cell(r_i, i, _rp_cell(c, row)) for i, c in enumerate(columns)])
    widths = [min(max(len(c["label"]), *(len(str(_rp_cell(c, r))) for r in rows[:200]), 8) + 2, 45) if rows else len(c["label"]) + 2 for c in columns]
    info_rows = [[cell(1, 0, title, 1)]] + [[cell(i + 2, 0, k, 1), cell(i + 2, 1, v)] for i, (k, v) in enumerate(info)]
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/><sheet name="Info" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF7"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        "xl/worksheets/sheet1.xml": sheet(data, widths),
        "xl/worksheets/sheet2.xml": sheet(info_rows, [26, 70]),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def _rp_pdf_bytes(title: str, columns: List[dict], rows: List[dict], info: List[tuple], who: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=title)
    ss = getSampleStyleSheet()
    small = ParagraphStyle("rp_small", parent=ss["Normal"], fontSize=7, leading=9)
    head = ParagraphStyle("rp_head", parent=small, textColor=colors.white, fontName="Helvetica-Bold")
    story = [Paragraph(f"<b>{_xml_escape(title)}</b>", ParagraphStyle("rp_t", parent=ss["Title"], fontSize=15, alignment=0, spaceAfter=2)),
             Paragraph(_xml_escape(" | ".join(f"{k}: {v}" for k, v in info + [("Generated by", who)])),
                       ParagraphStyle("rp_i", parent=small, fontSize=8, leading=11, textColor=colors.HexColor("#475569"))),
             Spacer(1, 4 * mm)]
    avail = 277 * mm
    weights = [max(min(len(c["label"]), 18), 6) for c in columns]
    for i, c in enumerate(columns):
        longest = max((len(str(_rp_cell(c, r))) for r in rows[:100]), default=6)
        weights[i] = max(weights[i], min(longest, 28))
    widths = [avail * w / sum(weights) for w in weights]
    data = [[Paragraph(_xml_escape(c["label"]), head) for c in columns]]
    for r in rows:
        data.append([Paragraph(_xml_escape(str(_rp_cell(c, r))), small) for c in columns])
    if not rows:
        data.append([Paragraph("No records match this report.", small)] + [""] * (len(columns) - 1))
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(t)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"{len(rows)} record(s)", small))
    doc.build(story)
    return buf.getvalue()


def _rp_export_response(fmt: str, rtype: str, result: dict, name: str, who: str, scope_label: str) -> Response:
    d = RP_DEFS[rtype]
    info = [("Report", d["label"]), ("Generated", _a_dt(result["generated_at"])), ("Data scope", scope_label)]
    info += [(f["label"], str(f["value"])) for f in result["filters_applied"]] or [("Filters", "none")]
    if result["warnings"]:
        info.append(("Note", " ".join(result["warnings"])))
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name or d["label"]).strip("_") or "report"
    stamp = datetime.now(audit_tz()).strftime("%Y%m%d_%H%M")
    if fmt == "pdf":
        body, mt, ext = _rp_pdf_bytes(name or d["label"], result["columns"], result["rows"], info, who), "application/pdf", "pdf"
    else:
        body = _rp_xlsx_bytes(name or d["label"], result["columns"], result["rows"], info)
        mt, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return Response(content=body, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{safe}_{stamp}.{ext}"', "Cache-Control": "no-store"})


class RpScopeIn(BaseModel):
    type: str = "all"
    department_ids: List[str] = []


class RpGrantIn(BaseModel):
    user_id: str


RP_PERMISSIONS = ("read", "print", "export")


def _rp_clean_perms(perms: Optional[List[str]]) -> List[str]:
    """Read is always included; Print and Export are the optional extras the Super Admin can tick."""
    bad = [p for p in (perms or []) if p not in RP_PERMISSIONS]
    if bad:
        raise HTTPException(status_code=400, detail="Unknown permission: " + ", ".join(bad))
    return [p for p in RP_PERMISSIONS if p == "read" or p in (perms or [])]


class RpSavedIn(BaseModel):
    name: str
    description: Optional[str] = None
    report_type: str
    filters: Dict[str, str] = {}
    scope: RpScopeIn = RpScopeIn()
    grants: List[RpGrantIn] = []
    permissions: List[str] = ["read"]          # applied to every assigned user: read / print / export


class RpSavedUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    filters: Optional[Dict[str, str]] = None
    scope: Optional[RpScopeIn] = None


class RpRunIn(BaseModel):
    report_type: Optional[str] = None
    filters: Dict[str, str] = {}
    sort_by: Optional[str] = None
    sort_dir: str = "asc"
    page: int = 1
    page_size: int = 25
    purpose: Literal["view", "print"] = "view"
    show_all: bool = False                    # Super Admin ad-hoc search only: deliberately list everything
    as_user_id: Optional[str] = None          # Super Admin only: evaluate a personal scope as this assignee


class RpExportIn(BaseModel):
    report_type: Optional[str] = None
    filters: Dict[str, str] = {}
    sort_by: Optional[str] = None
    sort_dir: str = "asc"
    format: Literal["pdf", "xlsx"] = "pdf"
    show_all: bool = False
    as_user_id: Optional[str] = None


class RpAccessIn(BaseModel):
    user_ids: List[str]
    permissions: Optional[List[str]] = None


class RpPermIn(BaseModel):
    permissions: List[str]


async def _rp_clean_scope(rtype: str, scope: Optional[RpScopeIn]) -> dict:
    st = (scope.type if scope else "all")
    if st not in RP_SCOPE_LABELS:
        raise HTTPException(status_code=400, detail="Unknown data scope")
    if st not in RP_DEFS[rtype]["scopes"]:
        raise HTTPException(status_code=400, detail=f"{RP_SCOPE_LABELS[st]} is not available for the {RP_DEFS[rtype]['label']}")
    ids: List[str] = []
    if st == "selected_departments":
        ids = list(dict.fromkeys(scope.department_ids))
        if not ids or any(not ObjectId.is_valid(i) for i in ids):
            raise HTTPException(status_code=400, detail="Select at least one department for this scope")
        found = {str(d["_id"]) for d in await dept_repo.list_by_ids(ids)}
        if set(ids) - found:
            raise HTTPException(status_code=400, detail="A selected department does not exist")
    return {"type": st, "department_ids": ids}


def _rp_check_type(rtype: Optional[str]) -> str:
    if rtype not in RP_DEFS:
        raise HTTPException(status_code=400, detail="Unknown report type")
    return rtype


async def _rp_scope_label(scope: dict, ref: Optional["_RpRef"] = None) -> str:
    label = RP_SCOPE_LABELS.get(scope.get("type"), "-")
    if scope.get("type") == "selected_departments":
        ref = ref or await _RpRef.load()
        label += ": " + ", ".join(ref.depts.get(i) or "(removed)" for i in scope.get("department_ids") or [])
    return label


async def _rp_serialize(rep: dict, ref: "_RpRef", full: bool = True) -> dict:
    out = {"id": str(rep["_id"]), "name": rep["name"], "description": rep.get("description"),
           "report_type": rep["report_type"], "type_label": RP_DEFS[rep["report_type"]]["label"],
           "filters": rep.get("filters") or {}, "filter_summary": await _rp_filter_summary(rep["report_type"], rep.get("filters") or {}, ref),
           "scope": rep.get("scope") or {"type": "all", "department_ids": []},
           "scope_label": await _rp_scope_label(rep.get("scope") or {"type": "all"}, ref),
           "created_by": rep.get("created_by"), "created_at": rep.get("created_at"), "updated_at": rep.get("updated_at")}
    if full:
        grants = await report_access_repo.list_all(report_id=out["id"])
        out["grants"] = [{"user_id": g["user_id"], "user_name": (ref.users.get(g["user_id"]) or {}).get("name") or g.get("user_name"),
                          "email": (ref.users.get(g["user_id"]) or {}).get("email"),
                          "permissions": g.get("permissions") or ["read"],
                          "status": g.get("status"), "granted_at": g.get("granted_at"), "granted_by": g.get("granted_by"),
                          "revoked_at": g.get("revoked_at"), "last_opened_at": g.get("last_opened_at")} for g in grants]
        out["active_grants"] = sum(1 for g in grants if g.get("status") == "active")
    return out


def _rp_audit(rep_audit: Optional[list], by: str, action: str, note: str = "") -> list:
    return ((rep_audit or []) + [{"at": now_iso(), "by": by, "action": action, "note": note}])[-100:]


async def _rp_set_grants(rep_id: str, user_ids: List[str], by: str, perms: Optional[List[str]] = None) -> None:
    perms = _rp_clean_perms(perms)
    ids = list(dict.fromkeys(user_ids))
    for uid in ids:
        if not ObjectId.is_valid(uid) or not await users_repo.get(uid):
            raise HTTPException(status_code=400, detail="One of the selected users does not exist")
    for uid in ids:
        u = await users_repo.get(uid)
        await report_access_repo.grant(rep_id, uid, {
            "status": "active", "user_name": u.get("name"), "granted_by": by, "granted_at": now_iso(), "revoked_at": None,
            "permissions": perms})


async def _rp_authorize(rep_id: str, user: dict):
    """The single gate for every saved-report endpoint. A report that is not assigned to the caller
    answers 404 (indistinguishable from a missing one), so reports cannot be discovered by guessing ids.
    Returns (report, grant_or_None); the grant is None for the Super Admin."""
    if not ObjectId.is_valid(rep_id):
        raise HTTPException(status_code=404, detail="Report not found")
    rep = await saved_reports_repo.get(rep_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "super_admin":
        return rep, None
    grant = await report_access_repo.find_active(rep_id, str(user["_id"]))
    if not grant:
        raise HTTPException(status_code=404, detail="Report not found")
    return rep, grant


async def _rp_subject(user: dict, as_user_id: Optional[str]) -> dict:
    """Whose identity a personal / own-department scope is evaluated for. Only the Super Admin may
    preview as someone else; everyone else is always evaluated as themselves."""
    if as_user_id and user["role"] == "super_admin" and ObjectId.is_valid(as_user_id):
        return (await users_repo.get(as_user_id)) or user
    return user


async def _rp_preview_subject(rep: dict, user: dict, as_user_id: Optional[str]) -> dict:
    """A scope such as 'Own Assets Only' means 'the assignee's own'. When the Super Admin opens such a
    report they must say whose view to preview, otherwise it would silently show the admin's data."""
    subject = await _rp_subject(user, as_user_id)
    st = (rep.get("scope") or {}).get("type", "all")
    if user["role"] == "super_admin" and subject is user and (st in RP_PERSONAL_SCOPES or st == "own_department"):
        raise HTTPException(status_code=400, detail="This report's data scope depends on who is viewing it. Choose an assigned user to preview it as.")
    return subject


SUPER_ADMIN_ONLY = require_roles("super_admin")


@api_router.get("/reports/meta")
async def reports_meta(user: dict = Depends(SUPER_ADMIN_ONLY)):
    ref = await _RpRef.load()
    cats = [{"id": k, "label": v} for k, v in PRODUCT_TYPE_LABELS.items()]
    for c in await cat_repo.list_all():
        cats.append({"id": str(c["_id"]), "label": c.get("name")})
    return {
        "types": [{"key": k, "label": d["label"], "icon": d["icon"], "short": d["short"], "fields": d["fields"],
                   "columns": d["columns"], "scopes": d["scopes"]} for k, d in RP_DEFS.items()],
        "scope_labels": RP_SCOPE_LABELS,
        "employees": sorted([{"id": i, "name": u.get("name"), "code": _rp_emp_code(u), "email": u.get("email"),
                              "department_id": u.get("department_id"), "department": ref.depts.get(u.get("department_id"))}
                             for i, u in ref.users.items()], key=lambda x: (x["name"] or "").lower()),
        "departments": sorted([{"id": i, "name": n} for i, n in ref.depts.items()], key=lambda x: (x["name"] or "").lower()),
        "categories": cats,
    }


@api_router.post("/reports/run")
async def reports_run(body: RpRunIn, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rtype = _rp_check_type(body.report_type)
    filters = _rp_clean_filters(rtype, body.filters)
    if not filters and not body.show_all:
        raise HTTPException(status_code=400, detail="Enter at least one search criterion (for example a product, employee or date range) and press Search, or use Show All.")
    return await _rp_run(rtype, filters, {"type": "all"}, user, body.sort_by, body.sort_dir, body.page, body.page_size, body.purpose)


@api_router.post("/reports/export")
async def reports_export(body: RpExportIn, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rtype = _rp_check_type(body.report_type)
    filters = _rp_clean_filters(rtype, body.filters)
    if not filters and not body.show_all:
        raise HTTPException(status_code=400, detail="Enter at least one search criterion before exporting.")
    res = await _rp_run(rtype, filters, {"type": "all"}, user, body.sort_by, body.sort_dir, 1, 25, "export")
    return _rp_export_response(body.format, rtype, res, RP_DEFS[rtype]["label"], user.get("name") or "-", RP_SCOPE_LABELS["all"])


@api_router.get("/reports/saved")
async def saved_list(user: dict = Depends(SUPER_ADMIN_ONLY)):
    ref = await _RpRef.load()
    reps = await saved_reports_repo.list_all()
    return [await _rp_serialize(r, ref) for r in reps]


@api_router.post("/reports/saved")
async def saved_create(body: RpSavedIn, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rtype = _rp_check_type(body.report_type)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the report a name")
    doc = {"name": name[:120], "description": (body.description or "").strip()[:300] or None, "report_type": rtype,
           "filters": _rp_clean_filters(rtype, body.filters), "scope": await _rp_clean_scope(rtype, body.scope),
           "created_by": user["name"], "created_by_id": str(user["_id"]), "created_at": now_iso(), "updated_at": now_iso(),
           "audit": _rp_audit([], user["name"], "created")}
    res = await saved_reports_repo.insert(doc)
    rid = str(res)
    if body.grants:
        await _rp_set_grants(rid, [g.user_id for g in body.grants], user["name"], body.permissions)
    doc["_id"] = res
    return await _rp_serialize(doc, await _RpRef.load())


@api_router.get("/reports/mine")
async def reports_mine(user: dict = Depends(get_current_user)):
    grants = await report_access_repo.list_all(user_id=str(user["_id"]), status="active", limit=500)
    ref = await _RpRef.load()
    out = []
    for g in grants:
        if not ObjectId.is_valid(g["report_id"]):
            continue
        rep = await saved_reports_repo.get(g["report_id"])
        if not rep:
            continue
        s = await _rp_serialize(rep, ref, full=False)
        out.append({"id": s["id"], "name": s["name"], "description": s["description"], "report_type": s["report_type"],
                    "type_label": s["type_label"], "scope_label": s["scope_label"],
                    "permissions": g.get("permissions") or ["read"],
                    "last_opened_at": g.get("last_opened_at"), "updated_at": s["updated_at"]})
    return sorted(out, key=lambda r: (r["name"] or "").lower())


@api_router.get("/reports/saved/{rep_id}")
async def saved_get(rep_id: str, user: dict = Depends(get_current_user)):
    rep, grant = await _rp_authorize(rep_id, user)
    ref = await _RpRef.load()
    out = await _rp_serialize(rep, ref, full=(user["role"] == "super_admin"))
    out["permissions"] = list(RP_PERMISSIONS) if user["role"] == "super_admin" else (grant.get("permissions") or ["read"])
    return out


@api_router.put("/reports/saved/{rep_id}")
async def saved_update(rep_id: str, body: RpSavedUpdate, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rep, _ = await _rp_authorize(rep_id, user)
    upd: dict = {}
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Give the report a name")
        upd["name"] = body.name.strip()[:120]
    if body.description is not None:
        upd["description"] = body.description.strip()[:300] or None
    if body.filters is not None:
        upd["filters"] = _rp_clean_filters(rep["report_type"], body.filters)
    if body.scope is not None:
        upd["scope"] = await _rp_clean_scope(rep["report_type"], body.scope)
    upd["updated_at"] = now_iso()
    upd["audit"] = _rp_audit(rep.get("audit"), user["name"], "updated", ", ".join(k for k in upd if k not in ("updated_at", "audit")))
    await saved_reports_repo.update_fields(rep["_id"], upd)
    return await _rp_serialize(await saved_reports_repo.get(rep["_id"]), await _RpRef.load())


@api_router.delete("/reports/saved/{rep_id}")
async def saved_delete(rep_id: str, user: dict = Depends(SUPER_ADMIN_ONLY)):
    """Removes the saved CONFIGURATION and its grants only - never inventory, employees,
    assignments or historical transactions."""
    rep, _ = await _rp_authorize(rep_id, user)
    await report_access_repo.delete_for_report(rep_id)
    await saved_reports_repo.delete(rep["_id"])
    return {"ok": True}


@api_router.post("/reports/saved/{rep_id}/run")
async def saved_run(rep_id: str, body: RpRunIn, user: dict = Depends(get_current_user)):
    rep, grant = await _rp_authorize(rep_id, user)
    perms = list(RP_PERMISSIONS) if user["role"] == "super_admin" else (grant.get("permissions") or ["read"])
    if body.purpose == "print" and "print" not in perms:
        raise HTTPException(status_code=403, detail="You do not have permission to print this report")
    subject = await _rp_preview_subject(rep, user, body.as_user_id)
    res = await _rp_run(rep["report_type"], dict(rep.get("filters") or {}), rep.get("scope") or {"type": "all"}, subject,
                        body.sort_by, body.sort_dir, body.page, body.page_size, body.purpose)
    res["scope_label"] = await _rp_scope_label(rep.get("scope") or {"type": "all"})
    res["name"] = rep["name"]
    res["permissions"] = perms
    if grant and body.purpose == "view" and body.page == 1:
        await report_access_repo.update_fields(grant["_id"], {"last_opened_at": now_iso()})
    return res


@api_router.post("/reports/saved/{rep_id}/export")
async def saved_export(rep_id: str, body: RpExportIn, user: dict = Depends(get_current_user)):
    rep, grant = await _rp_authorize(rep_id, user)
    if user["role"] != "super_admin" and "export" not in (grant.get("permissions") or ["read"]):
        raise HTTPException(status_code=403, detail="You do not have permission to export this report")
    subject = await _rp_preview_subject(rep, user, body.as_user_id)
    scope = rep.get("scope") or {"type": "all"}
    res = await _rp_run(rep["report_type"], dict(rep.get("filters") or {}), scope, subject, body.sort_by, body.sort_dir, 1, 25, "export")
    return _rp_export_response(body.format, rep["report_type"], res, rep["name"], user.get("name") or "-", await _rp_scope_label(scope))


@api_router.get("/reports/saved/{rep_id}/access")
async def access_list(rep_id: str, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rep, _ = await _rp_authorize(rep_id, user)
    return (await _rp_serialize(rep, await _RpRef.load()))["grants"]


@api_router.post("/reports/saved/{rep_id}/access")
async def access_grant(rep_id: str, body: RpAccessIn, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rep, _ = await _rp_authorize(rep_id, user)
    if not body.user_ids:
        raise HTTPException(status_code=400, detail="Select at least one user")
    await _rp_set_grants(rep_id, body.user_ids, user["name"], body.permissions)
    await saved_reports_repo.update_fields(rep["_id"], {"audit": _rp_audit(rep.get("audit"), user["name"], "granted", f"{len(body.user_ids)} user(s), permissions: {', '.join(_rp_clean_perms(body.permissions))}")})
    for uid in dict.fromkeys(body.user_ids):
        await _notify(uid, "report_assigned", f"You were given access to the report \"{rep['name']}\". Open My Reports to view it.")
    return (await _rp_serialize(rep, await _RpRef.load()))["grants"]


@api_router.put("/reports/saved/{rep_id}/access/{target_id}")
async def access_set_permissions(rep_id: str, target_id: str, body: RpPermIn, user: dict = Depends(SUPER_ADMIN_ONLY)):
    rep, _ = await _rp_authorize(rep_id, user)
    perms = _rp_clean_perms(body.permissions)
    if not await report_access_repo.update_by({"report_id": rep_id, "user_id": target_id, "status": "active"}, {"permissions": perms}):
        raise HTTPException(status_code=404, detail="That user has no active access to this report")
    await saved_reports_repo.update_fields(rep["_id"], {"audit": _rp_audit(rep.get("audit"), user["name"], "permissions", f"{target_id}: {', '.join(perms)}")})
    return (await _rp_serialize(rep, await _RpRef.load()))["grants"]


@api_router.delete("/reports/saved/{rep_id}/access/{target_id}")
async def access_revoke(rep_id: str, target_id: str, user: dict = Depends(SUPER_ADMIN_ONLY)):
    """Takes effect immediately on every endpoint (the gate checks the grant on each request), so a
    previously opened link or a cached page stops working at the next call."""
    rep, _ = await _rp_authorize(rep_id, user)
    if not await report_access_repo.update_by({"report_id": rep_id, "user_id": target_id, "status": "active"},
                                              {"status": "revoked", "revoked_at": now_iso()}):
        raise HTTPException(status_code=404, detail="That user has no active access to this report")
    await saved_reports_repo.update_fields(rep["_id"], {"audit": _rp_audit(rep.get("audit"), user["name"], "revoked", target_id)})
    return (await _rp_serialize(rep, await _RpRef.load()))["grants"]