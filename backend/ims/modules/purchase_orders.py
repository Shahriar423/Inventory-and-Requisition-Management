"""Purchase Orders."""

from fastapi import HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime, timezone
from ims.ids import ObjectId
from ims.repositories import requisitions as req_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import products as prod_repo
from ims.repositories import counters as counter_repo
from ims.repositories import files_repo
from ims.common import (
    FINALIZED,
    ROLE_LABELS,
    _department_is_purchase,
    _next_no,
    _pkey,
    active_delegators_of,
    api_router,
    can_view_po_quotes,
    get_current_user,
    get_po_threshold,
    is_purchase_head_user,
    now_iso,
    po_user_can_act,
    strip_id,
)

class POLineItemIn(BaseModel):
    product_id: Optional[str] = None
    product_name: Optional[str] = None      # catalog product (exact name)
    item_description: str                   # free-text description / specs
    brand_model: Optional[str] = None
    quantity: int = 1
    unit_price: float = 0


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
    tax_percent: float = 0.0
    discount_amount: float = 0.0
    transport_charge: float = 0.0
    special_terms_notes: Optional[str] = None


def _po_line_total(it: dict) -> float:
    return round(it["quantity"] * it["unit_price"], 2)


def _po_totals(items: List[dict], tax_percent: float = 0.0, discount_amount: float = 0.0, transport_charge: float = 0.0) -> dict:
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


def _previous_approver_note(po: dict, req: Optional[dict]) -> Optional[dict]:
    """The note left by the approver IMMEDIATELY before the PO's current stage - nobody else's.
       Purchase Head   <- IT Head (PR review step on the requisition)
       MD              <- Purchase Head
       Accounts Head   <- MD (high-value PO) or, when there is no MD stage, the Purchase Head."""
    st = po.get("status")
    if st == "pending_purchase_head_approval":
        steps = [x for x in (req or {}).get("approval_chain") or [] if x.get("status") == "approved"]
        prev = steps[-1] if steps else None
        if prev and (prev.get("note") or "").strip():
            return {"by": prev.get("acted_by_name") or prev.get("approver_name"), "label": prev.get("label") or "IT Head",
                    "note": prev["note"].strip(), "at": prev.get("acted_at"), "source": "it_head"}
        return None
    if st in ("pending_md_approval", "pending_accounts_head_approval"):
        ok = [c for c in po.get("approval_comments") or [] if c.get("action") == "approve"]
        prev = ok[-1] if ok else None
        if prev and (prev.get("comment") or "").strip():
            return {"by": prev.get("by"), "label": ROLE_LABELS.get(prev.get("role"), prev.get("role")),
                    "note": prev["comment"].strip(), "at": prev.get("at")}
    return None


async def _enrich_po(doc: dict) -> dict:
    doc = strip_id(doc)
    req = None
    if ObjectId.is_valid(doc.get("requisition_id", "")):
        req = await req_repo.get(doc["requisition_id"])
    doc["requisition_no"] = req.get("requisition_no") if req else None
    # Vendor quotation files attached on the PO form -> id + name + size, so approvers
    # can open them. Ids that aren't real stored files (old placeholder ids) are skipped.
    atts = []
    for fid in doc.get("cs_attachment_file_ids") or []:
        rec = await files_repo.get(fid)
        if rec:
            atts.append({"id": fid, "name": rec.get("original_filename"), "size": rec.get("size")})
    doc["cs_attachments"] = atts
    doc["previous_approver_note"] = _previous_approver_note(doc, req)
    return doc


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
    req = await req_repo.get(rid)
    if not req or req.get("status") in FINALIZED:
        return
    new_status = PO_TO_REQ_STATUS.get(po["status"])
    if not new_status:
        return
    req.setdefault("history", []).append({"at": now_iso(), "by": by, "action": action, "note": note})
    await req_repo.save_progress(req["_id"], status=new_status, history=req["history"], updated_at=now_iso())


