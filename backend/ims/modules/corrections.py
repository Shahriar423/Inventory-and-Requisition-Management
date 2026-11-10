"""Delivery corrections (not-received / wrong-item flow) and analytics."""

from fastapi import HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal, Dict
from datetime import datetime, timezone
from ims.ids import ObjectId
import re
from ims.repositories import users as users_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import notifications_repo as notif_repo
from ims.repositories import files_repo
from ims.repositories import correction_cases as case_repo
from ims.repositories import assets as asset_repo
from ims.repositories import handovers as handover_repo
from ims.common import (
    CONDITION_LABELS,
    COR_OPEN_STATUSES,
    COR_REASONS,
    COR_STATUS_LABELS,
    RP_UNIT_STATUS_LABEL,
    _can_manage_handovers,
    _cor_attempt,
    _cor_delivered_for,
    _cor_escalate,
    _cor_event,
    _cor_finalize_original,
    _cor_mirror,
    _cor_notify,
    _cor_notify_it,
    _cor_requested_for,
    _cor_save,
    _cor_set_status,
    _is_it_head,
    _log_asset_event,
    _next_no,
    _parse_iso,
    _pkey,
    _release_slip_locks,
    _rp_and,
    api_router,
    get_correction_settings,
    get_current_user,
    mark_handover_delivered,
    next_req_number,
    now_iso,
    process_waiting_stock_requisitions,
    resolve_category_name,
)

COR_CLOSE_REASONS = {
    "resolved": "Resolved - employee confirmed the correct item",
    "requirement_cancelled": "Requirement cancelled",
    "employee_withdrew": "Employee withdrew the report",
    "duplicate": "Duplicate / raised in error",
    "other": "Other (explain in the note)",
}


COR_RETURN_DESTINATIONS = ("in_stock", "under_repair", "scrapped")


def _cor_open(case: dict) -> bool:
    return case.get("status") in COR_OPEN_STATUSES


async def _cor_asset_event(asset: Optional[dict], event: str, case: dict, by: str, **extra) -> None:
    if asset:
        await _log_asset_event(asset, event, by, employee_user_id=case.get("employee_user_id"),
                               employee_name=case.get("employee_name"), correction_case=case["case_no"], **extra)


async def _handover_it_user(h: dict) -> Optional[dict]:
    """The IT employee who did the original handover (the one who pressed Handover Done), falling
    back to the person who prepared the slip."""
    u = None
    if h.get("delivered_by_id") and ObjectId.is_valid(h["delivered_by_id"]):
        u = await users_repo.get(h["delivered_by_id"])
    for nm in (h.get("delivered_by"), h.get("prepared_by")):
        if not u and nm and nm != "system":
            u = await users_repo.get_by_name(nm)
    return u


def _cor_norm(s: Optional[str]) -> str:
    return re.sub(r"[\s\"']+", "", (s or "").lower())


_COR_SPEC_TOKEN = re.compile(r"\d+(?:\.\d+)?\s*(?:inch|in|\"|gb|tb|mb|mhz|ghz|hz|w|mp|v|a)?", re.I)


def _cor_spec_check(requested: dict, asset: Optional[dict]) -> dict:
    """Soft check of a stock unit against the approved requirement. Numeric specs (21 inch, 16GB,
    512GB ...) must all appear in the unit's brand/model/specification text; a requested brand must
    match. Returns {match, warnings} - the caller decides whether a mismatch may be overridden."""
    a = asset or {}
    blob = _cor_norm(" ".join(str(x or "") for x in (a.get("name"), a.get("brand"), a.get("model"), a.get("specification"))))
    warnings: List[str] = []
    specs = (requested or {}).get("detailed_specs") or ""
    for tok in dict.fromkeys(t.strip() for t in _COR_SPEC_TOKEN.findall(specs) if t.strip()):
        if _cor_norm(tok) and _cor_norm(tok) not in blob:
            warnings.append(f"Requested “{tok}” is not found in this unit's specification")
    pb = (requested or {}).get("preferred_brand")
    if pb and _cor_norm(pb) not in _cor_norm(a.get("brand")):
        warnings.append(f"Requested brand “{pb}” - this unit is {a.get('brand') or 'unbranded'}")
    if specs and not (a.get("specification") or a.get("model")) and not warnings:
        warnings.append("This unit has no recorded specification, so it cannot be verified against the requirement")
    return {"match": not warnings, "warnings": warnings}


async def _cor_viewer(case: dict, user: dict) -> str:
    """'it' (can run the case), 'employee' (the reporter), 'target' (asked to clarify) or '' (no access)."""
    if user["role"] == "super_admin" or await _can_manage_handovers(user):
        return "it"
    uid = str(user["_id"])
    if uid == case.get("responsible_it_id"):
        return "it"
    if uid == case.get("employee_user_id"):
        return "employee"
    if any(c.get("to_user_id") == uid for c in case.get("clarifications") or []):
        return "target"
    return ""


