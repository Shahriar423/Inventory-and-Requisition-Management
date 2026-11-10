"""Requisitions: create, edit, approve, PR handling, dashboard."""

from fastapi import Request, Response, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime, timezone
from ims.ids import ObjectId
import io
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from xml.sax.saxutils import escape as _xml_escape
from reportlab.pdfgen import canvas as _rl_canvas
from reportlab.platypus import KeepTogether
from ims.repositories import handovers as handover_repo
from ims.repositories import products as prod_repo
from ims.repositories import counters as counter_repo
from ims.repositories import notifications_repo as notif_repo
from ims.repositories import departments as dept_repo
from ims.repositories import users as users_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import assets as asset_repo
from ims.common import (
    CONDITION_LABELS,
    COR_REASONS,
    COR_STATUS_LABELS,
    FINALIZED,
    IT_TEAM_LABELS,
    MD_THRESHOLD,
    PO_STAGE_ROLE,
    ROLE_LABELS,
    SERVICE_CATEGORIES,
    SERVICE_QUEUE_OPEN,
    _a_dt,
    _department_is_it,
    _department_is_purchase,
    _enrich_asset,
    _enrich_assets,
    _img_from_datauri,
    _next_no,
    _notify,
    _notify_with_delegate,
    _pkey,
    active_delegators_of,
    api_router,
    attach_department_names,
    attach_file_info,
    audit_can_view,
    auto_generate_handover,
    build_audit_timeline,
    can_handle_pr,
    canonicalize_product_names,
    collect_audit_data,
    find_admin_dept,
    find_dept_by_type,
    dept_type_of,
    find_requisition_for_audit,
    get_current_user,
    get_po_threshold,
    has_pr_raise_flag,
    has_sufficient_stock,
    is_purchase_head_user,
    next_req_number,
    now_iso,
    po_user_can_act,
    resolve_approver,
    serialize_req,
    user_from_token,
)

# Ordered operational stages for service requisitions.
SERVICE_STAGES = [
    "pending_it_service", "product_collected_by_it", "sent_to_service_center",
    "service_completed_and_returned",
]


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
    u = await users_repo.find_by_role("dept_head", department_id)
    if u:
        return u
    return await users_repo.find_by_roles_in_department(DEPT_HEAD_EQUIVALENT_ROLES, department_id)


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


ADMIN_TRACK_TYPES = ("consumable", "furniture")


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

    it_dept = await find_dept_by_type("it")
    it_dept_id = str(it_dept["_id"]) if it_dept else None

    if is_admin_track(req_type, items or []):
        admin_dept = await find_admin_dept()
        admin_dept_id = str(admin_dept["_id"]) if admin_dept else None
        await step(1, "dept_head", "Admin Head", admin_dept_id)
        steps[-1]["stage"] = "admin_review"
        if not steps[-1]["approver_id"]:
            # No Admin department / head configured: Super Admin can still act on it.
            sa = await users_repo.find_by_role("super_admin")
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
    it_dept = await find_dept_by_type("it")
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
    """True if department_id is the Accounts or the Purchase department (by department type)."""
    if not department_id or not ObjectId.is_valid(department_id):
        return False
    return dept_type_of(await dept_repo.get(department_id)) in ("accounts", "purchase")


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
    # PR HANDLER OWNS THE DECISION: whatever the stock position (in stock, partial, out of
    # stock), a Dept-Head-approved product requisition ALWAYS lands in the PR Handler's queue
    # ("pending_pr"). There it is fulfilled from stock (any unit, substitutes allowed) or
    # bypassed into a Purchase Requisition — see fulfill_from_stock / bypass_stock. The old
    # automatic "stock available -> IT Head stock approval" branch no longer fires here
    # (make_it_stock_review_step / finish_stock_review stay only for requisitions that were
    # already in that step before this change).
    d["status"] = "pending_pr"
    d["pr_flow"] = True
    extra["pr_flow"] = True
    d.setdefault("history", []).append({
        "at": now_iso(), "by": "system", "action": "awaiting_pr_handler",
        "note": "Department Head approved — awaiting PR Handler review (fulfill from stock or raise PR)."})
    extra["history"] = d["history"]
    extra["approval_chain"] = d["approval_chain"]
    return extra


async def finish_stock_review(d: dict, extra: dict):
    """IT Head approved the stock issue: reserve stock + create the handover, or fall back to
    PR if the stock was taken in the meantime."""
    if d.get("fulfillment_type") == FULFILLMENT_STOCK and d.get("allocated_item_details") and not d.get("handover_id"):
        # PR Handler picked specific units (substitutes allowed): hand over exactly those.
        hid = await create_allocation_handover(d)
        d.setdefault("history", [])
        if hid:
            d["status"], d["handover_id"] = "pending_handover", hid
            extra["handover_id"] = hid
            d["history"].append({"at": now_iso(), "by": "system", "action": "stock_approved",
                                 "note": "IT Head approved the stock allocation — handover started."})
        else:
            await release_allocation(d)
            d["status"], d["pr_flow"] = "pending_pr", True
            extra.update({"pr_flow": True, "allocated_item_details": None, "fulfillment_type": None})
            d["history"].append({"at": now_iso(), "by": "system", "action": "stock_allocation_void",
                                 "note": "A selected stock unit is no longer available — returned to the PR Handler."})
        extra["history"] = d["history"]
        return
    if await has_sufficient_stock(d["items"]):
        hid = await auto_generate_handover(d)
        d["status"], d["handover_id"] = "pending_handover", hid
        extra["handover_id"] = hid
    else:
        d["status"], d["pr_flow"] = "pending_pr", True
        extra["pr_flow"] = True


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


class RequisitionItemIn(BaseModel):
    product_type: Literal["asset", "consumable", "it_accessories", "network", "furniture"]
    product_name: str
    quantity: int = 1
    rate: float = 0
    remarks: Optional[str] = None
    category_id: Optional[str] = None
    # What the requester actually wants (product requisitions). Kept apart from the PR raiser's own
    # detailed_specs / preferred_brand so the receipt check compares against the ORIGINAL request.
    preferred_specification: Optional[str] = None
    brand_name: Optional[str] = None
    model: Optional[str] = None
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
    # "revise"    = Revise Request: back to the requester (employee).
    # "pr_revise" = PR Revise: IT Head PR-review step only, back to the PR Raiser.
    action: Literal["approve", "reject", "revise", "pr_revise"]
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


@api_router.post("/requisitions/preview-chain")
async def preview_chain(payload: dict, user: dict = Depends(get_current_user)):
    req_type = payload.get("requisition_type", "product")
    if req_type == "service":
        # Standard service tasks skip IT Head approval and go straight to a sub-team queue.
        return {"chain": [await service_queue_bypass_step()]}
    # Product types come from the catalog (never trusted from the client).
    prev_items = []
    for it in payload.get("items") or []:
        p = await prod_repo.get_by_name_key(_pkey(it.get("product_name")))
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
    doc["_id"] = await req_repo.insert(doc)
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
        await req_repo.save_creation_routing(doc["_id"], status=doc["status"], approval_chain=doc["approval_chain"],
                                             extra=extra)

    doc["id"] = str(doc["_id"])
    doc.pop("_id", None)
    return doc