def _redact_po_comments(e: dict, user: dict, can_act: bool, is_purchase_head: bool = False) -> dict:
    """Approve comments on a PO are hand-over notes: only their author, the approver acting now
    and Super Admin get them in the API response. Reject reasons stay visible.
    EXCEPTION: the IT Head's PR-review note is also visible to PO creators and the Purchase Dept Head."""
    if can_act or user["role"] == "super_admin":
        return e
    prev = e.get("previous_approver_note")
    if prev and prev.get("source") == "it_head" and (is_purchase_head or user.get("can_create_po")):
        pass                                    # keep the IT Head note for the PO team
    else:
        e["previous_approver_note"] = None
    e["approval_comments"] = [
        ({**c, "comment": None} if c.get("action") == "approve" and c.get("by") != user.get("name") else c)
        for c in e.get("approval_comments") or []]
    return e


MAX_PO_QUOTE_FILES = 3


async def _validate_po_quote_files(ids: List[str]) -> List[str]:
    """PO creators may attach at most 3 vendor-quotation PDFs."""
    ids = list(dict.fromkeys(ids or []))
    if len(ids) > MAX_PO_QUOTE_FILES:
        raise HTTPException(status_code=400, detail=f"You can attach a maximum of {MAX_PO_QUOTE_FILES} PDF files to a Purchase Order")
    for fid in ids:
        rec = await files_repo.get(fid)
        if not rec:
            raise HTTPException(status_code=400, detail="One of the attached files could not be found - please upload it again")
        name = (rec.get("original_filename") or "").lower()
        if not (name.endswith(".pdf") or rec.get("content_type") == "application/pdf"):
            raise HTTPException(status_code=400, detail=f"{rec.get('original_filename')}: only PDF files are allowed")
    return ids


async def _hide_quotes_if_not_allowed(e: dict, po: dict, user: dict) -> dict:
    if not await can_view_po_quotes(po, user):
        e["cs_attachments"] = []
        e["cs_attachment_file_ids"] = []
    return e


@api_router.post("/purchase-orders")
async def create_purchase_order(payload: PurchaseOrderIn, user: dict = Depends(get_current_user)):
    """Create a new Purchase Order (draft). Only allowed when requisition is in pending_po_entry."""
    if not user.get("can_create_po") or await is_purchase_head_user(user):
        raise HTTPException(status_code=403, detail="You are not allowed to create a Purchase Order")

    req = await req_repo.get(payload.requisition_id) if ObjectId.is_valid(payload.requisition_id) else None
    if not req:
        raise HTTPException(status_code=404, detail="Linked requisition not found")
    if req.get("status") != "pending_po_entry":
        raise HTTPException(status_code=400,
                            detail="This requisition is not awaiting a Purchase Order (IT Head must approve the PR review first)")

    quote_ids = await _validate_po_quote_files(payload.cs_attachment_file_ids)
    items = [it.model_dump() for it in payload.items]
    for it in items:
        # Keep the catalog product and the free-text description as two separate fields.
        pn = (it.get("product_name") or "").strip() or it["item_description"]
        cat = await prod_repo.get_by_name_key(_pkey(pn))
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
        "cs_attachment_file_ids": quote_ids,
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

    doc["_id"] = await po_repo.insert(doc)

    # Move parent requisition out of the pending_po_entry queue
    req.setdefault("history", []).append({
        "at": now_iso(),
        "by": user["name"],
        "action": "po_created",
        "note": f"Purchase Order {po_no} created by Purchase Dept (vendor: {payload.vendor_name})."
    })
    # status po_draft: leaves the File PR queue; the PO is not submitted yet
    await req_repo.save_progress(req["_id"], status="po_draft", history=req["history"], updated_at=now_iso(),
                                 po_id=str(doc["_id"]))

    return await _enrich_po(doc)