async def _cor_load(case_id: str, user: dict, need: Optional[str] = None):
    if not ObjectId.is_valid(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    case = await case_repo.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    role = await _cor_viewer(case, user)
    if not role:
        raise HTTPException(status_code=404, detail="Case not found")      # no access: indistinguishable from missing
    if need == "it" and role != "it":
        raise HTTPException(status_code=403, detail="Only IT can do this")
    return case, role


class CorrectionCreateIn(BaseModel):
    notification_id: str
    reason: str
    note: str
    attachment_file_id: Optional[str] = None
    attachment_name: Optional[str] = None


@api_router.get("/corrections/reasons")
async def correction_reasons(user: dict = Depends(get_current_user)):
    return [{"value": k, "label": v} for k, v in COR_REASONS.items()]


@api_router.post("/corrections")
async def correction_create(payload: CorrectionCreateIn, user: dict = Depends(get_current_user)):
    if payload.reason not in COR_REASONS:
        raise HTTPException(status_code=400, detail="Choose a reason from the list")
    note = (payload.note or "").strip()
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Please explain the problem in writing")
    if not ObjectId.is_valid(payload.notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    n = await notif_repo.get(payload.notification_id)
    if not n or n.get("type") != "asset_receipt":
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.get("user_id") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="This is not your delivery")
    if n.get("status") == "confirmed":
        raise HTTPException(status_code=400, detail="You already confirmed this delivery. It is final and cannot be rejected now.")
    if n.get("status") not in ("unread", "pending"):
        raise HTTPException(status_code=409, detail="A problem was already reported for this item")
    if payload.attachment_file_id:
        rec = await files_repo.get(payload.attachment_file_id)
        if not rec or not str(rec.get("content_type") or "").startswith("image/"):
            raise HTTPException(status_code=400, detail="The attachment must be a photo (an image file)")

    hid = n.get("handover_id")
    h = await handover_repo.get(hid) if hid and ObjectId.is_valid(hid) else None
    if not h:
        raise HTTPException(status_code=404, detail="The handover for this item was not found")
    asset = await asset_repo.get(n["asset_id"]) if n.get("asset_id") and ObjectId.is_valid(n["asset_id"]) else None
    now = now_iso()

    # --- a rejected RE-DELIVERY reopens the same case as a failed attempt ---
    if n.get("correction_case_id") and ObjectId.is_valid(n["correction_case_id"]):
        case = await case_repo.get(n["correction_case_id"])
        if not case or case.get("status") != "delivered_again":
            raise HTTPException(status_code=409, detail="This replacement is no longer awaiting your confirmation")
        att = _cor_attempt(case)
        att["status"] = "rejected"
        att["rejected_at"] = now
        case["failed_attempts"] = case.get("failed_attempts", 0) + 1
        case.update({"reason": payload.reason, "reason_label": COR_REASONS[payload.reason], "note": note,
                     "attachment_file_id": payload.attachment_file_id, "attachment_name": payload.attachment_name,
                     "notification_id": str(n["_id"])})
        case.setdefault("rejections", []).append({"at": now, "attempt_no": att["attempt_no"], "reason": payload.reason,
                                                  "note": note, "attachment_file_id": payload.attachment_file_id})
        _cor_event(case, user["name"], "rejected_by_employee", f"Attempt {att['attempt_no']} rejected: {COR_REASONS[payload.reason]} — {note}",
                   reason=payload.reason, attachment=payload.attachment_file_id)
        _cor_set_status(case, user["name"], "reported_to_it", "Replacement rejected - IT notified", action="reported_to_it")
        await _cor_save(case)
        await notif_repo.update_fields(n["_id"], {"status": "correction", "acted_at": now})
        await _cor_asset_event(asset, "correction_rejected", case, user["name"], remarks=f"{COR_REASONS[payload.reason]}: {note}")
        await _cor_mirror(case, user["name"], "correction_rejected_again", f"Attempt {att['attempt_no']} rejected - {COR_REASONS[payload.reason]}")
        await _cor_notify_it(case, "correction_reported",
                             f"{case['employee_name']} rejected the replacement ({case['case_no']}, attempt {att['attempt_no']}): {COR_REASONS[payload.reason]} — {note}")
        cfg = await get_correction_settings()
        if case["failed_attempts"] >= cfg["max_failed_attempts"]:
            await _cor_escalate(case, "failed_deliveries", f"{case['failed_attempts']} delivery attempts have failed")
        return await _cor_view(case, user)

    # --- first rejection of this item ---
    if await case_repo.find_open_for_notification(str(n["_id"]), COR_OPEN_STATUSES):
        raise HTTPException(status_code=409, detail="A problem was already reported for this item")
    req = await req_repo.get(h["requisition_id"]) if h.get("requisition_id") and ObjectId.is_valid(h["requisition_id"]) else None
    it_user = await _handover_it_user(h)
    pname = (asset or {}).get("name") or n.get("asset_name") or "Item"
    case = {
        "case_no": await _next_no("COR", "correction"), "status": "reported_to_it", "version": 0,
        "requisition_id": h.get("requisition_id"), "requisition_no": (req or {}).get("requisition_no"),
        "original_handover_id": hid, "original_slip_no": h.get("slip_no"),
        "employee_user_id": str(user["_id"]), "employee_name": n.get("employee_name") or user["name"],
        "department_id": h.get("department_id"), "notification_id": str(n["_id"]),
        "item": {"asset_id": n.get("asset_id"), "product_name": pname,
                 "requested": await _cor_requested_for(req, pname), "delivered": await _cor_delivered_for(asset)},
        "reason": payload.reason, "reason_label": COR_REASONS[payload.reason], "note": note,
        "attachment_file_id": payload.attachment_file_id, "attachment_name": payload.attachment_name,
        "responsible_it_id": str(it_user["_id"]) if it_user else None, "responsible_it_name": it_user.get("name") if it_user else None,
        "attempts": [{"attempt_no": 1, "handover_id": hid, "slip_no": h.get("slip_no"), "asset_id": n.get("asset_id"),
                      "asset_summary": " ".join(str(x) for x in (
                          (asset or {}).get("brand"), (asset or {}).get("model") or (asset or {}).get("specification"),
                          (asset or {}).get("serial_no") or (asset or {}).get("tag_id")) if x) or pname,
                      "delivered_at": h.get("delivered_at"), "delivered_by": h.get("delivered_by"),
                      "status": "rejected", "rejected_at": now, "return": None}],
        "failed_attempts": 1, "clarifications": [], "notes": [], "events": [], "procurement": None,
        "rejections": [{"at": now, "attempt_no": 1, "reason": payload.reason, "note": note, "attachment_file_id": payload.attachment_file_id}],
        "reminders": {"count": 0, "last_at": None}, "escalated_at": None, "escalations": [],
        "created_at": now, "last_activity_at": now, "closed_at": None, "closure": None, "confirmed_at": None,
    }
    _cor_event(case, user["name"], "rejected_by_employee", f"{COR_REASONS[payload.reason]} — {note}", None, "reported_to_it",
               reason=payload.reason, attachment=payload.attachment_file_id)
    _cor_event(case, "system", "reported_to_it", f"IT employee {case['responsible_it_name'] or '(none identified)'} notified", "reported_to_it", "reported_to_it")
    new_id = await case_repo.insert(case)
    case["_id"] = new_id
    # the original prompt is replaced by a status; nothing else on the slip is touched
    await notif_repo.update_fields(n["_id"], {
        "status": "correction", "correction_case_id": str(case["_id"]), "acted_at": now,
        "message": "Reported to IT — Waiting for Correction"})
    confirmed_siblings = await notif_repo.count({"handover_id": hid, "type": "asset_receipt", "status": "confirmed"})
    await handover_repo.update_fields(hid, {
        "status": "partially_confirmed" if confirmed_siblings else "correction_open"})
    await handover_repo.push_correction_case(hid, str(case["_id"]))
    await _cor_asset_event(asset, "correction_rejected", case, user["name"], slip_no=h.get("slip_no"), handover_id=hid,
                           remarks=f"{COR_REASONS[payload.reason]}: {note}")
    await _cor_mirror(case, user["name"], "correction_reported", f"{pname} rejected by the employee - {COR_REASONS[payload.reason]}")
    d = case["item"]["delivered"]
    await _cor_notify_it(case, "correction_reported", (
        f"{case['employee_name']} rejected {pname} on {case['requisition_no'] or 'slip ' + str(h.get('slip_no'))} ({case['case_no']}). "
        f"Reason: {COR_REASONS[payload.reason]} — “{note}”. Requested: {case['item']['requested'].get('detailed_specs') or '-'}; "
        f"delivered: {' '.join(str(x) for x in (d.get('brand'), d.get('model') or d.get('specification'), d.get('serial_no') or d.get('tag_id')) if x) or '-'}."
        f"{' Photo attached.' if payload.attachment_file_id else ''}"))
    return await _cor_view(case, user)


async def _cor_allowed_actions(case: dict, role: str, user: dict) -> List[str]:
    """What THIS viewer may do right now. The UI only renders these; the endpoints re-check them."""
    out: List[str] = []
    st = case["status"]
    head = user["role"] == "super_admin" or await _is_it_head(user)
    if st == "closed":
        if head and (case.get("closure") or {}).get("reason") != "resolved":
            out.append("reopen")
        return out
    out.append("note")
    if role in ("target", "employee"):
        if st == "waiting_clarification" and any(c.get("to_user_id") == str(user["_id"]) and not c.get("answer") for c in case["clarifications"]):
            out.append("answer_clarification")
        return out
    if role != "it":
        return out
    if st == "confirmed":
        return out + ["close"]
    att = _cor_attempt(case)
    needs_return = bool(att.get("asset_id")) and not att.get("return") and att["status"] == "rejected"
    if st == "reported_to_it":
        out.append("acknowledge")
    if needs_return and st in ("reported_to_it", "under_review", "waiting_clarification", "waiting_for_stock"):
        out.append("record_return")
    if st in ("reported_to_it", "under_review", "returned_to_it"):
        out.append("clarify")
    if st in ("reported_to_it", "under_review", "returned_to_it", "waiting_for_stock") and not needs_return:
        out.append("replace")
        if st != "waiting_for_stock":
            out.append("request_stock")
    if st == "redelivery_in_progress":
        out.append("deliver")
        out.append("cancel_replacement")
    if head and st != "delivered_again":          # closing without a confirmed replacement is an authorised decision
        out.append("close")
    return out


async def _cor_view(case: dict, user: dict, role: Optional[str] = None) -> dict:
    role = role or await _cor_viewer(case, user)
    c = dict(case)
    c["id"] = str(c.pop("_id"))
    c["status_label"] = COR_STATUS_LABELS.get(c["status"], c["status"])
    c["viewer_role"] = role
    c["allowed_actions"] = await _cor_allowed_actions(case, role, user)
    c["current_attempt"] = case["attempts"][-1]
    c["requires_return"] = bool(case["attempts"][-1].get("asset_id")) and not case["attempts"][-1].get("return")
    cfg = await get_correction_settings()
    age_h = (datetime.now(timezone.utc) - (_parse_iso(case.get("created_at")) or datetime.now(timezone.utc))).total_seconds() / 3600
    idle_h = (datetime.now(timezone.utc) - (_parse_iso(case.get("last_activity_at")) or datetime.now(timezone.utc))).total_seconds() / 3600
    c["age_hours"] = round(age_h, 1)
    c["overdue"] = _cor_open(case) and (idle_h >= cfg["reminder_hours"] or age_h >= cfg["escalation_hours"]) and case["status"] not in ("delivered_again",)
    if case.get("procurement") and case["procurement"].get("requisition_id") and ObjectId.is_valid(case["procurement"]["requisition_id"]):
        pr = await req_repo.get(case["procurement"]["requisition_id"])
        po = await po_repo.get(pr["po_id"]) if pr and pr.get("po_id") else None
        c["procurement_progress"] = {
            "requisition_id": case["procurement"]["requisition_id"], "requisition_no": (pr or {}).get("requisition_no"),
            "requisition_status": (pr or {}).get("status"), "pr_no": (pr or {}).get("purchase_pr_no"),
            "po_number": (po or {}).get("po_number"), "po_status": (po or {}).get("status")}
    if role == "it" and case["status"] in ("waiting_for_stock", "under_review", "returned_to_it", "reported_to_it"):
        name = case["item"]["product_name"]
        c["matching_stock"] = await asset_repo.count_available(name)
    return c


@api_router.get("/corrections")
async def correction_list(scope: str = "auto", status: Optional[str] = None, reason: Optional[str] = None,
                          overdue: bool = False, mine: bool = False, product: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    """IT / Super Admin see every case; everybody else only the cases they reported or were asked about."""
    manager = user["role"] == "super_admin" or await _can_manage_handovers(user)
    uid = str(user["_id"])
    q: dict = {} if (manager and scope != "mine") else {"employee_user_id": uid}
    if mine and manager:
        q = _rp_and(q, {"responsible_it_id": uid})
    if status == "open":
        q = _rp_and(q, {"status": {"$in": COR_OPEN_STATUSES}})
    elif status == "done":
        q = _rp_and(q, {"status": {"$in": ["confirmed", "closed"]}})
    elif status:
        q = _rp_and(q, {"status": status})
    if reason:
        q = _rp_and(q, {"reason": reason})
    docs = await case_repo.list_all(limit=2000)  # status filter applied in-memory for now
    if not manager:
        have = {str(d["_id"]) for d in docs}
        for c in await case_repo.list_all(limit=5000):
            if str(c["_id"]) not in have and any(x.get("to_user_id") == uid for x in c.get("clarifications") or []):
                docs.append(c)
    out = []
    for d in docs:
        v = await _cor_view(d, user)
        if product and product.lower() not in (d["item"].get("product_name") or "").lower():
            continue
        if overdue and not v["overdue"]:
            continue
        for k in ("events", "notes", "clarifications"):
            v.pop(k, None)
        out.append(v)
    return out


@api_router.get("/corrections/{case_id}")
async def correction_get(case_id: str, user: dict = Depends(get_current_user)):
    case, role = await _cor_load(case_id, user)
    return await _cor_view(case, user, role)


@api_router.post("/corrections/{case_id}/acknowledge")
async def correction_ack(case_id: str, user: dict = Depends(get_current_user)):
    case, role = await _cor_load(case_id, user, "it")
    if case["status"] != "reported_to_it":
        raise HTTPException(status_code=400, detail="Only a newly reported case can be acknowledged")
    case["acknowledged_by"], case["acknowledged_at"] = user["name"], now_iso()
    _cor_set_status(case, user["name"], "under_review", "IT acknowledged the report", action="acknowledged")
    await _cor_save(case)
    await _cor_notify(case["employee_user_id"], "correction_update", f"IT has acknowledged your report ({case['case_no']}) and is looking into it.", case)
    await _cor_mirror(case, user["name"], "correction_acknowledged", "IT acknowledged the report")
    return await _cor_view(case, user, role)


class CorrectionReturnIn(BaseModel):
    verify_code: Optional[str] = None
    condition: str = "good"
    destination: str = "in_stock"
    remarks: Optional[str] = None


@api_router.post("/corrections/{case_id}/return")
async def correction_return(case_id: str, payload: CorrectionReturnIn, user: dict = Depends(get_current_user)):
    """IT records that the rejected unit is physically back. Only now is the reservation released
    and the unit given its new inventory state - the employee's 'No' alone never touches stock."""
    case, role = await _cor_load(case_id, user, "it")
    if "record_return" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=400, detail="There is nothing to return at this stage of the case")
    att = _cor_attempt(case)
    asset = await asset_repo.get(att.get("asset_id"))
    if not asset:
        raise HTTPException(status_code=400, detail="No asset is linked to this delivery")
    code = (payload.verify_code or "").strip().lower()
    ids = {str(x).strip().lower() for x in (asset.get("tag_id"), asset.get("serial_no")) if x}
    if ids and code not in ids:
        raise HTTPException(status_code=400, detail="The asset tag / serial number you entered does not match the rejected unit. Check the device in your hands.")
    if payload.condition not in CONDITION_LABELS:
        raise HTTPException(status_code=400, detail="Choose a valid condition")
    if payload.destination not in COR_RETURN_DESTINATIONS:
        raise HTTPException(status_code=400, detail="Choose where the unit goes")
    if payload.condition != "good" and payload.destination == "in_stock":
        raise HTTPException(status_code=400, detail=f"A unit that is {CONDITION_LABELS.get(payload.condition, payload.condition)} must go to Under Repair or Scrapped, not back to stock.")
    if case["reason"] == "damaged" and payload.destination == "in_stock":
        raise HTTPException(status_code=400, detail="A unit reported damaged / not working must go to Under Repair for assessment before it can return to stock.")
    if asset.get("status") == "assigned" or (asset.get("status") == "in_stock" and asset.get("pending_handover_id") not in (att.get("handover_id"), None)):
        raise HTTPException(status_code=409, detail="This unit is no longer held for this delivery - check its inventory record.")
    if not await asset_repo.update_if(asset["_id"], {"status": asset.get("status")}, {
            "status": payload.destination, "condition": payload.condition, "pending_receipt": False, "pending_handover_id": None,
            "assigned_to_tentative": None, "assigned_department_id": None, "last_returned_at": now_iso(),
            "last_returned_by": case["employee_name"]}):
        raise HTTPException(status_code=409, detail="The asset changed while recording the return. Reload and try again.")
    att["return"] = {"at": now_iso(), "by": user["name"], "condition": payload.condition, "destination": payload.destination,
                     "verified_with": code or None, "remarks": payload.remarks}
    await _log_asset_event(asset, "correction_return", user["name"], slip_no=att.get("slip_no"), handover_id=att.get("handover_id"),
                           employee_user_id=case["employee_user_id"], employee_name=case["employee_name"], correction_case=case["case_no"],
                           condition=payload.condition, next_status=payload.destination, remarks=payload.remarks)
    note = f"Unit returned and verified; condition {CONDITION_LABELS.get(payload.condition)}, now {RP_UNIT_STATUS_LABEL.get(payload.destination, payload.destination)}"
    if case["status"] in ("reported_to_it", "under_review"):
        _cor_set_status(case, user["name"], "returned_to_it", note, action="returned_to_it", remarks=payload.remarks)
    else:
        _cor_event(case, user["name"], "returned_to_it", note, case["status"], case["status"], remarks=payload.remarks)
    await _cor_save(case)
    await _cor_mirror(case, user["name"], "correction_returned", note)
    if payload.destination == "in_stock":
        await process_waiting_stock_requisitions()
    return await _cor_view(case, user, role)


class CorrectionClarifyIn(BaseModel):
    question: str
    to: Literal["requester", "approver"] = "requester"


@api_router.post("/corrections/{case_id}/clarify")
async def correction_clarify(case_id: str, payload: CorrectionClarifyIn, user: dict = Depends(get_current_user)):
    case, role = await _cor_load(case_id, user, "it")
    if "clarify" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=400, detail="A clarification cannot be requested at this stage")
    q = (payload.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Write the question")
    req = await req_repo.get(case["requisition_id"]) if case.get("requisition_id") and ObjectId.is_valid(case["requisition_id"]) else None
    if not req:
        raise HTTPException(status_code=400, detail="The original requisition was not found")
    if payload.to == "requester":
        target_id, target_name = req.get("requisitioner_id"), req.get("requisitioner_name")
    else:
        step = next((s for s in req.get("approval_chain") or [] if s.get("status") == "approved" and s.get("approver_id")), None)
        if not step:
            raise HTTPException(status_code=400, detail="The original approver could not be found - ask the requester instead")
        target_id, target_name = step["approver_id"], step.get("approver_name")
    case["clarifications"].append({"asked_by": user["name"], "asked_by_id": str(user["_id"]), "asked_at": now_iso(), "question": q,
                                   "to_user_id": target_id, "to_name": target_name, "to_role": payload.to, "answer": None, "answered_at": None})
    case["status_before_clarification"] = case["status"]
    _cor_set_status(case, user["name"], "waiting_clarification", f"Asked {target_name}: {q}", action="clarification_requested")
    await _cor_save(case)
    await _cor_notify(target_id, "correction_clarification", f"IT needs a clarification for {case['item']['product_name']} ({case['case_no']}): “{q}”", case)
    await _cor_mirror(case, user["name"], "correction_clarification_requested", f"Question to {target_name}")
    return await _cor_view(case, user, role)


class CorrectionAnswerIn(BaseModel):
    answer: str


@api_router.post("/corrections/{case_id}/clarification")
async def correction_answer(case_id: str, payload: CorrectionAnswerIn, user: dict = Depends(get_current_user)):
    case, role = await _cor_load(case_id, user)
    uid = str(user["_id"])
    pending = next((c for c in reversed(case["clarifications"]) if c.get("to_user_id") == uid and not c.get("answer")), None)
    if case["status"] != "waiting_clarification" or not pending:
        raise HTTPException(status_code=400, detail="There is no open question for you on this case")
    a = (payload.answer or "").strip()
    if not a:
        raise HTTPException(status_code=400, detail="Write your answer")
    pending["answer"], pending["answered_at"], pending["answered_by"] = a, now_iso(), user["name"]
    back = case.get("status_before_clarification") or "under_review"
    if back == "reported_to_it":
        back = "under_review"
    _cor_set_status(case, user["name"], back, f"Clarification received: {a}", action="clarification_answered")
    await _cor_save(case)
    await _cor_notify_it(case, "correction_update", f"{user['name']} answered the clarification on {case['case_no']}: “{a}”", exclude=uid)
    await _cor_mirror(case, user["name"], "correction_clarification_answered", "Clarification answered")
    return await _cor_view(case, user, role)


class CorrectionNoteIn(BaseModel):
    text: str


@api_router.post("/corrections/{case_id}/notes")
async def correction_note(case_id: str, payload: CorrectionNoteIn, user: dict = Depends(get_current_user)):
    """Append-only conversation between IT and the employee. Notes cannot be edited or deleted."""
    case, role = await _cor_load(case_id, user)
    if case["status"] == "closed":
        raise HTTPException(status_code=400, detail="This case is closed")
    t = (payload.text or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail="Write a message")
    case["notes"].append({"at": now_iso(), "by": user["name"], "by_id": str(user["_id"]), "role": "IT" if role == "it" else "Employee", "text": t[:1000]})
    _cor_event(case, user["name"], "note_added", t[:200])
    await _cor_save(case)
    if role == "it":
        await _cor_notify(case["employee_user_id"], "correction_update", f"IT update on {case['case_no']}: “{t[:160]}”", case)
    else:
        await _cor_notify_it(case, "correction_update", f"{user['name']} added a note on {case['case_no']}: “{t[:160]}”", exclude=str(user["_id"]))
    return await _cor_view(case, user, role)


class CorrectionStockIn(BaseModel):
    note: Optional[str] = None


@api_router.post("/corrections/{case_id}/request-stock")
async def correction_request_stock(case_id: str, payload: CorrectionStockIn, user: dict = Depends(get_current_user)):
    """Correct item is not in stock -> Waiting for Stock, linked to the EXISTING PR/PO process by creating
    one linked requisition that carries the original (already approved) data into the PR Handler's queue."""
    case, role = await _cor_load(case_id, user, "it")
    if "request_stock" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=400, detail="Stock cannot be requested at this stage (the rejected unit must be returned first)")
    name = case["item"]["product_name"]
    # IT may always choose to buy, even when matching units are in stock (their call, not a system rule).
    if case.get("procurement"):
        raise HTTPException(status_code=409, detail="A procurement request is already linked to this case")
    orig = await req_repo.get(case["requisition_id"]) if case.get("requisition_id") and ObjectId.is_valid(case["requisition_id"]) else None
    if not orig:
        raise HTTPException(status_code=400, detail="The original requisition was not found")
    line = next((dict(i) for i in orig["items"] if _pkey(i.get("product_name")) == _pkey(name)), dict(orig["items"][0]))
    line["quantity"] = 1
    line["remarks"] = f"Replacement for rejected delivery ({case['case_no']}): {case['reason_label']}"
    req_no = await next_req_number()
    child = {
        "requisition_no": req_no, "requisitioner_id": orig.get("requisitioner_id"), "requisitioner_name": orig.get("requisitioner_name"),
        "requisitioner_department_id": orig.get("requisitioner_department_id"), "requisition_for": orig.get("requisition_for"),
        "requisition_type": orig.get("requisition_type", "product"), "items": [line], "total_amount": 0,
        "pr_flow": True, "po_flow": False, "stock_check_at_submission": "out_of_stock",
        "requester_note": f"Correction of {orig['requisition_no']} ({case['case_no']})",
        "attachment_path": orig.get("attachment_path"), "attachment_file_id": orig.get("attachment_file_id"),
        "attachment_name": orig.get("attachment_name"), "requisition_date": now_iso(),
        "approval_chain": orig.get("approval_chain") or [],           # already approved - not asked again
        "status": "pending_pr", "created_at": now_iso(), "updated_at": now_iso(),
        "overall_business_justification": orig.get("overall_business_justification"),
        "delivery_location": orig.get("delivery_location"), "required_by_date": orig.get("required_by_date"),
        "urgency_level": "High", "correction_case_id": str(case["_id"]), "correction_of_requisition_id": case["requisition_id"],
        "history": [{"at": now_iso(), "by": user["name"], "action": "created", "note": f"Raised from correction case {case['case_no']} (original {orig['requisition_no']})."},
                    {"at": now_iso(), "by": "system", "action": "awaiting_pr_handler",
                     "note": "Original approvals reused - awaiting PR Handler (raise the PR; normal PR/PO approvals still apply)."}],
    }
    child_oid = await req_repo.insert(child)
    case["procurement"] = {"requisition_id": str(child_oid), "requisition_no": req_no, "created_at": now_iso(), "created_by": user["name"]}
    _cor_set_status(case, user["name"], "waiting_for_stock", payload.note or f"No matching stock - procurement requisition {req_no} raised", action="waiting_for_stock")
    await _cor_save(case)
    await _cor_notify(case["employee_user_id"], "correction_update", f"The correct {name} is not in stock. IT has started procurement ({req_no}). You will be updated here.", case)
    for pr_user in await users_repo.list_pr_processors():
        if str(pr_user["_id"]) == str(user["_id"]):
            continue          # the person who just raised it does not need a notification about their own action
        await _cor_notify(str(pr_user["_id"]), "correction_update", f"{req_no}: replacement for {name} needs a Purchase Requisition ({case['case_no']}).", case)
    await _cor_mirror(case, user["name"], "correction_waiting_for_stock", f"Procurement requisition {req_no} linked")
    return await _cor_view(case, user, role)