def req_visibility_scope(user: dict) -> tuple[dict, str]:
    """Three-tier data-visibility rule for requisitions/dashboard data:
    - executive (no approval/admin authority): own requisitions only ("personal").
    - dept_head / accounts / purchase_head: their own department's requisitions — their
      own plus their team's ("department"). These roles have approval authority over their
      department but are not company-wide admins.
    - super_admin / md ("System Admins and Top Management"): company-wide ("global").
    Returns (filter dict, scope_label)."""
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
    # DISABLED: the PR Handler now decides stock vs. purchase for every approved requisition,
    # so a requisition must never be pulled out of the handler's queue automatically.
    return
    docs = await req_repo.find_filtered({"status": "pending_pr", "requisition_type": "product",
                                         "purchase_pr_no": {"$in": [None, ""]}}, newest_first=None, limit=200)
    for d in docs:
        if await has_sufficient_stock(d["items"]):
            d["history"].append({"at": now_iso(), "by": "system", "action": "stock_available",
                                 "note": "Stock is now available - routed to IT Head stock approval instead of purchase."})
            d["pr_flow"] = False
            extra = await route_after_base_chain(d, None)
            extra["pr_flow"] = d.get("pr_flow", False)
            await req_repo.save_progress(d["_id"], status=d["status"], history=d["history"],
                                         updated_at=now_iso(), extra=extra)


@api_router.get("/requisitions")
async def list_requisitions(response: Response, scope: str = "all", status: Optional[str] = None,
                            page: Optional[int] = None, page_size: int = 25, q: Optional[str] = None, lean: bool = False,
                            user: dict = Depends(get_current_user)):
    """Without `page` this behaves exactly as before (plain array, capped at 1000 rows). With `page` (1-based) it
    returns just that slice and the total in the `X-Total-Count` header; `q` searches requisition no / requester /
    type server-side and `lean=true` leaves out the heavy `history` array (fetch it from /requisitions/{id})."""
    # "all"/"history" use the 3-tier visibility rule: personal (executive), department
    # (dept_head/accounts/purchase_head — their own department's requisitions), or global
    # (super_admin/md — company-wide). See req_visibility_scope().
    query, _vis = req_visibility_scope(user)
    if user["role"] == "md":
        # The MD sees only what he decided himself: requisitions whose Purchase Order he approved or rejected.
        if scope != "history":
            return []
        want = {"approved": {"approve"}, "rejected": {"reject"}}.get(status or "", {"approve", "reject"})
        rids = []
        for po in await po_repo.list_submitted():
            if any(c.get("role") == "md" and c.get("action") in want for c in po.get("approval_comments") or []):
                if po.get("requisition_id") and po["requisition_id"] not in rids:
                    rids.append(po["requisition_id"])
        docs = [d for d in [await req_repo.get(r) for r in rids] if d]
        if q and q.strip():
            ql = q.strip().lower()
            docs = [d for d in docs if ql in " ".join(str(d.get(k) or "") for k in ("requisition_no", "requisitioner_name", "requisition_type")).lower()]
        docs.sort(key=lambda d: d.get("created_at") or "", reverse=True)
        response.headers["X-Total-Count"] = str(len(docs))
        if page:
            size = max(1, min(page_size, 200))
            docs = docs[(max(page, 1) - 1) * size: max(page, 1) * size]
        if lean:
            docs = [{k: v for k, v in d.items() if k != "history"} for d in docs]
        return _flag_modifiable(await redact_approval_notes(await attach_po_approvals(await attach_department_names(await attach_file_info([serialize_req(d) for d in docs]))), user), user)
    if scope in ("purchase", "pending_pr", "approve"):
        await recheck_pending_pr_against_stock()
    if scope == "mine":
        query = {"requisitioner_id": str(user["_id"])}
    elif scope == "pending":
        query = {"requisitioner_id": str(user["_id"]), "status": {"$nin": FINALIZED}}
    elif scope == "approve":
        # requisitions where current pending step is assigned to this user
        docs = await req_repo.list_not_in_statuses(FINALIZED, newest_first=True, limit=1000)
        delegators = await active_delegators_of(user)
        out = []
        for d in docs:
            chain = d["approval_chain"]
            current = next((s for s in chain if s["status"] == "pending"), None)
            if current and is_current_approver(current, user, delegators):
                out.append(serialize_req(d))
        return _flag_modifiable(await redact_approval_notes(await attach_po_approvals(await attach_department_names(await attach_file_info(out))), user), user)
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
        can_raise = user.get("can_raise_pr") or user.get("can_process_requisition") or user["role"] == "super_admin"
        is_it_head = user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))
        if not (can_raise or is_it_head):
            return []
        query = {"status": {"$in": ["pending_pr", "pending_it_review", "pending_md", "pending_accounts", "po_draft", "pending_purchase", "buy_process", "pending_pr_revision"]}}
    elif scope == "purchase-order":
        # PO creation queue for users with can_create_po (Purchase dept).
        can_create = user["role"] == "super_admin" or (
            user.get("can_create_po") and not await is_purchase_head_user(user))
        if not can_create:
            return []
        # po_draft = a Purchase Order was saved as a draft but not submitted yet - keep it in the queue
        # so the creator can find it again ("Continue Draft PO").
        query = {"status": {"$in": ["pending_po_entry", "po_draft"]}}
    elif scope == "handover":
        # Items ready to be physically handed over — IT prints the slip and clicks
        # "Handover Done". Not a chain-step assignment either, so it's role-gated here
        # rather than matched against approver_id.
        it_dept = await find_dept_by_type("it")
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
        if not (user["role"] == "super_admin" or (
                user.get("can_create_po") and not await is_purchase_head_user(user))):
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

    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query = {"$and": [query, {"$or": [{"requisition_no": rx}, {"requisitioner_name": rx}, {"requisition_type": rx}]}]} if query else \
                {"$or": [{"requisition_no": rx}, {"requisitioner_name": rx}, {"requisition_type": rx}]}
    exclude = ["history"] if lean else None
    if page:
        size = max(1, min(page_size, 200))
        response.headers["X-Total-Count"] = str(await req_repo.count_filtered(query))
        docs = await req_repo.find_filtered(query, exclude_fields=exclude, skip=(max(page, 1) - 1) * size, limit=size)
    else:
        docs = await req_repo.find_filtered(query, exclude_fields=exclude, limit=1000)
    return _flag_modifiable(await redact_approval_notes(await attach_po_approvals(await attach_department_names(await attach_file_info([serialize_req(d) for d in docs]))), user), user)


@api_router.get("/requisitions/{req_id}")
async def get_requisition(req_id: str, user: dict = Depends(get_current_user)):
    d = await req_repo.get(req_id)
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    out = serialize_req(d)
    did = d.get("requisitioner_department_id")
    if did and ObjectId.is_valid(did):
        dept = await dept_repo.get(did)
        out["requisitioner_department_name"] = dept["name"] if dept else None
    # Per-item current available stock, for the PR pricing form's "In Stock" column.
    for it in out.get("items", []):
        it["in_stock"] = await asset_repo.count_available(it["product_name"])
    await attach_file_info([out])
    await attach_po_approvals([out])
    await redact_approval_notes([out], user)
    _flag_modifiable([out], user)
    return out


