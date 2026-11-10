"""User management."""

from fastapi import Response, HTTPException, Depends, Body
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, timezone
from ims.ids import ObjectId
from sqlalchemy.exc import IntegrityError as _SqlIntegrityError
from ims.repositories import assets as asset_repo
from ims.repositories import handovers as handover_repo
from ims.repositories import correction_cases as case_repo
from ims.repositories import departments as dept_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import users as users_repo
from ims.repositories import products as prod_repo
from ims.common import (
    dept_type_of,
    IT_TEAMS,
    MIN_PASSWORD_LENGTH,
    ROLES,
    ROLE_LABELS,
    _can_manage_handovers,
    _department_is_it,
    _department_is_purchase,
    _env,
    _held_filter,
    _skey,
    _users_in_dept_matching,
    api_router,
    clean_user,
    generate_temp_password,
    get_current_user,
    hash_password,
    now_iso,
    require_roles,
    resolve_category_name,
)

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
            dd = await dept_repo.get(did)
            dept_names[did] = dd["name"] if dd else None
        out.append({"id": str(u["_id"]), "name": u["name"], "department_id": did,
                    "department_name": dept_names.get(did)})
    return out


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


async def enrich_user(u: dict) -> dict:
    data = clean_user(u)
    dept_name = dept_kind = None
    if u.get("department_id") and ObjectId.is_valid(u["department_id"]):
        d = await dept_repo.get(u["department_id"])
        dept_name = d["name"] if d else None
        dept_kind = dept_type_of(d)
    data["department_name"] = dept_name
    data["department_type"] = dept_kind
    data["role_label_display"] = u.get("role_label") or ROLE_LABELS.get(u.get("role"), u.get("role"))
    data.setdefault("it_team", None)
    return data


@api_router.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    docs = await users_repo.list_all(sort_by_name=True, limit=20000)
    return [await enrich_user(u) for u in docs]


@api_router.post("/users")
async def create_user(payload: UserIn, user: dict = Depends(require_roles("super_admin"))):
    email = payload.email.lower()
    if await users_repo.get_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if payload.can_raise_pr and not await _department_is_it(payload.department_id):
        raise HTTPException(status_code=400, detail="Can Raise PR is only available for users in the IT department")
    if payload.can_create_po and not await _department_is_purchase(payload.department_id):
        raise HTTPException(status_code=400, detail="Can Create PO is only available for users in the Purchase department")
    it_team = await validate_it_team(payload.it_team, payload.department_id)
    initial_pw = payload.password or _env("SEED_USER_PASSWORD")      # no built-in default password any more
    if not initial_pw:
        raise HTTPException(status_code=400, detail="A password is required for the new user")
    doc = {
        "name": payload.name,
        "email": email,
        "password_hash": hash_password(initial_pw),
        "department_id": payload.department_id,
        "role": payload.role,
        "role_label": payload.role_label or ROLE_LABELS.get(payload.role),
        "can_raise_pr": payload.can_raise_pr,
        "can_create_po": payload.can_create_po,
        "it_team": it_team,
        "created_at": now_iso(),
    }
    doc["_id"] = await users_repo.insert(doc)
    return await enrich_user(doc)