@api_router.get("/corrections/{case_id}/stock-options")
async def correction_stock_options(case_id: str, user: dict = Depends(get_current_user)):
    case, role = await _cor_load(case_id, user, "it")
    name = case["item"]["product_name"]
    out = []
    for a in await asset_repo.list_available(name, limit=500):
        if a.get("condition") not in (None, "good"):
            continue
        chk = _cor_spec_check(case["item"]["requested"], a)
        out.append({"asset_id": str(a["_id"]), "name": a.get("name"), "brand": a.get("brand"), "model": a.get("model"), "specification": a.get("specification"),
                    "serial_no": a.get("serial_no"), "tag_id": a.get("tag_id"), "category_name": await resolve_category_name(a.get("category_id")),
                    "received_at": a.get("created_at"), "match": chk["match"], "warnings": chk["warnings"]})
    out.sort(key=lambda x: (not x["match"], str(x["tag_id"] or x["serial_no"])))
    return {"requested": case["item"]["requested"], "options": out}


class CorrectionReplaceIn(BaseModel):
    asset_id: str
    confirm_mismatch: bool = False
    remarks: Optional[str] = None


@api_router.post("/corrections/{case_id}/replace")
async def correction_replace(case_id: str, payload: CorrectionReplaceIn, user: dict = Depends(get_current_user)):
    """Option A: reserve an in-stock unit and create a NEW linked handover slip (attempt N)."""
    case, role = await _cor_load(case_id, user, "it")
    if "replace" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=400, detail="A replacement cannot be allocated yet - the rejected unit must be returned first and the case must not be waiting for a clarification")
    if not ObjectId.is_valid(payload.asset_id):
        raise HTTPException(status_code=400, detail="Choose a unit")
    asset = await asset_repo.get(payload.asset_id)
    if not asset or asset.get("status") != "in_stock" or asset.get("pending_receipt") or asset.get("condition") not in (None, "good"):
        raise HTTPException(status_code=409, detail="That unit is not available (it may be reserved, assigned or under repair)")
    if _pkey(asset.get("name")) != _pkey(case["item"]["product_name"]):
        raise HTTPException(status_code=400, detail="The replacement must be the same product")
    chk = _cor_spec_check(case["item"]["requested"], asset)
    if not chk["match"] and not payload.confirm_mismatch:
        raise HTTPException(status_code=409, detail={"code": "spec_mismatch", "message": "This unit does not match the approved requirement.", "warnings": chk["warnings"]})
    n_attempt = len(case["attempts"]) + 1
    child_id = (case.get("procurement") or {}).get("requisition_id")
    emp = await users_repo.get(case["employee_user_id"])
    orig_h = await handover_repo.get(case["original_handover_id"])
    slip_no = await _next_no("HO", "handover")
    doc = {
        "slip_no": slip_no, "type": "handover", "employee_name": case["employee_name"], "employee_user_id": case["employee_user_id"],
        "department_id": case.get("department_id") or (emp or {}).get("department_id"),
        "items": [{"item": asset["name"], "brand": asset.get("brand"), "quantity": 1, "remarks": payload.remarks, "asset_id": payload.asset_id}],
        "remarks": f"Replacement ({case['case_no']}, attempt {n_attempt}) for slip {case['original_slip_no']}",
        "note": None, "handover_date": now_iso(), "prepared_by": user["name"], "prepared_by_sign": None, "received_by_sign": None,
        "created_at": now_iso(), "status": "prepared", "requisition_id": child_id or case.get("requisition_id"),
        "correction_case_id": str(case["_id"]), "correction_case_no": case["case_no"], "attempt_no": n_attempt,
        "original_handover_id": case["original_handover_id"], "original_slip_no": case["original_slip_no"],
        "original_requisition_no": case.get("requisition_no"),
        "requested_spec": case["item"]["requested"].get("detailed_specs"),
        "delivered_spec": " ".join(str(x) for x in (asset.get("brand"), asset.get("model"), asset.get("specification")) if x),
    }
    new_hid = await handover_repo.insert(doc)
    hid = str(new_hid)
    if not await asset_repo.update_if(asset["_id"], {"status": "in_stock", "pending_receipt": {"$ne": True}}, {
            "pending_receipt": True, "pending_handover_id": hid, "assigned_to_tentative": case["employee_name"],
            "assigned_department_id": doc["department_id"]}):
        await handover_repo.delete(new_hid)
        raise HTTPException(status_code=409, detail="Someone reserved that unit a moment ago. Pick another.")
    if child_id and ObjectId.is_valid(child_id):
        await req_repo.link_handover(child_id, hid, "pending_handover")
    case["attempts"].append({"attempt_no": n_attempt, "handover_id": hid, "slip_no": slip_no, "asset_id": payload.asset_id,
                             "asset_summary": " ".join(str(x) for x in (asset.get("brand"), asset.get("model") or asset.get("specification"), asset.get("serial_no") or asset.get("tag_id")) if x) or asset["name"],
                             "delivered_at": None, "delivered_by": None, "status": "prepared", "return": None,
                             "spec_warnings": chk["warnings"], "mismatch_override": bool(chk["warnings"] and payload.confirm_mismatch)})
    note = f"Replacement reserved: slip {slip_no} (attempt {n_attempt})" + (f" - mismatch accepted by {user['name']}: {'; '.join(chk['warnings'])}" if chk["warnings"] else "")
    _cor_set_status(case, user["name"], "redelivery_in_progress", note, action="replacement_allocated", handover_id=hid)
    await _cor_save(case)
    await _log_asset_event(asset, "correction_replacement_reserved", user["name"], slip_no=slip_no, handover_id=hid,
                           employee_user_id=case["employee_user_id"], employee_name=case["employee_name"], correction_case=case["case_no"])
    await _cor_notify(case["employee_user_id"], "correction_update", f"IT has prepared a replacement {asset['name']} for you ({case['case_no']}, attempt {n_attempt}).", case)
    await _cor_mirror(case, user["name"], "correction_replacement", note)
    return await _cor_view(case, user, role)