@api_router.post("/requisitions/{req_id}/action")
async def act_on_requisition(req_id: str, payload: ApproveIn, user: dict = Depends(get_current_user)):
    d = await req_repo.get(req_id)
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d["status"] in FINALIZED:
        raise HTTPException(status_code=400, detail="Requisition already finalized")
    if d["requisition_type"] == "service":
        raise HTTPException(status_code=400, detail="Use the service workflow to manage service requisitions")
    if payload.action in ("revise", "pr_revise") and not (payload.note and payload.note.strip()):
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

    if payload.action == "pr_revise" and current.get("stage") != "pr_review":
        raise HTTPException(status_code=400, detail="PR Revise is only available on the IT Head PR review step")

    if payload.action == "approve":
        current["status"] = "approved"
    elif payload.action == "reject":
        current["status"] = "rejected"
    elif payload.action == "pr_revise":
        # Sent back to the PR Raiser (not the employee). The step stays in the chain, the PR and
        # the requisition are kept exactly as filed; the PR Raiser edits the PR and re-files it.
        current["status"] = "pr_revision_requested"
    else:  # revise: sent back to the requester, doesn't finalize or advance the chain
        current["status"] = "revision_requested"
    current["note"] = payload.note
    current["acted_at"] = now_iso()
    d["history"].append({"at": now_iso(), "by": user["name"], "action": payload.action,
                         "level": current["level"], "note": payload.note,
                         **({"as": acted_as, "on_behalf_of": current.get("approver_name")} if acted_as else {})})
    d["updated_at"] = now_iso()
    if payload.action == "revise":
        d["status"] = "revision_requested"
    elif payload.action == "pr_revise":
        d["status"] = "pending_pr_revision"
        extra_set["pr_revision_feedback"] = {
            "note": payload.note, "by": user["name"], "label": current.get("label"), "at": now_iso()}
    else:
        d["status"] = compute_status(d)
    if payload.action == "revise":
        # Keep the feedback on the requisition itself (in addition to the chain step's note)
        # so every screen can show what the approver asked for.
        extra_set["revision_feedback"] = {
            "note": payload.note, "by": user["name"], "label": current.get("label"), "at": now_iso()}

    if (payload.action == "reject" and d.get("fulfillment_type") == FULFILLMENT_STOCK
            and not d.get("handover_id")):
        await release_allocation(d)          # IT Head rejected the stock issue: free the units

    # NOTE: neither "Revise Request" nor "PR Revise" voids or cancels the PR / requisition.
    # (Older versions voided the PR here and forced a brand-new PR; that is gone.)

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

    await req_repo.save_decision(req_id, approval_chain=chain, status=d["status"], history=d["history"],
                                 updated_at=d["updated_at"], extra=extra_set)

    # An approver's (optional) note travels with the requisition: it is stored on their chain step
    # (shown to everyone who opens the requisition) and the NEXT approver is told about it too.
    if payload.action == "approve" and (payload.note or "").strip():
        nxt = next((st for st in chain if st.get("status") == "pending" and st.get("approver_id")), None)
        if nxt and ObjectId.is_valid(nxt["approver_id"]):
            nxt_user = await users_repo.get(nxt["approver_id"])
            await _notify_with_delegate(
                nxt_user, "approval_note",
                f"{user['name']} approved {d['requisition_no']} ({current.get('label') or 'approval'}) "
                f"with a note: \"{payload.note.strip()}\"",
                requisition_id=str(d["_id"]))
    return serialize_req(d)


@api_router.post("/requisitions/{req_id}/resubmit")
async def resubmit_requisition(req_id: str, payload: ResubmitIn, user: dict = Depends(get_current_user)):
    """After a step returns 'revise', the original requester edits the requisition (items,
    note, attachment, etc. — whatever the revision feedback asked for) and resubmits it here.
    Every field in the payload is optional: only what was actually changed needs to be sent,
    everything else keeps its existing value. This resets the step that requested the
    revision back to 'pending' so the SAME approver who asked for it reviews the edited
    requisition next — it never restarts the chain from level 1.

    IT Head "Revise Request" (PR-review step) works the same way: the filed PR is kept and the
    SAME PR-review step is reopened for the IT Head. Only requisitions voided by the older
    flow (pr_needs_refile) still route back to pending_pr for a new PR."""
    d = await req_repo.get(req_id)
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
        # Keep what the PR Raiser filled in (specs, brand, UoM, estimate...) for every line the
        # employee left on the same product; an edit never wipes the existing PR details.
        old_items = d.get("items") or []
        for idx, it in enumerate(items):
            old = old_items[idx] if idx < len(old_items) else None
            if old and (old.get("product_name") or "").strip().lower() == (it.get("product_name") or "").strip().lower():
                for k in ("detailed_specs", "preferred_brand", "uom", "estimated_unit_price",
                          "line_date_required", "justification_remarks", "category"):
                    if old.get(k) is not None and it.get(k) is None:
                        it[k] = old[k]
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
    if d.get("pr_needs_refile"):
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
        await req_repo.save_resubmission(req_id, update)
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
    await req_repo.save_resubmission(req_id, update)
    return serialize_req(d)


def requester_can_modify(d: dict) -> bool:
    """A requester may edit or cancel their own PRODUCT requisition only while it is still
    waiting on its first (Dept Head) approval: nobody has approved, rejected or sent it back.
    The moment the approver acts, the requisition is locked for the requester."""
    if d.get("requisition_type") != "product" or d.get("status") != "pending_dept":
        return False
    chain = d.get("approval_chain") or []
    if not chain or chain[0].get("status") != "pending":
        return False
    return not any(s.get("status") != "pending" for s in chain)


def _item_sig(it: dict) -> str:
    return f"{it.get('quantity')} × {it.get('product_name')}"


def describe_requisition_changes(old: dict, new_items: Optional[list], new_fields: dict) -> List[str]:
    """Human-readable list of what the requester changed, shown to the approver."""
    out: List[str] = []
    if new_items is not None:
        old_by = {}
        for it in old.get("items") or []:
            old_by.setdefault((it.get("product_name") or "").strip().lower(), []).append(it)
        new_by = {}
        for it in new_items:
            new_by.setdefault((it.get("product_name") or "").strip().lower(), []).append(it)
        for k, lst in new_by.items():
            if k not in old_by:
                out.extend(f"Added item: {_item_sig(it)}" for it in lst)
            else:
                oq = sum(int(i.get("quantity") or 0) for i in old_by[k])
                nq = sum(int(i.get("quantity") or 0) for i in lst)
                if oq != nq:
                    out.append(f"{lst[0].get('product_name')}: quantity {oq} → {nq}")
                elif [i.get("remarks") for i in old_by[k]] != [i.get("remarks") for i in lst]:
                    out.append(f"{lst[0].get('product_name')}: remarks changed")
        for k, lst in old_by.items():
            if k not in new_by:
                out.extend(f"Removed item: {_item_sig(it)}" for it in lst)
    labels = {"requisition_for": "Requisition for", "requester_note": "Requester note",
              "attachment_name": "Attachment", "requisition_date": "Requisition date"}
    for key, label in labels.items():
        if key in new_fields and (old.get(key) or None) != (new_fields[key] or None):
            if key == "requisition_date" and str(old.get(key) or "")[:10] == str(new_fields[key] or "")[:10]:
                continue
            out.append(f"{label} changed")
    return out


