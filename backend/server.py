from dotenv import load_dotenv
from pathlib import Path
import os
import asyncio
import secrets

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends, UploadFile, File, Body, Form
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal, Dict
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import logging
import bcrypt
import jwt

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_ALGORITHM = "HS256"

def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]

app = FastAPI(title="IRM - IT Requisition & Asset Management")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ims")

# ---------------------------------------------------------------------------
# Constants: roles, menu, permissions
# ---------------------------------------------------------------------------
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
        {"key": "assigned-assets", "label": "Assigned Assets", "path": "/assigned-assets"},
    ]},
    {"group": "Requisition", "icon": "ClipboardList", "badge": "B1", "items": [
        {"key": "new-requisition", "label": "New Requisition", "path": "/requisitions/new"},
        {"key": "pending-requisition", "label": "Pending Requisition", "path": "/requisitions/pending"},
        {"key": "file-purchase-requisition", "label": "File Purchase Requisition", "path": "/requisitions/purchase"},
        {"key": "file-purchase-order", "label": "File Purchase Order", "path": "/requisitions/purchase-order"},
        {"key": "handover-queue", "label": "Handover Queue", "path": "/requisitions/handover"},
        {"key": "it-service-queue", "label": "IT Service Queue", "path": "/it-service/queue"},
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
    ]},
    {"group": "Approvals", "icon": "UserCheck", "badge": "F1", "items": [
        {"key": "approver-management", "label": "Approver Management", "path": "/approvals"},
    ]},
    {"group": "Organization", "icon": "Building2", "badge": "G1", "items": [
        {"key": "departments", "label": "Departments", "path": "/organization/departments"},
        {"key": "categories", "label": "Categories", "path": "/organization/categories"},
        {"key": "products", "label": "Products", "path": "/organization/products"},
        {"key": "users-roles", "label": "Users & Roles", "path": "/organization/users"},
        {"key": "bulk-import", "label": "Bulk Import", "path": "/organization/import"},
    ]},
]

ALL_MENU_KEYS = [item["key"] for g in MENU for item in g["items"]]

# Default sidebar permission map keyed by canonical role.
# Note: "dept_head" here is the IT-department dept head's menu (this role also carries IT
# operational duties — Handover Queue, Stock GRN's records, Approver Management — since
# nothing in this system distinguishes "IT Head" from "Department Head" as separate roles).
# A dept_head in any OTHER department gets the reduced NON_IT_DEPT_HEAD_PERMISSIONS set
# below (employee menu + Approve Requisitions only) — see my_permissions().
DEFAULT_PERMISSIONS = {
    "super_admin": ALL_MENU_KEYS,
    "dept_head": [
        "overview", "assigned-assets",
        "new-requisition", "pending-requisition", "approve-requisition", "handover-queue", "requisition-history",
        "stock-list", "handover-module", "handover-records", "approver-management", "products",
    ],
    "executive": [
        "overview", "new-requisition", "pending-requisition", "requisition-history",
    ],
    "accounts": [
         "overview", "approve-requisition",
         "requisition-history", "stock-list", "po-approvals",
    ],
    "md": [
         "overview", "approve-requisition", "requisition-history", "po-approvals",
    ],
    "purchase_head": [
         "overview", "approve-requisition",
        "requisition-history", "stock-grn", "stock-list", "po-approvals", "create-po",
    ],
}

# Reduced menu for a dept_head in any department OTHER than IT: employee essentials plus
# just the Approve Requisitions queue — no Stock/Handover/Approver-Management operational
# tooling, which is specific to the IT team's day-to-day duties.
NON_IT_DEPT_HEAD_PERMISSIONS = [
    "overview", "new-requisition", "pending-requisition", "requisition-history", "approve-requisition",
]

REQ_STATUSES = [
    "pending_dept", "pending_it_service", "product_collected_by_it", "sent_to_service_center",
    "service_completed_and_returned", "pending_it", "pending_pr", "pending_it_review", "pending_po_entry",
    "pending_accounts", "pending_md",
    "po_draft", "pending_purchase", "buy_process", "stock_received_in_it", "pending_handover", "awaiting_requester_confirmation",
    "handover_done", "approved", "rejected", "revision_requested", "pr_cancelled",
    "pending_admin", "waiting_stock",
    "service_in_progress", "pending_repair_approval", "product_in_service",
]



