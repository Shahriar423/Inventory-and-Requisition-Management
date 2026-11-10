"""Login, logout, current user, permissions."""

import os
from fastapi import Response, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timezone, timedelta
from ims.ids import ObjectId
import bcrypt
import jwt
from ims.repositories import sidebar_permissions as sidebar_repo
from ims.repositories import departments as dept_repo
from ims.repositories import users as users_repo
from ims.repositories import correction_cases as case_repo
from ims.repositories import report_access as report_access_repo
from ims.common import (
    dept_type_of,
    ALL_MENU_KEYS,
    JWT_ALGORITHM,
    MENU,
    MIN_PASSWORD_LENGTH,
    ROLES,
    ROLE_LABELS,
    _can_manage_handovers,
    _delegation_active,
    _department_is_it,
    _department_is_purchase,
    _is_it_head,
    _notify,
    active_delegators_of,
    api_router,
    can_handle_pr,
    clean_user,
    find_admin_dept,
    get_current_user,
    get_jwt_secret,
    has_pr_raise_flag,
    hash_password,
    it_queue_teams_for,
    now_iso,
    require_roles,
    run_reminder_sweep,
)

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
        "stock-list", "handover-module", "handover-records", "paper-records", "approver-management", "products",
    ],
    "executive": [
        "overview", "new-requisition", "pending-requisition", "requisition-history",
    ],
    "accounts": [
         "overview", "approve-requisition",
         "requisition-history", "stock-list", "po-approvals",
    ],
    "md": [
         "overview", "requisition-history", "po-approvals",
    ],
    "purchase_head": [
         "overview", "approve-requisition",
        "requisition-history", "stock-grn", "stock-list", "po-approvals",
    ],
}


# Reduced menu for a dept_head in any department OTHER than IT: employee essentials plus
# just the Approve Requisitions queue — no Stock/Handover/Approver-Management operational
# tooling, which is specific to the IT team's day-to-day duties.
NON_IT_DEPT_HEAD_PERMISSIONS = [
    "overview", "new-requisition", "pending-requisition", "requisition-history", "approve-requisition",
]


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


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


# Anyone holding the per-user "Can Raise PR" flag (the PR raiser) also gets the Handover
# module and Stock GRN. The access is DERIVED from the flag at request time (nothing extra is
# stored), so when Super Admin / IT Head moves "Can Raise PR" from one person to another, the
# new PR raiser gains these screens immediately and the previous one loses them.
PR_RAISER_MENU_KEYS = ["handover-module", "handover-records", "stock-grn"]


async def _department_is_admin(department_id: Optional[str]) -> bool:
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    d = await find_admin_dept()
    return bool(d) and str(d["_id"]) == department_id


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
        x = await users_repo.get(did)
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
        if not ObjectId.is_valid(payload.delegate_user_id) or not await users_repo.get(payload.delegate_user_id):
            raise HTTPException(status_code=400, detail="Selected delegate does not exist")
        if not (_valid_date(payload.delegate_from) and _valid_date(payload.delegate_until)):
            raise HTTPException(status_code=400, detail="Choose a start and end date for the leave")
        if payload.delegate_until < payload.delegate_from:
            raise HTTPException(status_code=400, detail="End date cannot be before the start date")
        await users_repo.update_fields(user["_id"], {
            "delegate_user_id": payload.delegate_user_id,
            "delegate_from": payload.delegate_from, "delegate_until": payload.delegate_until})
        await _notify(payload.delegate_user_id, "delegation_assigned",
            f"{user['name']} has delegated their approvals to you from {payload.delegate_from} to {payload.delegate_until}.")
    else:
        await users_repo.unset_fields(user["_id"], ["delegate_user_id", "delegate_from", "delegate_until"])
    return await _delegation_view(await users_repo.get(user["_id"]))


