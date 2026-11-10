"""Notifications."""

from fastapi import HTTPException, Depends
from pydantic import BaseModel
from typing import Literal
from ims.ids import ObjectId
import re
from ims.repositories import assets as asset_repo
from ims.repositories import correction_cases as case_repo
from ims.repositories import handovers as handover_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import notifications_repo as notif_repo
from ims.common import (
    _cor_attempt,
    _cor_delivered_for,
    _cor_finalize_original,
    _cor_mirror,
    _cor_notify_it,
    _cor_open_cases_for_handover,
    _cor_requested_for,
    _cor_requisition_blocked,
    _cor_save,
    _cor_set_status,
    _log_asset_event,
    api_router,
    get_current_user,
    now_iso,
    strip_id,
)

class NotifyConfirmIn(BaseModel):
    action: Literal["received", "pending"]


@api_router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    # "correction" = the employee reported a problem. That item is no longer shown in the bell (the
    # progress lives on the Corrections page); it comes back as a normal prompt if IT re-delivers.
    docs = await notif_repo.list_for_user(str(user["_id"]), ["unread", "pending"])
    out = []
    for n in docs:
        n = strip_id(n)
        if n.get("type") == "asset_receipt":
            await _enrich_receipt_notification(n)
        out.append(n)
    return out


async def _enrich_receipt_notification(n: dict) -> None:
    """What the employee needs to decide 'is this what I asked for?': the requested specification next
    to what was actually delivered (brand, model/spec, serial, tag)."""
    a = await asset_repo.get(n.get("asset_id"))
    req = await req_repo.get(n["requisition_id"]) if n.get("requisition_id") and ObjectId.is_valid(n["requisition_id"]) else None
    n["delivered"] = await _cor_delivered_for(a)
    n["requested"] = await _cor_requested_for(req, n.get("asset_name") or (a or {}).get("name") or "") if req else None
    n["requisition_no"] = (req or {}).get("requisition_no")


@api_router.post("/notifications/{nid}/read")
async def mark_notification_read(nid: str, user: dict = Depends(get_current_user)):
    """Generic mark-as-read for informational notifications (e.g. type == 'stock_allocated')
    that don't need a Yes/No confirmation, unlike asset_receipt notifications."""
    n = await notif_repo.get(nid)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.get("user_id") != str(user["_id"]) and user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Not your notification")
    await notif_repo.update_fields(nid, {"status": "read", "acted_at": now_iso()})
    return {"ok": True}