@api_router.put("/purchase-orders/{po_id}")
async def update_purchase_order(po_id: str, payload: PurchaseOrderIn, user: dict = Depends(get_current_user)):
    """Save changes to a DRAFT Purchase Order (the form's "Save Draft" on an existing draft, and the
    save that happens right before "Submit PO for Approval"). Only the user who created the draft
    (or a Super Admin) can change it, and only while it is still a draft."""
    if not user.get("can_create_po") or await is_purchase_head_user(user):
        raise HTTPException(status_code=403, detail="You are not allowed to edit a Purchase Order")
    po = await po_repo.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Only a draft Purchase Order can be edited")
    if po.get("created_by_id") != str(user["_id"]) and user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Only the person who created this draft can edit it")
    if payload.requisition_id != po.get("requisition_id"):
        raise HTTPException(status_code=400, detail="A Purchase Order cannot be moved to a different requisition")

    quote_ids = await _validate_po_quote_files(payload.cs_attachment_file_ids)
    items = [it.model_dump() for it in payload.items]
    for it in items:
        pn = (it.get("product_name") or "").strip() or it["item_description"]
        cat = await prod_repo.get_by_name_key(_pkey(pn))
        it["product_name"] = cat["name"] if cat else pn
        if "brand_model" in it and "specification" not in it:
            it["specification"] = it.get("brand_model")
        it["line_total"] = _po_line_total(it)

    totals = _po_totals(items, tax_percent=payload.tax_percent,
                        discount_amount=payload.discount_amount, transport_charge=payload.transport_charge)
    changes = {
        "vendor_id": payload.vendor_id,
        "vendor_name": payload.vendor_name,
        "contact_person": payload.contact_person,
        "vendor_email": payload.vendor_email,
        "bin_tin": payload.bin_tin,
        "delivery_location": payload.delivery_location,
        "attention_to": payload.attention_to,
        "delivery_date": payload.delivery_date,
        "payment_terms": payload.payment_terms,
        "po_date": payload.po_date or po.get("po_date") or now_iso()[:10],
        "cs_reference_no": payload.cs_reference_no,
        "cs_attachment_file_ids": quote_ids,
        "items": items,
        "special_terms_notes": payload.special_terms_notes,
        **totals,
        "updated_at": now_iso(),
    }
    await po_repo.update_fields(po["_id"], changes)
    po.update(changes)
    return await _enrich_po(po)


@api_router.get("/purchase-orders")
async def list_purchase_orders(mine: bool = False, user: dict = Depends(get_current_user)):
    is_purchase_head = (
        user["role"] == "purchase_head" or
        (user["role"] == "dept_head" and await _department_is_purchase(user.get("department_id")))
    )
    me_purchase_head = is_purchase_head
    delegators = await active_delegators_of(user)
    if not (
        user.get("can_create_po")
        or user["role"] in ("super_admin", "md", "accounts", "purchase_head")
        or is_purchase_head
        or delegators
    ):
        return []
    docs = await po_repo.list_all(created_by=(str(user["_id"]), user["name"]) if mine else None)
    out = []
    for d in docs:
        e = await _enrich_po(d)
        await _hide_quotes_if_not_allowed(e, d, user)
        e["can_act"] = await po_user_can_act(d, user, delegators)
        _redact_po_comments(e, user, e["can_act"], me_purchase_head)   # hand-over notes: next approver only (+ IT Head note for PO team)
        out.append(e)
    return out


