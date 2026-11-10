"""Shared setup: config, database, auth helpers, constants, models and helpers used by several modules."""

from pathlib import Path
import os
import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from ims.ids import ObjectId
from ims.repositories import counters as counter_repo
from ims.repositories import files_repo
from ims.repositories import products as prod_repo
from ims.repositories import categories as cat_repo
from ims.repositories import assets as asset_repo
from ims.repositories import system_settings as settings_repo
from ims.repositories import grns as grn_repo
from ims.repositories import asset_history as ah_repo
from ims.repositories import notifications_repo as notif_repo
from ims.repositories import handovers as handover_repo
import logging
import bcrypt
import jwt
import io
import re
import base64
import requests as _requests
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from ims.database import ROOT_DIR, _env, _env_int  # noqa: F401 (re-exported)
from ims.repositories import departments as dept_repo
from ims.repositories import users as users_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import correction_cases as case_repo

JWT_ALGORITHM = "HS256"


_JWT_SECRET = _env("JWT_SECRET", "SECRET_KEY", required=True)


_WEAK_SECRETS = {"secret", "changeme", "change-me", "your-secret-key", "jwt_secret", "secret_key", "password", "test", "dev"}


def get_jwt_secret() -> str:
    return _JWT_SECRET


api_router = APIRouter(prefix="/api")


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


ROLES = ["super_admin", "dept_head", "executive", "accounts", "md", "purchase_head"]


ROLE_LABELS = {
    "super_admin": "Super Admin",
    "dept_head": "Dept Head",
    "executive": "Executive",
    "accounts": "Accounts",
    "md": "Managing Director",
    "purchase_head": "Purchase Head",
}


# Sidebar menu structure (groups -> items). Mirrors the navigation screenshot.
MENU = [
    {"group": "Dashboard", "icon": "LayoutDashboard", "badge": "A1", "items": [
        {"key": "overview", "label": "Overview", "path": "/dashboard"},
    ]},
    {"group": "Requisition", "icon": "ClipboardList", "badge": "B1", "items": [
        {"key": "new-requisition", "label": "New Requisition", "path": "/requisitions/new"},
        {"key": "pending-requisition", "label": "Pending Requisition", "path": "/requisitions/pending"},
        {"key": "file-purchase-requisition", "label": "File Purchase Requisition", "path": "/requisitions/purchase"},
        {"key": "file-purchase-order", "label": "File Purchase Order", "path": "/requisitions/purchase-order"},
        {"key": "handover-queue", "label": "Handover Queue", "path": "/requisitions/handover"},
        {"key": "it-service-queue", "label": "IT Service Queue", "path": "/it-service/queue"},
        {"key": "repair-approvals", "label": "Repair Approvals", "path": "/it-service/queue"},
        {"key": "audit-search", "label": "Audit Search", "path": "/audit/search"},
        {"key": "approve-requisition", "label": "Approve Requisition", "path": "/requisitions/approve"},
        {"key": "requisition-history", "label": "Requisition History", "path": "/requisitions/history"},
    ]},
    {"group": "Stock", "icon": "Boxes", "badge": "C1", "items": [
        {"key": "stock-list", "label": "Stock List", "path": "/stock"},
    ]},
    {"group": "Purchase", "icon": "ShoppingCart", "badge": "D1", "items": [
        {"key": "stock-grn", "label": "Stock GRN", "path": "/purchase/grn"},
        {"key": "po-approvals", "label": "PO Approvals", "path": "/purchase/po-approvals"},
        {"key": "create-po", "label": "Create Purchase Order", "path": "/purchase/orders/new"},
    ]},
    {"group": "Handover", "icon": "Handshake", "badge": "E1", "items": [
        {"key": "handover-module", "label": "Handover", "path": "/handover"},
        {"key": "handover-records", "label": "Handover Records", "path": "/handover/records"},
        {"key": "paper-records", "label": "Paper Records", "path": "/handover/paper-records"},
    ]},
    {"group": "Approvals", "icon": "UserCheck", "badge": "F1", "items": [
        {"key": "approver-management", "label": "Approver Management", "path": "/approvals"},
    ]},
    {"group": "Corrections", "icon": "ClipboardList", "badge": "J1", "items": [
        {"key": "corrections", "label": "Correction Cases", "path": "/corrections"},
        {"key": "my-corrections", "label": "My Corrections", "path": "/corrections/mine"},
    ]},
    {"group": "Report", "icon": "FileBarChart", "badge": "H1", "items": [
        {"key": "report-center", "label": "Report Center", "path": "/reports"},
        {"key": "assigned-assets", "label": "Assigned Assets", "path": "/assigned-assets"},
        {"key": "my-reports", "label": "My Reports", "path": "/reports/mine"},
    ]},
    {"group": "Organization", "icon": "Building2", "badge": "G1", "items": [
        {"key": "departments", "label": "Departments", "path": "/organization/departments"},
        {"key": "categories", "label": "Categories", "path": "/organization/categories"},
        {"key": "products", "label": "Products", "path": "/organization/products"},
        {"key": "users-roles", "label": "Users & Roles", "path": "/organization/users"},
        {"key": "bulk-import", "label": "Bulk Import", "path": "/organization/import"},
        {"key": "settings", "label": "Settings", "path": "/organization/settings"},
    ]},
]


ALL_MENU_KEYS = [item["key"] for g in MENU for item in g["items"]]


REQ_STATUSES = [
    "pending_dept", "pending_it_service", "product_collected_by_it", "sent_to_service_center",
    "service_completed_and_returned", "pending_it", "pending_pr", "pending_it_review", "pending_po_entry",
    "pending_accounts", "pending_md",
    "po_draft", "pending_purchase", "buy_process", "stock_received_in_it", "pending_handover", "awaiting_requester_confirmation",
    "handover_done", "approved", "rejected", "revision_requested", "pr_cancelled", "cancelled",
    "pending_admin", "waiting_stock", "pending_pr_revision",
    "service_in_progress", "pending_repair_approval", "product_in_service",
]


# ---- IT sub-teams (service tickets only) ------------------------------------------------
# `it_team` is optional metadata on a user ("Application" | "Network_Infra" | None). It is NOT a
# role: the user's role stays "executive". It is only ever read by the IT Service Ticket queue
# (/it-service/*). PR / PO / Handover code never looks at it.
IT_TEAMS = ("Application", "Network_Infra")


IT_TEAM_LABELS = {"Application": "Application Team", "Network_Infra": "Network & Infra Team"}


# Status of a new-style service ticket sitting unclaimed in its sub-team's shared queue is the
# existing "pending_it_service"; once an executive picks it up it becomes "service_in_progress";
# finishing it uses the existing final status "service_completed_and_returned".
SERVICE_QUEUE_OPEN = "pending_it_service"


# Statuses that mean the requisition is closed (no further approval action).
FINALIZED = ["handover_done", "approved", "rejected", "service_completed_and_returned", "pr_cancelled", "cancelled"]