class RequisitionEditIn(BaseModel):
    items: Optional[List[RequisitionItemIn]] = None
    requester_note: Optional[str] = None
    attachment_file_id: Optional[str] = None
    attachment_name: Optional[str] = None
    requisition_for: Optional[str] = None
    requisition_date: Optional[str] = None


class RequisitionCancelIn(BaseModel):
    note: Optional[str] = None


async def _load_own_modifiable_req(req_id: str, user: dict) -> dict:
    if not ObjectId.is_valid(req_id):
        raise HTTPException(status_code=404, detail="Requisition not found")
    d = await req_repo.get(req_id)
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if not (d.get("requisitioner_id") == str(user["_id"]) or user["role"] == "super_admin"):
        raise HTTPException(status_code=403, detail="Only the requester can change this requisition")
    if not requester_can_modify(d):
        raise HTTPException(status_code=400, detail="This requisition can no longer be changed - the approver has already acted on it")
    return d


@api_router.put("/requisitions/{req_id}")
async def edit_requisition(req_id: str, payload: RequisitionEditIn, user: dict = Depends(get_current_user)):
    """Requester edits a submitted requisition until the Dept Head approves, rejects or sends it
    back. The change is recorded (history + `last_edit`) and the approver is notified, so the
    approver always reviews the latest version and can see exactly what changed."""
    d = await _load_own_modifiable_req(req_id, user)
    update: dict = {}
    new_items = None
    if payload.items is not None:
        if not payload.items:
            raise HTTPException(status_code=400, detail="At least one item is required")
        new_items = [it.model_dump() for it in payload.items]
        await canonicalize_product_names(new_items)
        for it in new_items:
            it["line_total"] = round(it["quantity"] * it["rate"], 2)
        update["items"] = new_items
        update["total_amount"] = round(sum(it["line_total"] for it in new_items), 2)
        update["stock_check_at_submission"] = "in_stock" if await has_sufficient_stock(new_items) else "out_of_stock"
    fields = {}
    if payload.requester_note is not None:
        fields["requester_note"] = payload.requester_note
    if payload.attachment_file_id is not None:
        fields["attachment_file_id"] = payload.attachment_file_id
    if payload.attachment_name is not None:
        fields["attachment_name"] = payload.attachment_name
    if payload.requisition_for is not None and payload.requisition_for.strip():
        fields["requisition_for"] = payload.requisition_for.strip()
    if payload.requisition_date is not None:
        fields["requisition_date"] = payload.requisition_date
    update.update(fields)

    changes = describe_requisition_changes(d, new_items, fields)
    if not changes:
        return serialize_req(d)          # nothing actually changed

    at = now_iso()
    last_edit = {"at": at, "by": user["name"], "changes": changes,
                 "count": int(d.get("edit_count") or 0) + 1,
                 "previous_items": d.get("items") or []}
    update["last_edit"] = last_edit
    update["edit_count"] = last_edit["count"]
    update["updated_at"] = at
    history = list(d.get("history") or [])
    history.append({"at": at, "by": user["name"], "action": "edited", "note": "; ".join(changes)})
    update["history"] = history

    # Atomic guard: only apply while the requisition is still waiting on its first approver.
    if not await req_repo.apply_requester_edit(d["_id"], update):
        raise HTTPException(status_code=409, detail="The approver just acted on this requisition - it can no longer be changed")

    current = next((st for st in d["approval_chain"] if st["status"] == "pending"), None)
    if current and current.get("approver_id") and ObjectId.is_valid(current["approver_id"]):
        approver = await users_repo.get(current["approver_id"])
        await _notify_with_delegate(
            approver, "requisition_edited",
            f"{user['name']} updated {d['requisition_no']} before your review: {'; '.join(changes)}",
            requisition_id=str(d["_id"]))
    fresh = await req_repo.get(d["_id"])
    return serialize_req(fresh)


@api_router.post("/requisitions/{req_id}/cancel")
async def cancel_requisition(req_id: str, payload: RequisitionCancelIn = RequisitionCancelIn(), user: dict = Depends(get_current_user)):
    """Requester withdraws their requisition while it is still waiting on the first approver."""
    d = await _load_own_modifiable_req(req_id, user)
    at = now_iso()
    note = (payload.note or "").strip() or "Cancelled by the requester."
    chain = d["approval_chain"]
    for st in chain:
        if st["status"] == "pending":
            st["status"] = "cancelled"
            st["acted_at"] = at
            st["note"] = note
    history = list(d.get("history") or [])
    history.append({"at": at, "by": user["name"], "action": "cancelled", "note": note})
    if not await req_repo.cancel_by_requester(d["_id"], approval_chain=chain, history=history,
                                              cancelled_by=user["name"], note=note, at=at):
        raise HTTPException(status_code=409, detail="The approver just acted on this requisition - it can no longer be cancelled")
    current = next((st for st in chain if st.get("status") == "cancelled" and st.get("approver_id")), None)
    if current and ObjectId.is_valid(current["approver_id"]):
        approver = await users_repo.get(current["approver_id"])
        await _notify_with_delegate(approver, "requisition_cancelled",
                                    f"{user['name']} cancelled {d['requisition_no']}.", requisition_id=str(d["_id"]))
    d.update({"status": "cancelled", "approval_chain": chain, "history": history})
    return serialize_req(d)


async def attach_po_approvals(outs: List[dict]) -> List[dict]:
    """Adds `po_approvals` to serialized product requisitions so the requester can see WHO approved
    or rejected after the IT Head (Purchase Head -> MD (high value only) -> Accounts Head). These
    decisions live on the Purchase Order, not in the requisition's approval_chain. Only stage,
    approver, decision, comment and time are exposed - never vendor or price data."""
    ids = [o["id"] for o in outs if o.get("requisition_type") == "product" and o.get("po_flow")]
    if not ids:
        return outs
    by_req = await po_repo.group_by_requisition(ids)
    threshold = await get_po_threshold()
    pending_of = {"pending_purchase_head_approval": "purchase_head", "pending_md_approval": "md",
                  "pending_accounts_head_approval": "accounts"}
    for o in outs:
        res = []
        for po in by_req.get(o.get("id"), []):
            if po.get("status") == "draft":
                continue                       # not submitted for approval yet
            comments = po.get("approval_comments") or []
            roles = ["purchase_head"]
            if (po.get("grand_total") or 0) > threshold or any(c.get("role") == "md" for c in comments) \
                    or po.get("status") == "pending_md_approval":
                roles.append("md")
            roles.append("accounts")
            stages = []
            for r in roles:
                c = next((x for x in reversed(comments) if x.get("role") == r), None)
                if c:
                    status = "approved" if c.get("action") == "approve" else "rejected"
                elif pending_of.get(po.get("status")) == r:
                    status = "pending"
                else:
                    status = "waiting"
                stages.append({"role": r, "label": {"purchase_head": "Purchase Head", "md": "Managing Director",
                                                    "accounts": "Accounts Head"}[r],
                               "status": status, "by": (c or {}).get("by"), "comment": (c or {}).get("comment"),
                               "at": (c or {}).get("at")})
            # A rejection ends the process: nothing after the rejecting stage will ever happen,
            # so those stages are not listed at all (no misleading "Waiting").
            rej = next((i for i, st in enumerate(stages) if st["status"] == "rejected"), None)
            if rej is not None:
                stages = stages[:rej + 1]
            res.append({"po_number": po.get("po_number"), "status": po.get("status"), "stages": stages})
        o["po_approvals"] = res
    return outs