@api_router.get("/purchase-orders/next-number")
async def preview_next_po_number(user: dict = Depends(get_current_user)):
    """Preview of the number the next PO will get (does NOT consume it). Shown on the blank
    PO form; the real number is assigned atomically when the draft is saved."""
    year = datetime.now(timezone.utc).year
    c = await counter_repo.get(f"po-{year}")
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
    doc = await po_repo.get(po_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    e = await _enrich_po(doc)
    await _hide_quotes_if_not_allowed(e, doc, user)
    e["can_act"] = await po_user_can_act(doc, user, await active_delegators_of(user))
    _redact_po_comments(e, user, e["can_act"], await is_purchase_head_user(user))
    return e


class POActionIn(BaseModel):
    action: Literal["approve", "reject"]
    comment: Optional[str] = None


@api_router.post("/purchase-orders/{po_id}/submit")
async def submit_purchase_order(po_id: str, user: dict = Depends(get_current_user)):
    """Submit draft PO into approval flow. Always goes to the Purchase Dept Head first."""
    if not user.get("can_create_po") or await is_purchase_head_user(user):
        raise HTTPException(status_code=403, detail="You are not allowed to submit a Purchase Order")

    po = await po_repo.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only a draft Purchase Order can be submitted")

    # Every submitted PO goes to the Purchase Dept Head first; then MD (only above the threshold) and
    # finally the Accounts Head (always) - see act_on_purchase_order.
    threshold = await get_po_threshold()
    next_status = "pending_purchase_head_approval"

    await po_repo.update_fields(po["_id"], {
        "status": next_status,
        "submitted_by": user["name"],
        "submitted_at": now_iso(),
        "threshold_at_submission": threshold,
        "updated_at": now_iso(),
    })
    po["status"] = next_status
    await sync_requisition_status_from_po(
        po, user["name"], "po_submitted",
        f"Purchase Order {po['po_number']} submitted for approval ({next_status.replace('_', ' ')}).")
    return await _hide_quotes_if_not_allowed(await _enrich_po(po), po, user)


@api_router.post("/purchase-orders/{po_id}/action")
async def act_on_purchase_order(po_id: str, payload: POActionIn, user: dict = Depends(get_current_user)):
    """Approve or reject a PO at the current stage.
    Stages:
      - pending_purchase_head_approval  → Purchase Head  → pending_md_approval (total > threshold)
                                                          or pending_accounts_head_approval (total <= threshold)
      - pending_md_approval             → MD             → pending_accounts_head_approval
      - pending_accounts_head_approval  → Accounts Head  → approved
    """

    po = await po_repo.get(po_id)
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
        # Approve path. Routing rule:
        #   total  >  threshold (50,000 BDT by default):  Purchase Head -> MD -> Accounts Head
        #   total <=  threshold:                          Purchase Head -> Accounts Head
        # The Accounts Head is always the final approver.
        if po["status"] == "pending_purchase_head_approval":
            if po["grand_total"] > await get_po_threshold():
                next_status = "pending_md_approval"            # high value: MD before Accounts
            else:
                next_status = "pending_accounts_head_approval"
        elif po["status"] == "pending_md_approval":
            next_status = "pending_accounts_head_approval"
        else:  # pending_accounts_head_approval
            next_status = "approved"

    # The Accounts Head is the last approver, so an approval carries no note (nobody to pass it on to).
    # A rejection reason is still kept - the requester should be able to see why.
    note_to_save = None if (stage_role == "accounts" and payload.action != "reject") else payload.comment
    comments = po.get("approval_comments", []) + [{
        "at": now_iso(),
        "by": user["name"],
        "role": stage_role,
        "action": payload.action,
        "comment": note_to_save,
    }]

    await po_repo.update_fields(po["_id"], {
        "status": next_status,
        "approval_comments": comments,
        "updated_at": now_iso(),
    })
    po["status"] = next_status
    po["approval_comments"] = comments

    # Every stage change (not just the final one) is reflected on the parent requisition
    await sync_requisition_status_from_po(
        po, user["name"], "po_" + next_status,
        f"Purchase Order {po['po_number']}: {payload.action}d by {ROLE_LABELS.get(stage_role, stage_role)} "
        f"→ {next_status.replace('_', ' ')}.".replace("rejectd", "rejected"))

    return await _hide_quotes_if_not_allowed(await _enrich_po(po), po, user)