from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal
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

app = FastAPI(title="IMS - IT Requisition & Asset Management")
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
        {"key": "approve-requisition", "label": "Approve Requisition", "path": "/requisitions/approve"},
        {"key": "requisition-history", "label": "Requisition History", "path": "/requisitions/history"},
    ]},
    {"group": "Stock", "icon": "Boxes", "badge": "C1", "items": [
        {"key": "stock-list", "label": "Stock List", "path": "/stock"},
    ]},
    {"group": "Purchase", "icon": "ShoppingCart", "badge": "D1", "items": [
        {"key": "stock-grn", "label": "Stock GRN (Vendor Challan)", "path": "/purchase/grn"},
    ]},
    {"group": "Handover", "icon": "Handshake", "badge": "E1", "items": [
        {"key": "handover-module", "label": "Handover Module", "path": "/handover"},
        {"key": "handover-records", "label": "Handover Records", "path": "/handover/records"},
    ]},
    {"group": "Approvals", "icon": "UserCheck", "badge": "F1", "items": [
        {"key": "approver-management", "label": "Approver Management", "path": "/approvals"},
    ]},
    {"group": "Organization", "icon": "Building2", "badge": "G1", "items": [
        {"key": "departments", "label": "Departments", "path": "/organization/departments"},
        {"key": "categories", "label": "Categories", "path": "/organization/categories"},
        {"key": "users-roles", "label": "Users & Roles", "path": "/organization/users"},
    ]},
]

ALL_MENU_KEYS = [item["key"] for g in MENU for item in g["items"]]

# Default sidebar permission map keyed by canonical role.
DEFAULT_PERMISSIONS = {
    "super_admin": ALL_MENU_KEYS,
    "dept_head": [
        "overview", "assigned-assets",
        "new-requisition", "pending-requisition", "approve-requisition", "requisition-history",
        "stock-list", "handover-module", "handover-records", "approver-management",
    ],
    "executive": [
        "overview", "assigned-assets",
        "new-requisition", "pending-requisition", "requisition-history",
        "stock-list", "handover-records",
    ],
    "accounts": [
        "overview", "approve-requisition", "file-purchase-requisition",
        "requisition-history", "stock-list",
    ],
    "md": [
        "overview", "approve-requisition", "requisition-history",
    ],
    "purchase_head": [
        "overview", "approve-requisition", "file-purchase-requisition",
        "requisition-history", "stock-grn", "stock-list",
    ],
}

REQ_STATUSES = [
    "pending_dept", "pending_it_service", "product_collected_by_it", "sent_to_service_center",
    "pending_it", "pending_accounts", "pending_md", "pending_purchase", "approved", "rejected",
]

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
               "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none", max_age=43200, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none", max_age=604800, path="/")