async def redact_approval_notes(outs: List[dict], user: dict) -> List[dict]:
    """Approval notes are a hand-over between two approvers, not something for everyone to read.
    An APPROVE note is visible only to: its author, the approver who is next in line (and their
    on-leave delegate) and Super Admin. The requester therefore never sees approver-to-approver
    notes. REJECT / revision-request notes stay visible to everybody - the requester needs the reason.
    EXCEPTION: the note the IT Head leaves while approving the PR review (stage "pr_review") is also
    shown to PO creators (can_create_po) and the Purchase Dept Head, because that note is guidance
    for whoever raises and approves the Purchase Order."""
    uid = str(user["_id"])
    is_super = user["role"] == "super_admin"
    delegators = await active_delegators_of(user)
    me_ids = {uid} | delegators
    me_purchase_head = await is_purchase_head_user(user)
    me_po_creator = bool(user.get("can_create_po")) and not me_purchase_head
    can_see_it_head_note = me_purchase_head or me_po_creator
    for o in outs:
        chain = o.get("approval_chain") or []
        cur = next((i for i, st in enumerate(chain) if st.get("status") == "pending"), None)
        for i, st in enumerate(chain):
            if st.get("status") != "approved" or not st.get("note"):
                continue
            mine = uid in (st.get("acted_by_id"), st.get("approver_id"))
            next_in_line = cur is not None and cur == i + 1 and chain[cur].get("approver_id") in me_ids
            it_head_note_for_po_team = st.get("stage") == "pr_review" and can_see_it_head_note
            if not (is_super or mine or next_in_line or it_head_note_for_po_team):
                st["note"] = None
        for h in o.get("history") or []:
            if h.get("action") == "approve" and h.get("note"):
                lvl = h.get("level")
                step = next((st for st in chain if st.get("level") == lvl), None)
                if step is not None and step.get("note") is None and not is_super and h.get("by") != user.get("name"):
                    h["note"] = None
        for po in o.get("po_approvals") or []:
            stages = po.get("stages") or []
            for k, st in enumerate(stages):
                if st.get("status") != "approved" or not st.get("comment"):
                    continue
                nxt = stages[k + 1] if k + 1 < len(stages) else None
                nxt_role = nxt["role"] if nxt and nxt.get("status") == "pending" else None
                next_in_line = (nxt_role == "purchase_head" and me_purchase_head) or \
                               (nxt_role == "md" and user["role"] == "md") or \
                               (nxt_role == "accounts" and user["role"] == "accounts")
                if not (is_super or st.get("by") == user.get("name") or next_in_line):
                    st["comment"] = None
    return outs


# Lets the UI know (per requisition) whether the Edit / Cancel buttons should be shown.
def _flag_modifiable(outs: List[dict], user: dict) -> List[dict]:
    uid = str(user["_id"])
    for o in outs:
        o["can_requester_modify"] = (o.get("requisitioner_id") == uid or user["role"] == "super_admin") and requester_can_modify(o)
    return outs


@api_router.get("/dashboard/stats")
async def dashboard_stats(response: Response, user: dict = Depends(get_current_user)):
    # Live counters: never let a browser / proxy / CDN serve an older copy of this response.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    # Three-tier visibility: personal (executive), department (dept_head/accounts/
    # purchase_head — their own department), global (super_admin/md — company-wide).
    base_filter, vis_scope = req_visibility_scope(user)
    personal = vis_scope == "personal"

    total = await req_repo.count_filtered(base_filter)
    pending = await req_repo.count_filtered({**base_filter, "status": {"$nin": FINALIZED}})
    approved = await req_repo.count_filtered({**base_filter, "status": {"$in": ["approved", "handover_done"]}})
    rejected = await req_repo.count_filtered({**base_filter, "status": "rejected"})
    high_value = await req_repo.count_filtered({**base_filter, "total_amount": {"$gte": await get_po_threshold()}})
    action_required = await req_repo.count_filtered({**base_filter, "status": "revision_requested"})
    in_progress = await req_repo.count_filtered({
        **base_filter, "status": {"$nin": FINALIZED + ["revision_requested"]}})

    if vis_scope == "global":
        assets_total = await asset_repo.count_where()
        assets_assigned = await asset_repo.count_where(statuses=["assigned", "return_pending"])
    elif vis_scope == "department":
        dept_users = await users_repo.list_by_department(user.get("department_id"), 500)
        names = [u["name"] for u in dept_users]
        assets_total = await asset_repo.count_where(assigned_to_in=names)
        assets_assigned = assets_total
    else:
        assets_total = await asset_repo.count_where(assigned_to=user["name"])
        assets_assigned = assets_total

    # my approvals queue (always personal — items waiting on me)
    docs = await req_repo.list_not_in_statuses(FINALIZED, only_fields=["approval_chain"], limit=1000)
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
        delegated_for = [d_["name"] for d_ in await users_repo.list_by_ids(delegators)]
        for po_ in await po_repo.list_in_statuses(PO_STAGE_ROLE):
            if await po_user_can_act(po_, user, delegators) and not await po_user_can_act(po_, user, set()):
                delegated_po += 1

    recent = await req_repo.find_filtered(base_filter, limit=6)

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
        po_pending = await po_repo.count_in_statuses(po_statuses)
    elif is_purchase_head:
        po_pending = await po_repo.count_with_status("pending_purchase_head_approval")
    elif user["role"] == "md":
        po_pending = await po_repo.count_with_status("pending_md_approval")
    elif user["role"] == "accounts":
        po_pending = await po_repo.count_with_status("pending_accounts_head_approval")
    else:
        po_pending = 0

    # PR raise queue (for users with can_raise_pr)
    awaiting_pr = 0
    prs_filed = 0
    if can_handle_pr(user):
        # Awaiting the PR Handler's decision, plus PRs the IT Head sent back for revision.
        awaiting_pr = await req_repo.count_filtered({"status": {"$in": ["pending_pr", "pending_pr_revision"]}})
        # Active (non-voided) PRs filed by this user — voided ones clear purchase_pr_no
        prs_filed = await req_repo.count_filtered({
            "pr_filed_by_id": str(user["_id"]),
            "purchase_pr_no": {"$exists": True, "$nin": [None, ""]},
        })

    # PO raise queue (for users with can_create_po) - mirrors the PR cards above
    awaiting_po = 0
    pos_created = 0
    if user["role"] == "super_admin" or (user.get("can_create_po") and not is_purchase_head):
        awaiting_po = await req_repo.count_filtered({"status": "pending_po_entry"})
        pos_created = await po_repo.count_created_by(str(user["_id"]), user["name"])

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
        pending_docs = await req_repo.find_filtered({**base_filter, "status": {"$nin": FINALIZED}}, limit=50)
        result["pending_list"] = [serialize_req(r) for r in pending_docs]
        my_assets = await asset_repo.list_all(assigned_to=user["name"], limit=200)
        result["my_assets"] = [await _enrich_asset(a) for a in my_assets]
    return result