# Ordered operational stages for service requisitions.
SERVICE_STAGES = [
    "pending_it_service", "product_collected_by_it", "sent_to_service_center",
    "service_completed_and_returned",
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
SERVICE_QUEUE_ACTIVE = "service_in_progress"
SERVICE_QUEUE_DONE = "service_completed_and_returned"
# External repair (device cannot be fixed on site): requested by the executive, approved by the IT Head.
SERVICE_REPAIR_PENDING = "pending_repair_approval"
SERVICE_IN_SERVICE = "product_in_service"          # at the external service center
SERVICE_WORKING = [SERVICE_QUEUE_ACTIVE, SERVICE_REPAIR_PENDING, SERVICE_IN_SERVICE]   # picked up, not yet closed

# Statuses that mean the requisition is closed (no further approval action).
FINALIZED = ["handover_done", "approved", "rejected", "service_completed_and_returned", "pr_cancelled"]
# The requisition has goods sitting in IT's central stock (via GRN) but hasn't been issued
# for handover yet. Used both by POST /requisitions/{id}/issue-stock and by the Handover
# Module's auto-link logic (see _find_requisition_for_handover) so an ad-hoc handover
# created for the same item can still close the loop back to the requisition.
READY_FOR_HANDOVER_STATUS = "stock_received_in_it"

MD_THRESHOLD = 50000  # BDT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "type": "access",
               "iat": int(datetime.now(timezone.utc).timestamp()),
               "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def set_auth_cookies(response: Response, access: str, refresh: str):
    # secure=True is required for SameSite=None cookies and is correct for production (https).
    # For local dev over plain http, browsers silently DROP secure cookies entirely, which breaks
    # session persistence on refresh. COOKIE_SECURE lets local/dev deployments opt out safely.
    secure = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
    samesite = "none" if secure else "lax"
    response.set_cookie("access_token", access, httponly=True, secure=secure, samesite=samesite, max_age=43200, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=secure, samesite=samesite, max_age=604800, path="/")

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
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
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

# Anyone holding the per-user "Can Raise PR" flag (the PR raiser) also gets the Handover
# module and Stock GRN. The access is DERIVED from the flag at request time (nothing extra is
# stored), so when Super Admin / IT Head moves "Can Raise PR" from one person to another, the
# new PR raiser gains these screens immediately and the previous one loses them.
PR_RAISER_MENU_KEYS = ["handover-module", "handover-records", "stock-grn"]

def has_pr_raise_flag(user: dict) -> bool:
    return bool(user.get("can_raise_pr"))

def require_roles_or_pr_raiser(*roles):
    """Same as require_roles(), but a user with can_raise_pr is also let through."""
    async def dep(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles and not has_pr_raise_flag(user):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dep

async def next_req_number() -> str:
    year = datetime.now(timezone.utc).year
    counter = await db.counters.find_one_and_update(
        {"_id": f"req-{year}"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER,
    )
    seq = counter["seq"]
    return f"REQ-{year}-{seq:04d}"

# ---------------------------------------------------------------------------
# Approval chain resolution
# ---------------------------------------------------------------------------
async def find_dept_by_name(name: str) -> Optional[dict]:
    return await db.departments.find_one({"name": name})

async def _department_is_it(department_id: Optional[str]) -> bool:
    """Can Raise PR is an IT-department-only permission (per user, not role-wide) — this
    guards it server-side so the restriction can't be bypassed by calling the API directly,
    even though the UI already hides the checkbox for non-IT users."""
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    it_dept = await find_dept_by_name("IT")
    return bool(it_dept) and str(it_dept["_id"]) == department_id

async def _department_is_admin(department_id: Optional[str]) -> bool:
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    d = await find_admin_dept()
    return bool(d) and str(d["_id"]) == department_id

async def _department_is_purchase(department_id: Optional[str]) -> bool:
    """Can Create PO is a Purchase-department-only permission (per user, not role-wide) —
    mirrors _department_is_it exactly, for the same reasons."""
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    purchase_dept = await find_dept_by_name("Purchase")
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

async def validate_it_team(value: Optional[str], department_id: Optional[str]) -> Optional[str]:
    """`it_team` is optional metadata: None clears it; a value must be a known sub-team and the
    user must be in the IT department (enforced server-side, not just hidden in the UI)."""
    if value in (None, ""):
        return None
    if value not in IT_TEAMS:
        raise HTTPException(status_code=400, detail=f"Invalid IT team. Use one of: {', '.join(IT_TEAMS)}")
    if not await _department_is_it(department_id):
        raise HTTPException(status_code=400, detail="IT team (Application / Network_Infra) is only available for users in the IT department")
    return value

async def resolve_approver(role: str, department_id: Optional[str] = None) -> Optional[dict]:
    query = {"role": role}
    if department_id:
        query["department_id"] = department_id
    elif role == "md":
        # MD sits under the top-level "Primitek Group" department, not IT/Purchase/etc.
        # Anchor explicitly to that department when it exists, so MD resolution can't
        # accidentally pick up a differently-departmented user if more than one "md"
        # role is ever created.
        pg = await find_dept_by_name("Primitek Group")
        if pg:
            query["department_id"] = str(pg["_id"])
    u = await db.users.find_one(query)
    if not u and role == "md" and department_id is None and "department_id" in query:
        # Fallback: no user is attached to "Primitek Group" yet — don't silently fail to
        # resolve an MD approver just because that department link hasn't been set up.
        u = await db.users.find_one({"role": "md"})
    return u

# Roles that act as the "head" of their own department. The Accounts Head (CFO) has role
# "accounts" and the Purchase Head has role "purchase_head" — neither has role "dept_head",
# so a plain resolve_approver("dept_head", <dept>) finds nobody for the Accounts / Purchase
# departments and the level-1 "Department Head" step ended up with approver_id = None
# (status showed "Dept Head approval pending" but it never reached anyone's queue).
DEPT_HEAD_EQUIVALENT_ROLES = ("dept_head", "accounts", "purchase_head")

async def resolve_department_head(department_id: Optional[str]) -> Optional[dict]:
    """Head of a department: prefer a real dept_head, else the accounts / purchase_head
    user who belongs to that same department."""
    if not department_id:
        return None
    u = await db.users.find_one({"role": "dept_head", "department_id": department_id})
    if u:
        return u
    return await db.users.find_one(
        {"role": {"$in": list(DEPT_HEAD_EQUIVALENT_ROLES)}, "department_id": department_id})

def is_current_approver(step: dict, user: dict, delegators: Optional[set] = None) -> bool:
    """True if `user` may act on this pending chain step:
      - super_admin (always);
      - the step's approver;
      - someone the approver has delegated to while on leave (`delegators` = ids of users who
        currently delegate to `user`, see active_delegators_of);
      - legacy unassigned level-1 Department Head steps: the head of that step's department."""
    if user["role"] == "super_admin":
        return True
    uid = str(user["_id"])
    if step.get("approver_id"):
        return step["approver_id"] == uid or (bool(delegators) and step["approver_id"] in delegators)
    return (
        step.get("role") == "dept_head"
        and bool(step.get("department_id"))
        and step.get("department_id") == user.get("department_id")
        and user["role"] in DEPT_HEAD_EQUIVALENT_ROLES
    )

# ---------------------------------------------------------------------------
# REMINDERS & LEAVE DELEGATION
#   * A pending approval with no action for `reminder_hours` (default 24) sends the approver
#     (and their active delegate) ONE reminder. Nothing is escalated or reassigned automatically.
#   * An approver can delegate to a colleague for a date range (leave). During that window the
#     delegate sees and acts on everything addressed to the approver.
#   * A background task runs the check every REMINDER_SWEEP_MINUTES (default 15).
# ---------------------------------------------------------------------------
DEFAULT_REMINDER_HOURS = 24

async def get_reminder_settings() -> dict:
    doc = await db.system_settings.find_one({"_id": "reminder"})
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
    async for u in db.users.find({"delegate_user_id": str(user["_id"])}):
        if _delegation_active(u):
            out.add(str(u["_id"]))
    return out

async def _notify(user_id: Optional[str], ntype: str, message: str, **extra):
    if not user_id:
        return
    await db.notifications.insert_one({
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
    async for d in db.requisitions.find({"status": {"$nin": FINALIZED}}):
        chain = d.get("approval_chain") or []
        cur = next((x for x in chain if x.get("status") == "pending"), None)
        if not cur or cur.get("reminded_at"):
            continue
        age_h = (now - step_pending_since(d, cur)).total_seconds() / 3600
        if age_h < cfg["reminder_hours"]:
            continue
        approver = None
        if cur.get("approver_id") and ObjectId.is_valid(cur["approver_id"]):
            approver = await db.users.find_one({"_id": ObjectId(cur["approver_id"])})
        await _notify_with_delegate(approver, "approval_reminder",
            f"Reminder: {d['requisition_no']} ({cur.get('label', 'approval')}) has been waiting for your approval for {int(age_h)} hours.",
            requisition_id=str(d["_id"]))
        cur["reminded_at"] = now_iso()
        await db.requisitions.update_one({"_id": d["_id"]}, {"$set": {"approval_chain": chain}})
        reminded += 1
    return reminded

PO_STAGE_ROLE = {
    "pending_purchase_head_approval": "purchase_head",
    "pending_md_approval": "md",
    "pending_accounts_head_approval": "accounts",
}

async def _po_stage_holders(stage_role: str) -> List[dict]:
    q = [{"role": stage_role}]
    if stage_role == "purchase_head":
        pd = await find_dept_by_name("Purchase")
        if pd:
            q.append({"role": "dept_head", "department_id": str(pd["_id"])})
    return await db.users.find({"$or": q}).to_list(50)

async def _sweep_purchase_orders(cfg: dict, now: datetime) -> int:
    reminded = 0
    async for po in db.purchase_orders.find({"status": {"$in": list(PO_STAGE_ROLE)}}):
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
        await db.purchase_orders.update_one({"_id": po["_id"]}, {"$set": {
            "reminder": {"status": po["status"], "reminded_at": now_iso()}}})
        reminded += 1
    return reminded

async def run_reminder_sweep() -> dict:
    cfg = await get_reminder_settings()
    now = datetime.now(timezone.utc)
    return {"requisitions_reminded": await _sweep_requisitions(cfg, now),
            "purchase_orders_reminded": await _sweep_purchase_orders(cfg, now),
            "settings": cfg}

async def reminder_loop():
    minutes = max(int(os.environ.get("REMINDER_SWEEP_MINUTES", "15")), 1)
    await asyncio.sleep(30)
    while True:
        try:
            res = await run_reminder_sweep()
            if res["requisitions_reminded"] or res["purchase_orders_reminded"]:
                logger.info(f"Reminder sweep: {res}")
        except Exception as e:
            logger.error(f"Reminder sweep failed: {e}")
        await asyncio.sleep(minutes * 60)

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

class DelegationIn(BaseModel):
    delegate_user_id: Optional[str] = None
    delegate_from: Optional[str] = None      # YYYY-MM-DD
    delegate_until: Optional[str] = None     # YYYY-MM-DD

def _valid_date(v: Optional[str]) -> bool:
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False

async def _delegation_view(u: dict) -> dict:
    name = None
    did = u.get("delegate_user_id")
    if did and ObjectId.is_valid(did):
        x = await db.users.find_one({"_id": ObjectId(did)})
        name = x["name"] if x else None
    return {"delegate_user_id": did, "delegate_name": name,
            "delegate_from": u.get("delegate_from"), "delegate_until": u.get("delegate_until"),
            "active": _delegation_active(u)}

@api_router.get("/me/delegation")
async def get_my_delegation(user: dict = Depends(get_current_user)):
    return await _delegation_view(user)

@api_router.put("/me/delegation")
async def set_my_delegation(payload: DelegationIn, user: dict = Depends(get_current_user)):
    """Set (or clear, by sending nulls) the colleague who approves on your behalf while on leave."""
    uid = str(user["_id"])
    if payload.delegate_user_id:
        if payload.delegate_user_id == uid:
            raise HTTPException(status_code=400, detail="You cannot delegate to yourself")
        if not ObjectId.is_valid(payload.delegate_user_id) or not await db.users.find_one({"_id": ObjectId(payload.delegate_user_id)}):
            raise HTTPException(status_code=400, detail="Selected delegate does not exist")
        if not (_valid_date(payload.delegate_from) and _valid_date(payload.delegate_until)):
            raise HTTPException(status_code=400, detail="Choose a start and end date for the leave")
        if payload.delegate_until < payload.delegate_from:
            raise HTTPException(status_code=400, detail="End date cannot be before the start date")
        await db.users.update_one({"_id": user["_id"]}, {"$set": {
            "delegate_user_id": payload.delegate_user_id,
            "delegate_from": payload.delegate_from, "delegate_until": payload.delegate_until}})
        await _notify(payload.delegate_user_id, "delegation_assigned",
            f"{user['name']} has delegated their approvals to you from {payload.delegate_from} to {payload.delegate_until}.")
    else:
        await db.users.update_one({"_id": user["_id"]}, {"$unset": {
            "delegate_user_id": "", "delegate_from": "", "delegate_until": ""}})
    return await _delegation_view(await db.users.find_one({"_id": user["_id"]}))

class ReminderSettingsIn(BaseModel):
    reminder_hours: float

@api_router.get("/settings/reminder")
async def get_reminder_setting(user: dict = Depends(get_current_user)):
    return await get_reminder_settings()

@api_router.put("/settings/reminder")
async def set_reminder_setting(payload: ReminderSettingsIn, user: dict = Depends(require_roles("super_admin"))):
    if payload.reminder_hours <= 0:
        raise HTTPException(status_code=400, detail="Reminder time must be greater than 0 hours")
    await db.system_settings.update_one({"_id": "reminder"}, {"$set": {
        "reminder_hours": payload.reminder_hours, "updated_at": now_iso(), "updated_by": user["name"]}}, upsert=True)
    return await get_reminder_settings()

@api_router.post("/admin/reminders/run")
async def run_reminders_now(user: dict = Depends(require_roles("super_admin"))):
    """Runs the reminder check immediately (it also runs automatically)."""
    return await run_reminder_sweep()

# ---------------------------------------------------------------------------
# ADMIN TRACK — consumable & furniture product requisitions.
# These skip the requester's own Dept Head (and Accounts Head) entirely: the ONLY approval is
# the Admin department head. After that: stock available -> handover starts at once;
# no stock -> status "waiting_stock" (no PR/PO) until the Admin dept restocks via GRN, at which
# point the handover starts automatically (see process_waiting_stock_requisitions).
# Applies only when EVERY line is consumable/furniture; a mixed requisition keeps the normal chain.
# ---------------------------------------------------------------------------
ADMIN_TRACK_TYPES = ("consumable", "furniture")

async def find_admin_dept() -> Optional[dict]:
    return await db.departments.find_one({"name": {"$regex": r"^\s*admin(istration)?\s*$", "$options": "i"}})

def is_admin_track(req_type: str, items: List[dict]) -> bool:
    return (req_type == "product" and bool(items)
            and all((it.get("product_type") in ADMIN_TRACK_TYPES) for it in items))

def is_admin_track_req(d: dict) -> bool:
    return any(s.get("stage") == "admin_review" for s in d.get("approval_chain", []))

def apply_admin_head_smart_bypass(chain: List[dict], requester: dict) -> bool:
    """Requester IS the approving Admin Head -> the single admin step is auto-approved."""
    if chain and chain[0].get("stage") == "admin_review" and chain[0].get("status") == "pending":
        if chain[0].get("approver_id") == str(requester["_id"]):
            chain[0]["status"] = "approved"
            chain[0]["note"] = "Auto-approved: requester is the Admin Head."
            chain[0]["acted_at"] = now_iso()
            return True
    return False

async def build_approval_chain(req_type: str, requester: dict, items: Optional[List[dict]] = None) -> List[dict]:
    """Base approval chain.

    STEP 4 of the PR/PO redesign (Decision #1, "Stock Checking & In-Stock Path"): product
    requisitions now get a SINGLE "Department Head" level as their base chain. Stock is
    checked informationally at submission (see create_requisition's
    stock_check_at_submission) and, authoritatively, again the moment the Dept Head
    approves — that single approval event is what branches straight to auto-handover
    (stock available) or into the out-of-stock PR/PO path (status "pending_pr"). See
    act_on_requisition's base_chain_just_completed, which needed NO changes for this: it
    already keys off "the base chain's last step just got approved", generically, for any
    chain length.

    IT Head is intentionally no longer part of this base chain. For the out-of-stock path,
    IT Head instead reviews the PR *after* it's been filed with estimated pricing — see
    make_it_head_review_step(), appended by set_pr_pricing() — matching workflow Step 3
    ("IT Department Head Approval... for specification and quantity review").

    Already-created requisitions keep whatever chain shape they were built with — this
    function is only ever called at creation time, so nothing retroactively changes for
    in-flight records.

    Service requisitions: unchanged, straight to IT Department Head (single level)."""
    steps: List[dict] = []

    async def step(level, role, label, department_id=None):
        if role == "dept_head" and department_id:
            approver = await resolve_department_head(department_id)
        else:
            approver = await resolve_approver(role, department_id)
        steps.append({
            "level": level, "role": role, "label": label, "department_id": department_id,
            "approver_id": str(approver["_id"]) if approver else None,
            "approver_name": approver["name"] if approver else None,
            "status": "pending", "note": None, "acted_at": None, "pending_since": now_iso(),
        })

    it_dept = await find_dept_by_name("IT")
    it_dept_id = str(it_dept["_id"]) if it_dept else None

    if is_admin_track(req_type, items or []):
        admin_dept = await find_admin_dept()
        admin_dept_id = str(admin_dept["_id"]) if admin_dept else None
        await step(1, "dept_head", "Admin Head", admin_dept_id)
        steps[-1]["stage"] = "admin_review"
        if not steps[-1]["approver_id"]:
            # No Admin department / head configured: Super Admin can still act on it.
            sa = await db.users.find_one({"role": "super_admin"})
            if sa:
                steps[-1]["approver_id"] = str(sa["_id"])
                steps[-1]["approver_name"] = sa["name"]
        return steps

    if req_type == "service":
        await step(1, "dept_head", "IT Department Head", it_dept_id)
    else:
        await step(1, "dept_head", "Department Head", requester.get("department_id"))
    return steps

async def make_it_head_review_step(level: int) -> dict:
    """The new "IT Head — PR Review" step (workflow Step 3), appended to a requisition's
    approval_chain by set_pr_pricing() once the PR Handler has filed estimated pricing.
    This is a strictly read-only review/approval step — approve, reject, or revise, same
    as any other chain step — no quantity or spec editing capability. Tagged with
    stage="pr_review" so status_for_step() can recognize it distinctly from the legacy
    base-chain "IT Head" step that older, already-created requisitions may still carry —
    a plain label/role match would risk conflating the two."""
    it_dept = await find_dept_by_name("IT")
    it_dept_id = str(it_dept["_id"]) if it_dept else None
    approver = await resolve_approver("dept_head", it_dept_id)
    return {
        "level": level, "role": "dept_head", "label": "IT Head — PR Review",
        "department_id": it_dept_id,
        "approver_id": str(approver["_id"]) if approver else None,
        "approver_name": approver["name"] if approver else None,
        "status": "pending", "note": None, "acted_at": None, "pending_since": now_iso(),
        "stage": "pr_review",
    }

# ---------------------------------------------------------------------------
# Purchase Orders — STEP 3: "Smart Bypass" (PR/PO redesign spec, workflow Step 1)
#
# "If the requester IS the Department Head, auto-approve this step." Applied
# ONLY to the product requisition's level-1 "Department Head" step (matched by
# its exact label, not just role+level) — never to the "IT Head — PR Review"
# step, service requisitions' single "IT Department Head" step, or anything on
# the separate Purchase Order. This is a separate, opt-in step called only
# from create_requisition/preview_chain — build_approval_chain() itself
# doesn't call it.
# ---------------------------------------------------------------------------
def apply_dept_head_smart_bypass(chain: List[dict], requester: dict) -> bool:
    """Mutates chain in place if the requester is themselves the resolved approver for
    the level-1 'Department Head' step. Returns True if the bypass was applied."""
    if not chain:
        return False
    step = chain[0]
    if step.get("label") == "Department Head" and step.get("approver_id") == str(requester["_id"]):
        step["status"] = "approved"
        step["note"] = "Auto-approved: requester is the Department Head for this department (Smart Bypass)."
        step["acted_at"] = now_iso()
        return True
    return False

async def apply_it_employee_base_bypass(chain: List[dict], requester: dict) -> bool:
    """Option A — avoid double IT Head approval for IT-department requesters.

    When an IT executive (or any non-head IT user) raises a *product* requisition, the
    base chain's single 'Department Head' step is the IT Head. Approving that, then
    later requiring 'IT Head — PR Review' after the PR is filed, forces the same person
    to approve twice. Auto-approve the base step at creation so the only IT Head action
    is the PR review (after specs/qty are on the PR). Non-IT requesters are unchanged:
    their Dept Head still approves first, then IT Head reviews the PR.

    Only touches a still-pending level-1 'Department Head' step (never service chains,
    never the later pr_review step). Safe to call after apply_dept_head_smart_bypass —
    if that already approved the step (requester is IT Head), this is a no-op."""
    if not chain:
        return False
    step = chain[0]
    if step.get("status") != "pending":
        return False
    if step.get("label") != "Department Head":
        return False
    if step.get("stage") == "pr_review":
        return False
    if not await _department_is_it(requester.get("department_id")):
        return False
    step["status"] = "approved"
    step["note"] = (
        "Auto-approved: requester is from the IT department — "
        "IT Head will review once at the PR stage if purchase is needed."
    )
    step["acted_at"] = now_iso()
    return True

async def _department_is_accounts_or_purchase(department_id: Optional[str]) -> bool:
    """True if department_id is the Accounts or the Purchase department (name matched
    case-insensitively, so 'Accounts' / 'Account' / 'Purchase' / 'Purchases' all work)."""
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    d = await db.departments.find_one({
        "_id": ObjectId(department_id),
        "name": {"$regex": r"^\s*(accounts?|purchases?)\s*$", "$options": "i"},
    })
    return bool(d)

async def apply_accounts_purchase_executive_bypass(chain: List[dict], requester: dict,
                                                   req_type: str = "product") -> bool:
    """A product requisition raised by an EXECUTIVE of the Accounts or Purchase department
    skips its own Dept Head approval (the Accounts Head / Purchase Head would otherwise
    approve here AND again later in the PR/PO chain). The level-1 'Department Head' step is
    auto-approved at creation; every later rule (stock check -> IT Head stock approval or
    PR -> IT Head PR review -> PO -> MD / Accounts / Purchase Head) then follows unchanged.

    Only touches a still-pending level-1 'Department Head' step of a product requisition,
    and only when the requester's role is 'executive'."""
    if req_type != "product" or not chain:
        return False
    if requester.get("role") != "executive":
        return False
    step = chain[0]
    if step.get("status") != "pending" or step.get("label") != "Department Head":
        return False
    if step.get("stage") == "pr_review":
        return False
    if not await _department_is_accounts_or_purchase(requester.get("department_id")):
        return False
    step["status"] = "approved"
    step["note"] = ("Auto-approved: requester is an executive of the Accounts/Purchase department — "
                    "own Dept Head approval bypassed; the PR/PO approval chain follows.")
    step["acted_at"] = now_iso()
    return True

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
    purchase_dept = await find_dept_by_name("Purchase")
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

def _stock_name_query(name: str) -> dict:
    """Case- and whitespace-insensitive match for an item name, so a requisition line
    'Laptop' finds stock recorded as 'laptop' / ' Laptop '."""
    return {"$regex": f"^\\s*{re.escape((name or '').strip())}\\s*$", "$options": "i"}

async def has_sufficient_stock(items: List[dict]) -> bool:
    need: dict = {}
    for it in items:
        key = (it["product_name"] or "").strip().lower()
        need[key] = need.get(key, 0) + int(it.get("quantity") or 1)
    for key, qty in need.items():
        available = await db.assets.count_documents({
            "name": _stock_name_query(key), "status": "in_stock", "pending_receipt": {"$ne": True}})
        if available < qty:
            return False
    return True

async def make_it_stock_review_step(level: int) -> dict:
    """In-stock path: after the Dept Head approves, the IT Head approves issuing from stock."""
    step = await make_it_head_review_step(level)
    step["label"] = "IT Head — Stock Approval"
    step["stage"] = "stock_review"
    return step

async def route_after_base_chain(d: dict, requester_id: Optional[str] = None) -> dict:
    """Called once the Dept Head step is fully approved. Stock available -> IT Head stock
    approval (then handover). No stock -> straight to the PR path. Returns extra $set fields."""
    extra = {}
    if is_admin_track_req(d):
        # Admin Head approved. No IT stock review, no PR/PO: in stock -> handover starts now,
        # otherwise the requester waits for the Admin department to restock.
        d.setdefault("history", [])
        if await has_sufficient_stock(d["items"]):
            hid = await auto_generate_handover(d)
            d["status"], d["handover_id"] = "pending_handover", hid
            extra["handover_id"] = hid
            d["history"].append({"at": now_iso(), "by": "system", "action": "stock_available",
                                 "note": "Admin Head approved and stock is available — handover started."})
        else:
            d["status"] = "waiting_stock"
            d["history"].append({"at": now_iso(), "by": "system", "action": "waiting_stock",
                                 "note": "Admin Head approved but stock is not available — waiting for the Admin department to restock."})
        extra["approval_chain"] = d["approval_chain"]
        extra["history"] = d["history"]
        return extra
    if await has_sufficient_stock(d["items"]):
        chain = d["approval_chain"]
        step = await make_it_stock_review_step(len(chain) + 1)
        if step.get("approver_id") and step["approver_id"] == requester_id:
            step["status"], step["acted_at"] = "approved", now_iso()
            step["note"] = "Auto-approved: requester is the IT Head."
        chain.append(step)
        d["approval_chain"] = chain
        d["status"] = compute_status(d)
        if d["status"] == "approved":            # IT Head raised it themselves
            await finish_stock_review(d, extra)
    else:
        d["status"] = "pending_pr"
        d["pr_flow"] = True
        extra["pr_flow"] = True
    extra["approval_chain"] = d["approval_chain"]
    return extra

async def finish_stock_review(d: dict, extra: dict):
    """IT Head approved the stock issue: reserve stock + create the handover, or fall back to
    PR if the stock was taken in the meantime."""
    if await has_sufficient_stock(d["items"]):
        hid = await auto_generate_handover(d)
        d["status"], d["handover_id"] = "pending_handover", hid
        extra["handover_id"] = hid
    else:
        d["status"], d["pr_flow"] = "pending_pr", True
        extra["pr_flow"] = True

async def process_waiting_stock_requisitions() -> int:
    """Called whenever stock is added (GRN, manual asset, returned asset). Starts the handover
    for admin-track requisitions that were 'waiting_stock', oldest first, as far as the new
    stock allows. Returns how many were started."""
    started = 0
    async for d in db.requisitions.find({"status": "waiting_stock"}).sort("created_at", 1):
        if not await has_sufficient_stock(d["items"]):
            continue
        hid = await auto_generate_handover(d)
        d.setdefault("history", []).append({"at": now_iso(), "by": "system", "action": "stock_available",
                                            "note": "Stock restocked — handover started."})
        await db.requisitions.update_one({"_id": d["_id"]}, {"$set": {
            "status": "pending_handover", "handover_id": hid, "history": d["history"], "updated_at": now_iso()}})
        item_names = ", ".join(it["product_name"] for it in d["items"])
        await db.notifications.insert_one({
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
        assets = await db.assets.find({
            "name": _stock_name_query(it["product_name"]), "status": "in_stock", "pending_receipt": {"$ne": True}
        }).to_list(it["quantity"])
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
    res = await db.handovers.insert_one(doc)
    hid = str(res.inserted_id)
    for it in items_out:
        await db.assets.update_one({"_id": ObjectId(it["asset_id"])}, {"$set": {
            "pending_receipt": True, "pending_handover_id": hid,
            "assigned_to_tentative": doc["employee_name"],
            "assigned_department_id": doc["department_id"]}})
    return hid

async def _users_in_dept_matching(name: str, department_id: Optional[str], exact: bool = True) -> List[dict]:
    q: dict = {}
    nm = (name or "").strip()
    if nm:
        pat = f"^{re.escape(nm)}$" if exact else re.escape(nm)
        q["name"] = {"$regex": pat, "$options": "i"}
    if department_id:
        q["department_id"] = department_id
    return await db.users.find(q).sort("name", 1).to_list(50)

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
        dd = await db.departments.find_one({"_id": ObjectId(department_id)})
        dept_name = dd["name"] if dd else None

    if user_id and ObjectId.is_valid(user_id):
        u = await db.users.find_one({"_id": ObjectId(user_id)})
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

@api_router.get("/users/lookup")
async def lookup_users(department_id: Optional[str] = None, q: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
    """Light employee picker for the Handover form: id, name, department only."""
    docs = await _users_in_dept_matching(q or "", department_id, exact=False)
    dept_names = {}
    out = []
    for u in docs:
        did = u.get("department_id")
        if did and did not in dept_names and ObjectId.is_valid(did):
            dd = await db.departments.find_one({"_id": ObjectId(did)})
            dept_names[did] = dd["name"] if dd else None
        out.append({"id": str(u["_id"]), "name": u["name"], "department_id": did,
                    "department_name": dept_names.get(did)})
    return out

async def _find_requisition_for_handover(employee_name: str, item_names: List[str], department_id: Optional[str] = None) -> Optional[dict]:
    """Best-effort match for the Handover Module's ad-hoc handover form: an open requisition
    (goods received via GRN, not yet issued) whose requester or `requisition_for` name
    matches AND shares at least one item name with what's being handed over. Only auto-links
    when the match is unambiguous (exactly one candidate) — on any doubt we leave
    requisition_id unset rather than risk linking to the wrong person's requisition.

    Without this, using the general Handover Module form for an item that actually came
    from a requisition (instead of the linked "Issue Stock" action in the Handover Queue)
    silently orphans that requisition: the handover itself proceeds through delivered ->
    confirmed just fine, but nothing ever tells the requisition to advance, so it stays
    stuck at "Stock Received in IT" forever even though the item was physically handed over
    and confirmed."""
    if not employee_name or not item_names:
        return None
    wanted = {n.strip().lower() for n in item_names if n and n.strip()}
    if not wanted:
        return None
    cand_q = {
        "status": READY_FOR_HANDOVER_STATUS,
        "$or": [
            {"requisitioner_name": {"$regex": f"^{re.escape(employee_name.strip())}$", "$options": "i"}},
            {"requisition_for": {"$regex": f"^{re.escape(employee_name.strip())}$", "$options": "i"}},
        ],
    }
    if department_id:
        cand_q["requisitioner_department_id"] = department_id
    candidates = await db.requisitions.find(cand_q).to_list(20)
    matches = [c for c in candidates
               if any(it.get("product_name", "").strip().lower() in wanted for it in c.get("items", []))]
    return matches[0] if len(matches) == 1 else None



def status_for_step(req_type: str, step: dict) -> str:
    if step.get("stage") == "admin_review":
        return "pending_admin"
    if step.get("stage") in ("pr_review", "stock_review"):
        # The new IT Head PR-review step (workflow Step 3) — distinguished by its explicit
        # "stage" marker rather than label/role, so it can never be confused with the
        # legacy base-chain "IT Head" step below.
        return "pending_it_review"
    role = step["role"]
    if role == "dept_head":
        if req_type == "service":
            return "pending_it_service"
        # first product step is dept, IT head is also dept_head but level 2
        return "pending_dept" if step["level"] == 1 else "pending_it"
    return {"accounts": "pending_accounts", "md": "pending_md", "purchase_head": "pending_purchase"}.get(role, "pending_dept")

def compute_status(req: dict) -> str:
    chain = req["approval_chain"]
    for s in chain:
        if s["status"] == "rejected":
            return "rejected"
    for s in chain:
        if s["status"] == "pending":
            return status_for_step(req["requisition_type"], s)
    # All chain steps approved.
    if req.get("po_flow"):
        # New PR/PO redesign path: IT Head has approved the PR review — next up is Purchase
        # Dept creating the CS/PO (a separate purchase_orders record, not more chain steps
        # on this requisition). NOT the same as the legacy "buy_process" meaning below.
        return "pending_po_entry"
    # Legacy PR pricing path (Accounts/MD/Purchase Dept Head appended dynamically by the
    # old build_pr_chain — still supported for any requisition that already has pr_flow set
    # without po_flow): full chain approval means goods still need to be procured and
    # handed over — not truly "approved" yet.
    return "buy_process" if req.get("pr_flow") else "approved"

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str

class ResetPasswordIn(BaseModel):
    new_password: Optional[str] = None     # leave empty to auto-generate a temporary password

class UserIn(BaseModel):
    name: str
    email: EmailStr
    password: Optional[str] = None
    department_id: Optional[str] = None
    role: str
    role_label: Optional[str] = None
    can_raise_pr: bool = False
    can_create_po: bool = False
    it_team: Optional[str] = None     # "Application" | "Network_Infra" | None  (IT department only)

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    department_id: Optional[str] = None
    role: Optional[str] = None
    role_label: Optional[str] = None
    can_raise_pr: Optional[bool] = None
    can_create_po: Optional[bool] = None
    it_team: Optional[str] = None     # send null explicitly to clear it (see update_user)

class UserPermissionsIn(BaseModel):
    can_raise_pr: Optional[bool] = None
    can_create_po: Optional[bool] = None

class DepartmentIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None

class CategoryIn(BaseModel):
    name: str
    department_id: Optional[str] = None
    description: Optional[str] = None

class RequisitionItemIn(BaseModel):
    product_type: Literal["asset", "consumable", "it_accessories", "network", "furniture"]
    product_name: str
    quantity: int = 1
    rate: float = 0
    remarks: Optional[str] = None
    category_id: Optional[str] = None
    # Service requisitions only (validated by normalize_service_items)
    priority: Optional[str] = None          # low | medium | high | critical
    request_type: Optional[str] = None      # service category key (see SERVICE_CATEGORIES); legacy keys still accepted
    request_detail: Optional[str] = None    # "Hardware & Physical Support": the device
    service_category: Optional[str] = None  # same as request_type; written back by the server on every line

class RequisitionIn(BaseModel):
    requisition_type: Literal["product", "service"]
    requisition_for: Optional[str] = None
    items: List[RequisitionItemIn]
    requester_note: Optional[str] = None
    attachment_path: Optional[str] = None
    attachment_file_id: Optional[str] = None
    attachment_name: Optional[str] = None
    requisition_date: Optional[str] = None

# ---- Service requisition options (the form's dropdowns) ---------------------------------
SERVICE_PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}

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
SERVICE_HARDWARE_DEVICES = ["Printer", "Scanner", "Desktop", "Laptop", "Monitor", "UPS", "Other"]
SERVICE_DEVICE_CATEGORIES = {"hardware_support"}     # categories that need a device picked

# Old request types (before sub-team routing) -> new category, so older clients / in-flight
# forms keep working. Old "software" is split by its action.
_LEGACY_CATEGORY = {"hardware": "hardware_support", "network": "network_connectivity", "others": "others"}
_LEGACY_SOFTWARE_ACTION = {"installation": "software_installation", "update": "software_update",
                           "troubleshooting": "others"}

def resolve_service_category(it: dict) -> Optional[str]:
    raw = (it.get("service_category") or it.get("request_type") or "").strip().lower()
    if raw in SERVICE_CATEGORIES:
        return raw
    for k, (label, _t) in SERVICE_CATEGORIES.items():       # the stored display label also works
        if raw == label.lower():
            return k
    if raw == "software":
        return _LEGACY_SOFTWARE_ACTION.get((it.get("request_detail") or "").strip().lower())
    return _LEGACY_CATEGORY.get(raw)

def service_team_for_items(items: List[dict]) -> str:
    """The ONE IT sub-team that owns a service requisition. A requisition whose lines belong to
    different teams is rejected so every ticket has exactly one shared queue and one owner."""
    teams = {SERVICE_CATEGORIES[it["service_category"]][1] for it in items}
    if len(teams) != 1:
        raise HTTPException(status_code=400, detail=(
            "This requisition mixes Application requests (ERP Software Access, Modify Access, "
            "New Entry / Edit Requests) with Network & Infra requests. Please raise them as "
            "two separate service requisitions."))
    return teams.pop()

def normalize_service_items(items: List[dict]) -> None:
    """Validates + normalises every line of a SERVICE requisition in place, so the API enforces
    the same rules as the form: priority and category are required, Hardware & Physical Support
    needs a device, and 'Others' / device 'Other' need a description in Remarks. Each line gets
    `service_category` (the key that drives sub-team routing). The line's name is built from the
    choices (e.g. 'Hardware & Physical Support - Printer') so lists and approvers read well."""
    for n, it in enumerate(items, 1):
        prio = (it.get("priority") or "").strip().lower()
        cat = resolve_service_category(it)
        detail = " ".join((it.get("request_detail") or "").split())
        if prio not in SERVICE_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"Item {n}: select a priority level")
        if not cat:
            raise HTTPException(status_code=400, detail=f"Item {n}: select a service category")
        if cat in SERVICE_DEVICE_CATEGORIES:
            match = next((o for o in SERVICE_HARDWARE_DEVICES if o.lower() == detail.lower()), None)
            if not match:
                raise HTTPException(status_code=400, detail=f"Item {n}: select the device")
            detail = match
        else:
            detail = ""
        if (cat == "others" or detail == "Other") and not (it.get("remarks") or "").strip():
            raise HTTPException(status_code=400, detail=f"Item {n}: describe the request in Remarks")
        label = SERVICE_CATEGORIES[cat][0]
        it.update({"priority": prio, "service_category": cat,
                   # lower-case label: old list screens print request_type as-is with CSS capitalize
                   "request_type": label.lower(),
                   "request_detail": detail or None,
                   "product_name": f"{label} - {detail}" if detail else label,
                   "category": "Service", "quantity": 1, "rate": 0})

class ApproveIn(BaseModel):
    action: Literal["approve", "reject", "revise"]
    note: Optional[str] = None

class ResubmitIn(BaseModel):
    # All optional: only the fields the requester actually edited need to be sent. Omitted
    # fields (None) keep their current value — see resubmit_requisition.
    items: Optional[List[RequisitionItemIn]] = None
    requester_note: Optional[str] = None
    attachment_file_id: Optional[str] = None
    attachment_name: Optional[str] = None
    requisition_for: Optional[str] = None
    requisition_date: Optional[str] = None
    note: Optional[str] = None  # optional note to the approver about what changed

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@api_router.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = create_access_token(str(user["_id"]), email)
    refresh = create_refresh_token(str(user["_id"]))
    set_auth_cookies(response, access, refresh)
    # Enrich the same way /auth/me does so department_name and role_label_display
    # are available immediately after login (no page refresh required).
    data = clean_user(user)
    dept = None
    if user.get("department_id"):
        d = await db.departments.find_one({"_id": ObjectId(user["department_id"])}) if ObjectId.is_valid(user["department_id"]) else None
        dept = d["name"] if d else None
    data["department_name"] = dept
    data["role_label_display"] = user.get("role_label") or ROLE_LABELS.get(user.get("role"), user.get("role"))
    return {"user": data, "access_token": access}
@api_router.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}

MIN_PASSWORD_LENGTH = 8

@api_router.post("/auth/change-password")
async def change_password(payload: ChangePasswordIn, user: dict = Depends(get_current_user)):
    """Self-service password change for ANY logged-in user. Super Admin sets the initial
    password when creating the account; from then on the user can keep it or replace it
    here at any time. The current password must be re-entered so a borrowed / unattended
    session can't be used to lock the real owner out. (Super Admin can still reset someone
    else's password from Users & Roles — PUT /users/{id}.)"""
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_pw = payload.new_password
    if len(new_pw) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters")
    if new_pw == payload.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current password")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {
        "password_hash": hash_password(new_pw), "password_changed_at": now_iso(),
        "must_change_password": False}})
    return {"ok": True}

@api_router.get("/auth/me")
async def me(response: Response, user: dict = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    data = clean_user(user)
    dept = None
    if user.get("department_id"):
        d = await db.departments.find_one({"_id": ObjectId(user["department_id"])}) if ObjectId.is_valid(user["department_id"]) else None
        dept = d["name"] if d else None
    data["department_name"] = dept
    data["role_label_display"] = user.get("role_label") or ROLE_LABELS.get(user.get("role"), user.get("role"))
    return data

@api_router.get("/auth/permissions")
async def my_permissions(response: Response, user: dict = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    perm = await db.sidebar_permissions.find_one({"role": user["role"]})
    if perm:
        # An explicit admin-customized permission set (via Approver Management) always wins.
        allowed = list(perm["items"])
    elif user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")):
        # Purchase Dept Head: base purchase_head menu + PO Approvals / Create PO
        allowed = list(DEFAULT_PERMISSIONS.get("purchase_head", []))
        for extra in ("po-approvals", "create-po"):
            if extra not in allowed:
                allowed.append(extra)
    elif user["role"] == "dept_head" and await _department_is_admin(user.get("department_id")):
        # Admin Head: base dept-head menu + what they need to restock and hand over
        # consumables / furniture (Stock GRN, Stock List, Handover Queue, Handover module).
        allowed = list(NON_IT_DEPT_HEAD_PERMISSIONS) + [
            "stock-list", "stock-grn", "handover-queue", "handover-module", "handover-records"]
    elif user["role"] == "dept_head" and not await _department_is_it(user.get("department_id")):
        allowed = list(NON_IT_DEPT_HEAD_PERMISSIONS)
    else:
        allowed = list(DEFAULT_PERMISSIONS.get(user["role"], []))

    # PR / PO queue menu items are driven by per-user flags (not role defaults):
    #   can_raise_pr  -> "File Purchase Requisition"
    #   can_create_po -> "File Purchase Order"
    is_it_head = user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))
    is_purchase_head = user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id"))
    can_raise = bool(user.get("can_raise_pr")) or user["role"] == "super_admin" or is_it_head
    can_create = bool(user.get("can_create_po")) or user["role"] == "super_admin" or is_purchase_head or user["role"] == "purchase_head"
    if can_raise and "file-purchase-requisition" not in allowed:
        allowed.append("file-purchase-requisition")
    if can_create and "file-purchase-order" not in allowed:
        allowed.append("file-purchase-order")
    if not can_raise and "file-purchase-requisition" in allowed and user["role"] != "super_admin":
        allowed = [k for k in allowed if k != "file-purchase-requisition"]
    if not can_create and "file-purchase-order" in allowed and user["role"] != "super_admin":
        allowed = [k for k in allowed if k != "file-purchase-order"]

    # PR raiser -> Handover (module + records) and Stock GRN. Driven by the same per-user flag,
    # so it follows the flag whenever the PR raiser is changed. This only ADDS menu items;
    # access a user already has through their role is left untouched.
    if has_pr_raise_flag(user):
        for key in PR_RAISER_MENU_KEYS:
            if key not in allowed:
                allowed.append(key)

    # IT service ticket queue: derived from the IT sub-team (it_team) / IT Head / Super Admin, same
    # idea as the PR-raiser block above. Only ADDS a menu item.
    if await it_queue_teams_for(user) and "it-service-queue" not in allowed:
        allowed.append("it-service-queue")

    # Audit Search: IT Head and Super Admin only (also enforced on the audit endpoints).
    if user["role"] == "super_admin" or is_it_head:
        if "audit-search" not in allowed:
            allowed.append("audit-search")
    else:
        allowed = [k for k in allowed if k != "audit-search"]

    # Approvers must always be able to reach the PO Approvals screen. A saved sidebar
    # override (Approver Management) that predates PO Approvals would otherwise hide it and
    # leave POs stuck "Pending MD / Accounts / Purchase Head" with nobody able to open them.
    if (user["role"] in ("md", "accounts", "purchase_head") or is_purchase_head) and "po-approvals" not in allowed:
        allowed.append("po-approvals")

    if user["role"] == "super_admin" and "products" not in allowed:
        allowed.append("products")      # new menu item; saved overrides predate it

    # Bulk Import: Super Admin only (also enforced on the /import endpoints).
    if user["role"] == "super_admin":
        if "bulk-import" not in allowed:
            allowed.append("bulk-import")
    else:
        allowed = [k for k in allowed if k != "bulk-import"]

    # Leave delegation: someone approving on behalf of a colleague needs the same approval
    # screens as that colleague (an Executive, for example, has no "Approve Requisition" menu
    # by default). Granted only while a delegation to this user is active.
    delegators = await active_delegators_of(user)
    delegated_only = {}      # menu key -> label, for items this user has ONLY because of a delegation
    if delegators:
        if "approve-requisition" not in allowed:
            allowed.append("approve-requisition")
            delegated_only["approve-requisition"] = "Delegated Approvals"
        for dg in await db.users.find({"_id": {"$in": [ObjectId(x) for x in delegators]}}).to_list(50):
            dg_purchase_head = dg["role"] == "dept_head" and await _department_is_purchase(dg.get("department_id"))
            if (dg["role"] in ("md", "accounts", "purchase_head") or dg_purchase_head) and "po-approvals" not in allowed:
                allowed.append("po-approvals")
                delegated_only["po-approvals"] = "Delegated PO Approvals"

    menu = []
    for g in MENU:
        items = [{**it, "label": delegated_only.get(it["key"], it["label"])} if it["key"] in delegated_only else it
                 for it in g["items"] if it["key"] in allowed]
        if items:
            menu.append({**g, "items": items})
    return {"allowed": allowed, "menu": menu}

# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
@api_router.get("/meta/roles")
async def meta_roles(user: dict = Depends(get_current_user)):
    return {"roles": [{"value": r, "label": ROLE_LABELS[r]} for r in ROLES]}

@api_router.get("/meta/menu")
async def meta_menu(user: dict = Depends(get_current_user)):
    return {"menu": MENU, "keys": ALL_MENU_KEYS}

# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
@api_router.get("/departments")
async def list_departments(user: dict = Depends(get_current_user)):
    docs = await db.departments.find().sort("name", 1).to_list(500)
    return [{"id": str(d["_id"]), "name": d["name"], "code": d.get("code"), "description": d.get("description")} for d in docs]

@api_router.post("/departments")
async def create_department(payload: DepartmentIn, user: dict = Depends(require_roles("super_admin"))):
    doc = payload.model_dump()
    doc["created_at"] = now_iso()
    res = await db.departments.insert_one(doc)
    return {"id": str(res.inserted_id), **payload.model_dump()}

@api_router.put("/departments/{dept_id}")
async def update_department(dept_id: str, payload: DepartmentIn, user: dict = Depends(require_roles("super_admin"))):
    await db.departments.update_one({"_id": ObjectId(dept_id)}, {"$set": payload.model_dump()})
    return {"id": dept_id, **payload.model_dump()}

@api_router.delete("/departments/{dept_id}")
async def delete_department(dept_id: str, user: dict = Depends(require_roles("super_admin"))):
    await db.departments.delete_one({"_id": ObjectId(dept_id)})
    return {"ok": True}

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@api_router.get("/categories")
async def list_categories(user: dict = Depends(get_current_user)):
    docs = await db.categories.find().sort("name", 1).to_list(500)
    out = []
    for c in docs:
        dept_name = None
        if c.get("department_id") and ObjectId.is_valid(c["department_id"]):
            d = await db.departments.find_one({"_id": ObjectId(c["department_id"])})
            dept_name = d["name"] if d else None
        out.append({"id": str(c["_id"]), "name": c["name"], "department_id": c.get("department_id"),
                    "department_name": dept_name, "description": c.get("description")})
    return out

@api_router.post("/categories")
async def create_category(payload: CategoryIn, user: dict = Depends(require_roles("super_admin"))):
    doc = payload.model_dump()
    doc["created_at"] = now_iso()
    res = await db.categories.insert_one(doc)
    return {"id": str(res.inserted_id), **payload.model_dump()}

@api_router.put("/categories/{cat_id}")
async def update_category(cat_id: str, payload: CategoryIn, user: dict = Depends(require_roles("super_admin"))):
    await db.categories.update_one({"_id": ObjectId(cat_id)}, {"$set": payload.model_dump()})
    return {"id": cat_id, **payload.model_dump()}

@api_router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, user: dict = Depends(require_roles("super_admin"))):
    await db.categories.delete_one({"_id": ObjectId(cat_id)})
    return {"ok": True}

# ---------------------------------------------------------------------------
# Product catalog — the single list of valid product names.
# Requisitions, GRN (stock), PR and PO all use these exact names, so "Laptop" / "laptop" /
# "LAPTOP " can never end up as different items again.
# ---------------------------------------------------------------------------
PRODUCT_TYPES = ("asset", "consumable", "it_accessories", "network", "furniture")
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
        c = await db.categories.find_one({"_id": ObjectId(category_id)})
        return c["name"] if c else None
    return None

class ProductIn(BaseModel):
    name: str
    product_type: Literal["asset", "consumable", "it_accessories", "network", "furniture"]
    brand: Optional[str] = None      # optional default brand (pre-fills the Handover / GRN forms)

def _pkey(name: str) -> str:
    return " ".join((name or "").split()).lower()

def _skey(name: Optional[str]) -> str:
    """Key for matching an asset's name to a catalog product. Same rule as _stock_name_query():
    case-insensitive, ignoring leading / trailing spaces."""
    return (name or "").strip().lower()

def _clean_brand(v: Optional[str]) -> Optional[str]:
    return " ".join((v or "").split()) or None

def _tracked_by_quantity(prod: dict) -> bool:
    """Consumables are received and issued by quantity - there is no serial / tag per unit to
    pick. Every other product type is tracked unit-by-unit."""
    return prod.get("product_type") == "consumable"

def _available_stock_query(name: str) -> dict:
    """Units that can be issued right now: in stock and not reserved by another slip. This is the
    same definition has_sufficient_stock() and prepare_handover_items() use."""
    return {"name": _stock_name_query(name), "status": "in_stock", "pending_receipt": {"$ne": True}}

async def _available_counts() -> Dict[str, int]:
    """Available units for EVERY product in one pass, keyed by _skey(asset name)."""
    rows = await db.assets.aggregate([
        {"$match": {"status": "in_stock", "pending_receipt": {"$ne": True}}},
        {"$group": {"_id": "$name", "n": {"$sum": 1}}},
    ]).to_list(None)
    out: Dict[str, int] = {}
    for r in rows:
        k = _skey(r["_id"])
        out[k] = out.get(k, 0) + r["n"]
    return out

def _product_out(d: dict, in_stock: int) -> dict:
    """The one product shape every screen relies on (Products, Stock GRN, Handover, forms)."""
    ptype = d.get("product_type")
    return {
        "id": str(d["_id"]), "name": d["name"], "product_type": ptype,
        "category_name": PRODUCT_TYPE_LABELS.get(ptype, "Other"),
        "brand": d.get("brand") or None,
        "tracked_by_quantity": _tracked_by_quantity(d),
        "in_stock": in_stock,
    }

async def _can_manage_products(user: dict) -> bool:
    if user["role"] == "super_admin":
        return True
    return user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))

@api_router.get("/products")
async def list_products(product_type: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"product_type": product_type} if product_type else {}
    docs = await db.products.find(q).sort("name_key", 1).to_list(5000)
    counts = await _available_counts()
    return [_product_out(d, counts.get(_skey(d["name"]), 0)) for d in docs]

@api_router.get("/products/{pid}/units")
async def product_units(pid: str, user: dict = Depends(get_current_user)):
    """The individual units of one product that can be issued right now (in stock, not reserved
    by another slip) - drives the unit picker on the Handover form. Oldest stock first.
    Quantity-tracked products (consumables) have no units to pick: only the count is returned."""
    if not ObjectId.is_valid(pid):
        raise HTTPException(status_code=404, detail="Product not found")
    prod = await db.products.find_one({"_id": ObjectId(pid)})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    q = _available_stock_query(prod["name"])
    by_qty = _tracked_by_quantity(prod)
    in_stock = await db.assets.count_documents(q)
    units: List[dict] = []
    if not by_qty:
        docs = await db.assets.find(q).sort([("created_at", 1), ("_id", 1)]).to_list(5000)
        units = [{"id": str(a["_id"]), "name": a.get("name"), "tag_id": a.get("tag_id"),
                  "serial_no": a.get("serial_no"), "brand": a.get("brand") or None} for a in docs]
    return {"product_id": pid, "name": prod["name"], "tracked_by_quantity": by_qty,
            "in_stock": in_stock, "units": units}

@api_router.post("/products")
async def create_product(payload: ProductIn, user: dict = Depends(get_current_user)):
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Product name is required")
    if await db.products.find_one({"name_key": _pkey(name)}):
        raise HTTPException(status_code=400, detail=f"'{name}' already exists in the catalog")
    doc = {"name": name, "name_key": _pkey(name), "product_type": payload.product_type,
           "brand": _clean_brand(payload.brand),
           "created_by": user["name"], "created_at": now_iso()}
    res = await db.products.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _product_out(doc, await db.assets.count_documents(_available_stock_query(name)))

class ProductBulkIn(BaseModel):
    product_type: Literal["asset", "consumable", "it_accessories", "network", "furniture"]
    names: List[str]

@api_router.post("/products/bulk")
async def bulk_create_products(payload: ProductBulkIn, user: dict = Depends(get_current_user)):
    """Add many products of one type at once (one name per entry). Duplicates - including
    case/space variants of existing names - are skipped, not errors."""
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    added, skipped, seen = [], [], set()
    for raw in payload.names:
        name = " ".join((raw or "").split())
        if not name:
            continue
        key = _pkey(name)
        if key in seen or await db.products.find_one({"name_key": key}):
            skipped.append(name)
            continue
        seen.add(key)
        await db.products.insert_one({"name": name, "name_key": key, "product_type": payload.product_type,
                                      "created_by": user["name"], "created_at": now_iso()})
        added.append(name)
    return {"added": len(added), "skipped": len(skipped), "skipped_names": skipped}