def clean_user(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
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

async def resolve_approver(role: str, department_id: Optional[str] = None) -> Optional[dict]:
    query = {"role": role}
    if department_id:
        query["department_id"] = department_id
    u = await db.users.find_one(query)
    return u

async def build_approval_chain(req_type: str, requester: dict, total_amount: float) -> List[dict]:
    """Return ordered list of approval steps."""
    steps: List[dict] = []

    async def step(level, role, label, department_id=None, status_key="pending"):
        approver = await resolve_approver(role, department_id)
        steps.append({
            "level": level,
            "role": role,
            "label": label,
            "department_id": department_id,
            "approver_id": str(approver["_id"]) if approver else None,
            "approver_name": approver["name"] if approver else None,
            "status": "pending",
            "note": None,
            "acted_at": None,
        })

    it_dept = await find_dept_by_name("IT")
    it_dept_id = str(it_dept["_id"]) if it_dept else None

    if req_type == "service":
        # Service requisition: straight to IT Department Head (bypass dept head & accounts).
        await step(1, "dept_head", "IT Department Head", it_dept_id)
    else:
        # Product requisition chain.
        await step(1, "dept_head", "Department Head", requester.get("department_id"))
        await step(2, "dept_head", "IT Head", it_dept_id)
        await step(3, "accounts", "Accounts")
        if total_amount >= MD_THRESHOLD:
            await step(4, "md", "Managing Director")
        purchase_dept = await find_dept_by_name("Purchase")
        purchase_dept_id = str(purchase_dept["_id"]) if purchase_dept else None
        # Purchase Head = dedicated purchase_head role if present, else the Purchase dept head.
        ph = await resolve_approver("purchase_head") or await resolve_approver("dept_head", purchase_dept_id)
        steps.append({
            "level": 5, "role": "purchase_head", "label": "Purchase Head",
            "department_id": purchase_dept_id,
            "approver_id": str(ph["_id"]) if ph else None,
            "approver_name": ph["name"] if ph else None,
            "status": "pending", "note": None, "acted_at": None,
        })
    # renumber levels sequentially
    for i, s in enumerate(steps):
        s["level"] = i + 1
    return steps

def status_for_step(req_type: str, step: dict) -> str:
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
    return "approved"

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserIn(BaseModel):
    name: str
    email: EmailStr
    password: Optional[str] = None
    department_id: Optional[str] = None
    role: str
    role_label: Optional[str] = None
    can_raise_pr: bool = False

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    department_id: Optional[str] = None
    role: Optional[str] = None
    role_label: Optional[str] = None
    can_raise_pr: Optional[bool] = None

class DepartmentIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None

class CategoryIn(BaseModel):
    name: str
    department_id: Optional[str] = None
    description: Optional[str] = None

class RequisitionItemIn(BaseModel):
    product_type: Literal["asset", "consumable"]
    product_name: str
    quantity: int = 1
    rate: float = 0
    remarks: Optional[str] = None
    category_id: Optional[str] = None

class RequisitionIn(BaseModel):
    requisition_type: Literal["product", "service"]
    requisition_for: Optional[str] = None
    items: List[RequisitionItemIn]
    requester_note: Optional[str] = None
    attachment_path: Optional[str] = None
    requisition_date: Optional[str] = None

class ApproveIn(BaseModel):
    action: Literal["approve", "reject"]
    note: Optional[str] = None

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
    return {"user": clean_user(user), "access_token": access}

@api_router.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}

@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    data = clean_user(user)
    dept = None
    if user.get("department_id"):
        d = await db.departments.find_one({"_id": ObjectId(user["department_id"])}) if ObjectId.is_valid(user["department_id"]) else None
        dept = d["name"] if d else None
    data["department_name"] = dept
    data["role_label_display"] = user.get("role_label") or ROLE_LABELS.get(user.get("role"), user.get("role"))
    return data