class ServiceTransitionIn(BaseModel):
    stage: Optional[str] = None
    note: Optional[str] = None


@api_router.post("/requisitions/{req_id}/service-transition")
async def service_transition(req_id: str, payload: ServiceTransitionIn, user: dict = Depends(get_current_user)):
    d = await req_repo.get(req_id)
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
    await req_repo.save_decision(req_id, approval_chain=d["approval_chain"], status=target, history=d["history"],
                                 updated_at=d["updated_at"])
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
    if not can_handle_pr(user):   # can_raise_pr / can_process_requisition / Super Admin
        raise HTTPException(status_code=403, detail="You are not allowed to raise a Purchase Requisition")
    d = await req_repo.get(req_id)
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    is_pr_revision = d["status"] == "pending_pr_revision"
    if d["status"] != "pending_pr" and not is_pr_revision:
        raise HTTPException(status_code=400, detail="This requisition is not awaiting a Purchase Requisition")
    if not is_pr_revision and (d.get("fulfillment_type") != FULFILLMENT_PR or not (d.get("procurement_notes") or "").strip()):
        raise HTTPException(status_code=400, detail=(
            "Use \"Bypass Stock & Raise PR\" from the queue and enter the reason for bypassing stock "
            "before filing the Purchase Requisition."))

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
    revision_step = next((s for s in chain if s.get("stage") == "pr_review"
                          and s.get("status") == "pr_revision_requested"), None) if is_pr_revision else None
    if revision_step:
        # PR Revise: re-file into the SAME IT Head review step (history of its note is kept in
        # requisition history); nothing is voided or recreated.
        revision_step["status"] = "pending"
        revision_step["note"] = None
        revision_step["acted_at"] = None
        revision_step["pending_since"] = now_iso()
        revision_step.pop("reminded_at", None)
    else:
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
        "note": ("Purchase Requisition revised by the PR Raiser and re-submitted to the IT Head."
                 if revision_step else
                 "Purchase Requisition filed (specs & quantities; optional est. unit price as guess only). Routed to IT Head for review.")
    })
    d["pr_filed_by"] = user["name"]
    d["pr_filed_by_id"] = str(user["_id"])
    await req_repo.save_pr_filing(
        req_id, items=items, approval_chain=chain, status=d["status"], history=d["history"],
        updated_at=d["updated_at"],
        overall_business_justification=d.get("overall_business_justification"),
        required_by_date=d.get("required_by_date"), urgency_level=d.get("urgency_level"),
        delivery_location=d.get("delivery_location"),
        pr_attachment_file_ids=d.get("pr_attachment_file_ids", []),
        pr_filed_by=user["name"], pr_filed_by_id=str(user["_id"]))
    return serialize_req(d)


FULFILLMENT_STOCK = "STOCK_ALLOCATION"


FULFILLMENT_PR = "PURCHASE_REQUISITION"


async def _get_pr_handling_req(req_id: str, user: dict) -> dict:
    if not can_handle_pr(user):
        raise HTTPException(status_code=403, detail="You are not allowed to process this requisition")
    if not ObjectId.is_valid(req_id):
        raise HTTPException(status_code=404, detail="Requisition not found")
    d = await req_repo.get(req_id)
    if not d:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if d.get("requisition_type") != "product" or d.get("status") != "pending_pr":
        raise HTTPException(status_code=400, detail="This requisition is not awaiting PR handling")
    return d


@api_router.get("/requisitions/{req_id}/stock-options")
async def pr_handling_stock_options(req_id: str, user: dict = Depends(get_current_user)):
    """Live inventory for the Stock Selection Modal: every unit that can be issued right now
    (in stock, not reserved by another slip), flagged when it matches a requested product."""
    d = await _get_pr_handling_req(req_id, user)
    wanted = {(it.get("product_name") or "").strip().lower() for it in d.get("items", [])}
    docs = await asset_repo.list_all_available(limit=5000)
    rows = await _enrich_assets(docs)
    for a in rows:
        a["matches_request"] = (a.get("name") or "").strip().lower() in wanted
    return {
        "requested_items": [{"product_name": it.get("product_name"), "quantity": it.get("quantity", 1),
                             "detailed_specs": it.get("detailed_specs"), "preferred_brand": it.get("preferred_brand")}
                            for it in d.get("items", [])],
        "total_quantity": sum(int(it.get("quantity") or 1) for it in d.get("items", [])),
        "assets": rows,
    }


class FulfillFromStockIn(BaseModel):
    asset_ids: List[str]
    notes: Optional[str] = None            # "Substitution / Allocation Notes"


@api_router.post("/requisitions/{req_id}/fulfill-from-stock")
async def fulfill_from_stock(req_id: str, payload: FulfillFromStockIn, user: dict = Depends(get_current_user)):
    d = await _get_pr_handling_req(req_id, user)
    # The PR Handler has full authority here: ANY item, ANY quantity, regardless of what the
    # requester asked for (fewer, more, or a different product). Only availability is checked.
    ids = list(dict.fromkeys(payload.asset_ids or []))
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one stock unit.")
    assets = []
    for aid in ids:
        a = await asset_repo.get(aid)
        tag = f"{a.get('name')} ({a.get('tag_id') or a.get('serial_no') or 'no tag'})" if a else "A selected unit"
        if not a:
            raise HTTPException(status_code=400, detail="A selected stock unit no longer exists. Pick again.")
        if a.get("status") != "in_stock" or a.get("pending_receipt"):
            raise HTTPException(status_code=400, detail=f"{tag} is no longer available. Pick again.")
        assets.append(a)

    requested = [(it.get("product_name") or "").strip().lower() for it in d.get("items", [])
                 for _ in range(int(it.get("quantity") or 1))]
    requested_label = ", ".join(it.get("product_name") or "" for it in d.get("items", []))
    allocated = []
    for a in assets:
        allocated.append({
            "asset_id": str(a["_id"]), "name": a.get("name"), "brand": a.get("brand"),
            "tag_id": a.get("tag_id"), "serial_no": a.get("serial_no"),
            "requested_item": requested_label,
            "is_substitute": (a.get("name") or "").strip().lower() not in requested,
        })

    # Reserve the chosen units now (nobody else can take them) but do NOT start the handover:
    # the IT Head must approve the stock issue first (same "IT Head — Stock Approval" step the
    # automatic in-stock path always used). The handover is created when the IT Head approves.
    rid = str(d["_id"])
    for x in allocated:
        await asset_repo.update_fields(x["asset_id"], {
            "pending_receipt": True, "reserved_for_req_id": rid,
            "assigned_to_tentative": d.get("requisition_for") or d["requisitioner_name"]})

    note = (payload.notes or "").strip()
    subs = [x for x in allocated if x["is_substitute"]]
    chain = [s for s in d.get("approval_chain", []) if s.get("stage") != "stock_review"]
    step = await make_it_stock_review_step(len(chain) + 1)
    chain.append(step)
    d.setdefault("history", []).append({
        "at": now_iso(), "by": user["name"], "action": "stock_allocated",
        "note": "PR Handler selected stock for this requisition: "
                + ", ".join(f"{x['name']} ({x['tag_id'] or x['serial_no'] or 'no tag'})" for x in allocated)
                + (" — substitute item allocated." if subs else ".") + (f" Notes: {note}" if note else "")
                + " Sent to the IT Head for stock approval."})
    await req_repo.save_stock_allocation(
        d["_id"], status="pending_it_review", approval_chain=chain, fulfillment_type=FULFILLMENT_STOCK,
        allocated_item_details=allocated, procurement_notes=note or None, allocated_by=user["name"],
        history=d["history"], updated_at=now_iso())
    return {"ok": True, "status": "pending_it_review", "fulfillment_type": FULFILLMENT_STOCK,
            "allocated_item_details": allocated}


