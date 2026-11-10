"""Application settings endpoints."""

from fastapi import HTTPException, Depends
from pydantic import BaseModel
from ims.repositories import system_settings as settings_repo
from ims.common import (
    MD_THRESHOLD,
    _is_it_head,
    api_router,
    get_correction_settings,
    get_current_user,
    get_po_threshold,
    get_reminder_settings,
    now_iso,
    require_roles,
)

class ReminderSettingsIn(BaseModel):
    reminder_hours: float


@api_router.get("/settings/reminder")
async def get_reminder_setting(user: dict = Depends(get_current_user)):
    return await get_reminder_settings()


@api_router.put("/settings/reminder")
async def set_reminder_setting(payload: ReminderSettingsIn, user: dict = Depends(require_roles("super_admin"))):
    if payload.reminder_hours <= 0:
        raise HTTPException(status_code=400, detail="Reminder time must be greater than 0 hours")
    await settings_repo.upsert("reminder", {
        "reminder_hours": payload.reminder_hours, "updated_at": now_iso(), "updated_by": user["name"]})
    return await get_reminder_settings()


# NOT used for routing any more: the Accounts Head now approves EVERY PO (see act_on_purchase_order).
# The setting and its endpoints are kept only so existing clients/data keep working.
DEFAULT_PO_ACCOUNTS_LIMIT = MD_THRESHOLD


async def get_po_accounts_limit() -> float:
    doc = await settings_repo.get("po_accounts_limit")
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
    await settings_repo.upsert("po_accounts_limit", {
        "amount": payload.amount, "updated_at": now_iso(), "updated_by": user["name"]})
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
    await settings_repo.upsert("po_threshold", {
        "amount": payload.amount, "updated_by": user["name"], "updated_at": now_iso()})
    return {"amount": payload.amount}


class CorrectionSettingsIn(BaseModel):
    reminder_hours: float
    escalation_hours: float
    max_failed_attempts: int
    max_reminders: int = 3


@api_router.get("/settings/correction")
async def get_correction_setting(user: dict = Depends(get_current_user)):
    return await get_correction_settings()


@api_router.put("/settings/correction")
async def set_correction_setting(payload: CorrectionSettingsIn, user: dict = Depends(get_current_user)):
    if not (user["role"] == "super_admin" or await _is_it_head(user)):
        raise HTTPException(status_code=403, detail="Only the IT Head or Super Admin can change these limits")
    if payload.reminder_hours <= 0 or payload.escalation_hours <= 0 or payload.max_failed_attempts < 1 or payload.max_reminders < 0:
        raise HTTPException(status_code=400, detail="Hours must be above 0 and attempts at least 1")
    if payload.escalation_hours < payload.reminder_hours:
        raise HTTPException(status_code=400, detail="The escalation time cannot be shorter than the reminder time")
    await settings_repo.upsert("correction", {
        "reminder_hours": payload.reminder_hours, "escalation_hours": payload.escalation_hours,
        "max_failed_attempts": payload.max_failed_attempts, "max_reminders": payload.max_reminders,
        "updated_at": now_iso(), "updated_by": user["name"]})
    return await get_correction_settings()