@api_router.put("/products/{pid}")
async def update_product(pid: str, payload: ProductIn, user: dict = Depends(get_current_user)):
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    if not ObjectId.is_valid(pid) or not await db.products.find_one({"_id": ObjectId(pid)}):
        raise HTTPException(status_code=404, detail="Product not found")
    name = " ".join(payload.name.split())
    clash = await db.products.find_one({"name_key": _pkey(name), "_id": {"$ne": ObjectId(pid)}})
    if not name or clash:
        raise HTTPException(status_code=400, detail=f"'{name}' already exists in the catalog" if clash else "Product name is required")
    upd = {"name": name, "name_key": _pkey(name), "product_type": payload.product_type}
    if payload.brand is not None:          # omitted -> keep the current brand; "" -> clear it
        upd["brand"] = _clean_brand(payload.brand)
    await db.products.update_one({"_id": ObjectId(pid)}, {"$set": upd})
    fresh = await db.products.find_one({"_id": ObjectId(pid)})
    return _product_out(fresh, await db.assets.count_documents(_available_stock_query(name)))

@api_router.delete("/products/{pid}")
async def delete_product(pid: str, user: dict = Depends(get_current_user)):
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    if ObjectId.is_valid(pid):
        await db.products.delete_one({"_id": ObjectId(pid)})
    return {"ok": True}

async def canonicalize_product_names(items: List[dict], strict_type: bool = True):
    """Replace each item's product_name with the catalog's exact spelling (case/space
    insensitive lookup). Unknown names are rejected so free-typed variants can't creep in."""
    for it in items:
        doc = await db.products.find_one({"name_key": _pkey(it.get("product_name"))})
        if not doc:
            raise HTTPException(status_code=400, detail=(
                f"'{(it.get('product_name') or '').strip()}' is not in the product catalog. "
                "Pick a product from the list, or ask IT to add it under Organization → Products."))
        it["product_name"] = doc["name"]
        if strict_type and "product_type" in it:
            it["product_type"] = doc["product_type"]

async def seed_products_if_empty():
    """One-time: build the catalog from names already used by requisitions and stock, so
    nothing existing is left un-pickable. Case variants collapse to one entry."""
    if await db.products.count_documents({}) > 0:
        return
    seen: dict = {}
    async for r in db.requisitions.find({"requisition_type": "product"}, {"items": 1}):
        for it in r.get("items", []):
            k = _pkey(it.get("product_name"))
            if k and k not in seen and it.get("product_type") in PRODUCT_TYPES:
                seen[k] = (" ".join(it["product_name"].split()), it["product_type"])
    async for a in db.assets.find({}, {"name": 1}):
        k = _pkey(a.get("name"))
        if k and k not in seen:
            seen[k] = (" ".join(a["name"].split()), "asset")
    for k, (name, ptype) in seen.items():
        await db.products.insert_one({"name": name, "name_key": k, "product_type": ptype,
                                      "created_by": "system", "created_at": now_iso()})

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
async def enrich_user(u: dict) -> dict:
    data = clean_user(u)
    dept_name = None
    if u.get("department_id") and ObjectId.is_valid(u["department_id"]):
        d = await db.departments.find_one({"_id": ObjectId(u["department_id"])})
        dept_name = d["name"] if d else None
    data["department_name"] = dept_name
    data["role_label_display"] = u.get("role_label") or ROLE_LABELS.get(u.get("role"), u.get("role"))
    data.setdefault("it_team", None)
    return data

@api_router.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    docs = await db.users.find().sort("name", 1).to_list(1000)
    return [await enrich_user(u) for u in docs]

@api_router.post("/users")
async def create_user(payload: UserIn, user: dict = Depends(require_roles("super_admin"))):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if payload.can_raise_pr and not await _department_is_it(payload.department_id):
        raise HTTPException(status_code=400, detail="Can Raise PR is only available for users in the IT department")
    if payload.can_create_po and not await _department_is_purchase(payload.department_id):
        raise HTTPException(status_code=400, detail="Can Create PO is only available for users in the Purchase department")
    it_team = await validate_it_team(payload.it_team, payload.department_id)
    doc = {
        "name": payload.name,
        "email": email,
        "password_hash": hash_password(payload.password or os.environ.get("SEED_USER_PASSWORD", "password123")),
        "department_id": payload.department_id,
        "role": payload.role,
        "role_label": payload.role_label or ROLE_LABELS.get(payload.role),
        "can_raise_pr": payload.can_raise_pr,
        "can_create_po": payload.can_create_po,
        "it_team": it_team,
        "created_at": now_iso(),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return await enrich_user(doc)

TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"   # no look-alike characters

def generate_temp_password(length: int = 10) -> str:
    return "".join(secrets.choice(TEMP_PW_ALPHABET) for _ in range(length))

@api_router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, response: Response, payload: Optional[ResetPasswordIn] = Body(default=None),
                              user: dict = Depends(require_roles("super_admin"))):
    """Forgot-password recovery (admin-assisted). Super Admin / IT Head sets a temporary password
    for a user who cannot sign in. The user is signed out everywhere and MUST choose their own
    password at next login. The temporary password is returned once and never stored in plain text."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if str(target["_id"]) == str(user["_id"]):
        raise HTTPException(status_code=400, detail="Use Change Password for your own account")
    temp = (payload.new_password if payload and payload.new_password else None) or generate_temp_password()
    if len(temp) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    await db.users.update_one({"_id": target["_id"]}, {"$set": {
        "password_hash": hash_password(temp), "password_changed_at": now_iso(),
        "must_change_password": True,
        "sessions_valid_from": int(datetime.now(timezone.utc).timestamp())}})
    await db.password_resets.insert_one({
        "user_id": str(target["_id"]), "user_email": target.get("email"),
        "reset_by": str(user["_id"]), "reset_by_name": user.get("name"), "at": now_iso()})
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "temporary_password": temp, "must_change_password": True}

@api_router.put("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, user: dict = Depends(require_roles("super_admin"))):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "email" in updates:
        updates["email"] = updates["email"].lower()
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
        # A password set by an admin for someone else is temporary: force a change at next login.
        if user_id != str(user["_id"]):
            updates["must_change_password"] = True
            updates["password_changed_at"] = now_iso()
            updates["sessions_valid_from"] = int(datetime.now(timezone.utc).timestamp())
    if "role" in updates and updates["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    # it_team: only touched when the client actually sent the field (so an explicit null clears
    # it). A value needs an IT-department user; moving someone out of IT clears the tag.
    updates.pop("it_team", None)
    if "it_team" in payload.model_fields_set or "department_id" in updates:
        existing_u = await db.users.find_one({"_id": ObjectId(user_id)})
        if not existing_u:
            raise HTTPException(status_code=404, detail="User not found")
        dept_for_team = updates.get("department_id", existing_u.get("department_id"))
        if "it_team" in payload.model_fields_set:
            updates["it_team"] = await validate_it_team(payload.it_team, dept_for_team)
        elif existing_u.get("it_team") and not await _department_is_it(dept_for_team):
            updates["it_team"] = None
    if updates.get("can_raise_pr") or updates.get("can_create_po"):
        existing = await db.users.find_one({"_id": ObjectId(user_id)})
        dept_id = updates.get("department_id", (existing or {}).get("department_id"))
        if updates.get("can_raise_pr") and not await _department_is_it(dept_id):
            raise HTTPException(status_code=400, detail="Can Raise PR is only available for users in the IT department")
        if updates.get("can_create_po") and not await _department_is_purchase(dept_id):
            raise HTTPException(status_code=400, detail="Can Create PO is only available for users in the Purchase department")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    u = await db.users.find_one({"_id": ObjectId(user_id)})
    return await enrich_user(u)

@api_router.put("/users/{user_id}/permissions")
async def update_user_permissions(user_id: str, payload: UserPermissionsIn, user: dict = Depends(get_current_user)):
    """Narrower, department-scoped alternative to PUT /users/{id} (Super Admin only). Lets a
    Department Head toggle just the ONE permission flag that belongs to their own
    department, for members of that same department only:
      - IT Dept Head            -> can_raise_pr,  IT Department members only.
      - Purchase Dept Head      -> can_create_po, Purchase Department members only.
    Super Admin can toggle BOTH flags for ANY user in ANY department (same authority as
    PUT /users/{id} already has — this endpoint doesn't add anything new for Super Admin,
    it's purely an additional, more limited path for a Department Head)."""
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    updates = {}
    if payload.can_raise_pr is not None:
        is_it_head = user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))
        same_dept = target.get("department_id") == user.get("department_id")
        if not (user["role"] == "super_admin" or (is_it_head and same_dept)):
            raise HTTPException(status_code=403,
                                detail="Only Super Admin or the IT Department Head can toggle Can Raise PR, and only for IT Department members")
        if payload.can_raise_pr and not await _department_is_it(target.get("department_id")):
            raise HTTPException(status_code=400, detail="Can Raise PR is only available for users in the IT department")
        updates["can_raise_pr"] = payload.can_raise_pr

    if payload.can_create_po is not None:
        is_purchase_head = user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id"))
        same_dept = target.get("department_id") == user.get("department_id")
        if not (user["role"] == "super_admin" or (is_purchase_head and same_dept)):
            raise HTTPException(status_code=403,
                                detail="Only Super Admin or the Purchase Department Head can toggle Can Create PO, and only for Purchase Department members")
        if payload.can_create_po and not await _department_is_purchase(target.get("department_id")):
            raise HTTPException(status_code=400, detail="Can Create PO is only available for users in the Purchase department")
        updates["can_create_po"] = payload.can_create_po

    if not updates:
        raise HTTPException(status_code=400, detail="No permission flags provided")

    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    u = await db.users.find_one({"_id": ObjectId(user_id)})
    return await enrich_user(u)

@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_roles("super_admin"))):
    if str(user["_id"]) == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    await db.users.delete_one({"_id": ObjectId(user_id)})
    return {"ok": True}

# ---------------------------------------------------------------------------
# Sidebar permissions management
# ---------------------------------------------------------------------------
@api_router.get("/permissions")
async def list_permissions(user: dict = Depends(require_roles("super_admin"))):
    out = []
    for r in ROLES:
        perm = await db.sidebar_permissions.find_one({"role": r})
        out.append({"role": r, "label": ROLE_LABELS[r], "items": perm["items"] if perm else DEFAULT_PERMISSIONS.get(r, [])})
    return out

@api_router.put("/permissions/{role}")
async def update_permissions(role: str, body: dict, user: dict = Depends(require_roles("super_admin"))):
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    items = [k for k in body.get("items", []) if k in ALL_MENU_KEYS]
    await db.sidebar_permissions.update_one({"role": role}, {"$set": {"items": items}}, upsert=True)
    return {"role": role, "items": items}

# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------
@api_router.post("/requisitions/preview-chain")
async def preview_chain(payload: dict, user: dict = Depends(get_current_user)):
    req_type = payload.get("requisition_type", "product")
    if req_type == "service":
        # Standard service tasks skip IT Head approval and go straight to a sub-team queue.
        return {"chain": [await service_queue_bypass_step()]}
    # Product types come from the catalog (never trusted from the client).
    prev_items = []
    for it in payload.get("items") or []:
        p = await db.products.find_one({"name_key": _pkey(it.get("product_name"))})
        if p:
            prev_items.append({"product_name": p["name"], "product_type": p["product_type"]})
    chain = await build_approval_chain(req_type, user, prev_items)
    apply_dept_head_smart_bypass(chain, user)
    apply_admin_head_smart_bypass(chain, user)
    await apply_it_employee_base_bypass(chain, user)
    await apply_accounts_purchase_executive_bypass(chain, user, req_type)
    return {"chain": chain}

@api_router.post("/requisitions")
async def create_requisition(payload: RequisitionIn, user: dict = Depends(get_current_user)):
    # Standard product/service requisitions are open to all active/authenticated users.
    # `can_raise_pr` only gates the downstream Purchase Requisition (see requisition_pdf below);
    # it must NOT block regular requisition submission.
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    items = [it.model_dump() for it in payload.items]
    if payload.requisition_type == "product":
        await canonicalize_product_names(items)
    else:
        normalize_service_items(items)
    for it in items:
        it["line_total"] = round(it["quantity"] * it["rate"], 2)
    total_amount = round(sum(it["line_total"] for it in items), 2)

    # Decision #1 ("Stock Checking & In-Stock Path"): stock is checked immediately upon
    # submission. This is informational/preparatory only — the AUTHORITATIVE decision is
    # made below, once the base chain (a single Dept Head level) is actually fully
    # approved. Normally that happens later via an explicit approval action
    # (act_on_requisition's base_chain_just_completed) — but the Smart Bypass can also
    # complete that single-step chain immediately, right here at creation, so this same
    # branch has to be checked in both places.
    stock_check_at_submission = None
    if payload.requisition_type == "product":
        stock_check_at_submission = "in_stock" if await has_sufficient_stock(items) else "out_of_stock"

    chain = await build_approval_chain(payload.requisition_type, user, items)
    smart_bypassed = apply_dept_head_smart_bypass(chain, user) or apply_admin_head_smart_bypass(chain, user)
    it_employee_bypassed = await apply_it_employee_base_bypass(chain, user)
    acc_pur_bypassed = await apply_accounts_purchase_executive_bypass(chain, user, payload.requisition_type)
    req_no = await next_req_number()

    history = [{"at": now_iso(), "by": user["name"], "action": "created", "note": None}]
    if stock_check_at_submission:
        history.append({"at": now_iso(), "by": "system", "action": "stock_check",
                        "note": f"Stock check at submission: {stock_check_at_submission.replace('_', ' ')}."})
    if smart_bypassed:
        history.append({"at": now_iso(), "by": "system", "action": "smart_bypass",
                        "note": "Department Head step auto-approved: requester is the Department Head."})
    if it_employee_bypassed:
        history.append({"at": now_iso(), "by": "system", "action": "it_employee_bypass",
                        "note": "Department Head step auto-approved: requester is from IT — IT Head reviews once at PR stage if needed."})

    if acc_pur_bypassed:
        history.append({"at": now_iso(), "by": "system", "action": "accounts_purchase_bypass",
                        "note": "Department Head step auto-approved: requester is an executive of the "
                                "Accounts/Purchase department (own Dept Head approval bypassed)."})

    doc = {
        "requisition_no": req_no,
        "requisitioner_id": str(user["_id"]),
        "requisitioner_name": user["name"],
        "requisitioner_department_id": user.get("department_id"),
        "requisition_for": payload.requisition_for or user["name"],
        "requisition_type": payload.requisition_type,
        "items": items,
        "total_amount": total_amount,
        "pr_flow": False,  # set True once this requisition goes down the out-of-stock PR path
        "po_flow": False,  # set True once the PR is filed under the new PR/PO redesign (set_pr_pricing)
        "stock_check_at_submission": stock_check_at_submission,
        "requester_note": payload.requester_note,
        "attachment_path": payload.attachment_path,
        "attachment_file_id": payload.attachment_file_id,
        "attachment_name": payload.attachment_name,
        "requisition_date": payload.requisition_date or now_iso(),
        "approval_chain": chain,
        "status": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "history": history,
    }
    doc["status"] = compute_status(doc)
    if payload.requisition_type == "service":
        await route_service_requisition(doc)      # sets it_team, bypass step, queue status
    res = await db.requisitions.insert_one(doc)
    doc["_id"] = res.inserted_id
    if payload.requisition_type == "service":
        await notify_service_queue(doc)

    # Smart Bypass edge case: for a product requisition whose base chain is now a single
    # Dept Head level (see build_approval_chain), a self-approving Dept Head's bypass alone
    # fully approves that entire chain right here — in which case the stock-check branch
    # that normally only fires from an explicit approval action needs to fire immediately
    # too, or the requisition would silently sit at "approved" without ever being issued,
    # handed over, or routed into the out-of-stock PR path. Mirrors
    # act_on_requisition's base_chain_just_completed exactly (same has_sufficient_stock
    # check, same auto_generate_handover call, same "pending_pr" fallback).
    if payload.requisition_type == "product" and chain and all(s["status"] == "approved" for s in chain):
        extra = await route_after_base_chain(doc, str(user["_id"]))
        doc["approval_chain"] = extra.pop("approval_chain")
        await db.requisitions.update_one({"_id": doc["_id"]}, {"$set": {
            "status": doc["status"], "approval_chain": doc["approval_chain"], **extra}})

    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc

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
        async for rec in db.files.find({"id": {"$in": list(ids)}, "is_deleted": False}):
            names[rec["id"]] = rec.get("original_filename")
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
        async for d in db.departments.find({"_id": {"$in": oids}}):
            names[str(d["_id"])] = d.get("name")
    for o in outs:
        o["requisitioner_department_name"] = names.get(o.get("requisitioner_department_id"))
    return outs

def req_visibility_scope(user: dict) -> tuple[dict, str]:
    """Three-tier data-visibility rule for requisitions/dashboard data:
    - executive (no approval/admin authority): own requisitions only ("personal").
    - dept_head / accounts / purchase_head: their own department's requisitions — their
      own plus their team's ("department"). These roles have approval authority over their
      department but are not company-wide admins.
    - super_admin / md ("System Admins and Top Management"): company-wide ("global").
    Returns (mongo_filter, scope_label)."""
    role = user["role"]
    if role in ("super_admin", "md"):
        return {}, "global"
    if role == "executive":
        return {"requisitioner_id": str(user["_id"])}, "personal"
    dept_id = user.get("department_id")
    if not dept_id:
        # No department on record — fail closed to personal-only rather than leaking
        # everyone's data through an unscoped filter.
        return {"requisitioner_id": str(user["_id"])}, "personal"
    return {"requisitioner_department_id": dept_id}, "department"

async def recheck_pending_pr_against_stock():
    """A requisition parked at 'pending_pr' (no PR filed yet) whose items are now in stock
    (e.g. stock was received after it was raised, or the old case-sensitive match missed it)
    goes to IT Head stock approval instead of a purchase."""
    docs = await db.requisitions.find({"status": "pending_pr", "requisition_type": "product",
                                       "purchase_pr_no": {"$in": [None, ""]}}).to_list(200)
    for d in docs:
        if await has_sufficient_stock(d["items"]):
            d["history"].append({"at": now_iso(), "by": "system", "action": "stock_available",
                                 "note": "Stock is now available - routed to IT Head stock approval instead of purchase."})
            d["pr_flow"] = False
            extra = await route_after_base_chain(d, None)
            extra["pr_flow"] = d.get("pr_flow", False)
            await db.requisitions.update_one({"_id": d["_id"]}, {"$set": {
                "status": d["status"], "history": d["history"], "updated_at": now_iso(), **extra}})

@api_router.get("/requisitions")
async def list_requisitions(scope: str = "all", status: Optional[str] = None, user: dict = Depends(get_current_user)):
    # "all"/"history" use the 3-tier visibility rule: personal (executive), department
    # (dept_head/accounts/purchase_head — their own department's requisitions), or global
    # (super_admin/md — company-wide). See req_visibility_scope().
    query, _vis = req_visibility_scope(user)
    if scope in ("purchase", "pending_pr", "approve"):
        await recheck_pending_pr_against_stock()
    if scope == "mine":
        query = {"requisitioner_id": str(user["_id"])}
    elif scope == "pending":
        query = {"requisitioner_id": str(user["_id"]), "status": {"$nin": FINALIZED}}
    elif scope == "approve":
        # requisitions where current pending step is assigned to this user
        docs = await db.requisitions.find({"status": {"$nin": FINALIZED}}).sort("created_at", -1).to_list(1000)
        delegators = await active_delegators_of(user)
        out = []
        for d in docs:
            chain = d["approval_chain"]
            current = next((s for s in chain if s["status"] == "pending"), None)
            if current and is_current_approver(current, user, delegators):
                out.append(serialize_req(d))
        return await attach_department_names(await attach_file_info(out))
    elif scope == "history":
        # Optional ?status= narrows this down to exactly what a dashboard stat card
        # represents — e.g. the Approval Total / Rejection Total cards on the department
        # dashboard link straight to the matching filtered list.
        if status == "approved":
            # Matches dashboard_stats' "approved" count, which also counts handover_done
            # (a completed handover is a successfully-approved requisition too).
            query["status"] = {"$in": ["approved", "handover_done"]}
        elif status in FINALIZED:
            query["status"] = status
        else:
            query["status"] = {"$in": FINALIZED}
    elif scope == "purchase":
        # PR filing queue (Tech Gatekeeper / can_raise_pr). PO creators use scope
        # "purchase-order" instead so each role only sees their own work queue.
        can_raise = user.get("can_raise_pr") or user["role"] == "super_admin"
        is_it_head = user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))
        if not (can_raise or is_it_head):
            return []
        query = {"status": {"$in": ["pending_pr", "pending_it_review", "pending_md", "pending_accounts", "po_draft", "pending_purchase", "buy_process"]}}
    elif scope == "purchase-order":
        # PO creation queue for users with can_create_po (Purchase dept).
        is_purchase_head = user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id"))
        can_create = user.get("can_create_po") or user["role"] == "super_admin" or is_purchase_head or user["role"] == "purchase_head"
        if not can_create:
            return []
        query = {"status": "pending_po_entry"}
    elif scope == "handover":
        # Items ready to be physically handed over — IT prints the slip and clicks
        # "Handover Done". Not a chain-step assignment either, so it's role-gated here
        # rather than matched against approver_id.
        it_dept = await find_dept_by_name("IT")
        it_dept_id = str(it_dept["_id"]) if it_dept else None
        admin_dept = await find_admin_dept()
        is_admin_head = bool(admin_dept) and user["role"] == "dept_head" and user.get("department_id") == str(admin_dept["_id"])
        is_it_side = user["role"] == "super_admin" or (user["role"] == "dept_head" and user.get("department_id") == it_dept_id)
        is_pr_raiser = has_pr_raise_flag(user)
        if not (is_it_side or is_admin_head or is_pr_raiser):
            return []
        query = {"status": {"$in": ["pending_handover", "stock_received_in_it"]}}
        if is_admin_head and not is_it_side and not is_pr_raiser:
            # Admin Head hands over only what came through the Admin track.
            query["approval_chain.stage"] = "admin_review"
    elif scope == "buy-process":
        # For the Stock GRN "link to requisition" dropdown — requisitions that have
        # cleared the PR approval chain and are waiting on goods to actually be received.
        if user["role"] not in ("super_admin", "dept_head", "purchase_head") and not has_pr_raise_flag(user):
            return []
        query = {"status": "buy_process"}
    elif scope == "pending_po_entry":
        # Queue for Purchase Dept to create PO after IT Head PR review.
        is_purchase_head = user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id"))
        if not (user.get("can_create_po") or user["role"] == "super_admin" or is_purchase_head):
            return []
        query = {"status": "pending_po_entry"}
    elif scope == "pending_pr":
        # Queue for IT users with can_raise_pr (or Super Admin / IT Dept Head)
        is_it_head = user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))
        if not (user.get("can_raise_pr") or user["role"] == "super_admin" or is_it_head):
            return []
        query = {"status": "pending_pr"}
    elif scope == "filed-prs":
        # PRs this user filed that are still live (not voided by IT Head revise)
        if not (user.get("can_raise_pr") or user["role"] == "super_admin"):
            return []
        query = {
            "pr_filed_by_id": str(user["_id"]),
            "purchase_pr_no": {"$exists": True, "$nin": [None, ""]},
        }

    docs = await db.requisitions.find(query).sort("created_at", -1).to_list(1000)
    return await attach_department_names(await attach_file_info([serialize_req(d) for d in docs]))

@api_router.get("/requisitions/{req_id}")
async def get_requisition(req_id: str, user: dict = Depends(get_current_user)):
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    out = serialize_req(d)
    did = d.get("requisitioner_department_id")
    if did and ObjectId.is_valid(did):
        dept = await db.departments.find_one({"_id": ObjectId(did)})
        out["requisitioner_department_name"] = dept["name"] if dept else None
    # Per-item current available stock, for the PR pricing form's "In Stock" column.
    for it in out.get("items", []):
        it["in_stock"] = await db.assets.count_documents({"name": _stock_name_query(it["product_name"]), "status": "in_stock", "pending_receipt": {"$ne": True}})
    await attach_file_info([out])
    return out

@api_router.post("/requisitions/{req_id}/action")
async def act_on_requisition(req_id: str, payload: ApproveIn, user: dict = Depends(get_current_user)):
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d["status"] in FINALIZED:
        raise HTTPException(status_code=400, detail="Requisition already finalized")
    if d["requisition_type"] == "service":
        raise HTTPException(status_code=400, detail="Use the service workflow to manage service requisitions")
    if payload.action == "revise" and not (payload.note and payload.note.strip()):
        raise HTTPException(status_code=400, detail="A note explaining the requested revision is required")
    chain = d["approval_chain"]
    current = next((s for s in chain if s["status"] == "pending"), None)
    if not current:
        raise HTTPException(status_code=400, detail="No pending step")
    delegators = await active_delegators_of(user)
    if not is_current_approver(current, user, delegators):
        raise HTTPException(status_code=403, detail="You are not the current approver")
    if not current.get("approver_id"):
        # Legacy unassigned step — record who actually acted on it.
        current["approver_id"] = str(user["_id"])
        current["approver_name"] = user["name"]
    # Record WHO really acted and in what capacity, so the audit trail is honest.
    acted_as = None
    if current.get("approver_id") != str(user["_id"]) and user["role"] != "super_admin":
        if current.get("approver_id") in delegators:
            acted_as = "delegate"
    current["acted_by_id"] = str(user["_id"])
    current["acted_by_name"] = user["name"]
    current["acted_as"] = acted_as

    extra_set = {}

    if payload.action == "approve":
        current["status"] = "approved"
    elif payload.action == "reject":
        current["status"] = "rejected"
    else:  # revise: sent back to the requester, doesn't finalize or advance the chain
        current["status"] = "revision_requested"
    current["note"] = payload.note
    current["acted_at"] = now_iso()
    d["history"].append({"at": now_iso(), "by": user["name"], "action": payload.action,
                         "level": current["level"], "note": payload.note,
                         **({"as": acted_as, "on_behalf_of": current.get("approver_name")} if acted_as else {})})
    d["updated_at"] = now_iso()
    d["status"] = "revision_requested" if payload.action == "revise" else compute_status(d)

    # Option 1 — IT Head revises AFTER a PR was filed (stage == pr_review):
    # void the current Purchase Requisition so Purchase never acts on stale specs/qty.
    # Requester still sees revision_requested and edits the product requisition; on
    # resubmit the case returns to pending_pr for the PR raiser to file a NEW PR.
    if payload.action == "revise" and current.get("stage") == "pr_review":
        voided_pr_no = d.get("purchase_pr_no")
        voided_list = list(d.get("voided_pr_numbers") or [])
        if voided_pr_no:
            voided_list.append({
                "pr_no": voided_pr_no,
                "voided_at": now_iso(),
                "voided_by": user["name"],
                "reason": payload.note,
            })
        # Drop every PR-review step from the chain (re-filed PR will append a fresh one)
        chain[:] = [s for s in chain if s.get("stage") != "pr_review"]
        d["approval_chain"] = chain
        d["history"].append({
            "at": now_iso(), "by": user["name"], "action": "pr_voided",
            "note": (
                f"PR {voided_pr_no or '(unnumbered)'} voided after IT Head revision request. "
                "Requester must update the product requisition; PR raiser will file a new PR."
            ),
        })
        extra_set.update({
            "po_flow": False,
            "purchase_pr_no": None,
            "pr_attachment_file_ids": [],
            "overall_business_justification": None,
            "required_by_date": None,
            "urgency_level": None,
            "delivery_location": None,
            "voided_pr_numbers": voided_list,
            "pr_needs_refile": True,
            "pr_void_reason": payload.note,
        })
        d["po_flow"] = False
        d["purchase_pr_no"] = None
        d["pr_needs_refile"] = True
        # Keep status revision_requested so the requester can Edit & Resubmit.

    # Stock-check branch point: this fires exactly once, when the base chain (now a single
    # Dept Head level for product requisitions — see build_approval_chain) just finished
    # with an approve and no PR sub-chain/review step has been appended yet. From here the
    # requisition either goes straight to auto-handover (Path A) or into the out-of-stock
    # PR path (Path B). Works unchanged for any base-chain length, so it fires correctly
    # both for new 1-level chains and for legacy 2-level (Dept Head -> IT Head) ones still
    # in flight from before this change.
    base_chain_just_completed = (
        payload.action == "approve" and d["status"] == "approved"
        and current["role"] == "dept_head" and current.get("stage") not in ("pr_review", "stock_review")
        and current["level"] == len(chain)
        and not any(s["role"] in ("md", "accounts", "purchase_head") for s in chain)
    )
    if base_chain_just_completed:
        extra_set.update(await route_after_base_chain(d, d.get("requisitioner_id")))
        chain = d["approval_chain"]
    elif (payload.action == "approve" and current.get("stage") == "stock_review"
          and d["status"] == "approved"):
        await finish_stock_review(d, extra_set)

    await db.requisitions.update_one({"_id": ObjectId(req_id)},
                                     {"$set": {"approval_chain": chain, "status": d["status"],
                                               "history": d["history"], "updated_at": d["updated_at"],
                                               **extra_set}})
    return serialize_req(d)