@api_router.post("/notifications/{nid}/confirm")
async def confirm_notification(nid: str, payload: NotifyConfirmIn, user: dict = Depends(get_current_user)):
    n = await notif_repo.get(nid)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not (n.get("user_id") == str(user["_id"]) or user["role"] == "super_admin"):
        raise HTTPException(status_code=403, detail="Not your notification")
    if n.get("status") not in ("unread", "pending"):
        raise HTTPException(status_code=400, detail="Notification already actioned")
    if payload.action != "received":
        # "No" is a correction request, not a dead end: it needs a reason and a note (POST /corrections).
        raise HTTPException(status_code=400, detail="Please report the problem with a reason and a written note so IT can correct it.")
    aid = n.get("asset_id")
    if payload.action == "received":
        # Employee confirmed receipt -> asset leaves central stock (deduct -1) and becomes assigned.
        if not (aid and ObjectId.is_valid(aid)) and n.get("asset_name"):
            # Older notifications / name-only handover lines have no asset_id, so nothing
            # would be deducted. Fall back to an in-stock asset of that name, preferring one
            # already reserved for this handover.
            cand = (await asset_repo.find_reservable(n["asset_name"], handover_id=n["handover_id"])
                    if n.get("handover_id") else None)
            if not cand:
                cand = await asset_repo.find_reservable(n["asset_name"])
            aid = str(cand["_id"]) if cand else None
        if aid and ObjectId.is_valid(aid):
            await asset_repo.update_fields(aid, {
                "status": "assigned", "assigned_to": n.get("employee_name"),
                "assigned_to_user_id": n.get("user_id"),
                "assigned_at": now_iso(), "assigned_handover_id": n.get("handover_id"),
                "assigned_slip_no": n.get("slip_no"),
                "receipt_confirmed": True, "receipt_confirmed_at": now_iso(),
                "pending_receipt": False, "pending_handover_id": None, "assigned_to_tentative": None})
            issued = await asset_repo.get(aid)
            if issued:
                await _log_asset_event(
                    issued, "issued", n.get("employee_name") or user["name"],
                    slip_no=n.get("slip_no"), handover_id=n.get("handover_id"),
                    employee_user_id=n.get("user_id"), employee_name=n.get("employee_name"))
        await notif_repo.update_fields(nid, {"status": "confirmed", "acted_at": now_iso()})

        hid = n.get("handover_id")
        rid = n.get("requisition_id")
        # Fall back to resolving the requisition via the handover. Notifications created
        # before requisition_id was carried through (or via an ad-hoc handover) have no
        # requisition_id of their own, which previously left the requisition stuck at its
        # pre-confirmation status forever.
        if not rid and hid and ObjectId.is_valid(hid):
            h = await handover_repo.get(hid)
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
            still_open = await notif_repo.count({
                "handover_id": hid, "type": "asset_receipt",
                "status": {"$in": ["unread", "pending"]}})
            # A replacement the employee just confirmed completes its correction case first, so the
            # checks below see it as done.
            await _cor_on_confirmed(n, user)
            # Items still in correction keep the slip (and the requisition) open: partial confirmation.
            open_cases = await _cor_open_cases_for_handover(hid)
            if still_open == 0 and open_cases > 0:
                await handover_repo.update_fields(hid, {"status": "partially_confirmed"})
            if still_open == 0 and open_cases == 0:
                # The handover record itself moves past "delivered" (physically handed
                # over, awaiting confirmation) to "confirmed" — this is what fixes the UI
                # showing a final-looking "Delivered" badge the instant IT clicks Handover
                # Done, before the employee has actually confirmed anything.
                await handover_repo.update_fields(hid, {"status": "confirmed", "confirmed_at": now_iso()})
                if rid and ObjectId.is_valid(rid) and not await _cor_requisition_blocked(rid):
                    req = await req_repo.get(rid)
                    if req:
                        req.setdefault("history", []).append({
                            "at": now_iso(), "by": n.get("employee_name") or "requester",
                            "action": "receipt_confirmed", "note": "Requester confirmed physical receipt."})
                        requisition_status = "handover_done"
                        await req_repo.save_progress(rid, status="handover_done", history=req["history"],
                                                     updated_at=now_iso(), closed_at=now_iso())
        return {"ok": True, "status": "confirmed", "stock_deducted": bool(aid and ObjectId.is_valid(aid)),
                "requisition_id": rid, "requisition_status": requisition_status}


async def _cor_on_confirmed(n: dict, user: dict) -> None:
    """Hook called when the employee confirms a correction-linked delivery."""
    cid = n.get("correction_case_id")
    if not (cid and ObjectId.is_valid(cid)):
        return
    case = await case_repo.get(cid)
    if not case or case["status"] != "delivered_again":
        return
    att = _cor_attempt(case)
    att.update({"status": "confirmed", "confirmed_at": now_iso()})
    case["confirmed_at"] = now_iso()
    _cor_set_status(case, user["name"], "confirmed", f"{case['employee_name']} confirmed receipt of the correct item (attempt {att['attempt_no']})", action="employee_confirmed")
    await _cor_save(case)
    await _cor_mirror(case, user["name"], "correction_confirmed", f"Replacement confirmed (attempt {att['attempt_no']})")
    await _cor_notify_it(case, "correction_update", f"{case['employee_name']} confirmed the replacement for {case['case_no']}. You can close the case.")
    await _cor_finalize_original(case, case["employee_name"])