@api_router.post("/corrections/{case_id}/deliver")
async def correction_deliver(case_id: str, user: dict = Depends(get_current_user)):
    """Physically delivered: same 'Handover Done' step as everywhere else (raises the employee's confirmation)."""
    case, role = await _cor_load(case_id, user, "it")
    if case["status"] != "redelivery_in_progress":
        raise HTTPException(status_code=400, detail="There is no replacement waiting to be delivered")
    await mark_handover_delivered(_cor_attempt(case)["handover_id"], user)
    case = await case_repo.get(case["_id"])
    return await _cor_view(case, user, role)


@api_router.post("/corrections/{case_id}/cancel-replacement")
async def correction_cancel_replacement(case_id: str, user: dict = Depends(get_current_user)):
    """IT picked a unit by mistake (before 'Handover Done'): free the reserved unit, drop the prepared
    slip and put the case back to where it was so another unit can be selected."""
    case, role = await _cor_load(case_id, user, "it")
    if "cancel_replacement" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=400, detail="There is no selected replacement to cancel")
    att = _cor_attempt(case)
    if att.get("status") != "prepared" or len(case["attempts"]) < 2:
        raise HTTPException(status_code=400, detail="The replacement was already handed over, so the selection cannot be cancelled")
    hid = att["handover_id"]
    h = await handover_repo.get(hid) if hid and ObjectId.is_valid(hid) else None
    if h and h.get("status") != "prepared":
        raise HTTPException(status_code=400, detail="The replacement slip is already in progress, so the selection cannot be cancelled")
    asset = await asset_repo.get(att.get("asset_id"))
    await _release_slip_locks(hid)
    if h:
        await handover_repo.delete(h["_id"])
    child_id = (case.get("procurement") or {}).get("requisition_id")
    if child_id and ObjectId.is_valid(child_id):
        await req_repo.clear_handover(child_id, "stock_received_in_it")
    back = next((e.get("from_status") for e in reversed(case.get("events", [])) if e.get("action") == "replacement_allocated"), None)
    if back not in ("reported_to_it", "under_review", "returned_to_it", "waiting_for_stock"):
        back = "returned_to_it"
    case["attempts"].pop()
    note = f"Replacement selection cancelled (slip {att['slip_no']} removed, {att['asset_summary']} released to stock)"
    _cor_set_status(case, user["name"], back, note, action="replacement_cancelled")
    await _cor_save(case)
    if asset:
        await _log_asset_event(asset, "correction_replacement_cancelled", user["name"], slip_no=att["slip_no"],
                               correction_case=case["case_no"])
    await _cor_mirror(case, user["name"], "correction_replacement_cancelled", note)
    return await _cor_view(case, user, role)