async def create_allocation_handover(d: dict) -> Optional[str]:
    """IT Head approved the PR Handler's stock selection: create the prepared handover slip for
    exactly the units that were picked (any item / quantity). Returns the handover id, or None
    when a picked unit is no longer available."""
    allocated = d.get("allocated_item_details") or []
    if not allocated:
        return None
    for x in allocated:
        a = await asset_repo.get(x["asset_id"])
        if not a or a.get("status") != "in_stock" or a.get("reserved_for_req_id") != str(d["_id"]):
            return None
    note = d.get("procurement_notes")
    slip_no = await _next_no("HO", "handover")
    doc = {
        "slip_no": slip_no, "type": "handover",
        "employee_name": d.get("requisition_for") or d["requisitioner_name"],
        "department_id": d.get("requisitioner_department_id"),
        "items": [{"item": x["name"], "brand": x.get("brand"), "quantity": 1, "remarks": note,
                   "asset_id": x["asset_id"], "tag_id": x.get("tag_id"), "serial_no": x.get("serial_no")}
                  for x in allocated],
        "remarks": f"Stock allocation for requisition {d['requisition_no']}",
        "note": note, "handover_date": now_iso(), "prepared_by": d.get("allocated_by") or "system",
        "prepared_by_sign": None, "received_by_sign": None, "created_at": now_iso(),
        "status": "prepared", "requisition_id": str(d["_id"]),
    }
    hid = str(await handover_repo.insert(doc))
    for x in allocated:
        await asset_repo.update_fields(x["asset_id"], {
            "pending_handover_id": hid, "assigned_department_id": doc["department_id"], "reserved_for_req_id": None})
    return hid


async def release_allocation(d: dict):
    """Give the reserved stock units back (stock approval rejected / allocation not usable)."""
    for x in d.get("allocated_item_details") or []:
        if not ObjectId.is_valid(x.get("asset_id") or ""):
            continue
        await asset_repo.update_if(
            x["asset_id"], {"reserved_for_req_id": str(d["_id"])},
            {"pending_receipt": False, "assigned_to_tentative": None, "reserved_for_req_id": None})


class BypassStockIn(BaseModel):
    reason: str


@api_router.post("/requisitions/{req_id}/bypass-stock")
async def bypass_stock(req_id: str, payload: BypassStockIn, user: dict = Depends(get_current_user)):
    d = await _get_pr_handling_req(req_id, user)
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Reason for bypassing stock is required")
    d.setdefault("history", []).append({
        "at": now_iso(), "by": user["name"], "action": "stock_bypassed",
        "note": f"PR Handler bypassed stock and is raising a Purchase Requisition. Reason: {reason}"})
    await req_repo.save_stock_bypass(d["_id"], fulfillment_type=FULFILLMENT_PR, reason=reason,
                                     bypassed_by=user["name"], history=d["history"], updated_at=now_iso())
    return {"ok": True, "status": "pending_pr", "fulfillment_type": FULFILLMENT_PR, "procurement_notes": reason}


# Safety net – reject any old pricing calls
@api_router.post("/requisitions/{req_id}/pricing")
async def set_pr_pricing_legacy(req_id: str, payload: dict, user: dict = Depends(get_current_user)):
    raise HTTPException(
        status_code=400,
        detail="Price/Cost data is masked at the PR stage. Use POST /requisitions/{req_id}/file-pr"
    )


async def _pr_number(req: dict) -> str:
    if req.get("purchase_pr_no"):
        return req["purchase_pr_no"]
    now = datetime.now(timezone.utc)
    c = await counter_repo.find_one_and_inc(f"pr-{now.year}")
    pr_no = f"LPRIT-{now.year}{now.month:02d}{c['seq']:04d}"
    await req_repo.set_pr_number(req["_id"], pr_no)
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

    d = await req_repo.get(req_id)
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
        dp = await dept_repo.get(did)
        dept_name = dp["name"] if dp else None
    d["_pr_signatories"] = await resolve_pr_signatories(d)
    pdf = build_pr_pdf(d, pr_no, dept_name or "Information Technology")
    return Response(content=pdf, media_type="application/pdf",
   headers={"Content-Disposition": f'inline; filename="{pr_no}.pdf"'})