@api_router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, response: Response, payload: Optional[ResetPasswordIn] = Body(default=None),
                              user: dict = Depends(require_roles("super_admin"))):
    """Forgot-password recovery (admin-assisted). Super Admin / IT Head sets a temporary password
    for a user who cannot sign in. The user is signed out everywhere and MUST choose their own
    password at next login. The temporary password is returned once and never stored in plain text."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    target = await users_repo.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if str(target["_id"]) == str(user["_id"]):
        raise HTTPException(status_code=400, detail="Use Change Password for your own account")
    temp = (payload.new_password if payload and payload.new_password else None) or generate_temp_password()
    if len(temp) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    await users_repo.update_fields(target["_id"], {
        "password_hash": hash_password(temp), "password_changed_at": now_iso(),
        "must_change_password": True,
        "sessions_valid_from": int(datetime.now(timezone.utc).timestamp())})
    await users_repo.log_password_reset({
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
        existing_u = await users_repo.get(user_id)
        if not existing_u:
            raise HTTPException(status_code=404, detail="User not found")
        dept_for_team = updates.get("department_id", existing_u.get("department_id"))
        if "it_team" in payload.model_fields_set:
            updates["it_team"] = await validate_it_team(payload.it_team, dept_for_team)
        elif existing_u.get("it_team") and not await _department_is_it(dept_for_team):
            updates["it_team"] = None
    if updates.get("can_raise_pr") or updates.get("can_create_po"):
        existing = await users_repo.get(user_id)
        dept_id = updates.get("department_id", (existing or {}).get("department_id"))
        if updates.get("can_raise_pr") and not await _department_is_it(dept_id):
            raise HTTPException(status_code=400, detail="Can Raise PR is only available for users in the IT department")
        if updates.get("can_create_po") and not await _department_is_purchase(dept_id):
            raise HTTPException(status_code=400, detail="Can Create PO is only available for users in the Purchase department")
    await users_repo.update_fields(user_id, updates)
    u = await users_repo.get(user_id)
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
    target = await users_repo.get(user_id)
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

    await users_repo.update_fields(user_id, updates)
    u = await users_repo.get(user_id)
    return await enrich_user(u)


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_roles("super_admin"))):
    """Delete a user - but only one who is not part of any record. A user who appears in requisitions, approvals, purchase
    orders, handovers, held assets or someone's delegation must be kept (the history refers to them)."""
    if str(user["_id"]) == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    target = await users_repo.get(user_id)
    if target is None:
        return {"ok": True}                                  # already gone
    refs = await _user_references(target)
    if refs:
        raise HTTPException(status_code=409, detail=(
            f"This user cannot be deleted because they appear in existing records: {', '.join(refs)}. "
            "Those records have to be kept."))
    try:
        await users_repo.delete(user_id)
    except _SqlIntegrityError:                               # MySQL's foreign keys are the last line of defence
        raise HTTPException(status_code=409, detail="This user cannot be deleted because other records still refer to them.")
    return {"ok": True}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def _user_references(target: dict) -> List[str]:
    """Human-readable list of the records that mention this user (empty = safe to delete)."""
    uid = str(target["_id"])
    out: List[str] = []
    n = await req_repo.count_filtered({"$or": [
        {"requisitioner_id": uid}, {"pr_filed_by_id": uid}, {"service_assigned_to_id": uid},
        {"approval_chain.approver_id": uid}, {"approval_chain.acted_by_id": uid}]})
    if n:
        out.append(_plural(n, "requisition"))
    n = await po_repo.count_created_by(uid, target.get("name") or "")
    if n:
        out.append(_plural(n, "purchase order"))
    n = await handover_repo.count_for_employee(uid)
    if n:
        out.append(_plural(n, "handover"))
    n = await asset_repo.count_filtered(_held_filter(target))
    if n:
        out.append(f"{_plural(n, 'asset')} currently held")
    n = await case_repo.count_for_employee(uid)
    if n:
        out.append(_plural(n, "delivery correction"))
    delegators = await users_repo.list_delegating_to(uid)
    if delegators:
        out.append("named as the delegate of " + ", ".join(sorted(d.get("name") or "a colleague" for d in delegators)))
    return out


@api_router.get("/users/{user_id}/held-assets")
async def employee_held_assets(user_id: str, user: dict = Depends(get_current_user)):
    """Everything this employee currently holds - drives the 'Currently holding' panel on the
    Handover form. Includes assets whose return is already in progress (flagged, not selectable)."""
    if not (await _can_manage_handovers(user) or str(user["_id"]) == user_id):
        raise HTTPException(status_code=403, detail="Not allowed")
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    emp = await users_repo.get(user_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    docs = await asset_repo.find(_held_filter(emp), sort=[("assigned_at", -1)], limit=200)
    # Consumables (tracked by quantity) are used up, not handed back, and an untagged unit cannot be
    # identified on a return slip - so they are not listed as something the employee can return.
    qty_names = {_skey(p["name"]) for p in await prod_repo.list_all(product_type="consumable")}
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