class CorrectionCloseIn(BaseModel):
    reason: str
    note: Optional[str] = None


@api_router.post("/corrections/{case_id}/close")
async def correction_close(case_id: str, payload: CorrectionCloseIn, user: dict = Depends(get_current_user)):
    case, role = await _cor_load(case_id, user, "it")
    if "close" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=403, detail="You cannot close this case now. Only a confirmed case can be closed by IT; an unresolved case needs the IT Head or Super Admin.")
    if payload.reason not in COR_CLOSE_REASONS:
        raise HTTPException(status_code=400, detail="Choose a closure reason")
    if payload.reason != "resolved" and not (user["role"] == "super_admin" or await _is_it_head(user)):
        raise HTTPException(status_code=403, detail="Closing without a confirmed replacement needs the IT Head or Super Admin")
    note = (payload.note or "").strip()
    if payload.reason == "resolved":
        if case["status"] != "confirmed":
            raise HTTPException(status_code=400, detail="A case can be closed as resolved only after the employee confirmed the correct item")
    else:
        if len(note) < 3:
            raise HTTPException(status_code=400, detail="Explain why the case is being closed without a confirmed replacement")
        att = _cor_attempt(case)
        if case["status"] == "delivered_again":
            raise HTTPException(status_code=400, detail="A replacement is awaiting the employee's confirmation")
        if att.get("asset_id") and att["status"] == "rejected" and not att.get("return"):
            raise HTTPException(status_code=400, detail="Record the physical return of the rejected unit before closing the case")
        if att["status"] == "prepared":                      # release the reserved replacement
            a = await asset_repo.get(att["asset_id"])
            if a:
                await asset_repo.update_fields(a["_id"], {"pending_receipt": False, "pending_handover_id": None,
                                                          "assigned_to_tentative": None, "assigned_department_id": None})
                await _log_asset_event(a, "correction_reservation_released", user["name"], correction_case=case["case_no"])
            await handover_repo.update_fields(att["handover_id"], {"status": "cancelled"})
            att["status"] = "cancelled"
    case["closure"] = {"reason": payload.reason, "reason_label": COR_CLOSE_REASONS[payload.reason], "note": note, "by": user["name"], "at": now_iso()}
    case["closed_at"] = now_iso()
    _cor_set_status(case, user["name"], "closed", f"{COR_CLOSE_REASONS[payload.reason]}{(' - ' + note) if note else ''}", action="closed")
    await _cor_save(case)
    await notif_repo.resolve_for_correction_case(str(case["_id"]))
    await _cor_notify(case["employee_user_id"], "correction_update", f"Your report {case['case_no']} was closed: {COR_CLOSE_REASONS[payload.reason]}.", case)
    await _cor_mirror(case, user["name"], "correction_closed", COR_CLOSE_REASONS[payload.reason])
    await _cor_finalize_original(case, user["name"])
    return await _cor_view(case, user, role)


