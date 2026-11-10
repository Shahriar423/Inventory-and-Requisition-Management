"""IT service requests."""

from fastapi import HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal
from ims.ids import ObjectId
from ims.repositories import users as users_repo
from ims.repositories import requisitions as req_repo
from ims.common import (
    IT_TEAMS,
    IT_TEAM_LABELS,
    SERVICE_QUEUE_OPEN,
    _is_it_head,
    _notify,
    _notify_with_delegate,
    api_router,
    attach_department_names,
    attach_file_info,
    find_dept_by_name,
    get_current_user,
    it_queue_teams_for,
    now_iso,
    serialize_req,
)

SERVICE_QUEUE_ACTIVE = "service_in_progress"


SERVICE_QUEUE_DONE = "service_completed_and_returned"


# External repair (device cannot be fixed on site): requested by the executive, approved by the IT Head.
SERVICE_REPAIR_PENDING = "pending_repair_approval"


SERVICE_IN_SERVICE = "product_in_service"          # at the external service center


SERVICE_WORKING = [SERVICE_QUEUE_ACTIVE, SERVICE_REPAIR_PENDING, SERVICE_IN_SERVICE]   # picked up, not yet closed


PRIORITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _is_hardware_ticket(t: dict) -> bool:
    return t.get("it_team") == "Network_Infra" and any(
        it.get("service_category") == "hardware_support" for it in t.get("items", []))


def _ticket_priority(t: dict) -> str:
    best = max((it.get("priority") or "low" for it in t.get("items", [])), key=lambda p: PRIORITY_RANK.get(p, 0), default="low")
    return best


async def _ticket_actions(t: dict, user: dict, teams: List[str]) -> dict:
    """What this user may do to this ticket right now (drives the buttons; the endpoints enforce it)."""
    uid = str(user["_id"])
    is_super = user.get("role") == "super_admin"
    head_only = (not is_super) and await _is_it_head(user)       # IT Head: supervises, does not work tickets
    is_head = is_super or head_only
    mine = t.get("service_assigned_to_id") == uid
    in_team = t.get("it_team") in teams
    st = t.get("status")
    return {
        "claim": in_team and st == SERVICE_QUEUE_OPEN and not head_only,
        "release": in_team and st == SERVICE_QUEUE_ACTIVE and (mine or is_super),
        "complete": in_team and st == SERVICE_QUEUE_ACTIVE and (mine or is_super),
        # External repair: Network_Infra hardware tickets only.
        "request_repair": (in_team and st == SERVICE_QUEUE_ACTIVE and (mine or is_super)
                           and _is_hardware_ticket(t)),
        "decide_repair": in_team and st == SERVICE_REPAIR_PENDING and is_head,
        "mark_repaired": in_team and st == SERVICE_IN_SERVICE and (mine or is_super),
    }


async def _load_visible_ticket(ticket_id: str, user: dict, allow_head: bool = False) -> tuple[dict, List[str]]:
    if not allow_head and await _is_it_head(user):
        raise HTTPException(status_code=403, detail="The IT Head does not work service tickets - only repair approvals are handled by the Head")
    teams = await it_queue_teams_for(user)
    if not teams:
        raise HTTPException(status_code=403, detail="You do not have access to the IT service queues")
    if not ObjectId.is_valid(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    t = await req_repo.get_service_ticket(ticket_id, IT_TEAMS)
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
    repair_only = await _is_it_head(user)       # IT Head: repair approvals only, not the working queue
    if repair_only:
        view = "repair"
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
    docs = await req_repo.find_filtered(q, newest_first=False, limit=500)
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
        "open": await req_repo.count_filtered({**base, "status": SERVICE_QUEUE_OPEN}),
        "active": await req_repo.count_filtered({**base, "status": {"$in": SERVICE_WORKING}}),
        "repair": await req_repo.count_filtered({**base, "status": {"$in": [SERVICE_REPAIR_PENDING, SERVICE_IN_SERVICE]}}),
        "repair_approvals": await req_repo.count_filtered({**base, "status": SERVICE_REPAIR_PENDING}),
        "mine": await req_repo.count_filtered({**base, "status": {"$in": SERVICE_WORKING}, "service_assigned_to_id": uid}),
    }
    if repair_only:
        counts = {"repair": counts["repair"], "repair_approvals": counts["repair_approvals"]}
    return {"allowed_teams": [{"key": k, "label": IT_TEAM_LABELS[k]} for k in teams],
            "viewing": scope, "counts": counts, "tickets": tickets, "mode": "repair_only" if repair_only else "full"}


@api_router.get("/it-service/tickets/{ticket_id}")
async def it_service_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    t, teams = await _load_visible_ticket(ticket_id, user, allow_head=True)
    if await _is_it_head(user) and t.get("status") not in (SERVICE_REPAIR_PENDING, SERVICE_IN_SERVICE):
        raise HTTPException(status_code=403, detail="The IT Head can open repair requests only")
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
    res = await req_repo.transition_service_ticket(ticket_id, flt, set_fields, entry, now_iso())
    if not res:
        cur = await req_repo.get(ticket_id)
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
    for h in await users_repo.list_dept_heads(str(it_dept["_id"])):
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
    t, teams = await _load_visible_ticket(ticket_id, user, allow_head=True)
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