@api_router.get("/auth/permissions")
async def my_permissions(user: dict = Depends(get_current_user)):
    perm = await db.sidebar_permissions.find_one({"role": user["role"]})
    allowed = perm["items"] if perm else DEFAULT_PERMISSIONS.get(user["role"], [])
    menu = []
    for g in MENU:
        items = [it for it in g["items"] if it["key"] in allowed]
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
    doc = {
        "name": payload.name,
        "email": email,
        "password_hash": hash_password(payload.password or os.environ.get("SEED_USER_PASSWORD", "password123")),
        "department_id": payload.department_id,
        "role": payload.role,
        "role_label": payload.role_label or ROLE_LABELS.get(payload.role),
        "can_raise_pr": payload.can_raise_pr,
        "created_at": now_iso(),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return await enrich_user(doc)

@api_router.put("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, user: dict = Depends(require_roles("super_admin"))):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "email" in updates:
        updates["email"] = updates["email"].lower()
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    if "role" in updates and updates["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
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
    total = float(payload.get("total_amount", 0))
    chain = await build_approval_chain(req_type, user, total)
    return {"chain": chain}

@api_router.post("/requisitions")
async def create_requisition(payload: RequisitionIn, user: dict = Depends(get_current_user)):
    if not (user.get("can_raise_pr") or user.get("role") in ("super_admin", "dept_head")):
        raise HTTPException(status_code=403, detail="You are not allowed to raise a requisition")
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    items = [it.model_dump() for it in payload.items]
    for it in items:
        it["line_total"] = round(it["quantity"] * it["rate"], 2)
    total_amount = round(sum(it["line_total"] for it in items), 2)

    chain = await build_approval_chain(payload.requisition_type, user, total_amount)
    req_no = await next_req_number()

    doc = {
        "requisition_no": req_no,
        "requisitioner_id": str(user["_id"]),
        "requisitioner_name": user["name"],
        "requisitioner_department_id": user.get("department_id"),
        "requisition_for": payload.requisition_for or user["name"],
        "requisition_type": payload.requisition_type,
        "items": items,
        "total_amount": total_amount,
        "requester_note": payload.requester_note,
        "attachment_path": payload.attachment_path,
        "requisition_date": payload.requisition_date or now_iso(),
        "approval_chain": chain,
        "status": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "history": [{"at": now_iso(), "by": user["name"], "action": "created", "note": None}],
    }
    doc["status"] = compute_status(doc)
    res = await db.requisitions.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc

def serialize_req(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc

@api_router.get("/requisitions")
async def list_requisitions(scope: str = "all", user: dict = Depends(get_current_user)):
    query: dict = {}
    if scope == "mine":
        query["requisitioner_id"] = str(user["_id"])
    elif scope == "pending":
        query = {"requisitioner_id": str(user["_id"]), "status": {"$nin": ["approved", "rejected"]}}
    elif scope == "approve":
        # requisitions where current pending step is assigned to this user
        docs = await db.requisitions.find({"status": {"$nin": ["approved", "rejected"]}}).sort("created_at", -1).to_list(1000)
        out = []
        for d in docs:
            chain = d["approval_chain"]
            current = next((s for s in chain if s["status"] == "pending"), None)
            if current and (current["approver_id"] == str(user["_id"]) or user["role"] == "super_admin"):
                out.append(serialize_req(d))
        return out
    elif scope == "history":
        query = {"status": {"$in": ["approved", "rejected"]}}
    docs = await db.requisitions.find(query).sort("created_at", -1).to_list(1000)
    return [serialize_req(d) for d in docs]

@api_router.get("/requisitions/{req_id}")
async def get_requisition(req_id: str, user: dict = Depends(get_current_user)):
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return serialize_req(d)

@api_router.post("/requisitions/{req_id}/action")
async def act_on_requisition(req_id: str, payload: ApproveIn, user: dict = Depends(get_current_user)):
    d = await db.requisitions.find_one({"_id": ObjectId(req_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d["status"] in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Requisition already finalized")
    chain = d["approval_chain"]
    current = next((s for s in chain if s["status"] == "pending"), None)
    if not current:
        raise HTTPException(status_code=400, detail="No pending step")
    if not (current["approver_id"] == str(user["_id"]) or user["role"] == "super_admin"):
        raise HTTPException(status_code=403, detail="You are not the current approver")

    current["status"] = "approved" if payload.action == "approve" else "rejected"
    current["note"] = payload.note
    current["acted_at"] = now_iso()
    d["history"].append({"at": now_iso(), "by": user["name"], "action": payload.action,
                         "level": current["level"], "note": payload.note})
    d["updated_at"] = now_iso()
    d["status"] = compute_status(d)
    await db.requisitions.update_one({"_id": ObjectId(req_id)},
                                     {"$set": {"approval_chain": chain, "status": d["status"],
                                               "history": d["history"], "updated_at": d["updated_at"]}})
    return serialize_req(d)

@api_router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    total = await db.requisitions.count_documents({})
    pending = await db.requisitions.count_documents({"status": {"$nin": ["approved", "rejected"]}})
    approved = await db.requisitions.count_documents({"status": "approved"})
    rejected = await db.requisitions.count_documents({"status": "rejected"})
    high_value = await db.requisitions.count_documents({"total_amount": {"$gte": MD_THRESHOLD}})
    # my approvals queue
    docs = await db.requisitions.find({"status": {"$nin": ["approved", "rejected"]}}).to_list(1000)
    my_queue = 0
    for dc in docs:
        cur = next((s for s in dc["approval_chain"] if s["status"] == "pending"), None)
        if cur and (cur["approver_id"] == str(user["_id"]) or user["role"] == "super_admin"):
            my_queue += 1
    recent = await db.requisitions.find().sort("created_at", -1).to_list(6)
    return {
        "total": total, "pending": pending, "approved": approved, "rejected": rejected,
        "high_value": high_value, "my_queue": my_queue,
        "recent": [serialize_req(r) for r in recent],
    }

# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
SEED_DEPARTMENTS = [
    {"name": "Primitek Group", "code": "GRP", "description": "Group / organization root"},
    {"name": "IT", "code": "IT", "description": "Information Technology"},
    {"name": "HR", "code": "HR", "description": "Human Resources"},
    {"name": "Accounts", "code": "ACC", "description": "Accounts & Finance"},
    {"name": "Purchase", "code": "PUR", "description": "Purchase & Procurement"},
    {"name": "Sales", "code": "SAL", "description": "Sales & Marketing"},
]

SEED_CATEGORIES = [
    {"name": "IT Assets", "dept": "IT", "description": "Laptops, desktops, monitors"},
    {"name": "Consumables", "dept": "IT", "description": "Cables, mice, toner"},
    {"name": "Networking", "dept": "IT", "description": "Switches, routers, APs"},
    {"name": "Furniture", "dept": "HR", "description": "Chairs, desks"},
    {"name": "Services", "dept": "IT", "description": "Repairs & maintenance"},
]

SEED_USERS = [
    {"name": "Ashik Chowdhury", "email": "ashik@gmail.com", "dept": "IT", "role": "dept_head", "label": "Dept Head", "pr": False},
    {"name": "Baitulla", "email": "baitulla@gmail.com", "dept": "IT", "role": "executive", "label": "Executive(IT)", "pr": True},
    {"name": "dipto", "email": "dipto@gmail.com", "dept": "HR", "role": "executive", "label": "Executive", "pr": False},
    {"name": "Karim", "email": "karim@gmail.com", "dept": "Accounts", "role": "executive", "label": "executive", "pr": False},
    {"name": "M.A Quieum", "email": "md@gmail.com", "dept": "Primitek Group", "role": "md", "label": "Managing Director", "pr": False},
    {"name": "Maruf Hossain", "email": "maruf@gmail.com", "dept": "HR", "role": "dept_head", "label": "Dept Head", "pr": False},
    {"name": "Shuvo", "email": "shuvo@gmail.com", "dept": "Purchase", "role": "dept_head", "label": "Dept Head", "pr": False},
    {"name": "SK", "email": "sk@gmail.com", "dept": "Accounts", "role": "accounts", "label": "CFO", "pr": False},
]

async def seed():
    await db.users.create_index("email", unique=True)
    await db.requisitions.create_index("requisition_no", unique=True)

    # departments
    dept_ids = {}
    for d in SEED_DEPARTMENTS:
        existing = await db.departments.find_one({"name": d["name"]})
        if existing:
            dept_ids[d["name"]] = str(existing["_id"])
        else:
            res = await db.departments.insert_one({**d, "created_at": now_iso()})
            dept_ids[d["name"]] = str(res.inserted_id)

    # categories
    for c in SEED_CATEGORIES:
        if not await db.categories.find_one({"name": c["name"]}):
            await db.categories.insert_one({"name": c["name"], "department_id": dept_ids.get(c["dept"]),
                                            "description": c["description"], "created_at": now_iso()})

    # owner / super admin
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_pw = os.environ["ADMIN_PASSWORD"]
    owner = await db.users.find_one({"email": admin_email})
    if not owner:
        await db.users.insert_one({
            "name": "Ashik Chowdhury", "email": admin_email, "password_hash": hash_password(admin_pw),
            "department_id": dept_ids.get("IT"), "role": "super_admin", "role_label": "Super Admin",
            "can_raise_pr": True, "created_at": now_iso(),
        })
    elif not verify_password(admin_pw, owner["password_hash"]):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_pw)}})

    # sample users
    seed_pw = os.environ.get("SEED_USER_PASSWORD", "password123")
    for u in SEED_USERS:
        if not await db.users.find_one({"email": u["email"]}):
            await db.users.insert_one({
                "name": u["name"], "email": u["email"], "password_hash": hash_password(seed_pw),
                "department_id": dept_ids.get(u["dept"]), "role": u["role"], "role_label": u["label"],
                "can_raise_pr": u["pr"], "created_at": now_iso(),
            })

    # sidebar permissions
    for role, items in DEFAULT_PERMISSIONS.items():
        if not await db.sidebar_permissions.find_one({"role": role}):
            await db.sidebar_permissions.insert_one({"role": role, "items": items})

    logger.info("Seed complete")

@app.on_event("startup")
async def on_startup():
    await seed()

@app.on_event("shutdown")
async def on_shutdown():
    client.close()

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000"), "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