MD_THRESHOLD = 50000  # BDT


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_user(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc


MUST_CHANGE_ALLOWED_PATHS = ("/auth/change-password", "/auth/me", "/auth/logout", "/auth/permissions")


async def get_current_user(request: Request) -> dict:
    # Authorization header takes priority over the cookie. Multiple browser tabs share one
    # cookie jar, so relying on the cookie would make every tab silently follow whichever
    # account most recently logged in elsewhere. The frontend stores its token per-tab
    # (sessionStorage) and sends it explicitly via this header, so each tab keeps its own
    # independent session.
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await users_repo.get(payload["sub"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        # An admin password reset signs the user out everywhere: tokens issued before the
        # reset are rejected.
        valid_from = user.get("sessions_valid_from")
        if valid_from and (payload.get("iat") or 0) < valid_from:
            raise HTTPException(status_code=401, detail="Session expired - please sign in again")
        # After an admin reset the user must set their own password before using anything else.
        if user.get("must_change_password") and not request.url.path.rstrip("/").endswith(MUST_CHANGE_ALLOWED_PATHS):
            raise HTTPException(status_code=403, detail="PASSWORD_CHANGE_REQUIRED")
        # Safety net: an account created by hand in the database may lack a name; many screens and
        # reports assume user["name"] exists, so fill it in rather than crash the dashboard.
        if not user.get("name"):
            user["name"] = (user.get("email") or "User").split("@")[0]
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_roles(*roles):
    async def dep(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dep


def has_pr_raise_flag(user: dict) -> bool:
    return bool(user.get("can_raise_pr"))


async def next_req_number() -> str:
    year = datetime.now(timezone.utc).year
    counter = await counter_repo.find_one_and_inc(f"req-{year}")
    seq = counter["seq"]
    return f"REQ-{year}-{seq:04d}"


async def find_dept_by_name(name: str) -> Optional[dict]:
    return await dept_repo.get_by_name(name)


# ---- Department TYPES ------------------------------------------------------------------------------
# The application never relies on a department's NAME for its rules. Each department carries a `dept_type`
# (set by the Super Admin on the Departments screen) and the code asks for "the IT department" / "the Purchase
# department" by type, so a department can be renamed freely. Departments saved before types existed fall back
# to their old names below, so nothing breaks until the Super Admin opens and saves them once.
DEPT_TYPES = {
    "it": "IT (service desk, stock, handover, PR raising)",
    "purchase": "Purchase (PO creation and Purchase Head approval)",
    "accounts": "Accounts",
    "admin": "Administration (admin-track requisitions)",
    "head_company": "Head company / top management (the MD sits here)",
}
_LEGACY_DEPT_NAMES = {
    "it": r"it",
    "purchase": r"purchases?",
    "accounts": r"accounts?",
    "admin": r"admin(istration)?",
    "head_company": r"primitek\s+group",
}


def dept_type_of(dept: Optional[dict]) -> Optional[str]:
    """The type of a department: the saved `dept_type`, else the type its legacy name implies, else None."""
    if not dept:
        return None
    if dept.get("dept_type") in DEPT_TYPES:
        return dept["dept_type"]
    name = (dept.get("name") or "").strip()
    for kind, pattern in _LEGACY_DEPT_NAMES.items():
        if re.fullmatch(pattern, name, re.IGNORECASE):
            return kind
    return None


async def find_dept_by_type(kind: str) -> Optional[dict]:
    """The department of this type (an explicitly typed one wins over a legacy name match)."""
    depts = await dept_repo.list_all()
    for d in depts:
        if d.get("dept_type") == kind:
            return d
    for d in depts:
        if not d.get("dept_type") and dept_type_of(d) == kind:
            return d
    return None


async def _department_is_it(department_id: Optional[str]) -> bool:
    """Can Raise PR is an IT-department-only permission (per user, not role-wide) — this
    guards it server-side so the restriction can't be bypassed by calling the API directly,
    even though the UI already hides the checkbox for non-IT users."""
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    it_dept = await find_dept_by_type("it")
    return bool(it_dept) and str(it_dept["_id"]) == department_id


async def _department_is_purchase(department_id: Optional[str]) -> bool:
    """Can Create PO is a Purchase-department-only permission (per user, not role-wide) —
    mirrors _department_is_it exactly, for the same reasons."""
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    purchase_dept = await find_dept_by_type("purchase")
    return bool(purchase_dept) and str(purchase_dept["_id"]) == department_id


async def _is_it_head(user: dict) -> bool:
    return user.get("role") == "dept_head" and await _department_is_it(user.get("department_id"))


async def it_queue_teams_for(user: dict) -> List[str]:
    """Which IT service queues this user may see. Super Admin + IT Head: both. An IT-department
    Executive: only the queue of the `it_team` they are tagged with. Anyone else: none.
    Used ONLY by the IT service ticket queue and its menu entry."""
    if user.get("role") == "super_admin" or await _is_it_head(user):
        return list(IT_TEAMS)
    team = user.get("it_team")
    if team in IT_TEAMS and await _department_is_it(user.get("department_id")):
        return [team]
    return []


async def resolve_approver(role: str, department_id: Optional[str] = None) -> Optional[dict]:
    scoped_to = department_id
    if not scoped_to and role == "md":
        # MD sits under the top-level "Primitek Group" department, not IT/Purchase/etc.
        # Anchor explicitly to that department when it exists, so MD resolution can't
        # accidentally pick up a differently-departmented user if more than one "md"
        # role is ever created.
        pg = await find_dept_by_type("head_company")
        if pg:
            scoped_to = str(pg["_id"])
    u = await users_repo.find_by_role(role, scoped_to)
    if not u and role == "md" and department_id is None and scoped_to:
        # Fallback: no user is attached to "Primitek Group" yet — don't silently fail to
        # resolve an MD approver just because that department link hasn't been set up.
        u = await users_repo.find_by_role("md")
    return u


DEFAULT_REMINDER_HOURS = 24


async def get_reminder_settings() -> dict:
    doc = await settings_repo.get("reminder")
    return {"reminder_hours": doc["reminder_hours"] if doc else DEFAULT_REMINDER_HOURS}


def _parse_iso(v) -> Optional[datetime]:
    if not v or not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _delegation_active(u: dict) -> bool:
    if not u.get("delegate_user_id"):
        return False
    today = _today_str()
    return (u.get("delegate_from") or "0000-00-00") <= today <= (u.get("delegate_until") or "9999-12-31")


async def active_delegators_of(user: dict) -> set:
    """Ids of users who are on leave and have delegated their approvals to `user` right now."""
    out = set()
    for u in await users_repo.list_delegating_to(str(user["_id"])):
        if _delegation_active(u):
            out.add(str(u["_id"]))
    return out


async def _notify(user_id: Optional[str], ntype: str, message: str, **extra):
    if not user_id:
        return
    await notif_repo.insert({
        "user_id": user_id, "employee_name": None, "type": ntype, "message": message,
        "status": "unread", "created_at": now_iso(), **extra})


async def _notify_with_delegate(approver: Optional[dict], ntype: str, message: str, **extra):
    """Notify an approver and, if they're on leave with an active delegate, the delegate too."""
    if not approver:
        return
    await _notify(str(approver["_id"]), ntype, message, **extra)
    if _delegation_active(approver):
        await _notify(approver["delegate_user_id"], ntype, f"(Delegated to you) {message}", **extra)


def step_pending_since(d: dict, step: dict) -> datetime:
    ts = _parse_iso(step.get("pending_since"))
    if ts:
        return ts
    prev = None
    for st in d.get("approval_chain", []):
        if st is step:
            break
        if st.get("status") == "approved":
            prev = _parse_iso(st.get("acted_at")) or prev
    return prev or _parse_iso(d.get("created_at")) or datetime.now(timezone.utc)


async def _sweep_requisitions(cfg: dict, now: datetime) -> int:
    reminded = 0
    for d in await req_repo.list_not_in_statuses(FINALIZED):
        chain = d.get("approval_chain") or []
        cur = next((x for x in chain if x.get("status") == "pending"), None)
        if not cur or cur.get("reminded_at"):
            continue
        age_h = (now - step_pending_since(d, cur)).total_seconds() / 3600
        if age_h < cfg["reminder_hours"]:
            continue
        approver = None
        if cur.get("approver_id") and ObjectId.is_valid(cur["approver_id"]):
            approver = await users_repo.get(cur["approver_id"])
        await _notify_with_delegate(approver, "approval_reminder",
            f"Reminder: {d['requisition_no']} ({cur.get('label', 'approval')}) has been waiting for your approval for {int(age_h)} hours.",
            requisition_id=str(d["_id"]))
        cur["reminded_at"] = now_iso()
        await req_repo.save_approval_chain(d["_id"], chain)
        reminded += 1
    return reminded


PO_STAGE_ROLE = {
    "pending_purchase_head_approval": "purchase_head",
    "pending_md_approval": "md",
    "pending_accounts_head_approval": "accounts",
}


async def _po_stage_holders(stage_role: str) -> List[dict]:
    pd = await find_dept_by_type("purchase") if stage_role == "purchase_head" else None
    return await users_repo.list_po_stage_holders(stage_role, str(pd["_id"]) if pd else None)


async def _sweep_purchase_orders(cfg: dict, now: datetime) -> int:
    reminded = 0
    for po in await po_repo.list_in_statuses(PO_STAGE_ROLE):
        rem = po.get("reminder") or {}
        if rem.get("status") == po["status"] and rem.get("reminded_at"):
            continue                      # already reminded for this stage
        since = _parse_iso(po.get("updated_at")) or _parse_iso(po.get("created_at")) or now
        age_h = (now - since).total_seconds() / 3600
        if age_h < cfg["reminder_hours"]:
            continue
        for h in await _po_stage_holders(PO_STAGE_ROLE[po["status"]]):
            await _notify_with_delegate(h, "approval_reminder",
                f"Reminder: Purchase Order {po.get('po_number')} has been waiting for approval for {int(age_h)} hours.",
                po_id=str(po["_id"]))
        await po_repo.mark_reminded(po["_id"], po["status"], now_iso())
        reminded += 1
    return reminded


async def run_reminder_sweep() -> dict:
    cfg = await get_reminder_settings()
    now = datetime.now(timezone.utc)
    return {"requisitions_reminded": await _sweep_requisitions(cfg, now),
            "purchase_orders_reminded": await _sweep_purchase_orders(cfg, now),
            "corrections": await run_correction_sweep(),
            "settings": cfg}


async def is_purchase_head_user(user: dict) -> bool:
    """Purchase Dept Head: dedicated purchase_head role, or the dept_head of the Purchase dept.
    They only APPROVE / REJECT Purchase Orders — they never create or submit one."""
    return user["role"] == "purchase_head" or (
        user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")))


async def po_user_can_act(po: dict, user: dict, delegators: Optional[set] = None) -> bool:
    """Who may approve/reject a PO at its current stage: the stage's role holders, their active
    on-leave delegates, and Super Admin."""
    stage_role = PO_STAGE_ROLE.get(po.get("status"))
    if not stage_role:
        return False
    if user["role"] == "super_admin" or user["role"] == stage_role:
        return True
    if stage_role == "purchase_head" and user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")):
        return True
    if delegators:
        for h in await _po_stage_holders(stage_role):
            if str(h["_id"]) in delegators:
                return True
    return False


async def find_admin_dept() -> Optional[dict]:
    return await find_dept_by_type("admin")


def build_pr_chain(total_amount: float) -> List[dict]:
    """PR sub-chain, appended to a requisition's approval_chain once the purchase team
    prices the PR. Order depends on the 50,000 BDT threshold."""
    def mk(role, label):
        return {"level": 0, "role": role, "label": label, "department_id": None,
                "approver_id": None, "approver_name": None, "status": "pending",
                "note": None, "acted_at": None}
    if total_amount >= MD_THRESHOLD:
        roles = [mk("md", "Managing Director"), mk("accounts", "Accounts Head (CFO)"), mk("purchase_head", "Purchase Dept Head")]
    else:
        roles = [mk("accounts", "Accounts Head (CFO)"), mk("purchase_head", "Purchase Dept Head")]
    return roles


async def resolve_pr_chain_approvers(pr_steps: List[dict]) -> List[dict]:
    purchase_dept = await find_dept_by_type("purchase")
    purchase_dept_id = str(purchase_dept["_id"]) if purchase_dept else None
    for s in pr_steps:
        if s["role"] == "purchase_head":
            # Purchase Dept Head = dedicated purchase_head role if one exists, else the
            # Purchase department's dept_head (e.g. Shuvo).
            approver = await resolve_approver("purchase_head") or await resolve_approver("dept_head", purchase_dept_id)
            s["department_id"] = purchase_dept_id
        else:
            approver = await resolve_approver(s["role"])
        s["approver_id"] = str(approver["_id"]) if approver else None
        s["approver_name"] = approver["name"] if approver else None
    return pr_steps


async def has_sufficient_stock(items: List[dict]) -> bool:
    need: dict = {}
    for it in items:
        key = (it["product_name"] or "").strip().lower()
        need[key] = need.get(key, 0) + int(it.get("quantity") or 1)
    for key, qty in need.items():
        available = await asset_repo.count_available(key)
        if available < qty:
            return False
    return True


async def process_waiting_stock_requisitions() -> int:
    """Called whenever stock is added (GRN, manual asset, returned asset). Starts the handover
    for admin-track requisitions that were 'waiting_stock', oldest first, as far as the new
    stock allows. Returns how many were started."""
    started = 0
    for d in await req_repo.list_with_status("waiting_stock"):
        if not await has_sufficient_stock(d["items"]):
            continue
        hid = await auto_generate_handover(d)
        d.setdefault("history", []).append({"at": now_iso(), "by": "system", "action": "stock_available",
                                            "note": "Stock restocked — handover started."})
        await req_repo.save_progress(d["_id"], status="pending_handover", history=d["history"],
                                     updated_at=now_iso(), handover_id=hid)
        item_names = ", ".join(it["product_name"] for it in d["items"])
        await notif_repo.insert({
            "user_id": d.get("requisitioner_id"),
            "employee_name": d.get("requisition_for") or d["requisitioner_name"],
            "type": "stock_allocated", "requisition_id": str(d["_id"]), "handover_id": hid,
            "message": f"Stock for {item_names} is now available and your handover is being prepared.",
            "status": "unread", "created_at": now_iso()})
        started += 1
    return started


async def auto_generate_handover(req: dict) -> str:
    """Reserves matching in-stock assets and creates a 'prepared' handover linked to this
    requisition. Does NOT create the bell notification yet — that happens only once IT
    clicks 'Handover Done' (see mark_handover_delivered)."""
    slip_no = await _next_no("HO", "handover")
    items_out = []
    for it in req["items"]:
        assets = await asset_repo.list_available(it["product_name"], limit=it["quantity"])
        for a in assets[: it["quantity"]]:
            items_out.append({"item": it["product_name"], "brand": a.get("brand"), "quantity": 1,
                              "remarks": it.get("remarks"), "asset_id": str(a["_id"])})
    doc = {
        "slip_no": slip_no, "type": "handover",
        "employee_name": req.get("requisition_for") or req["requisitioner_name"],
        "department_id": req.get("requisitioner_department_id"),
        "items": items_out, "remarks": f"Auto-generated for requisition {req['requisition_no']}",
        "note": None, "handover_date": now_iso(), "prepared_by": "system",
        "prepared_by_sign": None, "received_by_sign": None, "created_at": now_iso(),
        "status": "prepared", "requisition_id": str(req["_id"]),
    }
    res_id = await handover_repo.insert(doc)
    hid = str(res_id)
    for it in items_out:
        await asset_repo.update_fields(it["asset_id"], {
            "pending_receipt": True, "pending_handover_id": hid,
            "assigned_to_tentative": doc["employee_name"],
            "assigned_department_id": doc["department_id"]})
    return hid


async def _users_in_dept_matching(name: str, department_id: Optional[str], exact: bool = True) -> List[dict]:
    return await users_repo.search_by_name(name, department_id, exact)


async def resolve_handover_employee(name: Optional[str], department_id: Optional[str] = None,
                                    user_id: Optional[str] = None, strict: bool = True) -> Optional[dict]:
    """Find the ONE employee a handover is for. The department the IT staff selected is part of
    the identity: 'anik' in IT and 'anik2' in Brand & Marketing are different people, and a
    name typed with the wrong/partial spelling must NEVER fall through to a same-named user in
    another department (that is what sent the confirmation to the wrong person).
      1. explicit user id (picked from the employee list) wins; its department must agree.
      2. otherwise case-insensitive exact name, restricted to the chosen department.
      3. no match / ambiguous -> strict: 400 with 'did you mean' suggestions; lenient: None."""
    dept_name = None
    if department_id and ObjectId.is_valid(department_id):
        dd = await dept_repo.get(department_id)
        dept_name = dd["name"] if dd else None

    if user_id and ObjectId.is_valid(user_id):
        u = await users_repo.get(user_id)
        if u:
            if department_id and u.get("department_id") and u["department_id"] != department_id:
                if strict:
                    raise HTTPException(status_code=400, detail=(
                        f"{u['name']} does not belong to the selected department"
                        f"{' (' + dept_name + ')' if dept_name else ''}. Pick the employee again."))
                return None
            return u

    matches = await _users_in_dept_matching(name or "", department_id, exact=True)
    if len(matches) == 1:
        return matches[0]
    if not strict:
        return matches[0] if matches else None

    where = f" in {dept_name}" if dept_name else ""
    if len(matches) > 1:
        raise HTTPException(status_code=400, detail=(
            f"More than one employee named '{(name or '').strip()}'{where}. "
            "Select the employee from the list."))
    similar = await _users_in_dept_matching(name or "", department_id, exact=False)
    if not similar and (name or "").strip():
        # nothing contains the typed text; offer everyone in the department instead
        similar = await _users_in_dept_matching("", department_id, exact=False) if department_id else []
    hint = ""
    if similar:
        hint = " Did you mean: " + ", ".join(u["name"] for u in similar[:6]) + "?"
    raise HTTPException(status_code=400, detail=(
        f"No employee named '{(name or '').strip()}'{where}.{hint}"))


# category key -> (label, owning IT sub-team). This table IS the routing rule.
SERVICE_CATEGORIES = {
    # Application team
    "erp_software_access":   ("ERP Software Access", "Application"),
    "modify_access":         ("Modify Access", "Application"),
    "new_entry_edit_request": ("New Entry / Edit Requests", "Application"),
    # Network & Infra team
    "software_installation": ("Software Installation", "Network_Infra"),
    "software_update":       ("Software Update", "Network_Infra"),
    "email_service":         ("Email Service", "Network_Infra"),
    "operating_system":      ("Operating System (OS)", "Network_Infra"),
    "hardware_support":      ("Hardware & Physical Support", "Network_Infra"),
    "network_connectivity":  ("Network & Connectivity", "Network_Infra"),
    "others":                ("Others", "Network_Infra"),
}


SERVICE_REQUEST_TYPES = {k: v[0] for k, v in SERVICE_CATEGORIES.items()}


MIN_PASSWORD_LENGTH = 8


PRODUCT_TYPE_LABELS = {"asset": "IT Asset", "it_accessories": "IT Accessories", "network": "Network",
                       "consumable": "Consumable", "furniture": "Furniture"}


async def resolve_category_name(category_id: Optional[str]) -> Optional[str]:
    """Stock GRN now tags items with the same categories as the New Requisition form
    (the product types), stored as e.g. category_id='asset'. Older records hold an ObjectId
    of an Organization > Categories entry. Resolve both."""
    if not category_id:
        return None
    if category_id in PRODUCT_TYPE_LABELS:
        return PRODUCT_TYPE_LABELS[category_id]
    if ObjectId.is_valid(category_id):
        c = await cat_repo.get(category_id)
        return c["name"] if c else None
    return None


def _pkey(name: str) -> str:
    return " ".join((name or "").split()).lower()


def _skey(name: Optional[str]) -> str:
    """Key for matching an asset's name to a catalog product. Same rule as asset_repo's name match:
    case-insensitive, ignoring leading / trailing spaces."""
    return (name or "").strip().lower()


def _clean_brand(v: Optional[str]) -> Optional[str]:
    return " ".join((v or "").split()) or None


def _tracked_by_quantity(prod: dict) -> bool:
    """Consumables are received and issued by quantity - there is no serial / tag per unit to
    pick. Every other product type is tracked unit-by-unit."""
    return prod.get("product_type") == "consumable"


async def canonicalize_product_names(items: List[dict], strict_type: bool = True):
    """Replace each item's product_name with the catalog's exact spelling (case/space
    insensitive lookup). Unknown names are rejected so free-typed variants can't creep in."""
    for it in items:
        doc = await prod_repo.get_by_name_key(_pkey(it.get("product_name")))
        if not doc:
            raise HTTPException(status_code=400, detail=(
                f"'{(it.get('product_name') or '').strip()}' is not in the product catalog. "
                "Pick a product from the list, or ask IT to add it under Organization → Products."))
        it["product_name"] = doc["name"]
        if strict_type and "product_type" in it:
            it["product_type"] = doc["product_type"]


TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"   # no look-alike characters


def generate_temp_password(length: int = 10) -> str:
    return "".join(secrets.choice(TEMP_PW_ALPHABET) for _ in range(length))


def serialize_req(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def attach_file_info(outs: List[dict]) -> List[dict]:
    """Adds `attachments` to serialized requisitions so approvers can open uploaded files:
    the requester's attachment (New Requisition form) and the PR Technical Docs
    (Purchase Requisition form). Each entry: {id, name, kind}. Ids that aren't real stored
    files (old placeholder 'local-...' ids) are skipped."""
    ids = set()
    for o in outs:
        if o.get("attachment_file_id"):
            ids.add(o["attachment_file_id"])
        ids.update(o.get("pr_attachment_file_ids") or [])
    names = {}
    if ids:
        for fid, rec in (await files_repo.get_map(ids)).items():
            names[fid] = rec.get("original_filename")
    for o in outs:
        atts = []
        fid = o.get("attachment_file_id")
        if fid and fid in names:
            atts.append({"id": fid, "name": o.get("attachment_name") or names[fid], "kind": "Requisition attachment"})
        for pid in o.get("pr_attachment_file_ids") or []:
            if pid in names:
                atts.append({"id": pid, "name": names[pid], "kind": "PR technical doc"})
        o["attachments"] = atts
    return outs


async def attach_department_names(outs: List[dict]) -> List[dict]:
    """Adds `requisitioner_department_name` to serialized requisitions (one batched lookup), so the
    details dialog opened straight from a list row can show the department - previously only the
    single-requisition endpoint supplied it."""
    ids = {o.get("requisitioner_department_id") for o in outs}
    oids = [ObjectId(i) for i in ids if i and ObjectId.is_valid(i)]
    names = {}
    if oids:
        for d in await dept_repo.list_by_ids(oids):
            names[str(d["_id"])] = d.get("name")
    for o in outs:
        o["requisitioner_department_name"] = names.get(o.get("requisitioner_department_id"))
    return outs


# External object-storage service: only used when EMERGENT_LLM_KEY is set, and then INTEGRATION_PROXY_URL must be too.
STORAGE_BASE = _env("INTEGRATION_PROXY_URL", default="")


STORAGE_URL = (STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage") if STORAGE_BASE else ""


EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")


if EMERGENT_KEY and not STORAGE_BASE:
    raise RuntimeError("EMERGENT_LLM_KEY is set but INTEGRATION_PROXY_URL is missing (set it in backend/.env, "
                       "or remove EMERGENT_LLM_KEY to store files on this server's disk)")


APP_NAME = "ims-req"


_storage_key = None


MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "csv": "text/csv", "txt": "text/plain",
    "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# Files are kept on this server's disk when LOCAL_STORAGE_DIR is set, or automatically when there is no
# EMERGENT_LLM_KEY (self-hosted installs). Otherwise the external storage service is used.
LOCAL_STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR") or (None if EMERGENT_KEY else str(ROOT_DIR / "uploads"))


def _local_file(path: str) -> Path:
    base = Path(LOCAL_STORAGE_DIR).resolve()
    p = (base / path).resolve()
    if base not in p.parents:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return p


def _fallback_file(path: str) -> Path:
    """Local-disk copy used when the external storage service can't be reached."""
    base = (ROOT_DIR / "uploads").resolve()
    p = (base / path).resolve()
    if base not in p.parents:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return p


def init_storage(force: bool = False):
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    resp = _requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if LOCAL_STORAGE_DIR:
        p = _local_file(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return {"path": path, "size": len(data)}
    try:
        key = init_storage()
        r = _requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
        if r.status_code == 404:
            key = init_storage(force=True)
            r = _requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        # The external storage service is unreachable / rejected the key (typical on a self-hosted
        # install). Don't fail the upload - keep the file on this server's disk instead.
        logging.getLogger(__name__).warning("Remote storage failed (%s) - saving %s locally", exc, path)
        p = _fallback_file(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return {"path": path, "size": len(data)}


def strip_id(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _next_no(prefix: str, key: str) -> str:
    year = datetime.now(timezone.utc).year
    c = await counter_repo.find_one_and_inc(f"{key}-{year}")
    return f"{prefix}-{year}-{c['seq']:04d}"


async def user_from_token(token: str):
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return await users_repo.get(payload["sub"])
    except Exception:
        return None


def can_handle_pr(user: dict) -> bool:
    return bool(user.get("can_raise_pr") or user.get("can_process_requisition")
                or user.get("role") == "super_admin")


async def _enrich_asset(a: dict) -> dict:
    a = strip_id(a)
    if a.get("category_id"):
        a["category_name"] = await resolve_category_name(a["category_id"])
    # Employee details for the Assigned Assets inventory view: department + email of the
    # person holding the asset. Department falls back to the employee's own user record
    # when the handover slip didn't carry one.
    if a.get("status") in ("assigned", "return_pending") and a.get("assigned_to"):
        u = None
        uid = a.get("assigned_to_user_id")
        if uid and ObjectId.is_valid(uid):
            u = await users_repo.get(uid)
        if not u:
            u = await users_repo.get_by_name(a['assigned_to'].strip())
        did = a.get("assigned_department_id") or (u or {}).get("department_id")
        if did and ObjectId.is_valid(did):
            d = await dept_repo.get(did)
            a["assigned_department_name"] = d["name"] if d else None
        a["assigned_email"] = (u or {}).get("email")
    return a


async def _enrich_assets(docs: list) -> list:
    """Same result as _enrich_asset for every document, using a handful of queries in total instead of
    three per asset (a company-wide list can hold thousands of assets after a bulk import)."""
    out = [strip_id(a) for a in docs]
    cats: dict = {}
    for a in out:
        cid = a.get("category_id")
        if cid:
            if cid not in cats:
                cats[cid] = await resolve_category_name(cid)
            a["category_name"] = cats[cid]
    held = [a for a in out if a.get("status") in ("assigned", "return_pending") and a.get("assigned_to")]
    if held:
        users = await users_repo.list_all(only_fields=["name", "email", "department_id"], limit=50000)
        by_id = {str(u["_id"]): u for u in users}
        by_name: dict = {}
        for u in users:
            by_name.setdefault((u.get("name") or "").strip().lower(), u)
        depts = {str(d["_id"]): d["name"] for d in await dept_repo.list_all()}
        for a in held:
            u = by_id.get(a.get("assigned_to_user_id") or "") or by_name.get(a["assigned_to"].strip().lower())
            did = a.get("assigned_department_id") or (u or {}).get("department_id")
            if did and ObjectId.is_valid(did):
                a["assigned_department_name"] = depts.get(did)
            a["assigned_email"] = (u or {}).get("email")
    return out


# ---- Asset return lifecycle -------------------------------------------------------------
#   in_stock -> (pending_receipt) -> assigned -> return_pending -> in_stock | under_repair | scrapped
ASSET_HELD_STATUSES = ["assigned", "return_pending"]


CONDITION_LABELS = {"good": "Good", "damaged": "Damaged", "missing_parts": "Missing parts"}


async def _can_manage_handovers(user: dict) -> bool:
    """Same people who can open the Handover module: Super Admin, the IT head, or the PR raiser."""
    if user.get("role") == "super_admin" or has_pr_raise_flag(user):
        return True
    it_dept = await find_dept_by_type("it")
    return bool(it_dept and user.get("role") == "dept_head"
                and user.get("department_id") == str(it_dept["_id"]))


def _held_filter(emp: dict, statuses: Optional[List[str]] = None) -> dict:
    """Filter dict for 'assets this employee holds'. Matches on the user id; assets created
    before assigned_to_user_id was stored fall back to an exact name match, restricted to the
    employee's department so a same-named person elsewhere is never picked up."""
    uid = str(emp["_id"])
    legacy: dict = {
        "assigned_to_user_id": {"$in": [None, ""]},
        "assigned_to": {"$regex": f"^{re.escape((emp.get('name') or '').strip())}$", "$options": "i"},
    }
    if emp.get("department_id"):
        legacy["assigned_department_id"] = {"$in": [None, emp["department_id"]]}
    return {"status": {"$in": statuses or ASSET_HELD_STATUSES},
            "$or": [{"assigned_to_user_id": uid}, legacy]}


async def _log_asset_event(asset: dict, event: str, by: str, emp: Optional[dict] = None,
                           slip_no: Optional[str] = None, handover_id: Optional[str] = None, **extra):
    """Append-only life history of an asset: who got it, who returned it, in what condition."""
    await ah_repo.insert({
        "asset_id": str(asset["_id"]), "asset_name": asset.get("name"),
        "tag_id": asset.get("tag_id"), "serial_no": asset.get("serial_no"),
        "event": event, "employee_user_id": str(emp["_id"]) if emp else extra.pop("employee_user_id", None),
        "employee_name": emp.get("name") if emp else extra.pop("employee_name", None),
        "slip_no": slip_no, "handover_id": handover_id, "by": by, "at": now_iso(), **extra})


async def _release_slip_locks(hid: str):
    """Undo everything a not-yet-completed slip locked: reserved stock goes back to in_stock and
    assets waiting to be returned go back to 'assigned'. Used on failed saves and slip deletion."""
    await asset_repo.release_reservations(hid)


async def _apply_returns(h: dict, user: dict, overrides: Optional[Dict[str, dict]] = None) -> int:
    """IT physically received the returned device(s): move each asset to its destination status,
    clear the assignment, write history and - if it is good to re-issue - restock waiting
    requisitions. Idempotent: does nothing if the slip's returns were already received.
    Raises 409 (and changes nothing further) if an asset is no longer awaiting return."""
    lines = h.get("return_items") or []
    if not lines or h.get("return_received"):
        return 0
    hid = str(h["_id"])
    overrides = overrides or {}

    # Validate every line first so a bad row never leaves a half-received slip.
    for ln in lines:
        ov = overrides.get(ln["asset_id"], {})
        cond = ov.get("condition") or ln.get("condition", "good")
        dest = ov.get("next_status") or ln.get("next_status", "in_stock")
        if cond != "good" and dest == "in_stock":
            raise HTTPException(status_code=400, detail=(
                f"{ln.get('item')} is {CONDITION_LABELS.get(cond, cond)} - choose Under Repair or Scrapped."))
        a = await asset_repo.get(ln["asset_id"])
        if not a or a.get("status") != "return_pending" or a.get("pending_return_handover_id") != hid:
            raise HTTPException(status_code=409, detail=(
                f"{ln.get('item')} ({ln.get('tag_id') or ln.get('serial_no') or 'no tag'}) is no longer waiting to be returned on this slip."))

    emp = None
    if h.get("employee_user_id") and ObjectId.is_valid(h["employee_user_id"]):
        emp = await users_repo.get(h["employee_user_id"])
    restock = False
    for ln in lines:
        ov = overrides.get(ln["asset_id"], {})
        ln["condition"] = ov.get("condition") or ln.get("condition", "good")
        ln["next_status"] = ov.get("next_status") or ln.get("next_status", "in_stock")
        if ov.get("accessories") is not None:
            ln["accessories"] = ov["accessories"]
        if ov.get("data_wiped") is not None:
            ln["data_wiped"] = bool(ov["data_wiped"])
        if ov.get("remarks"):
            ln["remarks"] = ov["remarks"]
        applied = await asset_repo.update_if(
            ln["asset_id"], {"status": "return_pending", "pending_return_handover_id": hid}, {
                "status": ln["next_status"], "condition": ln["condition"],
                "assigned_to": None, "assigned_to_user_id": None, "assigned_department_id": None,
                "assigned_at": None, "assigned_handover_id": None, "assigned_slip_no": None,
                "receipt_confirmed": False, "pending_receipt": False, "pending_handover_id": None,
                "pending_return_handover_id": None, "pending_return_slip_no": None,
                "last_returned_at": now_iso(), "last_returned_by": h.get("employee_name"),
                "data_wiped": ln["data_wiped"]})
        if not applied:
            raise HTTPException(status_code=409, detail="An asset changed while receiving. Reload and try again.")
        ln["received"] = True
        asset_doc = await asset_repo.get(ln["asset_id"])
        await _log_asset_event(
            asset_doc, "returned", user["name"], emp=emp, slip_no=h.get("slip_no"), handover_id=hid,
            employee_user_id=h.get("employee_user_id"), employee_name=h.get("employee_name"),
            condition=ln["condition"], next_status=ln["next_status"],
            accessories=ln["accessories"], data_wiped=ln["data_wiped"], remarks=ln.get("remarks"))
        if ln["next_status"] == "in_stock":
            restock = True

    upd = {"return_items": lines, "return_received": True,
           "return_received_at": now_iso(), "return_received_by": user["name"]}
    if h.get("type") == "takeover":      # a pure takeover is finished once IT has the device
        upd["status"] = "completed"
    await handover_repo.update_fields(h["_id"], upd)
    h.update(upd)
    if restock:
        await process_waiting_stock_requisitions()    # a returned laptop can fulfil a waiting requisition
    return len(lines)


@api_router.post("/handovers/{hid}/deliver")
async def mark_handover_delivered(hid: str, user: dict = Depends(get_current_user)):
    """'Handover Done' button: IT confirms they've printed the slip and physically
    delivered the item(s). This is what actually raises the requester's bell notification."""
    h = await handover_repo.get(hid)
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    if h.get("type") not in ("handover", "swap"):
        raise HTTPException(status_code=400, detail="Only handovers and swaps (not takeovers) go through delivery confirmation")
    if h.get("status") in ("delivered", "confirmed"):
        raise HTTPException(status_code=400, detail="Already marked as delivered")
    if not await _can_manage_handovers(user):
        raise HTTPException(status_code=403, detail="Only IT / Super Admin can mark a handover as delivered")

    # Swap: the old device comes in at the same moment the new one goes out. Done FIRST so a
    # problem with the returned asset stops the delivery before any notification is sent.
    await _apply_returns(h, user)

    # Resolve the employee who must confirm receipt.
    # Priority: 1) linked requisition's requisitioner_id  2) name match on handover employee_name
    emp_user = None
    req = None
    if h.get("requisition_id") and ObjectId.is_valid(h["requisition_id"]):
        req = await req_repo.get(h["requisition_id"])
    # 1) the employee chosen on the slip (id saved at creation) — always wins.
    if h.get("employee_user_id") and ObjectId.is_valid(h["employee_user_id"]):
        emp_user = await users_repo.get(h["employee_user_id"])
    # 2) older slips: name + the slip's department (never a same-named user elsewhere).
    if not emp_user and h.get("employee_name"):
        emp_user = await resolve_handover_employee(h["employee_name"], h.get("department_id"), None, strict=False)
    # 3) linked requisition's requester — only if that person is in the slip's department.
    if not emp_user and req and req.get("requisitioner_id") and ObjectId.is_valid(req["requisitioner_id"]):
        cand = await users_repo.get(req["requisitioner_id"])
        if cand and (not h.get("department_id") or cand.get("department_id") == h.get("department_id")):
            emp_user = cand

    target_user_id = str(emp_user["_id"]) if emp_user else None
    items = h.get("items") or []
    notif_count = 0

    # Guarantee each line is bound to a concrete asset before notifying. Lines saved with only
    # an item name (no asset_id) could never be deducted from stock after the employee
    # confirmed. Reserve a matching in-stock asset now and persist the link on the slip.
    used = {i.get("asset_id") for i in items if i.get("asset_id")}
    changed = False
    for it in items:
        aid0 = it.get("asset_id")
        if aid0 and ObjectId.is_valid(aid0):
            continue
        nm0 = (it.get("item") or it.get("product_name") or "").strip()
        if not nm0:
            continue
        cand = await asset_repo.find_reservable(nm0, handover_id=hid, exclude_ids=used)
        if not cand:
            cand = await asset_repo.find_reservable(nm0, exclude_ids=used)
        if cand:
            it["asset_id"] = str(cand["_id"])
            it["brand"] = it.get("brand") or cand.get("brand")
            used.add(it["asset_id"])
            changed = True
            await asset_repo.update_fields(cand["_id"], {
                "pending_receipt": True, "pending_handover_id": hid,
                "assigned_to_tentative": h.get("employee_name"),
                "assigned_department_id": h.get("department_id")})
    if changed:
        await handover_repo.update_fields(hid, {"items": items})

    for it in items:
        aid = it.get("asset_id")
        asset = None
        if aid and ObjectId.is_valid(aid):
            asset = await asset_repo.get(aid)
        asset_name = (asset or {}).get("name") or it.get("item") or it.get("product_name") or "Item"
        asset_tag = (asset or {}).get("tag_id") or (asset or {}).get("serial_no")
        await notif_repo.insert({
            "user_id": target_user_id,
            "employee_name": h.get("employee_name") or (emp_user or {}).get("name"),
            "type": "asset_receipt",
            "asset_id": aid if aid and ObjectId.is_valid(aid) else None,
            "asset_name": asset_name,
            "asset_tag": asset_tag,
            "handover_id": hid,
            "slip_no": h.get("slip_no"),
            "requisition_id": h.get("requisition_id"),
            "correction_case_id": h.get("correction_case_id"),
            "message": f"Please confirm physical receipt of {asset_name}.",
            "status": "unread",
            "created_at": now_iso(),
        })
        notif_count += 1

    # Always create at least one confirmation notification even if handover has no line items
    if notif_count == 0:
        await notif_repo.insert({
            "user_id": target_user_id,
            "employee_name": h.get("employee_name") or (emp_user or {}).get("name"),
            "type": "asset_receipt",
            "asset_id": None,
            "asset_name": "Handover item(s)",
            "asset_tag": None,
            "handover_id": hid,
            "slip_no": h.get("slip_no"),
            "requisition_id": h.get("requisition_id"),
            "message": f"Please confirm physical receipt of items on slip {h.get('slip_no')}.",
            "status": "unread",
            "created_at": now_iso(),
        })

    await handover_repo.update_fields(hid, {
        "status": "delivered", "delivered_by": user["name"], "delivered_by_id": str(user["_id"]),
        "delivered_at": now_iso()})
    if h.get("correction_case_id"):
        await _cor_on_redelivered(h, user)          # attempt N delivered - awaiting the employee's confirmation

    # The earlier "item is being prepared for handover" info notification is now superseded
    # by the receipt-confirmation one(s) above; mark it read so the requester doesn't see
    # a duplicate bell entry for the same slip.
    await notif_repo.update_where(
        {"handover_id": hid, "type": "stock_allocated", "status": "unread"},
        {"status": "read", "acted_at": now_iso()})

    if req:
        req.setdefault("history", []).append({
            "at": now_iso(), "by": user["name"], "action": "handover_delivered",
            "note": f"Physically delivered via slip {h['slip_no']}. Awaiting requester confirmation."})
        await req_repo.save_progress(req["_id"], status="awaiting_requester_confirmation",
                                     history=req["history"], updated_at=now_iso())
    elif h.get("requisition_id") and ObjectId.is_valid(h["requisition_id"]):
        req2 = await req_repo.get(h["requisition_id"])
        if req2:
            req2.setdefault("history", []).append({
                "at": now_iso(), "by": user["name"], "action": "handover_delivered",
                "note": f"Physically delivered via slip {h['slip_no']}. Awaiting requester confirmation."})
            await req_repo.save_progress(req2["_id"], status="awaiting_requester_confirmation",
                                         history=req2["history"], updated_at=now_iso())

    return {
        "ok": True,
        "status": "delivered",
        "requisition_status": "awaiting_requester_confirmation",
        "notification_user_id": target_user_id,
        "notifications_created": max(notif_count, 1),
    }


async def _warn_handover_not_received(n: dict):
    """The requester answered "Not received": warn whoever did the handover (the person who
    clicked 'Handover Done'; falls back to the slip's preparer) so they can follow up."""
    hid = n.get("handover_id")
    h = await handover_repo.get(hid) if hid and ObjectId.is_valid(hid) else None
    recipient = None
    if h:
        if h.get("delivered_by_id") and ObjectId.is_valid(h["delivered_by_id"]):
            recipient = await users_repo.get(h["delivered_by_id"])
        for nm in (h.get("delivered_by"), h.get("prepared_by")):
            if not recipient and nm and nm != "system":
                recipient = await users_repo.get_by_name(nm)
    if not recipient:
        return
    # one open warning per slip + item is enough (the requester can tap "Not received" again)
    if await notif_repo.exists({
            "user_id": str(recipient["_id"]), "type": "handover_not_received", "handover_id": hid,
            "asset_name": n.get("asset_name"), "status": "unread"}):
        return
    who = n.get("employee_name") or "The requester"
    await notif_repo.insert({
        "user_id": str(recipient["_id"]), "employee_name": who,
        "type": "handover_not_received", "handover_id": hid, "slip_no": n.get("slip_no"),
        "asset_name": n.get("asset_name"), "asset_id": n.get("asset_id"),
        "requisition_id": n.get("requisition_id"),
        "message": (f"Warning: {who} says they have NOT received {n.get('asset_name') or 'the item'}"
                    f"{' (slip ' + n['slip_no'] + ')' if n.get('slip_no') else ''}. "
                    "Please check the handover and follow up."),
        "status": "unread", "created_at": now_iso()})


def _img_from_datauri(uri):
    try:
        if not uri or "," not in uri:
            return None
        raw = base64.b64decode(uri.split(",", 1)[1])
        return RLImage(io.BytesIO(raw), width=45 * mm, height=18 * mm)
    except Exception:
        return None


PO_STATUSES = [
    "draft",
    "pending_purchase_head_approval",
    "pending_md_approval",
    "pending_accounts_head_approval",
    "approved",
    "rejected"
]


async def can_view_po_quotes(po: dict, user: dict) -> bool:
    """Vendor quotation PDFs are for the Purchase Head (and whoever uploaded them / Super Admin) only -
    not for the MD, Accounts Head or anyone else."""
    if user["role"] == "super_admin" or po.get("created_by_id") == str(user["_id"]):
        return True
    if await is_purchase_head_user(user):
        return True
    if po.get("status") == "pending_purchase_head_approval":     # on-leave delegate of the Purchase Head
        return await po_user_can_act(po, user, await active_delegators_of(user))
    return False


MIN_CS_QUOTES = 3  # spec: "cs_attachments (Minimum 3 vendor quotes)"


DEFAULT_PO_THRESHOLD = MD_THRESHOLD  # spec: "Configurable Threshold Amount (Default: 50,000 BDT)"


async def get_po_threshold() -> float:
    doc = await settings_repo.get("po_threshold")
    return doc["amount"] if doc else DEFAULT_PO_THRESHOLD


_AUDIT_TZ = timezone(timedelta(hours=6))      # Bangladesh time (UTC+6); the report says so in its header


_AUDIT_ACTION_LABELS = {
    "created": "Requisition created", "approve": "Approved", "reject": "Rejected", "revise": "Revision requested",
    "resubmit": "Resubmitted by requester", "smart_bypass": "Department Head step auto-approved",
    "it_employee_bypass": "Department Head step auto-approved (IT requester)",
    "accounts_purchase_bypass": "Department Head step auto-approved",
    "stock_check": "Stock check", "stock_available": "Stock available", "stock_issued": "Stock issued for handover",
    "stock_received_in_it": "Stock received in IT", "waiting_stock": "Waiting for stock",
    "pr_filed": "Purchase Requisition filed", "pr_voided": "Purchase Requisition voided",
    "pr_cancelled": "Purchase Requisition cancelled", "po_created": "Purchase Order created",
    "handover_delivered": "Delivered to user (handover done)", "receipt_confirmed": "User confirmed receipt",
    "it_queue_routed": "Routed to IT sub-team queue", "auto_approve": "Auto-approved",
    "service:picked_up": "Picked up by IT executive", "service:released": "Returned to IT queue",
    "service:service_completed_and_returned": "Service completed",
    "repair:requested": "External repair requested", "repair:approved": "External repair approved by IT Head",
    "repair:rejected": "External repair rejected by IT Head", "repair:repaired_and_delivered": "Repaired and delivered to user",
    "correction_reported": "Delivery rejected by employee (correction case opened)",
    "correction_rejected_again": "Replacement rejected by employee",
    "correction_acknowledged": "Correction acknowledged by IT",
    "correction_returned": "Rejected unit physically returned to IT",
    "correction_clarification_requested": "Clarification requested", "correction_clarification_answered": "Clarification answered",
    "correction_waiting_for_stock": "Correct item unavailable - waiting for stock",
    "correction_replacement": "Replacement allocated (new handover slip)",
    "correction_delivered_again": "Replacement delivered - awaiting confirmation",
    "correction_confirmed": "Replacement confirmed by employee",
    "correction_closed": "Correction case closed", "correction_reopened": "Correction case reopened",
}


def _a_dt(v) -> str:
    dt = _parse_iso(v) if isinstance(v, str) else v
    return dt.astimezone(_AUDIT_TZ).strftime("%d %b %Y, %H:%M") if dt else "-"


def _a_label(action: str) -> str:
    if action in _AUDIT_ACTION_LABELS:
        return _AUDIT_ACTION_LABELS[action]
    return (action or "event").replace("service:", "Service: ").replace("_", " ").replace(":", ": ").capitalize()


def build_audit_timeline(d: dict, pos: List[dict]) -> List[dict]:
    """One chronological list: the requisition's own history + every PO creation / approval step
    (taken from the PO record itself, so PO approvals are never missing)."""
    ev = []
    for h in d.get("history") or []:
        if (h.get("action") or "").startswith("po_") and h.get("action") != "po_created":
            continue                                  # PO stage syncs: shown from the PO records below
        if h.get("action") == "po_created":
            continue                                  # replaced by the richer PO event below
        ev.append({"at": h.get("at"), "by": h.get("by"), "event": _a_label(h.get("action")), "note": h.get("note")})
    for po in pos:
        ev.append({"at": po.get("created_at"), "by": po.get("created_by"), "event": f"Purchase Order {po.get('po_number')} created",
                   "note": f"Vendor: {po.get('vendor_name') or '-'}"})
        for c in po.get("approval_comments") or []:
            who = ROLE_LABELS.get(c.get("role"), c.get("role") or "")
            ev.append({"at": c.get("at"), "by": c.get("by"), "event": f"PO {po.get('po_number')}: {who} - {(c.get('action') or '').replace('_', ' ')}",
                       "note": c.get("comment")})
    ev.sort(key=lambda e: _parse_iso(e["at"]) or datetime.min.replace(tzinfo=timezone.utc))
    return ev


async def find_requisition_for_audit(ref: str) -> Optional[dict]:
    """Look up by requisition number (REQ-2026-0433); a filed PR number (LPRIT-...) also works."""
    ref = (ref or "").strip()
    if not ref or len(ref) > 40:
        return None
    return await req_repo.find_by_reference(ref)


async def collect_audit_data(d: dict) -> dict:
    rid = str(d["_id"])
    requester = None
    if d.get("requisitioner_id") and ObjectId.is_valid(d["requisitioner_id"]):
        requester = await users_repo.get(d["requisitioner_id"])
    dept_name = None
    did = d.get("requisitioner_department_id") or (requester or {}).get("department_id")
    if did and ObjectId.is_valid(did):
        dp = await dept_repo.get(did)
        dept_name = dp["name"] if dp else None
    pos = [] if d.get("requisition_type") == "service" else await po_repo.list_for_requisition(rid)
    hos = []
    if d.get("requisition_type") != "service":
        hos = await handover_repo.list_for_requisition(rid, also_id=d.get("handover_id"))
        await _attach_grn_prices(hos, rid)
    corrections = await case_repo.list_for_requisition(rid)
    return {"req": d, "requester": requester, "department_name": dept_name, "pos": pos, "handovers": hos, "corrections": corrections}


def grn_line_for_asset(grn: dict, asset: Optional[dict], name: Optional[str]) -> Optional[dict]:
    """The GRN line that received this unit: matched on its serial / tag first (so two lines of the same
    product with different rates never get mixed up), then on the product name."""
    items = (grn or {}).get("items") or []
    keys = {str(v).strip().lower() for v in ((asset or {}).get("serial_no"), (asset or {}).get("tag_id")) if v}
    if keys:
        for x in items:
            for u in x.get("assets") or []:
                if {str(v).strip().lower() for v in (u.get("serial_no"), u.get("tag_id")) if v} & keys:
                    return x
    want = _pkey(name or (asset or {}).get("name"))
    return next((x for x in items if _pkey(x.get("product_name")) == want), None)


async def _attach_grn_prices(hos: List[dict], rid: Optional[str] = None) -> None:
    """Adds `grn_rate` / `grn_no` to every handover item: the unit price typed in on the Stock GRN.
    The GRN received against THIS requisition wins (that is where the user typed the price for it);
    otherwise the GRN the delivered unit was originally received on (asset.source_grn_id)."""
    req_grns = await grn_repo.list_for_requisition(rid) if rid else []
    grn_cache: dict = {}
    for h in hos:
        for it in h.get("items") or []:
            aid = it.get("asset_id")
            a = await asset_repo.get(aid) if aid and ObjectId.is_valid(aid) else None
            name = it.get("item") or (a or {}).get("name")
            g = gi = None
            for cand in reversed(req_grns):                     # newest GRN for this requisition first
                gi = grn_line_for_asset(cand, a, name)
                if gi is not None:
                    g = cand
                    break
            if gi is None:
                gid = (a or {}).get("source_grn_id")
                if not (gid and ObjectId.is_valid(gid)):
                    continue
                if gid not in grn_cache:
                    grn_cache[gid] = await grn_repo.get(gid)
                g = grn_cache[gid]
                if not g:
                    continue
                gi = grn_line_for_asset(g, a, name)
            if gi is not None:
                it["grn_rate"] = float(gi.get("rate") or 0)
                it["grn_no"] = g.get("grn_no")


async def audit_can_view(user: dict, d: dict, pos: List[dict]) -> bool:
    """Master audit reports are restricted to Super Admin and the IT Head."""
    return user.get("role") == "super_admin" or await _is_it_head(user)


RP_UNIT_STATUS_OPTIONS = [
    {"value": "in_stock", "label": "In Stock"}, {"value": "assigned", "label": "Assigned"},
    {"value": "return_pending", "label": "Return Pending"}, {"value": "under_repair", "label": "Under Repair"},
    {"value": "scrapped", "label": "Scrapped"}, {"value": "lost", "label": "Lost"},
]


RP_UNIT_STATUS_LABEL = {o["value"]: o["label"] for o in RP_UNIT_STATUS_OPTIONS}


def _rp_and(*qs) -> dict:
    qs = [q for q in qs if q]
    return {"$and": qs} if len(qs) > 1 else (qs[0] if qs else {})


COR_REASONS = {
    "wrong_spec": "Wrong size or specification",
    "wrong_model": "Wrong model or brand",
    "damaged": "Damaged or not working",
    "missing_accessory": "Missing accessory",
    "quantity_short": "Quantity short",
    "nothing_delivered": "Nothing delivered",
    "other": "Other",
}


COR_STATUS_LABELS = {
    "reported_to_it": "Reported to IT",
    "under_review": "Under Review",
    "returned_to_it": "Returned to IT",
    "waiting_clarification": "Waiting for Clarification",
    "waiting_for_stock": "Waiting for Stock",
    "redelivery_in_progress": "Re-delivery in Progress",
    "delivered_again": "Delivered Again — Awaiting Confirmation",
    "confirmed": "Confirmed",
    "closed": "Closed",
}


COR_OPEN_STATUSES = ["reported_to_it", "under_review", "returned_to_it", "waiting_clarification",
                     "waiting_for_stock", "redelivery_in_progress", "delivered_again"]


COR_DEFAULTS = {"reminder_hours": 24.0, "escalation_hours": 72.0, "max_failed_attempts": 2, "max_reminders": 3}


async def get_correction_settings() -> dict:
    doc = await settings_repo.get("correction") or {}
    return {k: doc.get(k, v) for k, v in COR_DEFAULTS.items()}


def _cor_attempt(case: dict) -> dict:
    return case["attempts"][-1]


def _cor_event(case: dict, by: str, action: str, note: Optional[str] = None, frm: Optional[str] = None,
               to: Optional[str] = None, **extra) -> None:
    case.setdefault("events", []).append({
        "at": now_iso(), "by": by, "action": action, "from_status": frm, "to_status": to, "note": note,
        "item": (case.get("item") or {}).get("product_name"), **extra})
    case["last_activity_at"] = now_iso()


def _cor_set_status(case: dict, by: str, new: str, note: Optional[str] = None, action: Optional[str] = None, **extra) -> None:
    old = case.get("status")
    case["status"] = new
    _cor_event(case, by, action or f"status_{new}", note, old, new, **extra)


async def _cor_save(case: dict) -> None:
    """Version-guarded write: two people (or a double click) acting on the same case at once cannot
    both succeed - the second gets a 409 and nothing is overwritten."""
    v = case.get("version", 0)
    body = {k: val for k, val in case.items() if k != "_id"}
    body["version"] = v + 1
    body["updated_at"] = now_iso()
    if not await case_repo.save_if_version(case, v, body):
        raise HTTPException(status_code=409, detail="This case was just changed by someone else. Reload and try again.")
    case["version"] = v + 1


async def _cor_mirror(case: dict, by: str, action: str, note: str) -> None:
    """Copy the milestone into the requisition history so Requisition History / Audit PDF show it."""
    rid = case.get("requisition_id")
    if rid and ObjectId.is_valid(rid):
        await req_repo.append_history(rid, {
            "at": now_iso(), "by": by, "action": action, "note": f"[{case['case_no']}] {note}"})


async def _cor_it_heads() -> List[dict]:
    it = await find_dept_by_type("it")
    if not it:
        return []
    return await users_repo.list_dept_heads(str(it["_id"]), 20)


async def _cor_notify(user_id: Optional[str], ntype: str, message: str, case: dict, **extra) -> None:
    await _notify(user_id, ntype, message, correction_case_id=str(case["_id"]), link=f"/corrections/{case['_id']}",
                  requisition_id=case.get("requisition_id"), **extra)


async def _cor_notify_it(case: dict, ntype: str, message: str, exclude: Optional[str] = None) -> None:
    ids = []
    if case.get("responsible_it_id"):
        ids.append(case["responsible_it_id"])
    if not ids:                                   # nobody identified: the IT Head must see it
        ids = [str(u["_id"]) for u in await _cor_it_heads()]
    for uid in dict.fromkeys(ids):
        if uid != exclude:
            await _cor_notify(uid, ntype, message, case)


async def _cor_requested_for(req: Optional[dict], product_name: str) -> dict:
    items = (req or {}).get("items") or []
    it = next((i for i in items if _pkey(i.get("product_name")) == _pkey(product_name)), items[0] if items else {})
    # "Requested" = what the employee typed on the New Requisition form (not the PR / PO details).
    return {"product_name": it.get("product_name") or product_name,
            "detailed_specs": it.get("preferred_specification"),
            "preferred_brand": it.get("brand_name"), "model": it.get("model"),
            "quantity": it.get("quantity"), "uom": it.get("uom"), "category": it.get("category")}


async def _cor_delivered_for(asset: Optional[dict]) -> dict:
    a = asset or {}
    return {"brand": a.get("brand"), "model": a.get("model"), "specification": a.get("specification"),
            "serial_no": a.get("serial_no"), "tag_id": a.get("tag_id"), "name": a.get("name"),
            "category": await resolve_category_name(a.get("category_id")) if a.get("category_id") else None}


async def _cor_open_cases_for_handover(hid: str) -> int:
    return await case_repo.count_open_for_handover(hid, COR_OPEN_STATUSES)


async def _cor_requisition_blocked(rid: str) -> bool:
    """A requisition must not be finalised while any of its items is still unconfirmed or in correction."""
    if await notif_repo.count({"requisition_id": rid, "type": "asset_receipt", "status": {"$in": ["unread", "pending"]}}):
        return True
    return await case_repo.count_open_for_requisition(rid, COR_OPEN_STATUSES) > 0


async def _cor_finalize_original(case: dict, who: str) -> None:
    """After a case is confirmed/closed: if nothing else on the original slip is outstanding, the slip
    and the requisition can complete exactly as they would have without a rejection."""
    hid, rid = case.get("original_handover_id"), case.get("requisition_id")
    if not (hid and ObjectId.is_valid(hid)):
        return
    if await notif_repo.count({"handover_id": hid, "type": "asset_receipt", "status": {"$in": ["unread", "pending"]}}):
        return
    if await _cor_open_cases_for_handover(hid):
        return
    await handover_repo.update_fields(hid, {"status": "confirmed", "confirmed_at": now_iso()})
    if rid and ObjectId.is_valid(rid) and not await _cor_requisition_blocked(rid):
        req = await req_repo.get(rid)
        if req and req.get("status") == "awaiting_requester_confirmation":
            req.setdefault("history", []).append({"at": now_iso(), "by": who, "action": "receipt_confirmed",
                                                  "note": f"All items confirmed (including correction {case['case_no']})."})
            await req_repo.save_progress(req["_id"], status="handover_done", history=req["history"],
                                         updated_at=now_iso(), closed_at=now_iso())


async def _cor_on_redelivered(h: dict, user: dict) -> None:
    """Hook called by mark_handover_delivered for a correction slip."""
    cid = h.get("correction_case_id")
    if not (cid and ObjectId.is_valid(cid)):
        return
    case = await case_repo.get(cid)
    if not case or case["status"] != "redelivery_in_progress":
        return
    att = _cor_attempt(case)
    att.update({"status": "awaiting_confirmation", "delivered_at": now_iso(), "delivered_by": user["name"]})
    _cor_set_status(case, user["name"], "delivered_again", f"Attempt {att['attempt_no']} delivered (slip {att['slip_no']}) - awaiting employee confirmation", action="delivered_again")
    await _cor_save(case)
    await _cor_mirror(case, user["name"], "correction_delivered_again", f"Attempt {att['attempt_no']} delivered - awaiting confirmation")


async def _cor_escalate(case: dict, reason: str, text: str) -> None:
    if case.get("escalated_at") and reason == "unresolved_time":
        return
    case["escalated_at"] = now_iso()
    case.setdefault("escalations", []).append({"at": now_iso(), "reason": reason, "text": text})
    _cor_event(case, "system", "escalated_to_it_head", text)
    heads = await _cor_it_heads()
    for h in heads:
        await _cor_notify(str(h["_id"]), "correction_escalated", f"Escalation — {case['case_no']} ({case['item']['product_name']}, {case['employee_name']}): {text}.", case)
    await _cor_save(case)


async def run_correction_sweep() -> dict:
    """One reminder per interval (capped) to the responsible IT employee, one escalation to the IT Head
    when the case stays unresolved past the escalation limit. All limits come from settings."""
    cfg = await get_correction_settings()
    now = datetime.now(timezone.utc)
    reminded = escalated = 0
    for case in await case_repo.list_all(status_in=COR_OPEN_STATUSES, limit=2000):
        created = _parse_iso(case.get("created_at")) or now
        last = _parse_iso(case.get("last_activity_at")) or created
        rem = case.get("reminders") or {"count": 0, "last_at": None}
        waiting_on_it = case["status"] in ("reported_to_it", "under_review", "returned_to_it", "redelivery_in_progress")
        last_rem = _parse_iso(rem.get("last_at"))
        if (waiting_on_it and (now - last).total_seconds() / 3600 >= cfg["reminder_hours"] and rem.get("count", 0) < cfg["max_reminders"]
                and (not last_rem or (now - last_rem).total_seconds() / 3600 >= cfg["reminder_hours"])):
            rem = {"count": rem.get("count", 0) + 1, "last_at": now_iso()}
            case["reminders"] = rem
            before = case.get("last_activity_at")
            _cor_event(case, "system", "reminder_sent", f"Reminder {rem['count']} sent to {case.get('responsible_it_name') or 'IT'}")
            case["last_activity_at"] = before                # a reminder is not activity
            await _cor_save(case)
            await _cor_notify_it(case, "correction_reminder", f"Reminder: {case['case_no']} ({case['item']['product_name']}, {case['employee_name']}) is still {COR_STATUS_LABELS[case['status']].lower()}.")
            reminded += 1
        if not case.get("escalated_at") and (now - created).total_seconds() / 3600 >= cfg["escalation_hours"]:
            await _cor_escalate(case, "unresolved_time", f"unresolved for more than {cfg['escalation_hours']:g} hours")
            escalated += 1
    return {"reminded": reminded, "escalated": escalated}