@api_router.post("/requisitions/{req_id}/issue-stock")
async def issue_stock_for_requisition(req_id: str, user: dict = Depends(get_current_user)):
    """IT's explicit 'Issue Stock for Requisition' action. Only valid once goods have been
    received via GRN against this requisition (status == stock_received_in_it). Generates
    the handover (same shape as the in-stock Path A) and pushes an info notification to the
    requester ahead of the later physical-receipt confirmation."""
    it_dept = await find_dept_by_type("it")
    it_dept_id = str(it_dept["_id"]) if it_dept else None
    if not (user["role"] == "super_admin" or (user["role"] == "dept_head" and user.get("department_id") == it_dept_id)):
        raise HTTPException(status_code=403, detail="Only the IT team can issue stock for a requisition")
    req = await req_repo.get(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if req.get("status") != "stock_received_in_it":
        raise HTTPException(status_code=400, detail="Stock can only be issued once goods have been received via GRN for this requisition")

    hid = await auto_generate_handover(req)
    item_names = ", ".join(it["product_name"] for it in req["items"])
    await notif_repo.insert({
        "user_id": req.get("requisitioner_id"), "employee_name": req.get("requisition_for") or req["requisitioner_name"],
        "type": "stock_allocated", "requisition_id": req_id, "handover_id": hid,
        "message": f"Your requested item {item_names} has arrived in IT inventory and is being prepared for handover.",
        "status": "unread", "created_at": now_iso(),
    })
    req["history"].append({"at": now_iso(), "by": user["name"], "action": "stock_issued", "note": None})
    await req_repo.save_progress(req_id, status="pending_handover", history=req["history"],
                                 updated_at=now_iso(), handover_id=hid)
    return {"ok": True, "status": "pending_handover", "handover_id": hid}


class CancelPRIn(BaseModel):
    note: Optional[str] = None


@api_router.post("/requisitions/{req_id}/cancel-pr")
async def cancel_pending_pr(req_id: str, payload: CancelPRIn = CancelPRIn(), user: dict = Depends(get_current_user)):
    """PR raiser (can_raise_pr / IT Head / super_admin) cancels a requisition that is still
    awaiting a Purchase Requisition (status == pending_pr). Use when the item is no longer
    needed so it leaves the PR queue and the requester sees status 'PR Cancelled'."""
    can_raise = bool(user.get("can_raise_pr")) or user["role"] == "super_admin"
    if not can_raise:
        it_dept = await find_dept_by_type("it")
        it_dept_id = str(it_dept["_id"]) if it_dept else None
        is_it_head = user["role"] == "dept_head" and user.get("department_id") == it_dept_id
        if not is_it_head:
            raise HTTPException(status_code=403, detail="Only a PR raiser (or IT Head) can cancel a pending PR")
    d = await req_repo.get(req_id)
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
    await req_repo.save_pr_cancellation(req_id, history=d["history"], updated_at=d["updated_at"],
                                        closed_at=d["closed_at"], note=note, cancelled_by=user["name"])
    return serialize_req(d)


async def service_queue_bypass_step(team: Optional[str] = None) -> dict:
    it_dept = await find_dept_by_type("it")
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
    it_dept = await find_dept_by_type("it")
    if not team or not it_dept:
        return
    msg = f"New {IT_TEAM_LABELS[team]} ticket {doc['requisition_no']}: {doc['items'][0]['product_name']} (requested by {doc['requisitioner_name']})."
    for u in await users_repo.list_it_ticket_recipients(str(it_dept["_id"]), team):
        if str(u["_id"]) != doc.get("requisitioner_id"):
            await _notify(str(u["_id"]), "it_service_ticket", msg, requisition_id=str(doc["_id"]))


def _a_txt(v, dash: str = "-") -> str:
    v = (str(v).strip() if v is not None else "")
    return _xml_escape(v) if v else dash


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
                ("Slip No.", _a_txt(h.get("slip_no"))),
                ("Delivery", (f"Attempt {h.get('attempt_no')} (replacement) - {h.get('correction_case_no')}" if h.get("correction_case_id") else "Original delivery")),
                ("Prepared By", _a_txt(h.get("prepared_by"))), ("Issued To", _a_txt(h.get("employee_name"))),
                ("Delivered By (IT Executive)", _a_txt(h.get("delivered_by"))), ("Delivery Timestamp", _a_dt(h.get("delivered_at"))),
                ("User Confirmation", "Confirmed" if h.get("confirmed_at") else "Awaiting user confirmation"),
                ("Acceptance Timestamp", _a_dt(h.get("confirmed_at"))),
            ]))
            tail = []
            if h.get("items"):
                irows = [["#", "Item", "Tag / Serial", "Qty", "Unit Price (BDT)", "Total (BDT)", "GRN"]]
                grand, any_price = 0.0, False
                for n, i in enumerate(h["items"], 1):
                    q = int(i.get("quantity") or 1)
                    rate = i.get("grn_rate")
                    if rate is not None:
                        any_price = True
                        grand += rate * q
                    irows.append([str(n), _a_txt(i.get("item")), _a_txt(i.get("tag_id") or i.get("serial_no")), str(q),
                                  f"{rate:,.2f}" if rate is not None else "-",
                                  f"{rate * q:,.2f}" if rate is not None else "-", _a_txt(i.get("grn_no"))])
                if any_price:
                    irows.append(["", "Total value", "", "", "", f"{grand:,.2f}", ""])
                tail = [grid(irows, [8 * mm, 46 * mm, 30 * mm, 12 * mm, 30 * mm, 30 * mm, 26 * mm])]
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

    # ---- 5A. delivery corrections ---------------------------------------------------------
    corrs = data.get("corrections") or []
    if corrs:
        story.append(P("5A. Delivery Corrections", h2))
        story.append(P("The employee rejected a delivery. The original delivery above is preserved unchanged; every later attempt is listed here."))
        for c in corrs:
            story.append(Spacer(1, 4))
            story.append(kv([
                ("Case No.", _a_txt(c.get("case_no"))), ("Status", _a_txt(COR_STATUS_LABELS.get(c.get("status"), c.get("status")))),
                ("Item", _a_txt(c["item"].get("product_name"))), ("Employee", _a_txt(c.get("employee_name"))),
                ("Requested", _a_txt((c["item"].get("requested") or {}).get("detailed_specs"))),
                ("Responsible IT", _a_txt(c.get("responsible_it_name"))),
                ("Reported", _a_dt(c.get("created_at"))), ("Closed", _a_dt(c.get("closed_at"))),
            ]))
            story.append(Spacer(1, 3))
            rr = [["Attempt", "Slip", "Unit delivered", "Delivered", "By", "Result", "Unit returned to IT"]]
            for a in c.get("attempts") or []:
                ret = a.get("return")
                rr.append([("Original" if a["attempt_no"] == 1 else f"Attempt {a['attempt_no']}"), _a_txt(a.get("slip_no")), _a_txt(a.get("asset_summary")),
                           _a_dt(a.get("delivered_at")), _a_txt(a.get("delivered_by")),
                           _a_txt((a.get("status") or "").replace("_", " ").title()),
                           (f"{_a_dt(ret['at'])} by {ret['by']} ({CONDITION_LABELS.get(ret.get('condition'), ret.get('condition'))})" if ret else "-")])
            story.append(grid(rr, [16 * mm, 22 * mm, 40 * mm, 26 * mm, 22 * mm, 24 * mm, 32 * mm]))
            rj = [["#", "Attempt", "Reason", "Employee note"]]
            for i, x in enumerate(c.get("rejections") or [], 1):
                rj.append([str(i), str(x.get("attempt_no")), COR_REASONS.get(x.get("reason"), _a_txt(x.get("reason"))) + (" (photo attached)" if x.get("attachment_file_id") else ""), _a_txt(x.get("note"))])
            story.append(Spacer(1, 3)); story.append(grid(rj, [8 * mm, 16 * mm, 56 * mm, 102 * mm]))
            if c.get("clarifications"):
                cq = [["Asked", "To", "Question", "Answer"]]
                for q in c["clarifications"]:
                    cq.append([_a_dt(q.get("asked_at")), _a_txt(q.get("to_name")), _a_txt(q.get("question")), _a_txt(q.get("answer"))])
                story.append(Spacer(1, 3)); story.append(grid(cq, [26 * mm, 28 * mm, 64 * mm, 60 * mm]))
            if c.get("procurement"):
                story.append(Spacer(1, 3)); story.append(P(f"<b>Procurement:</b> linked requisition {_a_txt(c['procurement'].get('requisition_no'))} (raised {_a_dt(c['procurement'].get('created_at'))})."))
            if c.get("closure"):
                story.append(Spacer(1, 3)); story.append(P(f"<b>Closure:</b> {_a_txt(c['closure'].get('reason_label'))} - {_a_txt(c['closure'].get('note'))} ({_a_txt(c['closure'].get('by'))}, {_a_dt(c['closure'].get('at'))})."))
            ev = [["Date / Time", "By", "Action", "Status change", "Detail"]]
            for e in c.get("events") or []:
                ev.append([_a_dt(e.get("at")), _a_txt(e.get("by")), _a_txt((e.get("action") or "").replace("_", " ").capitalize()),
                           (f"{COR_STATUS_LABELS.get(e.get('from_status'), e.get('from_status') or '-')} → {COR_STATUS_LABELS.get(e.get('to_status'), e.get('to_status') or '-')}" if e.get("to_status") else "-"),
                           _a_txt(e.get("note"))])
            story.append(Spacer(1, 3)); story.append(grid(ev, [26 * mm, 22 * mm, 34 * mm, 46 * mm, 50 * mm]))
            story.append(Spacer(1, 5))

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