class CorrectionReopenIn(BaseModel):
    note: str


@api_router.post("/corrections/{case_id}/reopen")
async def correction_reopen(case_id: str, payload: CorrectionReopenIn, user: dict = Depends(get_current_user)):
    """Authorised users only. A case that ended with the employee's confirmation is final."""
    case, role = await _cor_load(case_id, user, "it")
    if "reopen" not in await _cor_allowed_actions(case, role, user):
        raise HTTPException(status_code=403, detail="Only the IT Head or Super Admin can reopen a case that was closed without a confirmed replacement")
    if not (payload.note or "").strip():
        raise HTTPException(status_code=400, detail="Explain why the case is being reopened")
    case["closure"], case["closed_at"] = None, None
    _cor_set_status(case, user["name"], "under_review", f"Reopened: {payload.note.strip()}", action="reopened")
    await _cor_save(case)
    await _cor_mirror(case, user["name"], "correction_reopened", payload.note.strip())
    return await _cor_view(case, user, role)


@api_router.get("/corrections-analytics")
async def correction_analytics(user: dict = Depends(get_current_user)):
    if not (user["role"] == "super_admin" or await _can_manage_handovers(user)):
        raise HTTPException(status_code=403, detail="Only IT can see correction analytics")
    cases = await case_repo.list_all(limit=20000)
    def bucket(key_fn):
        d: Dict[str, dict] = {}
        for c in cases:
            k = key_fn(c) or "-"
            b = d.setdefault(k, {"key": k, "total": 0, "open": 0, "attempts": 0})
            b["total"] += 1
            b["open"] += 1 if _cor_open(c) else 0
            b["attempts"] += len(c["attempts"])
        return sorted(d.values(), key=lambda x: -x["total"])
    rb: Dict[str, dict] = {}                      # every rejection counts (a failed replacement is a second one)
    for c in cases:
        for rj in (c.get("rejections") or [{"reason": c.get("reason")}]):
            b = rb.setdefault(rj.get("reason") or "-", {"key": rj.get("reason") or "-", "total": 0, "open": 0, "attempts": 0})
            b["total"] += 1
    reason_buckets = sorted(rb.values(), key=lambda x: -x["total"])
    done = [c for c in cases if c.get("status") in ("confirmed", "closed")]
    hrs = []
    for c in done:
        s, e = _parse_iso(c.get("created_at")), _parse_iso(c.get("confirmed_at") or c.get("closed_at"))
        if s and e:
            hrs.append((e - s).total_seconds() / 3600)
    cfg = await get_correction_settings()
    overdue = []
    for c in cases:
        if _cor_open(c):
            v = await _cor_view(c, user)
            if v["overdue"]:
                overdue.append({"id": v["id"], "case_no": c["case_no"], "product": c["item"]["product_name"], "employee": c["employee_name"],
                                "status_label": v["status_label"], "age_hours": v["age_hours"], "responsible_it": c.get("responsible_it_name")})
    return {
        "total": len(cases), "open": sum(1 for c in cases if _cor_open(c)),
        "by_reason": [{**b, "label": COR_REASONS.get(b["key"], b["key"])} for b in reason_buckets],
        "by_product": bucket(lambda c: c["item"]["product_name"]),
        "by_model": bucket(lambda c: " ".join(str(x) for x in (c["item"]["delivered"].get("brand"), c["item"]["delivered"].get("model") or c["item"]["delivered"].get("specification")) if x)),
        "by_it_employee": bucket(lambda c: c.get("responsible_it_name")),
        "by_status": [{**b, "label": COR_STATUS_LABELS.get(b["key"], b["key"])} for b in bucket(lambda c: c["status"])],
        "by_attempts": bucket(lambda c: f"{len(c['attempts'])} attempt(s)"),
        "avg_resolution_hours": round(sum(hrs) / len(hrs), 1) if hrs else None, "resolved_count": len(done),
        "overdue": overdue, "settings": cfg,
    }