@api_router.post("/requisitions/{req_id}/resubmit")
async def resubmit_requisition(req_id: str, payload: ResubmitIn, user: dict = Depends(get_current_user)):
    """After a step returns 'revise', the original requester edits the requisition (items,
    note, attachment, etc. — whatever the revision feedback asked for) and resubmits it here.
    Every field in the payload is optional: only what was actually changed needs to be sent,
    everything else keeps its existing value. This resets the step that requested the
    revision back to 'pending' so the SAME approver who asked for it reviews the edited
    requisition next — it never restarts the chain from level 1.

    Option 1 exception: if IT Head voided a filed PR (pr_needs_refile), resubmit routes
    to pending_pr so the PR raiser files a NEW Purchase Requisition instead of reopening
    the old PR-review step."""
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d["status"] != "revision_requested":
        raise HTTPException(status_code=400, detail="Requisition is not awaiting revision")
    if not (d.get("requisitioner_id") == str(user["_id"]) or user["role"] == "super_admin"):
        raise HTTPException(status_code=403, detail="Only the original requester can resubmit this requisition")
    chain = d.get("approval_chain") or []
    step = next((s for s in chain if s["status"] == "revision_requested"), None)
    # After IT Head voids a filed PR (Option 1), PR-review steps are removed from the
    # chain and only pr_needs_refile remains — still allow the requester to resubmit.
    if not step and not d.get("pr_needs_refile"):
        raise HTTPException(status_code=400, detail="No revision-requested step found")

    update = {}
    if payload.items is not None:
        if not payload.items:
            raise HTTPException(status_code=400, detail="At least one item is required")
        items = [it.model_dump() for it in payload.items]
        if d.get("requisition_type") == "product":
            await canonicalize_product_names(items)
        else:
            normalize_service_items(items)
        for it in items:
            it["line_total"] = round(it["quantity"] * it["rate"], 2)
        d["items"] = items
        d["total_amount"] = round(sum(it["line_total"] for it in items), 2)
        update["items"] = d["items"]
        update["total_amount"] = d["total_amount"]
    if payload.requester_note is not None:
        d["requester_note"] = payload.requester_note
        update["requester_note"] = d["requester_note"]
    if payload.attachment_file_id is not None:
        d["attachment_file_id"] = payload.attachment_file_id
        update["attachment_file_id"] = d["attachment_file_id"]
    if payload.attachment_name is not None:
        d["attachment_name"] = payload.attachment_name
        update["attachment_name"] = d["attachment_name"]
    if payload.requisition_for is not None and payload.requisition_for.strip():
        d["requisition_for"] = payload.requisition_for.strip()
        update["requisition_for"] = d["requisition_for"]
    if payload.requisition_date is not None:
        d["requisition_date"] = payload.requisition_date
        update["requisition_date"] = d["requisition_date"]

    # Option 1: if IT Head voided the PR and sent the case back, do NOT reopen the
    # PR-review step. After the requester updates items, route to pending_pr so the
    # PR raiser files a fresh Purchase Requisition from the corrected quantities/specs.
    if d.get("pr_needs_refile") or (step and step.get("stage") == "pr_review"):
        # Remove any leftover PR-review steps (already stripped on void, but be safe)
        chain[:] = [s for s in chain if s.get("stage") != "pr_review"]
        d["approval_chain"] = chain
        d["status"] = "pending_pr"
        d["pr_flow"] = True
        d["po_flow"] = False
        d["pr_needs_refile"] = False
        d["history"].append({
            "at": now_iso(), "by": user["name"], "action": "resubmit",
            "note": (payload.note or "Requester updated items after PR was voided. "
                     "Awaiting new Purchase Requisition filing."),
        })
        d["updated_at"] = now_iso()
        update.update({
            "approval_chain": chain,
            "status": "pending_pr",
            "pr_flow": True,
            "po_flow": False,
            "pr_needs_refile": False,
            "history": d["history"],
            "updated_at": d["updated_at"],
        })
        await db.requisitions.update_one({"_id": ObjectId(req_id)}, {"$set": update})
        return serialize_req(d)

    if not step:
        raise HTTPException(status_code=400, detail="No revision-requested step found")
    step["status"] = "pending"
    step["note"] = None
    step["acted_at"] = None
    step["pending_since"] = now_iso()
    step.pop("reminded_at", None)
    d["history"].append({"at": now_iso(), "by": user["name"], "action": "resubmit",
                         "level": step["level"], "note": payload.note})
    d["updated_at"] = now_iso()
    d["status"] = compute_status(d)
    update.update({"approval_chain": chain, "status": d["status"],
                   "history": d["history"], "updated_at": d["updated_at"]})
    await db.requisitions.update_one({"_id": ObjectId(req_id)}, {"$set": update})
    return serialize_req(d)


@api_router.get("/dashboard/stats")
async def dashboard_stats(response: Response, user: dict = Depends(get_current_user)):
    # Live counters: never let a browser / proxy / CDN serve an older copy of this response.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    # Three-tier visibility: personal (executive), department (dept_head/accounts/
    # purchase_head — their own department), global (super_admin/md — company-wide).
    base_filter, vis_scope = req_visibility_scope(user)
    personal = vis_scope == "personal"

    total = await db.requisitions.count_documents(base_filter)
    pending = await db.requisitions.count_documents({**base_filter, "status": {"$nin": FINALIZED}})
    approved = await db.requisitions.count_documents({**base_filter, "status": {"$in": ["approved", "handover_done"]}})
    rejected = await db.requisitions.count_documents({**base_filter, "status": "rejected"})
    high_value = await db.requisitions.count_documents({**base_filter, "total_amount": {"$gte": MD_THRESHOLD}})
    action_required = await db.requisitions.count_documents({**base_filter, "status": "revision_requested"})
    in_progress = await db.requisitions.count_documents({
        **base_filter, "status": {"$nin": FINALIZED + ["revision_requested"]}})

    if vis_scope == "global":
        assets_total = await db.assets.count_documents({})
        assets_assigned = await db.assets.count_documents({"status": {"$in": ["assigned", "return_pending"]}})
    elif vis_scope == "department":
        dept_users = await db.users.find({"department_id": user.get("department_id")}).to_list(500)
        names = [u["name"] for u in dept_users]
        assets_total = await db.assets.count_documents({"assigned_to": {"$in": names}})
        assets_assigned = assets_total
    else:
        assets_total = await db.assets.count_documents({"assigned_to": user["name"]})
        assets_assigned = assets_total

    # my approvals queue (always personal — items waiting on me)
    docs = await db.requisitions.find({"status": {"$nin": FINALIZED}}).to_list(1000)
    my_queue = 0
    delegated_queue = 0          # waiting on someone who is on leave and delegated to me
    delegators = await active_delegators_of(user)
    for dc in docs:
        cur = next((s for s in dc.get("approval_chain", []) if s["status"] == "pending"), None)
        if cur and is_current_approver(cur, user, delegators):
            my_queue += 1
            if cur.get("approver_id") in delegators and cur.get("approver_id") != str(user["_id"]):
                delegated_queue += 1
    delegated_for, delegated_po = [], 0
    if delegators:
        delegated_for = [d_["name"] async for d_ in db.users.find({"_id": {"$in": [ObjectId(x) for x in delegators]}})]
        async for po_ in db.purchase_orders.find({"status": {"$in": list(PO_STAGE_ROLE)}}):
            if await po_user_can_act(po_, user, delegators) and not await po_user_can_act(po_, user, set()):
                delegated_po += 1

    recent = await db.requisitions.find(base_filter).sort("created_at", -1).to_list(6)

    # PO approvals waiting on this user (role-based queue)
    is_purchase_head = (
        user["role"] == "purchase_head" or
        (user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")))
    )
    if user["role"] == "super_admin":
        po_statuses = [
            "pending_purchase_head_approval",
            "pending_md_approval",
            "pending_accounts_head_approval",
        ]
        po_pending = await db.purchase_orders.count_documents({"status": {"$in": po_statuses}})
    elif is_purchase_head:
        po_pending = await db.purchase_orders.count_documents({"status": "pending_purchase_head_approval"})
    elif user["role"] == "md":
        po_pending = await db.purchase_orders.count_documents({"status": "pending_md_approval"})
    elif user["role"] == "accounts":
        po_pending = await db.purchase_orders.count_documents({"status": "pending_accounts_head_approval"})
    else:
        po_pending = 0

    # PR raise queue (for users with can_raise_pr)
        # PR raise queue (for users with can_raise_pr)
    awaiting_pr = 0
    prs_filed = 0
    if user.get("can_raise_pr") or user["role"] == "super_admin":
        awaiting_pr = await db.requisitions.count_documents({"status": "pending_pr"})
        # Active (non-voided) PRs filed by this user — voided ones clear purchase_pr_no
        prs_filed = await db.requisitions.count_documents({
            "pr_filed_by_id": str(user["_id"]),
            "purchase_pr_no": {"$exists": True, "$nin": [None, ""]},
        })

    # PO raise queue (for users with can_create_po) - mirrors the PR cards above
    awaiting_po = 0
    pos_created = 0
    if user.get("can_create_po") or user["role"] == "super_admin" or is_purchase_head:
        awaiting_po = await db.requisitions.count_documents({"status": "pending_po_entry"})
        pos_created = await db.purchase_orders.count_documents({
            "$or": [{"created_by_id": str(user["_id"])}, {"created_by": user["name"]}]})

    result = {
        "total": total, "pending": pending, "approved": approved, "rejected": rejected,
        "high_value": high_value, "my_queue": my_queue,
        "delegated_queue": delegated_queue, "delegated_po": delegated_po, "delegated_for": delegated_for,
        "in_progress": in_progress, "action_required": action_required,
        "assets_total": assets_total, "assets_assigned": assets_assigned,
        "recent": [serialize_req(r) for r in recent],
        "scope": vis_scope,
        "po_pending": po_pending,
        "awaiting_pr": awaiting_pr,
        "prs_filed": prs_filed,
        "awaiting_po": awaiting_po,
        "pos_created": pos_created,
    }
    if personal:
        pending_docs = await db.requisitions.find(
            {**base_filter, "status": {"$nin": FINALIZED}}).sort("created_at", -1).to_list(50)
        result["pending_list"] = [serialize_req(r) for r in pending_docs]
        my_assets = await db.assets.find({"assigned_to": user["name"]}).sort("created_at", -1).to_list(200)
        result["my_assets"] = [await _enrich_asset(a) for a in my_assets]
    return result
# ===========================================================================
# STEP 2 FEATURES: storage, files, service workflow, PDF, handovers, assets, GRN
# ===========================================================================
import io
import uuid
import re
import base64
import requests as _requests
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "ims-req"
_storage_key = None

MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "csv": "text/csv", "txt": "text/plain",
    "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

def init_storage(force: bool = False):
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    resp = _requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key

def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    r = _requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = _requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    r.raise_for_status()
    return r.json()

def get_object(path: str):
    key = init_storage()
    r = _requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = _requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "application/octet-stream")