@api_router.post("/admin/reminders/run")
async def run_reminders_now(user: dict = Depends(require_roles("super_admin"))):
    """Runs the reminder check immediately (it also runs automatically)."""
    return await run_reminder_sweep()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@api_router.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower()
    user = await users_repo.get_by_email(email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = create_access_token(str(user["_id"]), email)
    refresh = create_refresh_token(str(user["_id"]))
    set_auth_cookies(response, access, refresh)
    # Enrich the same way /auth/me does so department_name and role_label_display
    # are available immediately after login (no page refresh required).
    data = clean_user(user)
    dept = dept_kind = None
    if user.get("department_id"):
        d = await dept_repo.get(user["department_id"]) if ObjectId.is_valid(user["department_id"]) else None
        dept = d["name"] if d else None
        dept_kind = dept_type_of(d)
    data["department_name"] = dept
    data["department_type"] = dept_kind
    data["role_label_display"] = user.get("role_label") or ROLE_LABELS.get(user.get("role"), user.get("role"))
    return {"user": data, "access_token": access}


@api_router.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


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
    await users_repo.update_fields(user["_id"], {
        "password_hash": hash_password(new_pw), "password_changed_at": now_iso(),
        "must_change_password": False})
    return {"ok": True}


@api_router.get("/auth/me")
async def me(response: Response, user: dict = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    data = clean_user(user)
    dept = dept_kind = None
    if user.get("department_id"):
        d = await dept_repo.get(user["department_id"]) if ObjectId.is_valid(user["department_id"]) else None
        dept = d["name"] if d else None
        dept_kind = dept_type_of(d)
    data["department_name"] = dept
    data["department_type"] = dept_kind
    data["can_handle_pr"] = can_handle_pr(user)
    data["role_label_display"] = user.get("role_label") or ROLE_LABELS.get(user.get("role"), user.get("role"))
    return data


@api_router.get("/auth/permissions")
async def my_permissions(response: Response, user: dict = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    saved = await sidebar_repo.get_items(user["role"])
    if saved is not None:
        # An explicit admin-customized permission set (via Approver Management) always wins.
        allowed = list(saved)
    elif user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")):
        # Purchase Dept Head: base purchase_head menu + PO Approvals / Create PO
        allowed = list(DEFAULT_PERMISSIONS.get("purchase_head", []))
        for extra in ("po-approvals",):
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
    # Purchase Dept Head only approves / rejects POs — never gets the create menus.
    is_po_head = is_purchase_head or user["role"] == "purchase_head"
    can_create = user["role"] == "super_admin" or (bool(user.get("can_create_po")) and not is_po_head)
    if is_po_head:
        allowed = [k for k in allowed if k not in ("create-po", "file-purchase-order")]
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

    # Stock List: PR raisers / PR handlers must always see it - they check stock before raising a PR -
    # even when the plain "user" (executive) role has Stock List switched off in Approver Management.
    # Derived from the per-user flag, so it follows whoever is the PR raiser; role settings only
    # decide the menu for everybody else.
    if can_handle_pr(user) and "stock-list" not in allowed:
        allowed.append("stock-list")

    # IT service ticket queue: derived from the IT sub-team (it_team) / IT Head / Super Admin, same
    # idea as the PR-raiser block above. Only ADDS a menu item.
    # The IT Head supervises but does not work tickets: no queue for the Head, only a small "Repair Approvals"
    # view (external-repair requests need the Head's decision). Super Admin and the IT sub-team executives
    # keep the full queue.
    if await _is_it_head(user):
        allowed = [k for k in allowed if k != "it-service-queue"]
        if "repair-approvals" not in allowed:
            allowed.append("repair-approvals")
    else:
        allowed = [k for k in allowed if k != "repair-approvals"]
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
        if "paper-records" not in allowed:
            allowed.append("paper-records")
        if "settings" not in allowed:
            allowed.append("settings")      # business limits (MD approval limit, reminder time)
    else:
        allowed = [k for k in allowed if k not in ("bulk-import", "settings")]
    # Paper Records: Super Admin and the IT Head only (also enforced on the /paper-records endpoints).
    if user["role"] != "super_admin" and not await _is_it_head(user):
        allowed = [k for k in allowed if k != "paper-records"]

    # Corrections: IT / Super Admin run the cases; anyone who reported (or was asked about) one sees "My Corrections".
    allowed = [k for k in allowed if k not in ("corrections", "my-corrections")]
    if user["role"] == "super_admin" or await _can_manage_handovers(user):
        allowed.append("corrections")

    uid_str = str(user["_id"])
    all_cases = await case_repo.list_all(limit=5000)
    reported_a_case = any(c.get("employee_user_id") == uid_str for c in all_cases)
    asked_for_clarification = any(
        c.get("status") == "waiting_clarification"
        and any(x.get("to_user_id") == uid_str for x in c.get("clarifications") or [])
        for c in all_cases
    )
    if reported_a_case or asked_for_clarification:
        allowed.append("my-corrections")

    # Reports: Report Center is Super Admin only, whatever a saved role setting says. "My Reports"
    # appears only for a user who currently holds at least one active report grant.
    allowed = [k for k in allowed if k not in ("report-center", "my-reports")]
    if user["role"] == "super_admin":
        allowed.append("report-center")
    elif await report_access_repo.count_active(str(user["_id"])):
        allowed.append("my-reports")

    # Leave delegation: someone approving on behalf of a colleague needs the same approval
    # screens as that colleague (an Executive, for example, has no "Approve Requisition" menu
    # by default). Granted only while a delegation to this user is active.
    delegators = await active_delegators_of(user)
    delegated_only = {}      # menu key -> label, for items this user has ONLY because of a delegation
    if delegators:
        if "approve-requisition" not in allowed:
            allowed.append("approve-requisition")
            delegated_only["approve-requisition"] = "Delegated Approvals"
        for dg in await users_repo.list_by_ids(delegators):
            dg_purchase_head = dg["role"] == "dept_head" and await _department_is_purchase(dg.get("department_id"))
            if (dg["role"] in ("md", "accounts", "purchase_head") or dg_purchase_head) and "po-approvals" not in allowed:
                allowed.append("po-approvals")
                delegated_only["po-approvals"] = "Delegated PO Approvals"

    # The MD only approves / rejects Purchase Orders and looks back at his own decisions - nothing else,
    # whatever a saved role setting says.
    if user["role"] == "md":
        allowed = [k for k in allowed if k in ("overview", "requisition-history", "po-approvals")]
        for k in ("overview", "requisition-history", "po-approvals"):
            if k not in allowed:
                allowed.append(k)

    menu = []
    for g in MENU:
        items = [{**it, "label": delegated_only.get(it["key"], it["label"])} if it["key"] in delegated_only else it
                 for it in g["items"] if it["key"] in allowed]
        if items:
            menu.append({**g, "items": items})
    return {"allowed": allowed, "menu": menu}


@api_router.get("/permissions")
async def list_permissions(user: dict = Depends(require_roles("super_admin"))):
    out = []
    for r in ROLES:
        saved = await sidebar_repo.get_items(r)
        out.append({"role": r, "label": ROLE_LABELS[r], "items": saved if saved is not None else DEFAULT_PERMISSIONS.get(r, [])})
    return out


@api_router.put("/permissions/{role}")
async def update_permissions(role: str, body: dict, user: dict = Depends(require_roles("super_admin"))):
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    items = [k for k in body.get("items", []) if k in ALL_MENU_KEYS]
    await sidebar_repo.set_items(role, items)
    return {"role": role, "items": items}