def strip_id(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc

async def _next_no(prefix: str, key: str) -> str:
    year = datetime.now(timezone.utc).year
    c = await db.counters.find_one_and_update({"_id": f"{key}-{year}"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return f"{prefix}-{year}-{c['seq']:04d}"

async def user_from_token(token: str):
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return await db.users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        return None

# --------------------------- File upload / download ------------------------
@api_router.post("/files/upload")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    fid = str(uuid.uuid4())
    path = f"{APP_NAME}/uploads/{user['_id']}/{fid}.{ext}"
    data = await file.read()
    ct = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")
    result = put_object(path, data, ct)
    doc = {
        "id": fid, "storage_path": result["path"], "original_filename": file.filename,
        "content_type": ct, "size": result.get("size", len(data)), "is_deleted": False,
        "uploaded_by": str(user["_id"]), "created_at": now_iso(),
    }
    await db.files.insert_one(doc)
    return {"id": fid, "original_filename": file.filename, "size": doc["size"], "content_type": ct}

@api_router.get("/files/{file_id}/download")
async def download_file(file_id: str, request: Request, auth: Optional[str] = None):
    token = auth or request.cookies.get("access_token")
    if not token:
        h = request.headers.get("Authorization", "")
        token = h[7:] if h.startswith("Bearer ") else None
    if not token or not await user_from_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    rec = await db.files.find_one({"id": file_id, "is_deleted": False})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct),
                    headers={"Content-Disposition": f'inline; filename="{rec["original_filename"]}"'})

# --------------------------- Service workflow ------------------------------
class ServiceTransitionIn(BaseModel):
    stage: Optional[str] = None
    note: Optional[str] = None

@api_router.post("/requisitions/{req_id}/service-transition")
async def service_transition(req_id: str, payload: ServiceTransitionIn, user: dict = Depends(get_current_user)):
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d["requisition_type"] != "service":
        raise HTTPException(status_code=400, detail="Not a service requisition")
    if d["status"] in ("service_completed_and_returned", "rejected"):
        raise HTTPException(status_code=400, detail="Service requisition already closed")
    if d.get("it_team"):
        raise HTTPException(status_code=400, detail="This ticket is handled in the IT Service Queue (pick up / complete there)")
    step = d["approval_chain"][0]
    if not (step["approver_id"] == str(user["_id"]) or user["role"] == "super_admin"):
        raise HTTPException(status_code=403, detail="Only the assigned IT Head can manage this service requisition")
    cur = d["status"] if d["status"] in SERVICE_STAGES else SERVICE_STAGES[0]
    idx = SERVICE_STAGES.index(cur)
    target = payload.stage or (SERVICE_STAGES[idx + 1] if idx + 1 < len(SERVICE_STAGES) else cur)
    if target not in SERVICE_STAGES or SERVICE_STAGES.index(target) <= idx:
        raise HTTPException(status_code=400, detail="Invalid stage transition (must move forward)")
    d["status"] = target
    d["updated_at"] = now_iso()
    d["history"].append({"at": now_iso(), "by": user["name"], "action": f"service:{target}", "note": payload.note})
    if target == "service_completed_and_returned":
        step["status"] = "approved"
        step["acted_at"] = now_iso()
    await db.requisitions.update_one({"_id": ObjectId(req_id)}, {"$set": {
        "status": target, "approval_chain": d["approval_chain"], "history": d["history"], "updated_at": d["updated_at"]}})
    return serialize_req(d)

class NonFinancialPRItemIn(BaseModel):
    """PR line item — specs/qty required; estimated_unit_price is optional guess only."""
    index: Optional[int] = None
    category: Optional[str] = None
    detailed_specs: Optional[str] = None
    preferred_brand: Optional[str] = None
    quantity: Optional[int] = None
    uom: Optional[str] = "Pcs"
    estimated_unit_price: Optional[float] = None  # optional guess; not official cost
    line_date_required: Optional[str] = None
    justification_remarks: Optional[str] = None


class FilePRIn(BaseModel):
    """Payload for filing the Purchase Requisition (Tech Gatekeeper Phase)."""
    items: Optional[List[NonFinancialPRItemIn]] = None
    overall_business_justification: Optional[str] = None
    required_by_date: Optional[str] = None
    urgency_level: Optional[str] = "Routine (Standard SLA)"
    delivery_location: Optional[str] = None
    attachment_file_ids: List[str] = []


@api_router.post("/requisitions/{req_id}/file-pr")
async def file_non_financial_pr(req_id: str, payload: FilePRIn, user: dict = Depends(get_current_user)):
    """PR Handler (can_raise_pr) files the Purchase Requisition.
    Official rate/total stay 0. estimated_unit_price is optional guess only."""
    if not user.get("can_raise_pr"):
        raise HTTPException(status_code=403, detail="You are not allowed to raise a Purchase Requisition")
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d["status"] != "pending_pr":
        raise HTTPException(status_code=400, detail="This requisition is not awaiting a Purchase Requisition")

    items = d.get("items", [])
    if payload.items:
        for pit in payload.items:
            idx = pit.index if pit.index is not None else None
            if idx is not None and 0 <= idx < len(items):
                if pit.category is not None:
                    items[idx]["category"] = pit.category
                if pit.detailed_specs is not None:
                    # product_name stays the catalog name chosen on the requisition (it drives
                    # stock matching / PO); the PR raiser's text is stored separately as specs.
                    items[idx]["detailed_specs"] = pit.detailed_specs.strip()
                if pit.preferred_brand is not None:
                    items[idx]["preferred_brand"] = pit.preferred_brand
                if pit.quantity is not None:
                    items[idx]["quantity"] = pit.quantity
                if pit.uom is not None:
                    items[idx]["uom"] = pit.uom
                if pit.justification_remarks is not None:
                    items[idx]["remarks"] = pit.justification_remarks
                    items[idx]["justification_remarks"] = pit.justification_remarks
                if pit.estimated_unit_price is not None:
                    items[idx]["estimated_unit_price"] = pit.estimated_unit_price
                else:
                    items[idx].pop("estimated_unit_price", None)
                if pit.line_date_required is not None:
                    items[idx]["line_date_required"] = pit.line_date_required
                # Official rate stays 0 at PR stage; estimate is informational only
                items[idx]["rate"] = 0
                items[idx].pop("line_total", None)

    chain = d.get("approval_chain", [])
    # Drop any stale PR-review steps (e.g. leftover from a voided PR) before appending a fresh one
    chain = [s for s in chain if s.get("stage") != "pr_review"]
    review_step = await make_it_head_review_step(level=len(chain) + 1)
    chain = chain + [review_step]
    d["items"] = items
    d["total_amount"] = 0
    d["approval_chain"] = chain
    d["pr_flow"] = True
    d["po_flow"] = True
    d["pr_needs_refile"] = False
    d["overall_business_justification"] = payload.overall_business_justification
    d["required_by_date"] = payload.required_by_date
    d["urgency_level"] = payload.urgency_level
    d["delivery_location"] = payload.delivery_location
    if payload.attachment_file_ids:
        d["pr_attachment_file_ids"] = payload.attachment_file_ids
    d["status"] = compute_status(d)
    d["updated_at"] = now_iso()
    d["history"].append({
        "at": now_iso(), "by": user["name"], "action": "pr_filed",
        "note": "Purchase Requisition filed (specs & quantities; optional est. unit price as guess only). Routed to IT Head for review."
    })
    d["pr_filed_by"] = user["name"]
    d["pr_filed_by_id"] = str(user["_id"])
    await db.requisitions.update_one({"_id": ObjectId(req_id)}, {"$set": {
        "items": items, "total_amount": 0, "approval_chain": chain, "pr_flow": True,
        "po_flow": True, "status": d["status"], "history": d["history"], "updated_at": d["updated_at"],
        "overall_business_justification": d.get("overall_business_justification"),
        "required_by_date": d.get("required_by_date"),
        "urgency_level": d.get("urgency_level"),
        "delivery_location": d.get("delivery_location"),
        "pr_attachment_file_ids": d.get("pr_attachment_file_ids", []),
        "pr_needs_refile": False,
        "pr_filed_by": user["name"],
        "pr_filed_by_id": str(user["_id"]),
    }})
    return serialize_req(d)

# Safety net – reject any old pricing calls
@api_router.post("/requisitions/{req_id}/pricing")
async def set_pr_pricing_legacy(req_id: str, payload: dict, user: dict = Depends(get_current_user)):
    raise HTTPException(
        status_code=400,
        detail="Price/Cost data is masked at the PR stage. Use POST /requisitions/{req_id}/file-pr"
    )

# --------------------------- Purchase Requisition PDF ----------------------
async def _pr_number(req: dict) -> str:
    if req.get("purchase_pr_no"):
        return req["purchase_pr_no"]
    now = datetime.now(timezone.utc)
    c = await db.counters.find_one_and_update({"_id": f"pr-{now.year}"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    pr_no = f"LPRIT-{now.year}{now.month:02d}{c['seq']:04d}"
    await db.requisitions.update_one({"_id": req["_id"]}, {"$set": {"purchase_pr_no": pr_no}})
    return pr_no

def build_pr_pdf(req: dict, pr_no: str, dept_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    story = []
    story.append(Paragraph("<b>Primitek Industries Limited</b>", ParagraphStyle("h", parent=styles["Title"], fontSize=15)))
    story.append(Paragraph("A concern of Primitek Group — Delivering Excellence", small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Purchase Requisition</b>", ParagraphStyle("c", parent=styles["Heading2"], alignment=1)))
    story.append(Spacer(1, 8))

    req_date = (req.get("requisition_date") or "")[:10]
    meta = [
        ["Department", ": " + (dept_name or "-"), "PR No.", ": " + pr_no],
        ["Purchase Type", ": Local Purchase Requisition", "PR Date", ": " + req_date],
        ["Delivery Location", ": Head Office", "Required Date", ": " + req_date],
        ["Status", ": " + req.get("status", "").replace("_", " ").title(), "", ""],
    ]
    mt = Table(meta, colWidths=[32 * mm, 60 * mm, 28 * mm, 60 * mm])
    mt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(mt)
    story.append(Spacer(1, 8))

    header = ["SL", "Item Code", "Item Name", "UoM", "Req Qty", "In Stock", "Rate", "Remarks"]
    rows = [header]
    for i, it in enumerate(req.get("items", []), start=1):
        rows.append([
            str(i),
            it.get("item_code") or f"IT{1000040 + i}",
            Paragraph(
                (it.get("product_name", "") or "") +
                (f"<br/><font size='7' color='#64748B'>{it['detailed_specs']}</font>" if it.get("detailed_specs") else ""),
                small),
            it.get("uom", "Nos"),
            f"{it.get('quantity', 0):.2f}",
            "0.00",
            f"{it.get('rate', 0):,.2f}",
            Paragraph(it.get("remarks") or "-", small),
        ])
    tbl = Table(rows, colWidths=[10 * mm, 24 * mm, 48 * mm, 14 * mm, 18 * mm, 18 * mm, 22 * mm, 30 * mm])
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (6, -1), "RIGHT"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Total Amount:</b> BDT {req.get('total_amount', 0):,.2f}", small))
    if req.get("requester_note"):
        story.append(Paragraph(f"<b>Note:</b> {req['requester_note']}", small))
    story.append(Spacer(1, 26))

    # Footer signatories (corporate PR form):
    #   Prepared By  = PR raiser (who filed the Purchase Requisition)
    #   Checked By   = IT Head
    #   Recommended By = Purchase Head
    #   Authorized By  = MD (if resolved), else blank
    #   Approved By  = Accounts Head
    sig_names = req.get("_pr_signatories") or {}
    names = [
        sig_names.get("prepared_by") or "-",
        sig_names.get("checked_by") or "-",
        sig_names.get("recommended_by") or "-",
        sig_names.get("authorized_by") or "-",
        sig_names.get("approved_by") or "-",
    ]
    labels = ["Prepared By", "Checked By", "Recommended By", "Authorized By", "Approved By"]
    sig = [names, labels]
    st = Table(sig, colWidths=[38 * mm] * 5)
    st.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 2),
    ]))
    story.append(st)
    doc.build(story)
    return buf.getvalue()
async def resolve_pr_signatories(req: dict) -> dict:
    """Names for the PR PDF footer lines — only filled AFTER the person has acted.

    Prepared By  → set when the PR is filed (pr_filed_by / history pr_filed)
    Checked By   → set only after IT Head approves the pr_review step
    Recommended By → set only after Purchase Head has approved on the chain
    Authorized By  → set only after MD has approved on the chain
    Approved By  → set only after Accounts has approved on the chain

    Until that action happens the line stays blank ("-").
    """
    prepared = req.get("pr_filed_by")
    if not prepared:
        for h in reversed(req.get("history") or []):
            if h.get("action") == "pr_filed" and h.get("by"):
                prepared = h["by"]
                break
    prepared = prepared or "-"

    checked = "-"
    recommended = "-"
    authorized = "-"
    approved = "-"

    for s in (req.get("approval_chain") or []):
        if s.get("status") != "approved":
            continue
        name = s.get("approver_name") or "-"
        stage = s.get("stage")
        role = s.get("role")
        if stage == "pr_review":
            checked = name
        elif role == "purchase_head":
            recommended = name
        elif role == "md":
            authorized = name
        elif role == "accounts":
            approved = name

    return {
        "prepared_by": prepared,
        "checked_by": checked,
        "recommended_by": recommended,
        "authorized_by": authorized,
        "approved_by": approved,
    }
@api_router.get("/requisitions/{req_id}/pdf")
async def requisition_pdf(req_id: str, request: Request, auth: Optional[str] = None):
    """View the Purchase Requisition PDF (form filled by the PR raiser).

    Available only after the PR has been filed. Allowed viewers:
      - IT Dept Head
      - Super Admin
      - The PR raiser who filed this specific PR
    """
    # Prefer Authorization Bearer (tab session), then ?auth=, then cookie
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = auth or request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    pr_user = await user_from_token(token)
    if not pr_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")

    # PR PDF is only available after a Purchase Requisition has been filed
    pr_filed = bool(d.get("purchase_pr_no") or d.get("po_flow") or d.get("pr_filed_by"))
    if not pr_filed:
        raise HTTPException(
            status_code=400,
            detail="Purchase Requisition has not been filed yet — PDF is available only after PR raise",
        )

    # Only IT Head, Super Admin, or the PR raiser who filed this PR may view it
    is_it_head = (
        pr_user.get("role") == "dept_head"
        and await _department_is_it(pr_user.get("department_id"))
    )
    is_pr_raiser = (
        d.get("pr_filed_by_id") == str(pr_user["_id"])
        or (
            bool(pr_user.get("can_raise_pr"))
            and d.get("pr_filed_by") == pr_user.get("name")
        )
    )
    can_view = is_it_head or pr_user.get("role") == "super_admin" or is_pr_raiser
    if not can_view:
        raise HTTPException(
            status_code=403,
            detail="NOT ALLOWED!",
        )

    pr_no = await _pr_number(d)
    dept_name = None
    did = d.get("requisitioner_department_id")
    if did and ObjectId.is_valid(did):
        dp = await db.departments.find_one({"_id": ObjectId(did)})
        dept_name = dp["name"] if dp else None
    d["_pr_signatories"] = await resolve_pr_signatories(d)
    pdf = build_pr_pdf(d, pr_no, dept_name or "Information Technology")
    return Response(content=pdf, media_type="application/pdf",
   headers={"Content-Disposition": f'inline; filename="{pr_no}.pdf"'})
# --------------------------- Assets ----------------------------------------
class AssetIn(BaseModel):
    name: str
    brand: Optional[str] = None
    serial_no: Optional[str] = None
    tag_id: Optional[str] = None
    category_id: Optional[str] = None

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
            u = await db.users.find_one({"_id": ObjectId(uid)})
        if not u:
            u = await db.users.find_one({"name": {"$regex": f"^{re.escape(a['assigned_to'].strip())}$", "$options": "i"}})
        did = a.get("assigned_department_id") or (u or {}).get("department_id")
        if did and ObjectId.is_valid(did):
            d = await db.departments.find_one({"_id": ObjectId(did)})
            a["assigned_department_name"] = d["name"] if d else None
        a["assigned_email"] = (u or {}).get("email")
    return a

@api_router.get("/assets/stock-summary")
async def stock_summary(user: dict = Depends(get_current_user)):
    """Aggregated available-stock view for the main Stock List dashboard.
    Groups by item name + category, counting only status == 'in_stock' assets
    (an asset stays 'in_stock' — i.e. still available — until the employee
    confirms receipt; see notifications/confirm). Per-asset detail fields
    (serial_no, tag_id, assigned_to, status) are intentionally NOT included
    here; use GET /assets for that granular, item-level view."""
    pipeline = [
        {"$match": {"status": "in_stock"}},
        {"$group": {
            "_id": {"name": "$name", "category_id": "$category_id"},
            "available_stock": {"$sum": 1},
        }},
        {"$sort": {"_id.name": 1}},
    ]
    rows = await db.assets.aggregate(pipeline).to_list(1000)
    out = []
    for r in rows:
        cid = r["_id"].get("category_id")
        cat_name = await resolve_category_name(cid)
        out.append({
            "name": r["_id"].get("name"),
            "category_id": cid,
            "category_name": cat_name,
            "available_stock": r["available_stock"],
        })
    return out

@api_router.get("/assets")
async def list_assets(status: Optional[str] = None, assigned_to: Optional[str] = None,
                      assigned_to_user_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {}
    if status:
        q["status"] = status
    if assigned_to:
        q["assigned_to"] = assigned_to
    if assigned_to_user_id:
        q["assigned_to_user_id"] = assigned_to_user_id
    if user["role"] == "executive" and status != "in_stock":
        # Plain employees only see their own assigned assets. in_stock items carry no
        # personal data (assigned_to is empty), so they're exempt — needed for the Stock
        # List detail drill-down and handover asset pickers. Any other query (no status
        # filter, "assigned", or an attempt to snoop via ?assigned_to=someone-else) is
        # forced back to the caller's own name.
        q["assigned_to"] = user["name"]
    docs = await db.assets.find(q).sort("created_at", -1).to_list(1000)
    return [await _enrich_asset(a) for a in docs]

@api_router.post("/assets")
async def create_asset(payload: AssetIn, user: dict = Depends(require_roles("super_admin", "dept_head", "purchase_head"))):
    doc = payload.model_dump()
    doc.update({"status": "in_stock", "assigned_to": None, "assigned_department_id": None,
                "source_grn_id": None, "created_at": now_iso()})
    res = await db.assets.insert_one(doc)
    doc["_id"] = res.inserted_id
    await process_waiting_stock_requisitions()     # restock -> start waiting handovers
    return await _enrich_asset(doc)

class ExistingDeviceIn(BaseModel):
    name: str
    brand: Optional[str] = None
    category_id: Optional[str] = None
    tag_id: Optional[str] = None
    serial_no: Optional[str] = None
    assigned_date: Optional[str] = None
    remarks: Optional[str] = None

class AssignExistingIn(BaseModel):
    user_id: str
    devices: List[ExistingDeviceIn]

@api_router.post("/assets/assign-existing")
async def assign_existing_assets(payload: AssignExistingIn, user: dict = Depends(get_current_user)):
    """Register devices an existing employee already holds (no handover slip / GRN behind
    them). Each is created directly as 'assigned' to that user, so it appears under Assigned
    Assets but never touches the available-stock count."""
    it_dept = await find_dept_by_name("IT")
    it_dept_id = str(it_dept["_id"]) if it_dept else None
    if not (user["role"] == "super_admin" or (user["role"] == "dept_head" and user.get("department_id") == it_dept_id)):
        raise HTTPException(status_code=403, detail="Only IT / Super Admin can add existing assets to a user")
    if not ObjectId.is_valid(payload.user_id):
        raise HTTPException(status_code=400, detail="Invalid user")
    emp = await db.users.find_one({"_id": ObjectId(payload.user_id)})
    if not emp:
        raise HTTPException(status_code=404, detail="User not found")
    if not payload.devices:
        raise HTTPException(status_code=400, detail="Add at least one device")

    # Validate everything first so a bad row doesn't leave a half-saved batch.
    seen_tags, seen_serials = set(), set()
    for d in payload.devices:
        if not d.name.strip():
            raise HTTPException(status_code=400, detail="Every device needs a product name")
        tag = (d.tag_id or "").strip()
        ser = (d.serial_no or "").strip()
        for val, field, seen in ((tag, "tag_id", seen_tags), (ser, "serial_no", seen_serials)):
            if not val:
                continue
            label = "Tag ID" if field == "tag_id" else "Serial No"
            if val.lower() in seen or await db.assets.find_one(
                    {field: {"$regex": f"^{re.escape(val)}$", "$options": "i"}}):
                raise HTTPException(status_code=400, detail=f"{label} '{val}' already exists in the system")
            seen.add(val.lower())

    created = []
    for d in payload.devices:
        when = d.assigned_date or now_iso()
        doc = {
            "name": d.name.strip(), "brand": (d.brand or "").strip() or None,
            "serial_no": (d.serial_no or "").strip() or None, "tag_id": (d.tag_id or "").strip() or None,
            "category_id": d.category_id or None, "status": "assigned",
            "assigned_to": emp["name"], "assigned_to_user_id": str(emp["_id"]),
            "assigned_department_id": emp.get("department_id"),
            "assigned_at": when, "receipt_confirmed": True, "receipt_confirmed_at": when,
            "pending_receipt": False, "pending_handover_id": None, "assigned_slip_no": None,
            "remarks": d.remarks, "source": "existing_entry",
            "added_by": user["name"], "created_at": now_iso(),
        }
        res = await db.assets.insert_one(doc)
        doc["_id"] = res.inserted_id
        await _log_asset_event(doc, "issued", user["name"], emp=emp, source="existing_entry")
        created.append(await _enrich_asset(doc))
    return {"ok": True, "employee": emp["name"], "created": len(created), "assets": created}

# --------------------------- Stock GRN & tagging ---------------------------
class GrnAssetIn(BaseModel):
    serial_no: Optional[str] = None
    tag_id: Optional[str] = None

class GrnItemIn(BaseModel):
    product_name: str
    brand: Optional[str] = None
    category_id: Optional[str] = None
    uom: Optional[str] = "Nos"
    quantity: int = 1
    rate: float = 0
    assets: List[GrnAssetIn] = []

class GrnIn(BaseModel):
    challan_no: str
    vendor_name: str
    received_date: Optional[str] = None
    delivery_location: Optional[str] = None
    requisition_id: Optional[str] = None
    items: List[GrnItemIn]

MAX_UNTAGGED_UNITS_PER_GRN_LINE = 5000   # typo guard for quantity-tracked (consumable) lines

@api_router.get("/grns")
async def list_grns(user: dict = Depends(get_current_user)):
    docs = await db.grns.find().sort("created_at", -1).to_list(1000)
    return [strip_id(g) for g in docs]

@api_router.post("/grns")
async def create_grn(payload: GrnIn, user: dict = Depends(require_roles_or_pr_raiser("super_admin", "dept_head", "purchase_head"))):
    grn_no = await _next_no("GRN", "grn")
    items = [it.model_dump() for it in payload.items]
    await canonicalize_product_names(items, strict_type=False)   # stock always uses catalog spelling

    # Work out the stock records each line creates BEFORE anything is saved, so a bad line
    # cannot leave a half-received GRN behind.
    #  - tagged units (serial / tag typed in) become one in-stock asset each;
    #  - quantity-tracked products (consumables) carry no serial/tag, so the received quantity
    #    becomes that many untagged in-stock units - that is what makes their "in stock" count real.
    plans = []
    for it in items:
        prod = await db.products.find_one({"name_key": _pkey(it["product_name"])}) or {}
        brand = _clean_brand(it.get("brand")) or prod.get("brand") or None
        it["brand"] = brand
        tagged = [a for a in (it.get("assets") or []) if a.get("serial_no") or a.get("tag_id")]
        untagged = 0
        if _tracked_by_quantity(prod):
            untagged = max(int(it.get("quantity") or 0) - len(tagged), 0)
            if untagged > MAX_UNTAGGED_UNITS_PER_GRN_LINE:
                raise HTTPException(status_code=400, detail=(
                    f"{it['product_name']}: {untagged} units on one line is too many "
                    f"(max {MAX_UNTAGGED_UNITS_PER_GRN_LINE}). Check the quantity, or split it across lines."))
        plans.append((it, brand, tagged, untagged))

    doc = {
        "grn_no": grn_no, "challan_no": payload.challan_no, "vendor_name": payload.vendor_name,
        "received_date": payload.received_date or now_iso(), "delivery_location": payload.delivery_location or "Head Office",
        "requisition_id": payload.requisition_id, "items": items,
        "received_by": user["name"], "created_at": now_iso(),
    }
    res = await db.grns.insert_one(doc)
    grn_id = str(res.inserted_id)
    created_assets = 0
    for it, brand, tagged, untagged in plans:
        for a in tagged:
            await db.assets.insert_one({
                "name": it["product_name"], "brand": brand,
                "serial_no": a.get("serial_no"), "tag_id": a.get("tag_id"),
                "category_id": it.get("category_id"), "status": "in_stock",
                "assigned_to": None, "assigned_department_id": None,
                "source_grn_id": grn_id, "created_at": now_iso(),
            })
            created_assets += 1
        if untagged:
            stamp = now_iso()
            await db.assets.insert_many([{
                "name": it["product_name"], "brand": brand, "serial_no": None, "tag_id": None,
                "category_id": it.get("category_id"), "status": "in_stock",
                "assigned_to": None, "assigned_department_id": None,
                "source_grn_id": grn_id, "created_at": stamp,
            } for _ in range(untagged)])
            created_assets += untagged
    doc["_id"] = res.inserted_id
    out = strip_id(doc)
    out["created_assets"] = created_assets
    out["waiting_handovers_started"] = await process_waiting_stock_requisitions()

    # Completes the receiving side of the out-of-stock PR flow: goods received against the
    # requisition's PR -> central stock already incremented above (assets created as
    # in_stock). Handover is NOT auto-generated here anymore — IT explicitly reviews and
    # clicks "Issue Stock for Requisition" first (see POST /requisitions/{id}/issue-stock).
    if payload.requisition_id and ObjectId.is_valid(payload.requisition_id):
        req = await db.requisitions.find_one({"_id": ObjectId(payload.requisition_id)})
        if req and req.get("status") == "buy_process":
            req["history"].append({"at": now_iso(), "by": user["name"], "action": "stock_received_in_it",
                                   "note": f"Received via GRN {grn_no} (challan {payload.challan_no})."})
            await db.requisitions.update_one({"_id": req["_id"]}, {"$set": {
                "status": "stock_received_in_it", "history": req["history"], "updated_at": now_iso()}})
            out["requisition_advanced_to"] = "stock_received_in_it"
    return out

@api_router.post("/requisitions/{req_id}/issue-stock")
async def issue_stock_for_requisition(req_id: str, user: dict = Depends(get_current_user)):
    """IT's explicit 'Issue Stock for Requisition' action. Only valid once goods have been
    received via GRN against this requisition (status == stock_received_in_it). Generates
    the handover (same shape as the in-stock Path A) and pushes an info notification to the
    requester ahead of the later physical-receipt confirmation."""
    it_dept = await find_dept_by_name("IT")
    it_dept_id = str(it_dept["_id"]) if it_dept else None
    if not (user["role"] == "super_admin" or (user["role"] == "dept_head" and user.get("department_id") == it_dept_id)):
        raise HTTPException(status_code=403, detail="Only the IT team can issue stock for a requisition")
    req = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if req.get("status") != "stock_received_in_it":
        raise HTTPException(status_code=400, detail="Stock can only be issued once goods have been received via GRN for this requisition")

    hid = await auto_generate_handover(req)
    item_names = ", ".join(it["product_name"] for it in req["items"])
    await db.notifications.insert_one({
        "user_id": req.get("requisitioner_id"), "employee_name": req.get("requisition_for") or req["requisitioner_name"],
        "type": "stock_allocated", "requisition_id": req_id, "handover_id": hid,
        "message": f"Your requested item {item_names} has arrived in IT inventory and is being prepared for handover.",
        "status": "unread", "created_at": now_iso(),
    })
    req["history"].append({"at": now_iso(), "by": user["name"], "action": "stock_issued", "note": None})
    await db.requisitions.update_one({"_id": ObjectId(req_id)}, {"$set": {
        "status": "pending_handover", "handover_id": hid, "history": req["history"], "updated_at": now_iso()}})
    return {"ok": True, "status": "pending_handover", "handover_id": hid}

# --------------------------- Handover / Takeover ---------------------------
class HandoverItemIn(BaseModel):
    item: str
    brand: Optional[str] = None
    quantity: int = 1
    remarks: Optional[str] = None
    asset_id: Optional[str] = None

class ReturnItemIn(BaseModel):
    """One asset the employee is handing back (takeover / swap). Always a real, tagged asset:
    the unit must currently be assigned to that employee."""
    asset_id: str
    condition: Literal["good", "damaged", "missing_parts"] = "good"
    next_status: Literal["in_stock", "under_repair", "scrapped"] = "in_stock"
    accessories: List[str] = []        # e.g. ["Charger", "Bag", "Mouse"]
    data_wiped: bool = False
    remarks: Optional[str] = None

class HandoverIn(BaseModel):
    # `type` is DERIVED by the server from the lines (items only -> handover, return_items only
    # -> takeover, both -> swap). It is still accepted so old clients do not break, but ignored.
    type: Optional[Literal["handover", "takeover", "swap"]] = None
    employee_name: str
    employee_user_id: Optional[str] = None   # picked from the employee list (preferred)
    department_id: Optional[str] = None
    items: List[HandoverItemIn] = []         # issued to the employee  (OUT)
    return_items: List[ReturnItemIn] = []    # received back from them (IN)
    receive_now: bool = False                # the returned devices are physically with IT right now
    remarks: Optional[str] = None
    note: Optional[str] = None
    handover_date: Optional[str] = None
    prepared_by_sign: Optional[str] = None
    received_by_sign: Optional[str] = None
    # Optional explicit link to the requisition this handover fulfils (see
    # _find_requisition_for_handover for the auto-detect fallback when this is omitted).
    requisition_id: Optional[str] = None

# ---- Asset return lifecycle -------------------------------------------------------------
#   in_stock -> (pending_receipt) -> assigned -> return_pending -> in_stock | under_repair | scrapped
ASSET_HELD_STATUSES = ["assigned", "return_pending"]
CONDITION_LABELS = {"good": "Good", "damaged": "Damaged", "missing_parts": "Missing parts"}

async def _can_manage_handovers(user: dict) -> bool:
    """Same people who can open the Handover module: Super Admin, the IT head, or the PR raiser."""
    if user.get("role") == "super_admin" or has_pr_raise_flag(user):
        return True
    it_dept = await find_dept_by_name("IT")
    return bool(it_dept and user.get("role") == "dept_head"
                and user.get("department_id") == str(it_dept["_id"]))

def _held_filter(emp: dict, statuses: Optional[List[str]] = None) -> dict:
    """Mongo filter for 'assets this employee holds'. Matches on the user id; assets created
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
    await db.asset_history.insert_one({
        "asset_id": str(asset["_id"]), "asset_name": asset.get("name"),
        "tag_id": asset.get("tag_id"), "serial_no": asset.get("serial_no"),
        "event": event, "employee_user_id": str(emp["_id"]) if emp else extra.pop("employee_user_id", None),
        "employee_name": emp.get("name") if emp else extra.pop("employee_name", None),
        "slip_no": slip_no, "handover_id": handover_id, "by": by, "at": now_iso(), **extra})

async def prepare_return_items(return_items: List[dict], emp: dict) -> List[dict]:
    """Every returned line must be a real asset that is assigned to THIS employee right now.
    Nothing is written here - this only validates and builds the slip's return lines."""
    if not return_items:
        return []
    out: List[dict] = []
    seen: set = set()
    for r in return_items:
        aid = r.get("asset_id")
        if not aid or not ObjectId.is_valid(aid):
            raise HTTPException(status_code=400, detail="An invalid asset was selected for return. Pick it again.")
        if aid in seen:
            raise HTTPException(status_code=400, detail="The same asset is listed for return more than once.")
        seen.add(aid)
        a = await db.assets.find_one({"_id": ObjectId(aid)})
        if not a:
            raise HTTPException(status_code=400, detail="A selected asset no longer exists. Pick it again.")
        label = f"{a.get('name')} ({a.get('tag_id') or a.get('serial_no') or 'no tag'})"
        if a.get("status") == "return_pending":
            raise HTTPException(status_code=400, detail=f"{label} already has a return in progress (slip {a.get('pending_return_slip_no') or '-'}).")
        held = await db.assets.find_one({"_id": ObjectId(aid), **_held_filter(emp, ["assigned"])})
        if not held:
            raise HTTPException(status_code=400, detail=f"{label} is not assigned to {emp['name']}, so it cannot be taken over.")
        if r.get("condition", "good") != "good" and r.get("next_status", "in_stock") == "in_stock":
            raise HTTPException(status_code=400, detail=(
                f"{label} is marked {CONDITION_LABELS.get(r.get('condition'))}; send it to Under Repair or Scrapped, not back to stock."))
        out.append({
            "asset_id": aid, "item": a.get("name"), "brand": a.get("brand"),
            "tag_id": a.get("tag_id"), "serial_no": a.get("serial_no"), "quantity": 1,
            "condition": r.get("condition", "good"), "next_status": r.get("next_status", "in_stock"),
            "accessories": r.get("accessories") or [], "data_wiped": bool(r.get("data_wiped")),
            "remarks": r.get("remarks"), "received": False,
        })
    return out

async def _release_slip_locks(hid: str):
    """Undo everything a not-yet-completed slip locked: reserved stock goes back to in_stock and
    assets waiting to be returned go back to 'assigned'. Used on failed saves and slip deletion."""
    await db.assets.update_many(
        {"pending_handover_id": hid, "status": "in_stock"},
        {"$set": {"pending_receipt": False, "pending_handover_id": None,
                  "assigned_to_tentative": None, "assigned_department_id": None}})
    await db.assets.update_many(
        {"pending_return_handover_id": hid, "status": "return_pending"},
        {"$set": {"status": "assigned", "pending_return_handover_id": None, "pending_return_slip_no": None}})

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
        a = await db.assets.find_one({"_id": ObjectId(ln["asset_id"])})
        if not a or a.get("status") != "return_pending" or a.get("pending_return_handover_id") != hid:
            raise HTTPException(status_code=409, detail=(
                f"{ln.get('item')} ({ln.get('tag_id') or ln.get('serial_no') or 'no tag'}) is no longer waiting to be returned on this slip."))

    emp = None
    if h.get("employee_user_id") and ObjectId.is_valid(h["employee_user_id"]):
        emp = await db.users.find_one({"_id": ObjectId(h["employee_user_id"])})
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
        res = await db.assets.update_one(
            {"_id": ObjectId(ln["asset_id"]), "status": "return_pending", "pending_return_handover_id": hid},
            {"$set": {
                "status": ln["next_status"], "condition": ln["condition"],
                "assigned_to": None, "assigned_to_user_id": None, "assigned_department_id": None,
                "assigned_at": None, "assigned_handover_id": None, "assigned_slip_no": None,
                "receipt_confirmed": False, "pending_receipt": False, "pending_handover_id": None,
                "pending_return_handover_id": None, "pending_return_slip_no": None,
                "last_returned_at": now_iso(), "last_returned_by": h.get("employee_name"),
                "data_wiped": ln["data_wiped"]}})
        if res.modified_count == 0:
            raise HTTPException(status_code=409, detail="An asset changed while receiving. Reload and try again.")
        ln["received"] = True
        asset_doc = await db.assets.find_one({"_id": ObjectId(ln["asset_id"])})
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
    await db.handovers.update_one({"_id": h["_id"]}, {"$set": upd})
    h.update(upd)
    if restock:
        await process_waiting_stock_requisitions()    # a returned laptop can fulfil a waiting requisition
    return len(lines)

async def _enrich_handover(h: dict) -> dict:
    h = strip_id(h)
    if h.get("department_id") and ObjectId.is_valid(h["department_id"]):
        d = await db.departments.find_one({"_id": ObjectId(h["department_id"])})
        h["department_name"] = d["name"] if d else None
    return h

@api_router.get("/handovers")
async def list_handovers(user: dict = Depends(get_current_user)):
    docs = await db.handovers.find().sort("created_at", -1).to_list(1000)
    return [await _enrich_handover(h) for h in docs]

@api_router.get("/handovers/{hid}")
async def get_handover(hid: str, user: dict = Depends(get_current_user)):
    h = await db.handovers.find_one({"_id": ObjectId(hid)})
    if not h:
        raise HTTPException(status_code=404, detail="Not found")
    return await _enrich_handover(h)

async def prepare_handover_items(items: List[dict]) -> List[dict]:
    """Every handed-over line must be backed by a REAL, currently-available unit from stock.
    - line with asset_id: the unit must exist, be in_stock and not reserved by another slip.
    - line without asset_id: the item must be a catalog product; the needed number of available
      units is picked automatically (one line per unit). If stock is short the slip is REJECTED
      with a clear message — never saved as a line that deducts nothing.
    - Only catalog 'consumable' products may be handed over as a counted line without tagged
      units (consumables are often received with no serial/tag)."""
    if not items:
        raise HTTPException(status_code=400, detail="Add at least one item")

    def label(a: dict) -> str:
        return f"{a.get('name')} ({a.get('tag_id') or a.get('serial_no') or 'no tag'})"

    picked: set = set()
    # Pass 1: validate explicitly chosen units.
    for it in items:
        aid = it.get("asset_id")
        if not aid:
            continue
        if not ObjectId.is_valid(aid):
            raise HTTPException(status_code=400, detail="An invalid asset was selected. Pick the unit again.")
        a = await db.assets.find_one({"_id": ObjectId(aid)})
        if not a:
            raise HTTPException(status_code=400, detail="A selected asset no longer exists. Pick the unit again.")
        if aid in picked:
            raise HTTPException(status_code=400, detail=f"{label(a)} is added more than once.")
        if a.get("status") != "in_stock":
            raise HTTPException(status_code=400, detail=f"{label(a)} is not in stock (status: {a.get('status')}).")
        if a.get("pending_receipt"):
            raise HTTPException(status_code=400, detail=f"{label(a)} is already reserved for another handover.")
        picked.add(aid)

    out: List[dict] = []
    # Pass 2: build final lines in the original order.
    for it in items:
        aid = it.get("asset_id")
        if aid:
            a = await db.assets.find_one({"_id": ObjectId(aid)})
            out.append({**it, "item": a["name"], "brand": it.get("brand") or a.get("brand"), "quantity": 1,
                        "tag_id": a.get("tag_id"), "serial_no": a.get("serial_no")})
            continue
        name = (it.get("item") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Every line needs an item. Select it from the list.")
        qty = max(int(it.get("quantity") or 1), 1)
        prod = await db.products.find_one({"name_key": _pkey(name)})
        if not prod:
            raise HTTPException(status_code=400, detail=f"'{name}' is not in the product catalog. Select the item from the list.")
        cands = await db.assets.find({
            "name": _stock_name_query(prod["name"]), "status": "in_stock",
            "pending_receipt": {"$ne": True},
        }).to_list(qty + len(picked) + 5)
        cands = [c for c in cands if str(c["_id"]) not in picked][:qty]
        if len(cands) < qty and not (prod.get("product_type") == "consumable"):
            raise HTTPException(status_code=400, detail=(
                f"Only {len(cands)} '{prod['name']}' available in stock, but {qty} requested."))
        for c in cands:
            picked.add(str(c["_id"]))
            out.append({**it, "item": c["name"], "quantity": 1, "asset_id": str(c["_id"]),
                        "brand": it.get("brand") or c.get("brand"),
                        "tag_id": c.get("tag_id"), "serial_no": c.get("serial_no")})
        if len(cands) < qty:   # consumable: remainder handed over as a counted line
            out.append({**it, "item": prod["name"], "quantity": qty - len(cands), "asset_id": None})
    return out

@api_router.post("/handovers")
async def create_handover(payload: HandoverIn, user: dict = Depends(get_current_user)):
    """Creates ONE slip that can carry issued lines (items), returned lines (return_items), or both.
    The type is derived, never chosen:
        items only        -> handover  (HO-)   new allocation
        return_items only -> takeover  (TO-)   resignation / plain return
        both              -> swap      (SW-)   replacement: old device in, new device out

    Issued assets are reserved (pending_receipt) and returned assets are locked
    (status 'return_pending') so neither can be double-booked. Everything is validated BEFORE the
    slip is written, and if a lock fails midway the whole slip is undone.

    The bell notification to the requester is intentionally NOT created here - IT still needs to
    print the slip and physically deliver the item first (POST /handovers/{hid}/deliver).
    Returned devices are received via POST /handovers/{hid}/receive-return, or immediately when
    receive_now is true.

    If the issued part fulfils an open requisition (status == stock_received_in_it) it is linked,
    explicitly via payload.requisition_id or auto-detected by requester + item match."""
    if not payload.items and not payload.return_items:
        raise HTTPException(status_code=400, detail="Add at least one item to issue or one asset to take back")
    if payload.return_items and not await _can_manage_handovers(user):
        raise HTTPException(status_code=403, detail="Only IT / Super Admin can take assets back from an employee")

    items = [it.model_dump() for it in payload.items]
    if items:
        items = await prepare_handover_items(items)   # strict: real, available units or a clear error

    # Resolve exactly who this slip is for (name + department, or the picked user id).
    # Always strict now: returns are matched to the employee by id, so a wrong person is not OK.
    emp_user = await resolve_handover_employee(
        payload.employee_name, payload.department_id, payload.employee_user_id, strict=True)
    if emp_user:
        payload.employee_name = emp_user["name"]
        payload.employee_user_id = str(emp_user["_id"])
        if not payload.department_id:
            payload.department_id = emp_user.get("department_id")

    return_lines = await prepare_return_items([r.model_dump() for r in payload.return_items], emp_user)

    if items and return_lines:
        slip_type, prefix = "swap", "SW"
    elif return_lines:
        slip_type, prefix = "takeover", "TO"
    else:
        slip_type, prefix = "handover", "HO"
    slip_no = await _next_no(prefix, "handover")   # one shared counter -> slip numbers never repeat

    linked_req = None
    if items:
        if payload.requisition_id and ObjectId.is_valid(payload.requisition_id):
            r = await db.requisitions.find_one({"_id": ObjectId(payload.requisition_id)})
            if r and r.get("status") == READY_FOR_HANDOVER_STATUS:
                linked_req = r
        else:
            linked_req = await _find_requisition_for_handover(
                payload.employee_name, [it["item"] for it in items], payload.department_id)

    doc = {
        "slip_no": slip_no, "type": slip_type, "employee_name": payload.employee_name,
        "employee_user_id": payload.employee_user_id,
        "department_id": payload.department_id, "items": items, "return_items": return_lines,
        "return_received": False, "remarks": payload.remarks,
        "note": payload.note, "handover_date": payload.handover_date or now_iso(),
        "prepared_by": user["name"], "prepared_by_sign": payload.prepared_by_sign,
        "received_by_sign": payload.received_by_sign, "created_at": now_iso(),
        "status": "prepared", "requisition_id": str(linked_req["_id"]) if linked_req else None,
    }
    res = await db.handovers.insert_one(doc)
    hid = str(res.inserted_id)

    async def undo(msg: str):
        await _release_slip_locks(hid)
        await db.handovers.delete_one({"_id": res.inserted_id})
        raise HTTPException(status_code=409, detail=msg)

    # 1) reserve the units being issued. Atomic: succeeds only if the unit is STILL in stock.
    for it in items:
        aid = it.get("asset_id")
        if not aid or not ObjectId.is_valid(aid):
            continue
        r = await db.assets.update_one(
            {"_id": ObjectId(aid), "status": "in_stock", "pending_receipt": {"$ne": True}},
            {"$set": {
                "pending_receipt": True, "pending_handover_id": hid,
                "assigned_to_tentative": payload.employee_name,
                "assigned_department_id": payload.department_id}})
        if r.modified_count == 0:
            await undo("One of the selected units was just taken by another handover. "
                       "Nothing was saved - please pick the units again.")

    # 2) lock the returned assets. Atomic: succeeds only if it is STILL assigned.
    for ln in return_lines:
        r = await db.assets.update_one(
            {"_id": ObjectId(ln["asset_id"]), "status": "assigned"},
            {"$set": {"status": "return_pending", "pending_return_handover_id": hid,
                      "pending_return_slip_no": slip_no}})
        if r.modified_count == 0:
            await undo(f"{ln.get('item')} ({ln.get('tag_id') or ln.get('serial_no') or 'no tag'}) "
                       "changed while saving. Nothing was saved - reload and try again.")

    if linked_req:
        # Mirror /requisitions/{id}/issue-stock: put the requisition into the same
        # pending_handover stage that flow would, and notify the requester, so the existing
        # deliver -> confirm pipeline closes the requisition out correctly later.
        item_names = ", ".join(it["product_name"] for it in linked_req["items"])
        await db.notifications.insert_one({
            "user_id": linked_req.get("requisitioner_id"),
            "employee_name": linked_req.get("requisition_for") or linked_req["requisitioner_name"],
            "type": "stock_allocated", "requisition_id": str(linked_req["_id"]), "handover_id": hid,
            "message": f"Your requested item {item_names} has arrived in IT inventory and is being prepared for handover.",
            "status": "unread", "created_at": now_iso(),
        })
        linked_req.setdefault("history", []).append({
            "at": now_iso(), "by": user["name"], "action": "stock_issued",
            "note": f"Linked to handover slip {slip_no} (created via Handover Module)."})
        await db.requisitions.update_one({"_id": linked_req["_id"]}, {"$set": {
            "status": "pending_handover", "handover_id": hid,
            "history": linked_req["history"], "updated_at": now_iso()}})

    doc["_id"] = res.inserted_id
    if payload.receive_now and return_lines:
        try:
            await _apply_returns(doc, user)
        except HTTPException:
            # keep the slip (it is valid); IT can press "Received by IT" later
            pass
    return await _enrich_handover(doc)

@api_router.post("/handovers/{hid}/deliver")
async def mark_handover_delivered(hid: str, user: dict = Depends(get_current_user)):
    """'Handover Done' button: IT confirms they've printed the slip and physically
    delivered the item(s). This is what actually raises the requester's bell notification."""
    h = await db.handovers.find_one({"_id": ObjectId(hid)})
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
        req = await db.requisitions.find_one({"_id": ObjectId(h["requisition_id"])})
    # 1) the employee chosen on the slip (id saved at creation) — always wins.
    if h.get("employee_user_id") and ObjectId.is_valid(h["employee_user_id"]):
        emp_user = await db.users.find_one({"_id": ObjectId(h["employee_user_id"])})
    # 2) older slips: name + the slip's department (never a same-named user elsewhere).
    if not emp_user and h.get("employee_name"):
        emp_user = await resolve_handover_employee(h["employee_name"], h.get("department_id"), None, strict=False)
    # 3) linked requisition's requester — only if that person is in the slip's department.
    if not emp_user and req and req.get("requisitioner_id") and ObjectId.is_valid(req["requisitioner_id"]):
        cand = await db.users.find_one({"_id": ObjectId(req["requisitioner_id"])})
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
        cand = await db.assets.find_one({
            "name": {"$regex": f"^{re.escape(nm0)}$", "$options": "i"},
            "status": "in_stock", "pending_handover_id": hid,
            "_id": {"$nin": [ObjectId(x) for x in used if x and ObjectId.is_valid(x)]}})
        if not cand:
            cand = await db.assets.find_one({
                "name": {"$regex": f"^{re.escape(nm0)}$", "$options": "i"},
                "status": "in_stock", "pending_receipt": {"$ne": True},
                "_id": {"$nin": [ObjectId(x) for x in used if x and ObjectId.is_valid(x)]}})
        if cand:
            it["asset_id"] = str(cand["_id"])
            it["brand"] = it.get("brand") or cand.get("brand")
            used.add(it["asset_id"])
            changed = True
            await db.assets.update_one({"_id": cand["_id"]}, {"$set": {
                "pending_receipt": True, "pending_handover_id": hid,
                "assigned_to_tentative": h.get("employee_name"),
                "assigned_department_id": h.get("department_id")}})
    if changed:
        await db.handovers.update_one({"_id": ObjectId(hid)}, {"$set": {"items": items}})

    for it in items:
        aid = it.get("asset_id")
        asset = None
        if aid and ObjectId.is_valid(aid):
            asset = await db.assets.find_one({"_id": ObjectId(aid)})
        asset_name = (asset or {}).get("name") or it.get("item") or it.get("product_name") or "Item"
        asset_tag = (asset or {}).get("tag_id") or (asset or {}).get("serial_no")
        await db.notifications.insert_one({
            "user_id": target_user_id,
            "employee_name": h.get("employee_name") or (emp_user or {}).get("name"),
            "type": "asset_receipt",
            "asset_id": aid if aid and ObjectId.is_valid(aid) else None,
            "asset_name": asset_name,
            "asset_tag": asset_tag,
            "handover_id": hid,
            "slip_no": h.get("slip_no"),
            "requisition_id": h.get("requisition_id"),
            "message": f"Please confirm physical receipt of {asset_name}.",
            "status": "unread",
            "created_at": now_iso(),
        })
        notif_count += 1

    # Always create at least one confirmation notification even if handover has no line items
    if notif_count == 0:
        await db.notifications.insert_one({
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

    await db.handovers.update_one({"_id": ObjectId(hid)}, {"$set": {
        "status": "delivered", "delivered_by": user["name"], "delivered_at": now_iso()}})

    # The earlier "item is being prepared for handover" info notification is now superseded
    # by the receipt-confirmation one(s) above; mark it read so the requester doesn't see
    # a duplicate bell entry for the same slip.
    await db.notifications.update_many(
        {"handover_id": hid, "type": "stock_allocated", "status": "unread"},
        {"$set": {"status": "read", "acted_at": now_iso()}})

    if req:
        req.setdefault("history", []).append({
            "at": now_iso(), "by": user["name"], "action": "handover_delivered",
            "note": f"Physically delivered via slip {h['slip_no']}. Awaiting requester confirmation."})
        await db.requisitions.update_one({"_id": req["_id"]}, {"$set": {
            "status": "awaiting_requester_confirmation", "history": req["history"],
            "updated_at": now_iso()}})
    elif h.get("requisition_id") and ObjectId.is_valid(h["requisition_id"]):
        req2 = await db.requisitions.find_one({"_id": ObjectId(h["requisition_id"])})
        if req2:
            req2.setdefault("history", []).append({
                "at": now_iso(), "by": user["name"], "action": "handover_delivered",
                "note": f"Physically delivered via slip {h['slip_no']}. Awaiting requester confirmation."})
            await db.requisitions.update_one({"_id": req2["_id"]}, {"$set": {
                "status": "awaiting_requester_confirmation", "history": req2["history"],
                "updated_at": now_iso()}})

    return {
        "ok": True,
        "status": "delivered",
        "requisition_status": "awaiting_requester_confirmation",
        "notification_user_id": target_user_id,
        "notifications_created": max(notif_count, 1),
    }

class ReceiveLineIn(BaseModel):
    """Optional per-asset correction made while physically inspecting the device."""
    asset_id: str
    condition: Optional[Literal["good", "damaged", "missing_parts"]] = None
    next_status: Optional[Literal["in_stock", "under_repair", "scrapped"]] = None
    accessories: Optional[List[str]] = None
    data_wiped: Optional[bool] = None
    remarks: Optional[str] = None

class ReceiveReturnIn(BaseModel):
    lines: List[ReceiveLineIn] = []

@api_router.post("/handovers/{hid}/receive-return")
async def receive_return(hid: str, payload: ReceiveReturnIn = ReceiveReturnIn(),
                         user: dict = Depends(get_current_user)):
    """'Received by IT': the returned device(s) of a takeover (or swap) are physically in IT's
    hands. Each asset leaves the employee, gets its condition + destination, and lands in
    in_stock / under_repair / scrapped. A takeover slip becomes 'completed'."""
    if not await _can_manage_handovers(user):
        raise HTTPException(status_code=403, detail="Only IT / Super Admin can receive returned assets")
    if not ObjectId.is_valid(hid):
        raise HTTPException(status_code=404, detail="Slip not found")
    h = await db.handovers.find_one({"_id": ObjectId(hid)})
    if not h:
        raise HTTPException(status_code=404, detail="Slip not found")
    if not h.get("return_items"):
        raise HTTPException(status_code=400, detail="This slip has no returned assets to receive")
    if h.get("return_received"):
        raise HTTPException(status_code=400, detail="The returned assets were already received")
    n = await _apply_returns(h, user, {l.asset_id: l.model_dump(exclude_none=True) for l in payload.lines})
    return {"ok": True, "received": n, "status": h.get("status"), "slip_no": h.get("slip_no")}

@api_router.get("/users/{user_id}/held-assets")
async def employee_held_assets(user_id: str, user: dict = Depends(get_current_user)):
    """Everything this employee currently holds - drives the 'Currently holding' panel on the
    Handover form. Includes assets whose return is already in progress (flagged, not selectable)."""
    if not (await _can_manage_handovers(user) or str(user["_id"]) == user_id):
        raise HTTPException(status_code=403, detail="Not allowed")
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    emp = await db.users.find_one({"_id": ObjectId(user_id)})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    docs = await db.assets.find(_held_filter(emp)).sort("assigned_at", -1).to_list(200)
    # Consumables (tracked by quantity) are used up, not handed back, and an untagged unit cannot be
    # identified on a return slip - so they are not listed as something the employee can return.
    qty_names = {_skey(p["name"]) async for p in db.products.find({"product_type": "consumable"}, {"name": 1})}
    out = []
    for a in docs:
        if _skey(a.get("name")) in qty_names and not (a.get("tag_id") or a.get("serial_no")):
            continue
        out.append({
            "id": str(a["_id"]), "name": a.get("name"), "brand": a.get("brand"),
            "tag_id": a.get("tag_id"), "serial_no": a.get("serial_no"),
            "category_name": await resolve_category_name(a.get("category_id")) if a.get("category_id") else None,
            "assigned_at": a.get("assigned_at"), "assigned_slip_no": a.get("assigned_slip_no"),
            "status": a.get("status"), "return_pending": a.get("status") == "return_pending",
            "pending_return_slip_no": a.get("pending_return_slip_no"),
        })
    return {"employee": {"id": str(emp["_id"]), "name": emp["name"], "department_id": emp.get("department_id")},
            "assets": out}

@api_router.get("/assets/{aid}/history")
async def asset_history(aid: str, user: dict = Depends(get_current_user)):
    """Full life history of one asset, newest first."""
    if not await _can_manage_handovers(user):
        raise HTTPException(status_code=403, detail="Not allowed")
    docs = await db.asset_history.find({"asset_id": aid}).sort("at", -1).to_list(500)
    return [strip_id(d) for d in docs]

@api_router.delete("/handovers/{hid}")
async def delete_handover(hid: str, user: dict = Depends(require_roles("super_admin"))):
    h = await db.handovers.find_one({"_id": ObjectId(hid)})
    if h and h.get("status") == "prepared":
        # A slip that was never completed still holds locks: free the reserved stock and put
        # assets waiting to be returned back with their employee. Completed slips only lose
        # the record - their asset changes already happened and are kept in asset_history.
        await _release_slip_locks(hid)
    await db.handovers.delete_one({"_id": ObjectId(hid)})
    return {"ok": True}

# --------------------------- Notifications ---------------------------------
class NotifyConfirmIn(BaseModel):
    action: Literal["received", "pending"]

@api_router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    docs = await db.notifications.find({"user_id": str(user["_id"]), "status": {"$in": ["unread", "pending"]}}).sort("created_at", -1).to_list(100)
    return [strip_id(n) for n in docs]

@api_router.post("/notifications/{nid}/read")
async def mark_notification_read(nid: str, user: dict = Depends(get_current_user)):
    """Generic mark-as-read for informational notifications (e.g. type == 'stock_allocated')
    that don't need a Yes/No confirmation, unlike asset_receipt notifications."""
    n = await db.notifications.find_one({"_id": ObjectId(nid)})
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.get("user_id") != str(user["_id"]) and user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Not your notification")
    await db.notifications.update_one({"_id": ObjectId(nid)}, {"$set": {"status": "read", "acted_at": now_iso()}})
    return {"ok": True}

@api_router.post("/notifications/{nid}/confirm")
async def confirm_notification(nid: str, payload: NotifyConfirmIn, user: dict = Depends(get_current_user)):
    n = await db.notifications.find_one({"_id": ObjectId(nid)})
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not (n.get("user_id") == str(user["_id"]) or user["role"] == "super_admin"):
        raise HTTPException(status_code=403, detail="Not your notification")
    if n.get("status") not in ("unread", "pending"):
        raise HTTPException(status_code=400, detail="Notification already actioned")
    aid = n.get("asset_id")
    if payload.action == "received":
        # Employee confirmed receipt -> asset leaves central stock (deduct -1) and becomes assigned.
        if not (aid and ObjectId.is_valid(aid)) and n.get("asset_name"):
            # Older notifications / name-only handover lines have no asset_id, so nothing
            # would be deducted. Fall back to an in-stock asset of that name, preferring one
            # already reserved for this handover.
            nm = {"$regex": f"^{re.escape(n['asset_name'])}$", "$options": "i"}
            cand = await db.assets.find_one({"name": nm, "pending_handover_id": n.get("handover_id"),
                                             "status": "in_stock"}) if n.get("handover_id") else None
            if not cand:
                cand = await db.assets.find_one({"name": nm, "status": "in_stock",
                                                 "pending_receipt": {"$ne": True}})
            aid = str(cand["_id"]) if cand else None
        if aid and ObjectId.is_valid(aid):
            await db.assets.update_one({"_id": ObjectId(aid)}, {"$set": {
                "status": "assigned", "assigned_to": n.get("employee_name"),
                "assigned_to_user_id": n.get("user_id"),
                "assigned_at": now_iso(), "assigned_handover_id": n.get("handover_id"),
                "assigned_slip_no": n.get("slip_no"),
                "receipt_confirmed": True, "receipt_confirmed_at": now_iso(),
                "pending_receipt": False, "pending_handover_id": None, "assigned_to_tentative": None}})
            issued = await db.assets.find_one({"_id": ObjectId(aid)})
            if issued:
                await _log_asset_event(
                    issued, "issued", n.get("employee_name") or user["name"],
                    slip_no=n.get("slip_no"), handover_id=n.get("handover_id"),
                    employee_user_id=n.get("user_id"), employee_name=n.get("employee_name"))
        await db.notifications.update_one({"_id": ObjectId(nid)}, {"$set": {"status": "confirmed", "acted_at": now_iso()}})

        hid = n.get("handover_id")
        rid = n.get("requisition_id")
        # Fall back to resolving the requisition via the handover. Notifications created
        # before requisition_id was carried through (or via an ad-hoc handover) have no
        # requisition_id of their own, which previously left the requisition stuck at its
        # pre-confirmation status forever.
        if not rid and hid and ObjectId.is_valid(hid):
            h = await db.handovers.find_one({"_id": ObjectId(hid)})
            rid = (h or {}).get("requisition_id")

        requisition_status = None
        if hid and ObjectId.is_valid(hid):
            # Only finalize once every item on the linked handover has been confirmed —
            # a requisition (or an ad-hoc handover with multiple items) can have several
            # notifications tied to one handover.
            # Count ONLY receipt-confirmation notifications. The informational
            # "stock_allocated" notification created with the slip shares the same
            # handover_id and stays "unread" until dismissed, which used to keep this
            # counter above zero forever and leave the requisition stuck at
            # "awaiting requester confirmation".
            still_open = await db.notifications.count_documents({
                "handover_id": hid, "type": "asset_receipt",
                "status": {"$in": ["unread", "pending"]}})
            if still_open == 0:
                # The handover record itself moves past "delivered" (physically handed
                # over, awaiting confirmation) to "confirmed" — this is what fixes the UI
                # showing a final-looking "Delivered" badge the instant IT clicks Handover
                # Done, before the employee has actually confirmed anything.
                await db.handovers.update_one({"_id": ObjectId(hid)}, {"$set": {
                    "status": "confirmed", "confirmed_at": now_iso()}})
                if rid and ObjectId.is_valid(rid):
                    req = await db.requisitions.find_one({"_id": ObjectId(rid)})
                    if req:
                        req.setdefault("history", []).append({
                            "at": now_iso(), "by": n.get("employee_name") or "requester",
                            "action": "receipt_confirmed", "note": "Requester confirmed physical receipt."})
                        requisition_status = "handover_done"
                        await db.requisitions.update_one({"_id": ObjectId(rid)}, {"$set": {
                            "status": "handover_done", "history": req["history"],
                            "closed_at": now_iso(), "updated_at": now_iso()}})
        return {"ok": True, "status": "confirmed", "stock_deducted": bool(aid and ObjectId.is_valid(aid)),
                "requisition_id": rid, "requisition_status": requisition_status}
    await db.notifications.update_one({"_id": ObjectId(nid)}, {"$set": {"status": "pending", "acted_at": now_iso()}})
    return {"ok": True, "status": "pending", "stock_deducted": False}

# --------------------------- Handover / Takeover PDF -----------------------
def _img_from_datauri(uri):
    try:
        if not uri or "," not in uri:
            return None
        raw = base64.b64decode(uri.split(",", 1)[1])
        return RLImage(io.BytesIO(raw), width=45 * mm, height=18 * mm)
    except Exception:
        return None

def build_handover_pdf(h: dict, dept_name: Optional[str]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=16 * mm, rightMargin=16 * mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8, leading=10)
    story = [
        Paragraph("<b>Primitek Group</b>", ParagraphStyle("h", parent=styles["Title"], fontSize=15)),
        Paragraph("Head Office: Primitek Tower, House 43/B, Road 24, Block CWS(B), Gulshan 1, Dhaka-1212, Bangladesh", small),
        Spacer(1, 8),
        Paragraph(f"<b>{ {'handover': 'HAND OVER', 'takeover': 'TAKE OVER', 'swap': 'ASSET REPLACEMENT (TAKE OVER + HAND OVER)'}.get(h['type'], 'HAND OVER') }</b>",
                  ParagraphStyle("c", parent=styles["Heading2"], alignment=1)),
        Spacer(1, 6),
    ]
    meta = Table([["Slip No.", ": " + h["slip_no"], "Date", ": " + (h.get("handover_date") or "")[:10]]],
                 colWidths=[26 * mm, 55 * mm, 26 * mm, 55 * mm])
    meta.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story += [meta, Spacer(1, 8)]
    hdr_bg = colors.HexColor("#E2E8F0")
    grid = [("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), hdr_bg),
            ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    def tag_serial(it):
        parts = [x for x in (it.get("tag_id"), it.get("serial_no")) if x]
        return Paragraph("<br/>".join(parts) if parts else "-", small)

    # Returned part (takeover / swap): what the employee handed back and in what condition.
    ret = h.get("return_items") or []
    if ret:
        story.append(Paragraph("<b>ASSETS RETURNED (Taken Over from employee)</b>", small))
        story.append(Spacer(1, 3))
        rows = [["S.N.", "Name", "Item", "Brand", "Tag / Serial", "Condition", "Accessories"]]
        for i, it in enumerate(ret, 1):
            rows.append([str(i), Paragraph(h["employee_name"], small), Paragraph(it.get("item", ""), small),
                         it.get("brand") or "-", tag_serial(it),
                         CONDITION_LABELS.get(it.get("condition"), "-"),
                         Paragraph(", ".join(it.get("accessories") or []) or "-", small)])
        t = Table(rows, colWidths=[10 * mm, 26 * mm, 36 * mm, 20 * mm, 32 * mm, 22 * mm, 30 * mm])
        t.setStyle(TableStyle(grid))
        story += [t, Spacer(1, 8)]

    # Issued part (handover / swap). Columns follow the printed slip: S.N., Name, Dept., Item,
    # Brand, Quantity (Name/Dept repeated per row, matching the paper form) + Tag / Serial.
    if h.get("items"):
        if ret:
            story.append(Paragraph("<b>ASSETS ISSUED (Handed Over to employee)</b>", small))
            story.append(Spacer(1, 3))
        rows = [["S.N.", "Name", "Dept.", "Item", "Brand", "Tag / Serial", "Qty"]]
        for i, it in enumerate(h.get("items", []), 1):
            rows.append([str(i), Paragraph(h["employee_name"], small), Paragraph(dept_name or "-", small),
                         Paragraph(it.get("item", ""), small), it.get("brand") or "-", tag_serial(it),
                         str(it.get("quantity", 1))])
        t = Table(rows, colWidths=[10 * mm, 28 * mm, 24 * mm, 40 * mm, 22 * mm, 36 * mm, 12 * mm])
        t.setStyle(TableStyle(grid))
        story += [t, Spacer(1, 8)]
    if h.get("note"):
        story.append(Paragraph(f"<b>Note:</b> {h['note']}", small))
    story.append(Paragraph("Note: You are responsible for the proper care, handling, and safekeeping of the assigned IT Equipment. In case of any damage, loss, or theft while the device is under your custody, you will bear full responsibility. You are also required to return the IT Equipment in good condition upon request or when your assignment/employment ends.", small))
    story.append(Spacer(1, 16))
    prep = _img_from_datauri(h.get("prepared_by_sign")) or Paragraph(" ", small)
    recv = _img_from_datauri(h.get("received_by_sign")) or Paragraph(" ", small)
    sig = Table([[prep, recv, Paragraph(" ", small)], ["Prepared By (IT Staff)", "Received By (Employee)", "Checked By"]],
                colWidths=[58 * mm, 58 * mm, 42 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 1), (-1, 1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, 0), "BOTTOM")]))
    story.append(sig)
    doc.build(story)
    return buf.getvalue()

@api_router.get("/handovers/{hid}/pdf")
async def handover_pdf(hid: str, request: Request, auth: Optional[str] = None):
    token = auth or request.cookies.get("access_token")
    if not token or not await user_from_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    h = await db.handovers.find_one({"_id": ObjectId(hid)})
    if not h:
        raise HTTPException(status_code=404, detail="Not found")
    dept_name = None
    if h.get("department_id") and ObjectId.is_valid(h["department_id"]):
        dp = await db.departments.find_one({"_id": ObjectId(h["department_id"])})
        dept_name = dp["name"] if dp else None
    for it in h.get("items") or []:
        if it.get("asset_id") and ObjectId.is_valid(it["asset_id"]) and not (it.get("tag_id") or it.get("serial_no")):
            a = await db.assets.find_one({"_id": ObjectId(it["asset_id"])})
            if a:
                it["tag_id"], it["serial_no"] = a.get("tag_id"), a.get("serial_no")
    pdf = build_handover_pdf(h, dept_name)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{h["slip_no"]}.pdf"'})

# --------------------------- Assigned assets summary PDF -------------------
def build_assets_summary_pdf(assets: list, employees: int = 0) -> bytes:
    """Assigned-assets register: one row per asset currently with an employee - what it is, its
    serial / tag, who holds it, their department and WHEN it was assigned (landscape, inventory style)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=12 * mm, bottomMargin=12 * mm, leftMargin=10 * mm, rightMargin=10 * mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8, leading=10)
    tiny = ParagraphStyle("t", parent=styles["Normal"], fontSize=6.5, leading=8, textColor=colors.HexColor("#B45309"))
    story = [
        Paragraph("<b>Primitek Group</b>", ParagraphStyle("h", parent=styles["Title"], fontSize=15)),
        Paragraph("Assigned Assets \u2014 Inventory Register", small),
        Paragraph(f"Generated: {now_iso()[:19].replace('T', ' ')} UTC &nbsp;|&nbsp; "
                  f"{len(assets)} asset(s) assigned to {employees} employee(s)", small),
        Spacer(1, 8),
    ]
    head = ["#", "Asset", "Brand", "Serial No.", "Tag / ID", "Category", "Assigned To", "Department", "Assigned On", "Slip No."]
    rows = [head]
    for i, a in enumerate(assets, 1):
        when = (a.get("assigned_at") or "")[:10] or "-"
        on_cell = [Paragraph(when, small)]
        if a.get("status") == "return_pending":
            on_cell.append(Paragraph("Return pending", tiny))
        rows.append([
            str(i), Paragraph(a.get("name") or "", small), Paragraph(a.get("brand") or "-", small),
            Paragraph(a.get("serial_no") or "-", small), Paragraph(a.get("tag_id") or "-", small),
            Paragraph(a.get("category_name") or "-", small), Paragraph(a.get("assigned_to") or "-", small),
            Paragraph(a.get("assigned_department_name") or "-", small), on_cell,
            Paragraph(a.get("assigned_slip_no") or "-", small)])
    if len(rows) == 1:
        rows.append(["", Paragraph("No assets are currently assigned.", small)] + [""] * 8)
    widths = [8, 38, 24, 32, 26, 28, 32, 32, 26, 31]
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()

@api_router.get("/assets/summary/pdf")
async def assets_summary_pdf(request: Request, status: Optional[str] = None, auth: Optional[str] = None):
    token = auth or request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    pdf_user = await user_from_token(token)
    if not pdf_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if pdf_user["role"] == "executive":
        # This is an org-wide report (every employee's assigned assets) - restricted to
        # admin/approver roles, same as the rest of the global-data access rules.
        raise HTTPException(status_code=403, detail="Only Admin/Approver roles can download the org-wide asset summary")
    # Only assets that are with an employee right now (a return in progress still counts as held).
    # `status` can still narrow it further, e.g. ?status=return_pending.
    q = {"status": status} if status in ASSET_HELD_STATUSES else {"status": {"$in": ASSET_HELD_STATUSES}}
    docs = await db.assets.find(q).sort([("assigned_to", 1), ("assigned_at", 1)]).to_list(5000)
    # Used-up consumables (e.g. pens) are issued by quantity with no serial/tag, so they can't be
    # listed as individually identifiable inventory.
    qty_names = {_skey(p["name"]) async for p in db.products.find({"product_type": "consumable"}, {"name": 1})}
    docs = [a for a in docs if not (_skey(a.get("name")) in qty_names and not (a.get("tag_id") or a.get("serial_no")))]
    enriched = [await _enrich_asset(a) for a in docs]
    employees = len({(a.get("assigned_to_user_id") or a.get("assigned_to") or "").lower() for a in enriched})
    return Response(content=build_assets_summary_pdf(enriched, employees), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="assigned-assets-register.pdf"'})

# ---------------------------------------------------------------------------
# Purchase Orders — NEW, separate collection (db.purchase_orders)
#
# STEP 1 of the PR/PO redesign: schema + basic CRUD only. Nothing in the
# existing requisition/PR workflow (build_approval_chain, act_on_requisition,
# set_pr_pricing, compute_status, REQ_STATUSES, approval chain, roles/permissions)
# is touched by this section. A Purchase Order is a standalone document that
# references a requisition via requisition_id — exactly as specified: "PO is a
# NEW SEPARATE database collection/entity, genuinely separate from the
# Requisition/PR document... maintains a foreign key / reference link back to
# the parent Requisition."
#
# Full target state machine (for reference across upcoming steps — only the PO
# side is actually wired up yet in this step; MD/Accounts approval actions,
# the Dept-Head "Smart Bypass", the IT Head spec/qty review step, and linking
# PO approval back into the requisition's own status are all later steps):
#
#   PO (this collection), created by Purchase Dept once the PR's specs/qty
#   have been reviewed by IT Head:
#     draft
#       --submit, total > threshold--> pending_md_approval
#           --MD approves--> pending_accounts_approval
#           --MD rejects--> rejected
#       --submit, total <= threshold--> pending_accounts_approval
#       pending_accounts_approval
#           --Accounts approves--> approved_for_purchase
#           --Accounts rejects--> rejected
#     approved_for_purchase and rejected are terminal.
#
# Threshold: reuses the existing MD_THRESHOLD constant (50,000 BDT) as the
# default; making it admin-configurable is a later step, not part of Step 1.
# ---------------------------------------------------------------------------
PO_STATUSES = [
    "draft",
    "pending_purchase_head_approval",
    "pending_md_approval",
    "pending_accounts_head_approval",
    "approved",
    "rejected"
]
class POLineItemIn(BaseModel):
    product_id: Optional[str] = None
    product_name: Optional[str] = None      # catalog product (exact name)
    item_description: str                   # free-text description / specs
    brand_model: Optional[str] = None
    quantity: int = 1
    unit_price: float = 0

class CancelPRIn(BaseModel):
    note: Optional[str] = None

class PurchaseOrderIn(BaseModel):
    requisition_id: str
    vendor_id: Optional[str] = None
    vendor_name: str
    contact_person: Optional[str] = None
    vendor_email: Optional[str] = None
    bin_tin: Optional[str] = None
    delivery_location: Optional[str] = None
    attention_to: Optional[str] = None
    delivery_date: Optional[str] = None
    payment_terms: Optional[str] = None
    po_date: Optional[str] = None
    cs_reference_no: Optional[str] = None
    cs_attachment_file_ids: List[str] = []
    items: List[POLineItemIn]
    tax_percent: float = 5.0
    discount_amount: float = 0.0
    transport_charge: float = 0.0
    special_terms_notes: Optional[str] = None

def _po_line_total(it: dict) -> float:
    return round(it["quantity"] * it["unit_price"], 2)

def _po_totals(items: List[dict], tax_percent: float = 5.0, discount_amount: float = 0.0, transport_charge: float = 0.0) -> dict:
    sub_total = round(sum(it["quantity"] * it["unit_price"] for it in items), 2)
    total_tax = round(sub_total * (tax_percent / 100), 2)
    grand_total = round(sub_total + total_tax - discount_amount + transport_charge, 2)
    return {
        "sub_total": sub_total,
        "tax_percent": tax_percent,
        "total_tax": total_tax,
        "discount_amount": discount_amount,
        "transport_charge": transport_charge,
        "grand_total": grand_total,
    }

async def _enrich_po(doc: dict) -> dict:
    doc = strip_id(doc)
    req = None
    if ObjectId.is_valid(doc.get("requisition_id", "")):
        req = await db.requisitions.find_one({"_id": ObjectId(doc["requisition_id"])})
    doc["requisition_no"] = req.get("requisition_no") if req else None
    # Vendor quotation files attached on the PO form -> id + name + size, so approvers
    # can open them. Ids that aren't real stored files (old placeholder ids) are skipped.
    atts = []
    for fid in doc.get("cs_attachment_file_ids") or []:
        rec = await db.files.find_one({"id": fid, "is_deleted": False})
        if rec:
            atts.append({"id": fid, "name": rec.get("original_filename"), "size": rec.get("size")})
    doc["cs_attachments"] = atts
    return doc

@api_router.post("/requisitions/{req_id}/cancel-pr")
async def cancel_pending_pr(req_id: str, payload: CancelPRIn = CancelPRIn(), user: dict = Depends(get_current_user)):
    """PR raiser (can_raise_pr / IT Head / super_admin) cancels a requisition that is still
    awaiting a Purchase Requisition (status == pending_pr). Use when the item is no longer
    needed so it leaves the PR queue and the requester sees status 'PR Cancelled'."""
    can_raise = bool(user.get("can_raise_pr")) or user["role"] == "super_admin"
    if not can_raise:
        it_dept = await find_dept_by_name("IT")
        it_dept_id = str(it_dept["_id"]) if it_dept else None
        is_it_head = user["role"] == "dept_head" and user.get("department_id") == it_dept_id
        if not is_it_head:
            raise HTTPException(status_code=403, detail="Only a PR raiser (or IT Head) can cancel a pending PR")
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d.get("status") != "pending_pr":
        raise HTTPException(status_code=400, detail="Only requisitions awaiting PR (Out of Stock) can be cancelled this way")
    note = (payload.note or "").strip() or "PR cancelled — item no longer required."
    d.setdefault("history", []).append({
        "at": now_iso(), "by": user["name"], "action": "pr_cancelled", "note": note,
    })
    d["status"] = "pr_cancelled"
    d["updated_at"] = now_iso()
    d["closed_at"] = now_iso()
    await db.requisitions.update_one({"_id": ObjectId(req_id)}, {"$set": {
        "status": "pr_cancelled",
        "history": d["history"],
        "updated_at": d["updated_at"],
        "closed_at": d["closed_at"],
        "pr_cancel_note": note,
        "pr_cancelled_by": user["name"],
    }})
    return serialize_req(d)

# Requisition status that mirrors each Purchase Order stage, so the requester / IT / dashboards
# always see who the PO is actually waiting on (not a stale "Pending Purchase Head").
PO_TO_REQ_STATUS = {
    "draft": "po_draft",
    "pending_purchase_head_approval": "pending_purchase",
    "pending_md_approval": "pending_md",
    "pending_accounts_head_approval": "pending_accounts",
    "approved": "buy_process",
    "rejected": "rejected",
}

async def sync_requisition_status_from_po(po: dict, by: str, action: str, note: str):
    """Push the PO's current stage into the parent requisition's status + history."""
    rid = po.get("requisition_id")
    if not rid or not ObjectId.is_valid(rid):
        return
    req = await db.requisitions.find_one({"_id": ObjectId(rid)})
    if not req or req.get("status") in FINALIZED:
        return
    new_status = PO_TO_REQ_STATUS.get(po["status"])
    if not new_status:
        return
    req.setdefault("history", []).append({"at": now_iso(), "by": by, "action": action, "note": note})
    await db.requisitions.update_one({"_id": req["_id"]}, {"$set": {
        "status": new_status, "history": req["history"], "updated_at": now_iso()}})

@api_router.post("/purchase-orders")
async def create_purchase_order(payload: PurchaseOrderIn, user: dict = Depends(get_current_user)):
    """Create a new Purchase Order (draft). Only allowed when requisition is in pending_po_entry."""
    if not user.get("can_create_po"):
        raise HTTPException(status_code=403, detail="You are not allowed to create a Purchase Order")

    req = await db.requisitions.find_one({"_id": ObjectId(payload.requisition_id)}) if ObjectId.is_valid(payload.requisition_id) else None
    if not req:
        raise HTTPException(status_code=404, detail="Linked requisition not found")
    if req.get("status") != "pending_po_entry":
        raise HTTPException(status_code=400,
                            detail="This requisition is not awaiting a Purchase Order (IT Head must approve the PR review first)")

    items = [it.model_dump() for it in payload.items]
    for it in items:
        # Keep the catalog product and the free-text description as two separate fields.
        pn = (it.get("product_name") or "").strip() or it["item_description"]
        cat = await db.products.find_one({"name_key": _pkey(pn)})
        it["product_name"] = cat["name"] if cat else pn
        if "brand_model" in it and "specification" not in it:
            it["specification"] = it.get("brand_model")
        it["line_total"] = _po_line_total(it)

    totals = _po_totals(
        items,
        tax_percent=payload.tax_percent,
        discount_amount=payload.discount_amount,
        transport_charge=payload.transport_charge,
    )
    po_no = await _next_no("PO", "po")

    doc = {
        "po_number": po_no,
        "requisition_id": payload.requisition_id,
        "vendor_id": payload.vendor_id,
        "vendor_name": payload.vendor_name,
        "contact_person": payload.contact_person,
        "vendor_email": payload.vendor_email,
        "bin_tin": payload.bin_tin,
        "delivery_location": payload.delivery_location,
        "attention_to": payload.attention_to,
        "delivery_date": payload.delivery_date,
        "payment_terms": payload.payment_terms,
        "po_date": payload.po_date or now_iso()[:10],
        "cs_reference_no": payload.cs_reference_no,
        "cs_attachment_file_ids": payload.cs_attachment_file_ids,
        "items": items,
        "special_terms_notes": payload.special_terms_notes,
        **totals,
        "status": "draft",
        "approval_comments": [],
        "created_by": user["name"],
        "created_by_id": str(user["_id"]),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    res = await db.purchase_orders.insert_one(doc)
    doc["_id"] = res.inserted_id

    # Move parent requisition out of the pending_po_entry queue
    req.setdefault("history", []).append({
        "at": now_iso(),
        "by": user["name"],
        "action": "po_created",
        "note": f"Purchase Order {po_no} created by Purchase Dept (vendor: {payload.vendor_name})."
    })
    await db.requisitions.update_one(
        {"_id": req["_id"]},
        {"$set": {
            "po_id": str(doc["_id"]),
            "status": "po_draft",                  # leaves the File PR queue; PO not submitted yet
            "history": req["history"],
            "updated_at": now_iso()
        }}
    )

    return await _enrich_po(doc)

@api_router.get("/purchase-orders")
async def list_purchase_orders(mine: bool = False, user: dict = Depends(get_current_user)):
    is_purchase_head = (
        user["role"] == "purchase_head" or
        (user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")))
    )
    delegators = await active_delegators_of(user)
    if not (
        user.get("can_create_po")
        or user["role"] in ("super_admin", "md", "accounts", "purchase_head")
        or is_purchase_head
        or delegators
    ):
        return []
    q = {"$or": [{"created_by_id": str(user["_id"])}, {"created_by": user["name"]}]} if mine else {}
    docs = await db.purchase_orders.find(q).sort("created_at", -1).to_list(1000)
    out = []
    for d in docs:
        e = await _enrich_po(d)
        e["can_act"] = await po_user_can_act(d, user, delegators)
        out.append(e)
    return out


@api_router.get("/purchase-orders/next-number")
async def preview_next_po_number(user: dict = Depends(get_current_user)):
    """Preview of the number the next PO will get (does NOT consume it). Shown on the blank
    PO form; the real number is assigned atomically when the draft is saved."""
    year = datetime.now(timezone.utc).year
    c = await db.counters.find_one({"_id": f"po-{year}"})
    return {"po_number": f"PO-{year}-{((c or {}).get('seq', 0) + 1):04d}"}

@api_router.get("/purchase-orders/{po_id}")
async def get_purchase_order(po_id: str, user: dict = Depends(get_current_user)):
    is_purchase_head = (
        user["role"] == "purchase_head" or
        (user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")))
    )
    if not (
        user.get("can_create_po")
        or user["role"] in ("super_admin", "md", "accounts", "purchase_head")
        or is_purchase_head
    ):
        raise HTTPException(status_code=403, detail="Not allowed to view Purchase Orders")
    if not ObjectId.is_valid(po_id):
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    doc = await db.purchase_orders.find_one({"_id": ObjectId(po_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    return await _enrich_po(doc)

# ---------------------------------------------------------------------------
# Purchase Orders — STEP 2: submit-for-approval + MD/Accounts approve/reject
#
# Wires up the state machine documented in Step 1:
#   draft --submit--> pending_md_approval (grand_total > threshold)
#                  or pending_accounts_approval (grand_total <= threshold)
#   pending_md_approval --MD approves--> pending_accounts_approval
#                        --MD rejects--> rejected
#   pending_accounts_approval --Accounts approves--> approved_for_purchase
#                              --Accounts rejects--> rejected
#
# Still NOT part of this step: the Dept-Head "Smart Bypass", the IT Head
# spec/qty review step on the PR itself, and linking PO approval back into the
# requisition's own status (e.g. auto-advancing to GRN once approved_for_purchase).
# Those come in later steps.
# ---------------------------------------------------------------------------
MIN_CS_QUOTES = 3  # spec: "cs_attachments (Minimum 3 vendor quotes)"
DEFAULT_PO_THRESHOLD = MD_THRESHOLD  # spec: "Configurable Threshold Amount (Default: 50,000 BDT)"

async def get_po_threshold() -> float:
    doc = await db.system_settings.find_one({"_id": "po_threshold"})
    return doc["amount"] if doc else DEFAULT_PO_THRESHOLD

# POs at or below this amount skip the Accounts Head: the system records an automatic limit
# check instead of asking a person. Above it, Accounts Head approves as before.
DEFAULT_PO_ACCOUNTS_LIMIT = MD_THRESHOLD   # 50,000 BDT unless changed in settings

async def get_po_accounts_limit() -> float:
    doc = await db.system_settings.find_one({"_id": "po_accounts_limit"})
    return doc["amount"] if doc else DEFAULT_PO_ACCOUNTS_LIMIT

class POAccountsLimitIn(BaseModel):
    amount: float

@api_router.get("/settings/po-accounts-limit")
async def get_po_accounts_limit_setting(user: dict = Depends(get_current_user)):
    return {"amount": await get_po_accounts_limit()}

@api_router.put("/settings/po-accounts-limit")
async def set_po_accounts_limit_setting(payload: POAccountsLimitIn, user: dict = Depends(require_roles("super_admin"))):
    """Accounts Head approves a PO only when its total is ABOVE this amount. 0 = Accounts Head
    approves every PO (the old behaviour)."""
    if payload.amount < 0:
        raise HTTPException(status_code=400, detail="Limit must be a non-negative amount")
    await db.system_settings.update_one({"_id": "po_accounts_limit"}, {"$set": {
        "amount": payload.amount, "updated_at": now_iso(), "updated_by": user["name"]}}, upsert=True)
    return {"amount": payload.amount}

class POThresholdIn(BaseModel):
    amount: float

@api_router.get("/settings/po-threshold")
async def get_po_threshold_setting(user: dict = Depends(get_current_user)):
    return {"amount": await get_po_threshold()}

@api_router.put("/settings/po-threshold")
async def set_po_threshold_setting(payload: POThresholdIn, user: dict = Depends(require_roles("super_admin"))):
    """Super Admin only — this governs ONLY the new PO's MD-routing decision (Step 5's
    'Dynamic Financial Threshold Approval'). It is a separate setting from the existing
    MD_THRESHOLD constant that drives the original PR approval chain in build_pr_chain();
    that chain is untouched by this step."""
    if payload.amount < 0:
        raise HTTPException(status_code=400, detail="Threshold must be a non-negative amount")
    await db.system_settings.update_one({"_id": "po_threshold"}, {"$set": {
        "amount": payload.amount, "updated_by": user["name"], "updated_at": now_iso()}}, upsert=True)
    return {"amount": payload.amount}

class POActionIn(BaseModel):
    action: Literal["approve", "reject"]
    comment: Optional[str] = None

@api_router.post("/purchase-orders/{po_id}/submit")
async def submit_purchase_order(po_id: str, user: dict = Depends(get_current_user)):
    """Submit draft PO into approval flow.
    ≤ 50,000 → Purchase Head first
    > 50,000 → MD first (bypasses Purchase Head)
    """
    if not user.get("can_create_po"):
        raise HTTPException(status_code=403, detail="You are not allowed to submit a Purchase Order")
    if not ObjectId.is_valid(po_id):
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    po = await db.purchase_orders.find_one({"_id": ObjectId(po_id)})
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only a draft Purchase Order can be submitted")

    threshold = await get_po_threshold()
    if po["grand_total"] > threshold:
        next_status = "pending_md_approval"               # > 50k → MD
    else:
        next_status = "pending_purchase_head_approval"    # ≤ 50k → Purchase Head

    await db.purchase_orders.update_one(
        {"_id": po["_id"]},
        {"$set": {
            "status": next_status,
            "submitted_by": user["name"],
            "submitted_at": now_iso(),
            "threshold_at_submission": threshold,
            "updated_at": now_iso()
        }}
    )
    po["status"] = next_status
    await sync_requisition_status_from_po(
        po, user["name"], "po_submitted",
        f"Purchase Order {po['po_number']} submitted for approval ({next_status.replace('_', ' ')}).")
    return await _enrich_po(po)


@api_router.post("/purchase-orders/{po_id}/action")
async def act_on_purchase_order(po_id: str, payload: POActionIn, user: dict = Depends(get_current_user)):
    """Approve or reject a PO at the current stage.
    Stages:
      - pending_purchase_head_approval  → Purchase Head  → pending_accounts_head_approval
      - pending_md_approval             → MD             → pending_accounts_head_approval
      - pending_accounts_head_approval  → Accounts Head  → approved
    """
    if not ObjectId.is_valid(po_id):
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    po = await db.purchase_orders.find_one({"_id": ObjectId(po_id)})
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    stage_role = {
        "pending_purchase_head_approval": "purchase_head",
        "pending_md_approval": "md",
        "pending_accounts_head_approval": "accounts"
    }.get(po["status"])

    if not stage_role:
        raise HTTPException(status_code=400, detail="This Purchase Order is not currently awaiting approval")

    # Permission check: stage role holder, their on-leave delegate, Super Admin
    allowed = await po_user_can_act(po, user, await active_delegators_of(user))
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Only {ROLE_LABELS.get(stage_role, stage_role)} can act on this Purchase Order right now"
        )

    if payload.action == "reject":
        next_status = "rejected"
    else:
        # Approve path
        if po["status"] in ("pending_purchase_head_approval", "pending_md_approval"):
            acc_limit = await get_po_accounts_limit()
            if po["grand_total"] <= acc_limit:
                # Small PO: automatic limit check replaces the Accounts Head approval.
                next_status = "approved"
                auto_accounts_note = (f"Accounts Head approval not required: PO total {po['grand_total']:,.2f} "
                                      f"is within the automatic limit of {acc_limit:,.2f}.")
            else:
                next_status = "pending_accounts_head_approval"
        else:  # pending_accounts_head_approval
            next_status = "approved"

    comments = po.get("approval_comments", []) + [{
        "at": now_iso(),
        "by": user["name"],
        "role": stage_role,
        "action": payload.action,
        "comment": payload.comment,
    }]
    if payload.action == "approve" and locals().get("auto_accounts_note"):
        comments.append({"at": now_iso(), "by": "system", "role": "accounts",
                         "action": "auto_approve", "comment": auto_accounts_note})

    await db.purchase_orders.update_one(
        {"_id": po["_id"]},
        {"$set": {
            "status": next_status,
            "approval_comments": comments,
            "updated_at": now_iso()
        }}
    )
    po["status"] = next_status
    po["approval_comments"] = comments

    # Every stage change (not just the final one) is reflected on the parent requisition
    await sync_requisition_status_from_po(
        po, user["name"], "po_" + next_status,
        f"Purchase Order {po['po_number']}: {payload.action}d by {ROLE_LABELS.get(stage_role, stage_role)} "
        f"→ {next_status.replace('_', ' ')}.".replace("rejectd", "rejected"))

    return await _enrich_po(po)
# ===========================================================================
# IT SERVICE TICKET QUEUES  (Application  vs  Network_Infra)
#
#  * Routing: each service line carries a `service_category`; SERVICE_CATEGORIES maps it to an IT
#    sub-team. The requisition gets `it_team` at creation (route_service_requisition).
#  * No IT Head approval for standard tasks: the chain holds one already-approved "bypass" step, so
#    nothing waits on an approver; the ticket sits in the sub-team's shared queue.
#  * Visibility: Application executives -> Application tickets, Network_Infra executives ->
#    Network_Infra tickets, IT Head / Super Admin -> both (see it_queue_teams_for).
#  * Atomic transitions: claim / release / complete are single find_one_and_update calls whose
#    filter contains the status (and assignee), so two people can never claim or advance the same
#    ticket - the loser gets HTTP 409.
#  * Hardware that cannot be fixed on site goes through the External Repair workflow (below):
#    in progress -> pending_repair_approval (IT Head) -> product_in_service -> completed.
#    No swap slip / temporary replacement is involved, and the Handover module is not touched.
#  Nothing in this block is referenced by any PR / PO / approval endpoint.
# ===========================================================================
PRIORITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

async def service_queue_bypass_step(team: Optional[str] = None) -> dict:
    it_dept = await find_dept_by_name("IT")
    where = f" -> {IT_TEAM_LABELS[team]} queue" if team else ""
    return {
        "level": 1, "role": "dept_head", "label": f"IT Head approval bypassed{where}",
        "department_id": str(it_dept["_id"]) if it_dept else None,
        "approver_id": None, "approver_name": None, "status": "approved", "stage": "it_queue_bypass",
        "note": "Standard service task: no IT Head approval required.",
        "acted_at": now_iso(), "acted_by_name": "system", "pending_since": now_iso(),
    }

async def route_service_requisition(doc: dict) -> None:
    """Called once from create_requisition for service requisitions (before insert)."""
    team = service_team_for_items(doc["items"])
    doc["it_team"] = team
    doc["approval_chain"] = [await service_queue_bypass_step(team)]
    doc["status"] = SERVICE_QUEUE_OPEN
    doc["service_assigned_to_id"] = None
    doc["service_assigned_to_name"] = None
    doc["history"].append({
        "at": now_iso(), "by": "system", "action": "it_queue_routed",
        "note": f"Routed to the {IT_TEAM_LABELS[team]} shared queue. IT Head approval bypassed (standard service task)."})

async def notify_service_queue(doc: dict) -> None:
    """Bell notification to the owning sub-team's executives and the IT Head."""
    team = doc.get("it_team")
    it_dept = await find_dept_by_name("IT")
    if not team or not it_dept:
        return
    msg = f"New {IT_TEAM_LABELS[team]} ticket {doc['requisition_no']}: {doc['items'][0]['product_name']} (requested by {doc['requisitioner_name']})."
    async for u in db.users.find({"department_id": str(it_dept["_id"]),
                                  "$or": [{"it_team": team}, {"role": "dept_head"}]}):
        if str(u["_id"]) != doc.get("requisitioner_id"):
            await _notify(str(u["_id"]), "it_service_ticket", msg, requisition_id=str(doc["_id"]))

def _is_hardware_ticket(t: dict) -> bool:
    return t.get("it_team") == "Network_Infra" and any(
        it.get("service_category") == "hardware_support" for it in t.get("items", []))

def _ticket_priority(t: dict) -> str:
    best = max((it.get("priority") or "low" for it in t.get("items", [])), key=lambda p: PRIORITY_RANK.get(p, 0), default="low")
    return best

async def _ticket_actions(t: dict, user: dict, teams: List[str]) -> dict:
    """What this user may do to this ticket right now (drives the buttons; the endpoints enforce it)."""
    uid = str(user["_id"])
    is_head = user.get("role") == "super_admin" or await _is_it_head(user)
    mine = t.get("service_assigned_to_id") == uid
    in_team = t.get("it_team") in teams
    st = t.get("status")
    return {
        "claim": in_team and st == SERVICE_QUEUE_OPEN,
        "release": in_team and st == SERVICE_QUEUE_ACTIVE and (mine or is_head),
        "complete": in_team and st == SERVICE_QUEUE_ACTIVE and (mine or is_head),
        # External repair: Network_Infra hardware tickets only.
        "request_repair": (in_team and st == SERVICE_QUEUE_ACTIVE and (mine or is_head)
                           and _is_hardware_ticket(t)),
        "decide_repair": in_team and st == SERVICE_REPAIR_PENDING and is_head,
        "mark_repaired": in_team and st == SERVICE_IN_SERVICE and (mine or is_head),
    }

async def _load_visible_ticket(ticket_id: str, user: dict) -> tuple[dict, List[str]]:
    teams = await it_queue_teams_for(user)
    if not teams:
        raise HTTPException(status_code=403, detail="You do not have access to the IT service queues")
    if not ObjectId.is_valid(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    t = await db.requisitions.find_one({"_id": ObjectId(ticket_id), "requisition_type": "service",
                                        "it_team": {"$in": IT_TEAMS}})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if t["it_team"] not in teams:
        # Same answer as "not found" would leak less, but a clear 403 is friendlier for staff.
        raise HTTPException(status_code=403, detail=f"This ticket belongs to the {IT_TEAM_LABELS[t['it_team']]} queue")
    return t, teams

async def _serialize_ticket(t: dict, user: dict, teams: List[str]) -> dict:
    out = serialize_req(t)
    out["priority"] = _ticket_priority(t)
    out["it_team_label"] = IT_TEAM_LABELS.get(t.get("it_team"), t.get("it_team"))
    out["actions"] = await _ticket_actions(t, user, teams)
    return out

@api_router.get("/it-service/queue")
async def it_service_queue(view: str = "open", team: Optional[str] = None, limit: int = 0, user: dict = Depends(get_current_user)):
    """Tickets the caller may see. view: open (unclaimed) | active (picked up, incl. repair stages) |
    repair (waiting for repair approval / at the service center) | mine | done | all.
    `team` narrows IT Head / Super Admin to one queue; an executive only ever gets their own."""
    teams = await it_queue_teams_for(user)
    if not teams:
        raise HTTPException(status_code=403, detail=(
            "You are not assigned to an IT sub-team. Ask Super Admin to set your IT team (Application / Network_Infra)."))
    if team:
        if team not in IT_TEAMS:
            raise HTTPException(status_code=400, detail="Unknown IT team")
        if team not in teams:
            raise HTTPException(status_code=403, detail=f"You cannot view the {IT_TEAM_LABELS[team]} queue")
        scope = [team]
    else:
        scope = teams
    base = {"requisition_type": "service", "it_team": {"$in": scope}}
    uid = str(user["_id"])
    q = dict(base)
    if view == "open":
        q["status"] = SERVICE_QUEUE_OPEN
    elif view == "active":
        q["status"] = {"$in": SERVICE_WORKING}
    elif view == "repair":
        q["status"] = {"$in": [SERVICE_REPAIR_PENDING, SERVICE_IN_SERVICE]}
    elif view == "mine":
        q.update({"status": {"$in": SERVICE_WORKING}, "service_assigned_to_id": uid})
    elif view == "done":
        q["status"] = SERVICE_QUEUE_DONE
    elif view == "all":
        q["status"] = {"$in": [SERVICE_QUEUE_OPEN, *SERVICE_WORKING, SERVICE_QUEUE_DONE]}
    else:
        raise HTTPException(status_code=400, detail="Unknown view")
    docs = await db.requisitions.find(q).sort("created_at", 1).to_list(500)
    if view == "done":
        docs = docs[-200:]
    tickets = [await _serialize_ticket(d, user, teams) for d in docs]
    if view != "done":      # most urgent first, then oldest first
        tickets.sort(key=lambda x: (-PRIORITY_RANK.get(x["priority"], 0), x.get("created_at") or ""))
    else:
        tickets.reverse()
    if limit and limit > 0:          # dashboard card: just the newest/most urgent few
        tickets = tickets[:limit]
    await attach_department_names(await attach_file_info(tickets))
    counts = {
        "open": await db.requisitions.count_documents({**base, "status": SERVICE_QUEUE_OPEN}),
        "active": await db.requisitions.count_documents({**base, "status": {"$in": SERVICE_WORKING}}),
        "repair": await db.requisitions.count_documents({**base, "status": {"$in": [SERVICE_REPAIR_PENDING, SERVICE_IN_SERVICE]}}),
        "repair_approvals": await db.requisitions.count_documents({**base, "status": SERVICE_REPAIR_PENDING}),
        "mine": await db.requisitions.count_documents({**base, "status": {"$in": SERVICE_WORKING}, "service_assigned_to_id": uid}),
    }
    return {"allowed_teams": [{"key": k, "label": IT_TEAM_LABELS[k]} for k in teams],
            "viewing": scope, "counts": counts, "tickets": tickets}

@api_router.get("/it-service/tickets/{ticket_id}")
async def it_service_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    t, teams = await _load_visible_ticket(ticket_id, user)
    out = await _serialize_ticket(t, user, teams)
    await attach_department_names(await attach_file_info([out]))
    return out

class ServiceNoteIn(BaseModel):
    note: Optional[str] = None

async def _atomic_ticket_transition(ticket_id: str, flt: dict, set_fields: dict, action: str,
                                    note: Optional[str], user: dict, conflict_msg) -> dict:
    """One find_one_and_update: the filter carries the status/assignee the caller expects, so only
    ONE of several simultaneous callers can win. The loser gets 409 with the current owner."""
    entry = {"at": now_iso(), "by": user["name"], "action": action, "note": note}
    res = await db.requisitions.find_one_and_update(
        {"_id": ObjectId(ticket_id), "requisition_type": "service", **flt},
        {"$set": {**set_fields, "updated_at": now_iso()}, "$push": {"history": entry}},
        return_document=ReturnDocument.AFTER)
    if not res:
        cur = await db.requisitions.find_one({"_id": ObjectId(ticket_id)})
        raise HTTPException(status_code=409, detail=conflict_msg(cur or {}))
    return res

@api_router.post("/it-service/tickets/{ticket_id}/claim")
async def it_service_claim(ticket_id: str, user: dict = Depends(get_current_user)):
    """Pick up a ticket from the shared queue (open -> in progress). Atomic."""
    t, teams = await _load_visible_ticket(ticket_id, user)
    def conflict(cur):
        if cur.get("service_assigned_to_name") and cur.get("status") == SERVICE_QUEUE_ACTIVE:
            return f"Already picked up by {cur['service_assigned_to_name']}."
        return "This ticket is no longer waiting in the queue."
    res = await _atomic_ticket_transition(
        ticket_id,
        {"it_team": t["it_team"], "status": SERVICE_QUEUE_OPEN, "service_assigned_to_id": None},
        {"status": SERVICE_QUEUE_ACTIVE, "service_assigned_to_id": str(user["_id"]),
         "service_assigned_to_name": user["name"], "service_claimed_at": now_iso()},
        "service:picked_up", f"Picked up by {user['name']}", user, conflict)
    await _notify(res.get("requisitioner_id"), "it_service_update",
                  f"{res['requisition_no']} has been picked up by {user['name']} ({IT_TEAM_LABELS[res['it_team']]}).",
                  requisition_id=ticket_id)
    return await _serialize_ticket(res, user, teams)

@api_router.post("/it-service/tickets/{ticket_id}/release")
async def it_service_release(ticket_id: str, payload: ServiceNoteIn, user: dict = Depends(get_current_user)):
    """Put a picked-up ticket back in the shared queue. Assignee, IT Head or Super Admin. Atomic."""
    t, teams = await _load_visible_ticket(ticket_id, user)
    is_head = user.get("role") == "super_admin" or await _is_it_head(user)
    flt = {"it_team": t["it_team"], "status": SERVICE_QUEUE_ACTIVE}
    if not is_head:
        flt["service_assigned_to_id"] = str(user["_id"])
    res = await _atomic_ticket_transition(
        ticket_id, flt,
        {"status": SERVICE_QUEUE_OPEN, "service_assigned_to_id": None, "service_assigned_to_name": None,
         "service_claimed_at": None},
        "service:released", payload.note or f"Returned to queue by {user['name']}", user,
        lambda cur: "Only the person who picked this ticket up (or the IT Head) can release it."
                    if cur.get("status") == SERVICE_QUEUE_ACTIVE else "This ticket is not in progress.")
    return await _serialize_ticket(res, user, teams)

@api_router.post("/it-service/tickets/{ticket_id}/complete")
async def it_service_complete(ticket_id: str, payload: ServiceNoteIn, user: dict = Depends(get_current_user)):
    """Finish a picked-up ticket (in progress -> completed). Assignee, IT Head or Super Admin. Atomic."""
    t, teams = await _load_visible_ticket(ticket_id, user)
    is_head = user.get("role") == "super_admin" or await _is_it_head(user)
    flt = {"it_team": t["it_team"], "status": SERVICE_QUEUE_ACTIVE}
    if not is_head:
        flt["service_assigned_to_id"] = str(user["_id"])
    res = await _atomic_ticket_transition(
        ticket_id, flt,
        {"status": SERVICE_QUEUE_DONE, "service_completed_at": now_iso(), "service_completed_by": user["name"]},
        f"service:{SERVICE_QUEUE_DONE}", payload.note, user,
        lambda cur: "Only the person who picked this ticket up (or the IT Head) can complete it."
                    if cur.get("status") == SERVICE_QUEUE_ACTIVE else "This ticket is not in progress.")
    await _notify(res.get("requisitioner_id"), "it_service_update",
                  f"{res['requisition_no']} has been completed by {user['name']}.", requisition_id=ticket_id)
    return await _serialize_ticket(res, user, teams)

# ---- External repair workflow ------------------------------------------------------------
#   service_in_progress --request-repair--> pending_repair_approval
#   pending_repair_approval --approve--> product_in_service          (IT Head / Super Admin)
#   pending_repair_approval --reject---> service_in_progress         (with the Head's feedback)
#   product_in_service --mark-repaired--> service_completed_and_returned
# Every hop is one atomic find_one_and_update that names the status it expects, so a request can
# be decided once and a repair closed once. The assignee stays on the ticket throughout.
class RepairRequestIn(BaseModel):
    reason: str
    device_details: Optional[str] = None      # e.g. tag / serial / what was checked on site

class RepairDecisionIn(BaseModel):
    action: Literal["approve", "reject"]
    note: Optional[str] = None                # required when rejecting (feedback to the executive)
    service_center: Optional[str] = None      # optional vendor / service center name on approval

async def _notify_it_heads(msg: str, ticket_id: str) -> None:
    it_dept = await find_dept_by_name("IT")
    if not it_dept:
        return
    async for h in db.users.find({"department_id": str(it_dept["_id"]), "role": "dept_head"}):
        await _notify_with_delegate(h, "it_service_repair", msg, requisition_id=ticket_id)

@api_router.post("/it-service/tickets/{ticket_id}/request-repair")
async def it_service_request_repair(ticket_id: str, payload: RepairRequestIn, user: dict = Depends(get_current_user)):
    """Executive could not fix a hardware task on site -> ask the IT Head to approve sending it to
    an external service center. Nothing is swapped or replaced for the user meanwhile."""
    t, teams = await _load_visible_ticket(ticket_id, user)
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Explain why this cannot be repaired on site")
    if not _is_hardware_ticket(t):
        raise HTTPException(status_code=400, detail="External repair applies to Network & Infra hardware tickets only")
    is_head = user.get("role") == "super_admin" or await _is_it_head(user)
    flt = {"it_team": "Network_Infra", "status": SERVICE_QUEUE_ACTIVE}
    if not is_head:
        flt["service_assigned_to_id"] = str(user["_id"])
    req = {"reason": reason, "device_details": (payload.device_details or "").strip() or None,
           "requested_by": user["name"], "requested_by_id": str(user["_id"]), "requested_at": now_iso(),
           "status": "pending", "decided_by": None, "decided_at": None, "decision_note": None, "service_center": None}
    res = await _atomic_ticket_transition(
        ticket_id, flt, {"status": SERVICE_REPAIR_PENDING, "repair_request": req},
        "repair:requested", reason, user,
        lambda cur: "Only the person handling this ticket (or the IT Head) can request an external repair."
                    if cur.get("status") == SERVICE_QUEUE_ACTIVE else "This ticket is not in progress.")
    await _notify_it_heads(f"Repair approval needed: {res['requisition_no']} ({res['items'][0]['product_name']}) - {reason}", ticket_id)
    return await _serialize_ticket(res, user, teams)

@api_router.post("/it-service/tickets/{ticket_id}/repair-decision")
async def it_service_repair_decision(ticket_id: str, payload: RepairDecisionIn, user: dict = Depends(get_current_user)):
    """IT Head (or Super Admin) approves or rejects the external-repair request."""
    t, teams = await _load_visible_ticket(ticket_id, user)
    if not (user.get("role") == "super_admin" or await _is_it_head(user)):
        raise HTTPException(status_code=403, detail="Only the IT Head can approve or reject an external repair")
    note = (payload.note or "").strip()
    if payload.action == "reject" and not note:
        raise HTTPException(status_code=400, detail="Give the executive feedback when rejecting")
    approve = payload.action == "approve"
    center = (payload.service_center or "").strip() or None
    decision = {"repair_request.status": "approved" if approve else "rejected",
                "repair_request.decided_by": user["name"], "repair_request.decided_at": now_iso(),
                "repair_request.decision_note": note or None, "repair_request.service_center": center}
    res = await _atomic_ticket_transition(
        ticket_id, {"it_team": "Network_Infra", "status": SERVICE_REPAIR_PENDING},
        {"status": SERVICE_IN_SERVICE if approve else SERVICE_QUEUE_ACTIVE, **decision},
        "repair:approved" if approve else "repair:rejected",
        (note or None) if not approve else (f"Sent to {center}. " if center else "") + (note or "Approved for external repair."),
        user, lambda cur: "This repair request has already been decided." if cur.get("status") != SERVICE_REPAIR_PENDING
                          else "Could not update the ticket. Reload and try again.")
    ref = res["requisition_no"]
    if approve:
        await _notify(res.get("requisitioner_id"), "it_service_update",
                      f"{ref}: your item has been sent to the service center for repair.", requisition_id=ticket_id)
        await _notify(res.get("service_assigned_to_id"), "it_service_update",
                      f"{ref}: external repair approved by {user['name']}. Item is now at the service center.", requisition_id=ticket_id)
    else:
        await _notify(res.get("service_assigned_to_id"), "it_service_update",
                      f"{ref}: external repair rejected by {user['name']} - {note}", requisition_id=ticket_id)
    return await _serialize_ticket(res, user, teams)

@api_router.post("/it-service/tickets/{ticket_id}/mark-repaired")
async def it_service_mark_repaired(ticket_id: str, payload: ServiceNoteIn, user: dict = Depends(get_current_user)):
    """Item is back from the service center and handed to the user -> close the ticket."""
    t, teams = await _load_visible_ticket(ticket_id, user)
    is_head = user.get("role") == "super_admin" or await _is_it_head(user)
    flt = {"it_team": "Network_Infra", "status": SERVICE_IN_SERVICE}
    if not is_head:
        flt["service_assigned_to_id"] = str(user["_id"])
    res = await _atomic_ticket_transition(
        ticket_id, flt,
        {"status": SERVICE_QUEUE_DONE, "service_completed_at": now_iso(), "service_completed_by": user["name"],
         "repair_request.returned_at": now_iso()},
        "repair:repaired_and_delivered", payload.note or "Repaired and delivered back to the user.", user,
        lambda cur: "Only the person handling this ticket (or the IT Head) can close it."
                    if cur.get("status") == SERVICE_IN_SERVICE else "This ticket is not at the service center.")
    await _notify(res.get("requisitioner_id"), "it_service_update",
                  f"{res['requisition_no']}: your item has been repaired and delivered back to you.", requisition_id=ticket_id)
    return await _serialize_ticket(res, user, teams)


# ===========================================================================
# MASTER AUDIT REPORT  (PR + SR lifecycle, generated on demand)
#
#  * Nothing is written to storage: the PDF is rendered in memory (io.BytesIO) from the live
#    database records every time it is requested, then streamed back inline.
#  * Read-only: it only READS requisitions / purchase_orders / handovers / users / departments.
#    No approval, PO, queue-filter or atomic-transition code is touched or called.
#  * GET /api/audit/requisitions/{req_no}      -> JSON summary card for the search page
#    GET /api/requisitions/{req_no}/audit-pdf  -> application/pdf, Content-Disposition: inline
# ===========================================================================
from xml.sax.saxutils import escape as _xml_escape
from reportlab.pdfgen import canvas as _rl_canvas
from reportlab.platypus import KeepTogether

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
}

def _a_dt(v) -> str:
    dt = _parse_iso(v) if isinstance(v, str) else v
    return dt.astimezone(_AUDIT_TZ).strftime("%d %b %Y, %H:%M") if dt else "-"

def _a_txt(v, dash: str = "-") -> str:
    v = (str(v).strip() if v is not None else "")
    return _xml_escape(v) if v else dash

def _a_label(action: str) -> str:
    if action in _AUDIT_ACTION_LABELS:
        return _AUDIT_ACTION_LABELS[action]
    return (action or "event").replace("service:", "Service: ").replace("_", " ").replace(":", ": ").capitalize()

def audit_request_type(d: dict) -> str:
    return "SR" if d.get("requisition_type") == "service" else "PR"

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

def build_audit_pdf(data: dict, generated_by: str) -> bytes:
    """Pure function: `data` is the dict produced by collect_audit_data(). Returns PDF bytes."""
    d, pos, hos = data["req"], data["pos"], data["handovers"]
    is_sr = d.get("requisition_type") == "service"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            title=f"Audit Report {d['requisition_no']}", author="Primitek Group")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("ab", parent=ss["Normal"], fontSize=8.5, leading=11)
    bold = ParagraphStyle("abb", parent=body, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("ah2", parent=ss["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#0f172a"))
    th = ParagraphStyle("ath", parent=body, fontName="Helvetica-Bold", textColor=colors.white)
    W = 182 * mm
    NAVY, LINE, ZEBRA = colors.HexColor("#0f172a"), colors.HexColor("#cbd5e1"), colors.HexColor("#f1f5f9")
    P = lambda t, st=body: Paragraph(t, st)

    def grid(rows, widths, header=True):
        rows = [[c if not isinstance(c, str) else P(c, th if (header and i == 0) else body) for c in r] for i, r in enumerate(rows)]
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), NAVY)]
            st += [("BACKGROUND", (0, i), (-1, i), ZEBRA) for i in range(2, len(rows), 2)]
        t.setStyle(TableStyle(st))
        return t

    def kv(pairs):          # two key/value pairs per row
        rows = []
        for i in range(0, len(pairs), 2):
            a = pairs[i]; b = pairs[i + 1] if i + 1 < len(pairs) else ("", "")
            rows.append([P(a[0], bold), P(a[1]), P(b[0], bold), P(b[1])])
        t = Table(rows, colWidths=[30 * mm, 61 * mm, 30 * mm, 61 * mm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (0, -1), ZEBRA), ("BACKGROUND", (2, 0), (2, -1), ZEBRA),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    story = []
    story.append(P("<b>Primitek Group</b>", ParagraphStyle("t1", parent=ss["Title"], fontSize=16, spaceAfter=0)))
    story.append(P("Master Audit Report - Requisition Lifecycle (all times UTC+6, Bangladesh)", ParagraphStyle("t2", parent=body, alignment=1, fontSize=10, textColor=colors.HexColor("#475569"))))
    story.append(Spacer(1, 6))
    story.append(P(f"<b>{_a_txt(d['requisition_no'])}</b> &nbsp; <font size=9 color='#475569'>"
                   f"{'Service Requisition (SR)' if is_sr else 'Product Requisition (PR)'}</font>",
                   ParagraphStyle("t3", parent=ss["Heading2"], alignment=1, fontSize=15)))

    # ---- 1. metadata ---------------------------------------------------------------------
    u, dept = data.get("requester") or {}, data.get("department_name")
    story.append(P("1. Requisition Details", h2))
    story.append(kv([
        ("Requisition No.", _a_txt(d["requisition_no"])), ("Request Type", "SR - Service" if is_sr else "PR - Product"),
        ("Created On", _a_dt(d.get("created_at"))), ("Current Status", _a_txt((d.get("status") or "").replace("_", " ").title())),
        ("Requisitioner", _a_txt(d.get("requisitioner_name"))), ("Department", _a_txt(dept)),
        ("Email", _a_txt(u.get("email"))), ("Phone", _a_txt(u.get("phone") or u.get("mobile"))),
        ("Requested For", _a_txt(d.get("requisition_for"))), ("Requisition Date", _a_dt(d.get("requisition_date"))),
    ]))

    # ---- 2. scope ------------------------------------------------------------------------
    story.append(P("2. Service Scope" if is_sr else "2. Item Scope", h2))
    if is_sr:
        story.append(P(f"<b>Assigned IT sub-team:</b> {_a_txt(IT_TEAM_LABELS.get(d.get('it_team'), d.get('it_team')), 'Not routed (created before sub-team routing)')}"))
        rows = [["#", "Service Category", "Device / Detail", "Priority", "Issue Description"]]
        for i, it in enumerate(d.get("items") or [], 1):
            cat = SERVICE_CATEGORIES.get(it.get("service_category"), (it.get("product_name"), None))[0]
            rows.append([str(i), _a_txt(cat), _a_txt(it.get("request_detail")), _a_txt((it.get("priority") or "").title()), _a_txt(it.get("remarks"))])
        story.append(grid(rows, [8 * mm, 52 * mm, 30 * mm, 20 * mm, 72 * mm]))
    else:
        rows = [["#", "Item", "Qty", "Type", "Specifications / Remarks"]]
        for i, it in enumerate(d.get("items") or [], 1):
            spec = " | ".join(x for x in [it.get("detailed_specs"), (f"Brand: {it['preferred_brand']}" if it.get("preferred_brand") else None),
                                          it.get("justification_remarks") or it.get("remarks")] if x)
            rows.append([str(i), _a_txt(it.get("product_name") or it.get("category")), _a_txt(f"{it.get('quantity', '')} {it.get('uom') or ''}".strip()),
                         _a_txt((it.get("product_type") or "").replace("_", " ").title()), _a_txt(spec)])
        story.append(grid(rows, [8 * mm, 52 * mm, 18 * mm, 28 * mm, 76 * mm]))
        extra = [(k, v) for k, v in [("Business justification", d.get("overall_business_justification")), ("Required by", d.get("required_by_date")),
                                    ("Urgency", d.get("urgency_level")), ("Delivery location", d.get("delivery_location")),
                                    ("Stock check at submission", (d.get("stock_check_at_submission") or "").replace("_", " "))] if v]
        if extra:
            story.append(Spacer(1, 4)); story.append(kv([(k, _a_txt(v)) for k, v in extra]))
    if d.get("requester_note"):
        story.append(Spacer(1, 3)); story.append(P(f"<b>Requester note:</b> {_a_txt(d['requester_note'])}"))

    # ---- 3. approvals --------------------------------------------------------------------
    story.append(P("3. Approval History", h2))
    chain = d.get("approval_chain") or []
    rows = [["Level", "Step", "Approver", "Decision", "Date / Time", "Remarks"]]
    for s in chain:
        who = s.get("acted_by_name") or s.get("approver_name") or "-"
        if s.get("acted_as") == "delegate":
            who += " (delegate)"
        if s.get("stage") == "it_queue_bypass":
            who = "System"
        rows.append([str(s.get("level", "")), _a_txt(s.get("label")), _a_txt(who),
                     _a_txt((s.get("status") or "").replace("_", " ").title()),
                     _a_dt(s.get("acted_at")) if s.get("acted_at") else "-", _a_txt(s.get("note"))])
    if len(rows) == 1:
        rows.append(["-", "No approval steps recorded", "-", "-", "-", "-"])
    story.append(grid(rows, [12 * mm, 44 * mm, 32 * mm, 22 * mm, 32 * mm, 40 * mm]))
    if not is_sr and (d.get("pr_filed_by") or d.get("purchase_pr_no")):
        story.append(Spacer(1, 3))
        story.append(P(f"<b>Purchase Requisition:</b> {_a_txt(d.get('purchase_pr_no'), 'number not yet generated')} - filed by "
                       f"{_a_txt(d.get('pr_filed_by'))} on {_a_dt(next((h.get('at') for h in (d.get('history') or []) if h.get('action') == 'pr_filed'), None))}"))

    # ---- 4. PR: procurement / SR: IT handling ---------------------------------------------
    if is_sr:
        story.append(P("4. IT Handling &amp; External Repair", h2))
        story.append(kv([
            ("IT Sub-team", _a_txt(IT_TEAM_LABELS.get(d.get("it_team")))), ("Handled By", _a_txt(d.get("service_assigned_to_name"))),
            ("Picked Up On", _a_dt(d.get("service_claimed_at"))), ("Closed By", _a_txt(d.get("service_completed_by"))),
            ("Closed On", _a_dt(d.get("service_completed_at"))), ("", ""),
        ]))
        rr = d.get("repair_request")
        story.append(Spacer(1, 4))
        if rr:
            story.append(kv([
                ("Repair Requested By", _a_txt(rr.get("requested_by"))), ("Requested On", _a_dt(rr.get("requested_at"))),
                ("Reason", _a_txt(rr.get("reason"))), ("Device Details", _a_txt(rr.get("device_details"))),
                ("IT Head Decision", _a_txt((rr.get("status") or "").title())), ("Decided By / On", f"{_a_txt(rr.get('decided_by'))} - {_a_dt(rr.get('decided_at'))}"),
                ("Service Center", _a_txt(rr.get("service_center"))), ("Head's Remarks", _a_txt(rr.get("decision_note"))),
                ("Returned From Service Center", _a_dt(rr.get("returned_at"))), ("", ""),
            ]))
        else:
            story.append(P("No external repair was requested for this ticket."))
    else:
        story.append(P("4. Procurement &amp; Purchase Order", h2))
        if not pos:
            story.append(P("No Purchase Order was raised for this requisition (fulfilled from stock, or not yet at the PO stage)."))
        for po in pos:
            story.append(kv([
                ("PO Number", _a_txt(po.get("po_number"))), ("PO Status", _a_txt((po.get("status") or "").replace("_", " ").title())),
                ("PO Created By", _a_txt(po.get("created_by"))), ("Created On", _a_dt(po.get("created_at"))),
                ("Vendor", _a_txt(po.get("vendor_name"))), ("Grand Total (BDT)", f"{po.get('grand_total', 0):,.2f}"),
            ]))
            rows = [["PO Approval Stage", "Approver", "Decision", "Date / Time", "Comment"]]
            for c in po.get("approval_comments") or []:
                rows.append([_a_txt(ROLE_LABELS.get(c.get("role"), c.get("role"))), _a_txt(c.get("by")),
                             _a_txt((c.get("action") or "").replace("_", " ").title()), _a_dt(c.get("at")), _a_txt(c.get("comment"))])
            if len(rows) == 1:
                rows.append(["-", "-", "Not yet submitted / no decisions", "-", "-"])
            story.append(Spacer(1, 3)); story.append(grid(rows, [40 * mm, 34 * mm, 28 * mm, 34 * mm, 46 * mm])); story.append(Spacer(1, 5))

    # ---- 5. delivery & acceptance ---------------------------------------------------------
    story.append(P("5. Delivery &amp; Final Acceptance", h2))
    if is_sr:
        done = d.get("status") == "service_completed_and_returned"
        story.append(kv([
            ("Delivered / Closed By", _a_txt(d.get("service_completed_by"))), ("Delivery Timestamp", _a_dt(d.get("service_completed_at"))),
            ("User Acceptance", "Not recorded - service tickets are closed by the IT executive; there is no separate user confirmation step." if done else "Pending - ticket not closed yet"),
            ("Final Status", _a_txt((d.get("status") or "").replace("_", " ").title())),
        ]))
    else:
        confirm = next((h for h in reversed(d.get("history") or []) if h.get("action") == "receipt_confirmed"), None)
        if not hos:
            story.append(P("No handover slip is linked to this requisition yet."))
        for h in hos:
            story.append(kv([
                ("Slip No.", _a_txt(h.get("slip_no"))), ("Slip Type", _a_txt((h.get("type") or "").title())),
                ("Prepared By", _a_txt(h.get("prepared_by"))), ("Issued To", _a_txt(h.get("employee_name"))),
                ("Delivered By (IT Executive)", _a_txt(h.get("delivered_by"))), ("Delivery Timestamp", _a_dt(h.get("delivered_at"))),
                ("User Confirmation", "Confirmed" if h.get("confirmed_at") else "Awaiting user confirmation"),
                ("Acceptance Timestamp", _a_dt(h.get("confirmed_at"))),
            ]))
            items = ", ".join(f"{i.get('item')} x{i.get('quantity', 1)}" + (f" [{i['tag_id']}]" if i.get("tag_id") else "") for i in h.get("items") or [])
            tail = [P(f"<b>Items:</b> {_a_txt(items)}")] if items else []
            sigs = [(lbl, _img_from_datauri(h.get(key))) for lbl, key in (("Prepared by (IT)", "prepared_by_sign"), ("Received by (user)", "received_by_sign"))]
            sigs = [(lbl, img) for lbl, img in sigs if img]
            if sigs:
                t = Table([[P(lbl, bold) for lbl, _ in sigs], [img for _, img in sigs]], colWidths=[60 * mm] * len(sigs))
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
                tail += [Spacer(1, 3), t]
            if tail:
                story.append(KeepTogether(tail))      # signatures never split from their label row
            story.append(Spacer(1, 5))
        if confirm:
            story.append(P(f"<b>Final acceptance:</b> {_a_txt(confirm.get('by'))} confirmed receipt on {_a_dt(confirm.get('at'))}."))

    # ---- 6. timeline ----------------------------------------------------------------------
    story.append(P("6. Complete Lifecycle Timeline", h2))
    rows = [["#", "Date / Time", "By", "Event", "Remarks"]]
    for i, e in enumerate(build_audit_timeline(d, pos), 1):
        rows.append([str(i), _a_dt(e["at"]), _a_txt(e["by"]), _a_txt(e["event"]), _a_txt(e["note"])])
    story.append(grid(rows, [8 * mm, 34 * mm, 32 * mm, 50 * mm, 58 * mm]))

    ref, stamp = d["requisition_no"], _a_dt(datetime.now(timezone.utc)) + " (UTC+6)"
    class _Numbered(_rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self._pages = []
        def showPage(self):
            self._pages.append(dict(self.__dict__)); self._startPage()
        def save(self):
            n = len(self._pages)
            for st in self._pages:
                self.__dict__.update(st)
                self.setFont("Helvetica", 7); self.setFillColor(colors.HexColor("#64748b"))
                self.drawString(14 * mm, 9 * mm, f"Master Audit Report {ref} - generated {stamp} by {generated_by} from live system records (no stored copy)")
                self.drawRightString(196 * mm, 9 * mm, f"Page {self._pageNumber} of {n}")
                super().showPage()
            super().save()
    doc.build(story, canvasmaker=_Numbered)
    return buf.getvalue()

async def find_requisition_for_audit(ref: str) -> Optional[dict]:
    """Look up by requisition number (REQ-2026-0433); a filed PR number (LPRIT-...) also works."""
    ref = (ref or "").strip()
    if not ref or len(ref) > 40:
        return None
    exact = {"$regex": f"^{re.escape(ref)}$", "$options": "i"}
    return await db.requisitions.find_one({"$or": [{"requisition_no": exact}, {"purchase_pr_no": exact}]})

async def collect_audit_data(d: dict) -> dict:
    rid = str(d["_id"])
    requester = None
    if d.get("requisitioner_id") and ObjectId.is_valid(d["requisitioner_id"]):
        requester = await db.users.find_one({"_id": ObjectId(d["requisitioner_id"])})
    dept_name = None
    did = d.get("requisitioner_department_id") or (requester or {}).get("department_id")
    if did and ObjectId.is_valid(did):
        dp = await db.departments.find_one({"_id": ObjectId(did)})
        dept_name = dp["name"] if dp else None
    pos = [] if d.get("requisition_type") == "service" else await db.purchase_orders.find({"requisition_id": rid}).sort("created_at", 1).to_list(20)
    hos = []
    if d.get("requisition_type") != "service":
        clauses = [{"requisition_id": rid}]
        if d.get("handover_id") and ObjectId.is_valid(d["handover_id"]):
            clauses.append({"_id": ObjectId(d["handover_id"])})
        hos = await db.handovers.find({"$or": clauses}).sort("created_at", 1).to_list(20)
    return {"req": d, "requester": requester, "department_name": dept_name, "pos": pos, "handovers": hos}

async def audit_can_view(user: dict, d: dict, pos: List[dict]) -> bool:
    """Master audit reports are restricted to Super Admin and the IT Head."""
    return user.get("role") == "super_admin" or await _is_it_head(user)

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

@api_router.get("/requisitions/{req_no}/audit-pdf")
async def requisition_audit_pdf(req_no: str, request: Request, auth: Optional[str] = None):
    """Master Audit PDF, rendered in memory on demand and returned inline (nothing is stored).
    Opened with window.open(), so - like the other PDF links - the tab's token may arrive as ?auth=."""
    token = None
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        token = h[7:]
    token = token or auth or request.cookies.get("access_token")
    viewer = await user_from_token(token) if token else None
    if not viewer:
        raise HTTPException(status_code=401, detail="Not authenticated")
    d = await find_requisition_for_audit(req_no)
    if not d:
        raise HTTPException(status_code=404, detail=f"No requisition found for '{req_no.strip()}'")
    data = await collect_audit_data(d)
    if not await audit_can_view(viewer, d, data["pos"]):
        raise HTTPException(status_code=403, detail="Audit reports are available to the IT Head and Super Admin only")
    pdf = build_audit_pdf(data, viewer.get("name") or "-")
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Audit_Report_{d["requisition_no"]}.pdf"',
        "Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# seed
@app.on_event("startup")
async def on_startup():
    try:
        # Indexes only (safe, does not insert business data)
        await db.users.create_index("email", unique=True)
        await db.requisitions.create_index("requisition_no", unique=True)
        await db.products.create_index("name_key", unique=True)
        await db.asset_history.create_index("asset_id")
        await seed_products_if_empty()
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    app.state.reminder_task = asyncio.create_task(reminder_loop())

@app.on_event("shutdown")
async def on_shutdown():
    client.close()

# ===========================================================================
# Bulk import (Super Admin only): existing employees and the assets they already hold.
#   GET  /api/import/template/{users|assets}?fmt=xlsx|csv   -> blank template to fill in
#   POST /api/import/{users|assets}   (multipart: file, dry_run, allow_partial)
#        dry_run=true  -> validate only, nothing is saved (the preview)
#        dry_run=false -> save every valid row
# Users get a generated temporary password and must choose their own at first login.
# Assets are saved exactly like "Add existing asset to an employee" (status 'assigned',
# source 'existing_entry', plus an 'issued' history event), so stock counts are not touched.
# ===========================================================================
import csv as _csv
from datetime import date as _date

IMPORT_MAX_ROWS = {"users": 2000, "assets": 5000}
IMPORT_MAX_BYTES = 5 * 1024 * 1024

USER_COLS = [  # (field, header, required)
    ("name", "Name", True), ("email", "Email", True), ("department", "Department", True),
    ("role", "Role", True), ("role_label", "Role Label", False), ("it_team", "IT Team", False),
    ("can_raise_pr", "Can Raise PR", False), ("can_create_po", "Can Create PO", False)]
ASSET_COLS = [
    ("email", "Employee Email", True), ("name", "Product Name", True), ("brand", "Brand", False),
    ("category", "Category", False), ("serial_no", "Serial No", False), ("tag_id", "Tag ID", False),
    ("assigned_date", "Assigned Date", False), ("remarks", "Remarks", False)]

# Accepted spellings for header cells (after normalising: lower-case, symbols -> spaces).
IMPORT_HEADER_ALIASES = {
    "name": ["name", "full name", "employee name", "product name", "product", "item", "item name", "device"], "email": ["email", "email address", "employee email", "e mail"],
    "department": ["department", "dept"], "role": ["role"], "role_label": ["role label", "designation", "title"],
    "it_team": ["it team", "team"], "can_raise_pr": ["can raise pr", "raise pr"], "can_create_po": ["can create po", "create po"],
    "brand": ["brand", "make"], "category": ["category", "type", "product type"],
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
    depts = {_imp_norm(d["name"]): d async for d in db.departments.find()}
    it_dept = await find_dept_by_name("IT")
    purchase_dept = await find_dept_by_name("Purchase")
    it_id = str(it_dept["_id"]) if it_dept else None
    po_id = str(purchase_dept["_id"]) if purchase_dept else None
    existing = {(u.get("email") or "").lower() async for u in db.users.find({}, {"email": 1})}
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

async def _imp_validate_assets(rows: List[tuple]) -> List[dict]:
    users = {(u.get("email") or "").lower(): u async for u in db.users.find()}
    tags, serials = set(), set()
    async for a in db.assets.find({}, {"tag_id": 1, "serial_no": 1}):
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
                    "messages": errs,
                    "data": {"emp_id": str(emp["_id"]) if emp else None, "name": r.get("name", ""), "brand": r.get("brand") or None,
                             "category_id": cat, "tag_id": r.get("tag_id") or None, "serial_no": r.get("serial_no") or None,
                             "assigned_date": when, "remarks": r.get("remarks") or None}})
    return out

@api_router.post("/import/{kind}")
async def bulk_import(kind: str, file: UploadFile = File(...), dry_run: bool = Form(True), allow_partial: bool = Form(False),
                      user: dict = Depends(require_roles("super_admin"))):
    if kind not in ("users", "assets"):
        raise HTTPException(status_code=404, detail="Unknown import type")
    data = await file.read()
    if len(data) > IMPORT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (5 MB maximum)")
    rows = _imp_read_table(file.filename or "", data, kind)
    result = await (_imp_validate_users(rows) if kind == "users" else _imp_validate_assets(rows))
    counts = {"total": len(result), "ok": sum(r["status"] == "ok" for r in result),
              "skipped": sum(r["status"] == "skip" for r in result), "errors": sum(r["status"] == "error" for r in result)}
    resp = {"kind": kind, "filename": file.filename, "dry_run": dry_run, **counts, "created": 0, "credentials": [], "batch_id": None}

    if not dry_run:
        if counts["errors"] and not allow_partial:
            raise HTTPException(status_code=400, detail=f"{counts['errors']} row(s) have errors. Fix the file, or choose to import only the valid rows.")
        good = [r for r in result if r["status"] == "ok"]
        if not good:
            raise HTTPException(status_code=400, detail="There are no valid rows to import")
        batch_id = secrets.token_hex(6)
        stamp = now_iso()
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
                await db.users.insert_many(docs, ordered=False)
            except Exception as e:                    # e.g. someone created the same email between preview and import
                raise HTTPException(status_code=409, detail=f"Import stopped: {str(e)[:200]}. Run the check again.")
            resp["credentials"] = [{"name": d["name"], "email": d["email"], "temporary_password": t} for d, t in zip(docs, temps)]
            resp["created"] = len(docs)
        else:
            emps = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": [ObjectId(r["data"]["emp_id"]) for r in good]}})}
            docs = []
            for r in good:
                d = r["data"]
                emp = emps[d["emp_id"]]
                when = d["assigned_date"] or stamp
                docs.append({"name": d["name"], "brand": d["brand"], "serial_no": d["serial_no"], "tag_id": d["tag_id"],
                             "category_id": d["category_id"], "status": "assigned", "assigned_to": emp["name"],
                             "assigned_to_user_id": str(emp["_id"]), "assigned_department_id": emp.get("department_id"),
                             "assigned_at": when, "receipt_confirmed": True, "receipt_confirmed_at": when,
                             "pending_receipt": False, "pending_handover_id": None, "assigned_slip_no": None,
                             "remarks": d["remarks"], "source": "existing_entry", "added_by": user["name"],
                             "created_at": stamp, "import_batch": batch_id})
            res = await db.assets.insert_many(docs)
            await db.asset_history.insert_many([{
                "asset_id": str(aid), "asset_name": a["name"], "tag_id": a["tag_id"], "serial_no": a["serial_no"],
                "event": "issued", "employee_user_id": a["assigned_to_user_id"], "employee_name": a["assigned_to"],
                "slip_no": None, "handover_id": None, "by": user["name"], "at": a["assigned_at"],
                "source": "existing_entry", "import_batch": batch_id} for aid, a in zip(res.inserted_ids, docs)])
            resp["created"] = len(docs)
        await db.import_batches.insert_one({"batch_id": batch_id, "kind": kind, "filename": file.filename, "by": user["name"],
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
        dept_names = [d["name"] async for d in db.departments.find().sort("name", 1)]
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
              "Tag ID and Serial No must be unique across the whole system (leave blank if the device has none).",
              "Assigned Date: 2025-03-31 or 31/03/2025. Blank = today.",
              "Assets are recorded as already assigned to the employee and do not change stock counts."])
    for n in notes:
        info.append([n])
    info.column_dimensions["A"].width = 120
    out = io.BytesIO()
    wb.save(out)
    return Response(content=out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{kind}_import_template.xlsx"'})

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000"), "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)