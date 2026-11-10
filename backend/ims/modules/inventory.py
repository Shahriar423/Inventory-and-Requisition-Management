"""Assets, GRNs and handovers."""

from fastapi import Request, Response, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional, Literal
from ims.ids import ObjectId
import io
import re
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from ims.repositories import departments as dept_repo
from ims.repositories import users as users_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import products as prod_repo
from ims.repositories import notifications_repo as notif_repo
from ims.repositories import assets as asset_repo
from ims.repositories import handovers as handover_repo
from ims.repositories import grns as grn_repo
from ims.repositories import asset_history as ah_repo
from ims.common import (
    ASSET_HELD_STATUSES,
    CONDITION_LABELS,
    _apply_returns,
    _can_manage_handovers,
    _clean_brand,
    _enrich_asset,
    _enrich_assets,
    _held_filter,
    _img_from_datauri,
    _log_asset_event,
    _next_no,
    _pkey,
    _release_slip_locks,
    _skey,
    _tracked_by_quantity,
    api_router,
    canonicalize_product_names,
    find_dept_by_name,
    get_current_user,
    has_pr_raise_flag,
    now_iso,
    process_waiting_stock_requisitions,
    require_roles,
    resolve_category_name,
    resolve_handover_employee,
    strip_id,
    user_from_token,
)

# The requisition has goods sitting in IT's central stock (via GRN) but hasn't been issued
# for handover yet. Used both by POST /requisitions/{id}/issue-stock and by the Handover
# Module's auto-link logic (see _find_requisition_for_handover) so an ad-hoc handover
# created for the same item can still close the loop back to the requisition.
READY_FOR_HANDOVER_STATUS = "stock_received_in_it"


def require_roles_or_pr_raiser(*roles):
    """Same as require_roles(), but a user with can_raise_pr is also let through."""
    async def dep(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles and not has_pr_raise_flag(user):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dep


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
    candidates = await req_repo.find_handover_candidates(READY_FOR_HANDOVER_STATUS, employee_name, department_id)
    matches = [c for c in candidates
               if any(it.get("product_name", "").strip().lower() in wanted for it in c.get("items", []))]
    return matches[0] if len(matches) == 1 else None


class AssetIn(BaseModel):
    name: str
    brand: Optional[str] = None
    serial_no: Optional[str] = None
    tag_id: Optional[str] = None
    category_id: Optional[str] = None


@api_router.get("/assets/stock-summary")
async def stock_summary(user: dict = Depends(get_current_user)):
    """Aggregated available-stock view for the main Stock List dashboard.
    Groups by item name + category, counting only status == 'in_stock' assets
    (an asset stays 'in_stock' — i.e. still available — until the employee
    confirms receipt; see notifications/confirm). Per-asset detail fields
    (serial_no, tag_id, assigned_to, status) are intentionally NOT included
    here; use GET /assets for that granular, item-level view."""
    rows = await asset_repo.stock_summary()
    out = []
    for r in rows:
        cid = r.get("category_id")
        cat_name = await resolve_category_name(cid)
        out.append({
            "name": r.get("name"),
            "category_id": cid,
            "category_name": cat_name,
            "available_stock": r["available_stock"],
        })
    return out


@api_router.get("/assets")
async def list_assets(response: Response, status: Optional[str] = None, assigned_to: Optional[str] = None,
                      assigned_to_user_id: Optional[str] = None, page: Optional[int] = None, page_size: int = 50,
                      search: Optional[str] = Query(None, alias="q"), user: dict = Depends(get_current_user)):
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
    if search and search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        q = {"$and": [q, {"$or": [{"name": rx}, {"tag_id": rx}, {"serial_no": rx}, {"assigned_to": rx}, {"brand": rx}]}]} if q else \
            {"$or": [{"name": rx}, {"tag_id": rx}, {"serial_no": rx}, {"assigned_to": rx}, {"brand": rx}]}
    newest_first = [("created_at", -1)]
    if page:                                    # opt-in server-side pagination; no `page` = legacy full list
        size = max(1, min(page_size, 200))
        response.headers["X-Total-Count"] = str(await asset_repo.count_filtered(q))
        docs = await asset_repo.find(q, sort=newest_first, skip=(max(page, 1) - 1) * size, limit=size)
    else:
        docs = await asset_repo.find(q, sort=newest_first, limit=50000)
    return await _enrich_assets(docs)


@api_router.post("/assets")
async def create_asset(payload: AssetIn, user: dict = Depends(require_roles("super_admin", "dept_head", "purchase_head"))):
    doc = payload.model_dump()
    doc.update({"status": "in_stock", "assigned_to": None, "assigned_department_id": None,
                "source_grn_id": None, "created_at": now_iso()})
    new_id = await asset_repo.insert(doc)
    doc["_id"] = new_id
    await process_waiting_stock_requisitions()     # restock -> start waiting handovers
    return await _enrich_asset(doc)


class ExistingDeviceIn(BaseModel):
    name: str
    brand: Optional[str] = None
    category_id: Optional[str] = None
    tag_id: Optional[str] = None
    serial_no: Optional[str] = None
    specification: Optional[str] = None     # e.g. "Core i5 / 8 GB RAM / 256 GB SSD / 14 inch"
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
    emp = await users_repo.get(payload.user_id)
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
            if val.lower() in seen or await asset_repo.find_by_field(field, val):
                raise HTTPException(status_code=400, detail=f"{label} '{val}' already exists in the system")
            seen.add(val.lower())

    created = []
    for d in payload.devices:
        when = d.assigned_date or now_iso()
        doc = {
            "name": d.name.strip(), "brand": (d.brand or "").strip() or None,
            "serial_no": (d.serial_no or "").strip() or None, "tag_id": (d.tag_id or "").strip() or None,
            "category_id": d.category_id or None, "specification": (d.specification or "").strip() or None,
            "status": "assigned",
            "assigned_to": emp["name"], "assigned_to_user_id": str(emp["_id"]),
            "assigned_department_id": emp.get("department_id"),
            "assigned_at": when, "receipt_confirmed": True, "receipt_confirmed_at": when,
            "pending_receipt": False, "pending_handover_id": None, "assigned_slip_no": None,
            "remarks": d.remarks, "source": "existing_entry",
            "added_by": user["name"], "created_at": now_iso(),
        }
        new_id = await asset_repo.insert(doc)
        doc["_id"] = new_id
        await _log_asset_event(doc, "issued", user["name"], emp=emp, source="existing_entry")
        created.append(await _enrich_asset(doc))
    return {"ok": True, "employee": emp["name"], "created": len(created), "assets": created}


class GrnAssetIn(BaseModel):
    serial_no: Optional[str] = None
    tag_id: Optional[str] = None


class GrnItemIn(BaseModel):
    product_name: str
    brand: Optional[str] = None
    category_id: Optional[str] = None
    uom: Optional[str] = "Nos"
    specification: Optional[str] = None     # product specification / details typed in on receipt
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
    docs = await grn_repo.list_all()
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
        prod = await prod_repo.get_by_name_key(_pkey(it["product_name"])) or {}
        brand = _clean_brand(it.get("brand")) or prod.get("brand") or None
        it["brand"] = brand
        it["specification"] = (it.get("specification") or "").strip() or None
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
    new_gid = await grn_repo.insert(doc)
    grn_id = str(new_gid)
    created_assets = 0
    for it, brand, tagged, untagged in plans:
        for a in tagged:
            await asset_repo.insert({
                "name": it["product_name"], "brand": brand, "specification": it.get("specification"),
                "serial_no": a.get("serial_no"), "tag_id": a.get("tag_id"),
                "category_id": it.get("category_id"), "status": "in_stock",
                "assigned_to": None, "assigned_department_id": None,
                "source_grn_id": grn_id, "created_at": now_iso(),
            })
            created_assets += 1
        if untagged:
            stamp = now_iso()
            for _ in range(untagged):
                await asset_repo.insert({
                    "name": it["product_name"], "brand": brand, "specification": it.get("specification"),
                    "serial_no": None, "tag_id": None,
                    "category_id": it.get("category_id"), "status": "in_stock",
                    "assigned_to": None, "assigned_department_id": None,
                    "source_grn_id": grn_id, "created_at": stamp,
                })
            created_assets += untagged
    doc["_id"] = new_gid
    out = strip_id(doc)
    out["created_assets"] = created_assets
    out["waiting_handovers_started"] = await process_waiting_stock_requisitions()

    # Completes the receiving side of the out-of-stock PR flow: goods received against the
    # requisition's PR -> central stock already incremented above (assets created as
    # in_stock). Handover is NOT auto-generated here anymore — IT explicitly reviews and
    # clicks "Issue Stock for Requisition" first (see POST /requisitions/{id}/issue-stock).
    if payload.requisition_id and ObjectId.is_valid(payload.requisition_id):
        req = await req_repo.get(payload.requisition_id)
        if req and req.get("status") == "buy_process":
            req["history"].append({"at": now_iso(), "by": user["name"], "action": "stock_received_in_it",
                                   "note": f"Received via GRN {grn_no} (challan {payload.challan_no})."})
            await req_repo.save_progress(req["_id"], status="stock_received_in_it", history=req["history"],
                                         updated_at=now_iso())
            out["requisition_advanced_to"] = "stock_received_in_it"
    return out


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
        a = await asset_repo.get(aid)
        if not a:
            raise HTTPException(status_code=400, detail="A selected asset no longer exists. Pick it again.")
        label = f"{a.get('name')} ({a.get('tag_id') or a.get('serial_no') or 'no tag'})"
        if a.get("status") == "return_pending":
            raise HTTPException(status_code=400, detail=f"{label} already has a return in progress (slip {a.get('pending_return_slip_no') or '-'}).")
        held = await asset_repo.get(aid)
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


async def _enrich_handover(h: dict) -> dict:
    h = strip_id(h)
    if h.get("department_id") and ObjectId.is_valid(h["department_id"]):
        d = await dept_repo.get(h["department_id"])
        h["department_name"] = d["name"] if d else None
    return h


@api_router.get("/handovers")
async def list_handovers(user: dict = Depends(get_current_user)):
    docs = await handover_repo.list_all()
    return [await _enrich_handover(h) for h in docs]


@api_router.get("/handovers/{hid}")
async def get_handover(hid: str, user: dict = Depends(get_current_user)):
    h = await handover_repo.get(hid)
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
        a = await asset_repo.get(aid)
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
            a = await asset_repo.get(aid)
            out.append({**it, "item": a["name"], "brand": it.get("brand") or a.get("brand"), "quantity": 1,
                        "tag_id": a.get("tag_id"), "serial_no": a.get("serial_no")})
            continue
        name = (it.get("item") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Every line needs an item. Select it from the list.")
        qty = max(int(it.get("quantity") or 1), 1)
        prod = await prod_repo.get_by_name_key(_pkey(name))
        if not prod:
            raise HTTPException(status_code=400, detail=f"'{name}' is not in the product catalog. Select the item from the list.")
        cands = await asset_repo.list_available(prod["name"], limit=qty + len(picked) + 5)
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
            r = await req_repo.get(payload.requisition_id)
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
    new_hid = await handover_repo.insert(doc)
    hid = str(new_hid)

    async def undo(msg: str):
        await _release_slip_locks(hid)
        await handover_repo.delete(new_hid)
        raise HTTPException(status_code=409, detail=msg)

    # 1) reserve the units being issued. Atomic: succeeds only if the unit is STILL in stock.
    for it in items:
        aid = it.get("asset_id")
        if not aid or not ObjectId.is_valid(aid):
            continue
        modified = await asset_repo.update_if(
            aid,
            {"status": "in_stock", "pending_receipt": {"$ne": True}},
            {"pending_receipt": True, "pending_handover_id": hid,
             "assigned_to_tentative": payload.employee_name,
             "assigned_department_id": payload.department_id})
        if modified == 0:
            await undo("One of the selected units was just taken by another handover. "
                       "Nothing was saved - please pick the units again.")

    # 2) lock the returned assets. Atomic: succeeds only if it is STILL assigned.
    for ln in return_lines:
        modified = await asset_repo.update_if(
            ln["asset_id"],
            {"status": "assigned"},
            {"status": "return_pending", "pending_return_handover_id": hid,
             "pending_return_slip_no": slip_no})
        if modified == 0:
            await undo(f"{ln.get('item')} ({ln.get('tag_id') or ln.get('serial_no') or 'no tag'}) "
                       "changed while saving. Nothing was saved - reload and try again.")

    if linked_req:
        # Mirror /requisitions/{id}/issue-stock: put the requisition into the same
        # pending_handover stage that flow would, and notify the requester, so the existing
        # deliver -> confirm pipeline closes the requisition out correctly later.
        item_names = ", ".join(it["product_name"] for it in linked_req["items"])
        await notif_repo.insert({
            "user_id": linked_req.get("requisitioner_id"),
            "employee_name": linked_req.get("requisition_for") or linked_req["requisitioner_name"],
            "type": "stock_allocated", "requisition_id": str(linked_req["_id"]), "handover_id": hid,
            "message": f"Your requested item {item_names} has arrived in IT inventory and is being prepared for handover.",
            "status": "unread", "created_at": now_iso(),
        })
        linked_req.setdefault("history", []).append({
            "at": now_iso(), "by": user["name"], "action": "stock_issued",
            "note": f"Linked to handover slip {slip_no} (created via Handover Module)."})
        await req_repo.save_progress(linked_req["_id"], status="pending_handover", history=linked_req["history"],
                                     updated_at=now_iso(), handover_id=hid)

    doc["_id"] = new_hid
    if payload.receive_now and return_lines:
        try:
            await _apply_returns(doc, user)
        except HTTPException:
            # keep the slip (it is valid); IT can press "Received by IT" later
            pass
    return await _enrich_handover(doc)


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
    h = await handover_repo.get(hid)
    if not h:
        raise HTTPException(status_code=404, detail="Slip not found")
    if not h.get("return_items"):
        raise HTTPException(status_code=400, detail="This slip has no returned assets to receive")
    if h.get("return_received"):
        raise HTTPException(status_code=400, detail="The returned assets were already received")
    n = await _apply_returns(h, user, {l.asset_id: l.model_dump(exclude_none=True) for l in payload.lines})
    return {"ok": True, "received": n, "status": h.get("status"), "slip_no": h.get("slip_no")}


@api_router.get("/assets/{aid}/history")
async def asset_history(aid: str, user: dict = Depends(get_current_user)):
    """Full life history of one asset, newest first."""
    if not await _can_manage_handovers(user):
        raise HTTPException(status_code=403, detail="Not allowed")
    docs = await ah_repo.list_for_asset(aid)
    return [strip_id(d) for d in docs]


@api_router.delete("/handovers/{hid}")
async def delete_handover(hid: str, user: dict = Depends(require_roles("super_admin"))):
    h = await handover_repo.get(hid)
    if h and (h.get("correction_case_id") or h.get("correction_case_ids")):
        # The slip is part of a correction case's audit history (original delivery or an attempt).
        raise HTTPException(status_code=400, detail="This slip belongs to a correction case and is part of its audit history, so it cannot be deleted.")
    if h and h.get("status") == "prepared":
        # A slip that was never completed still holds locks: free the reserved stock and put
        # assets waiting to be returned back with their employee. Completed slips only lose
        # the record - their asset changes already happened and are kept in asset_history.
        await _release_slip_locks(hid)
    await handover_repo.delete(hid)
    return {"ok": True}


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
    h = await handover_repo.get(hid)
    if not h:
        raise HTTPException(status_code=404, detail="Not found")
    dept_name = None
    if h.get("department_id") and ObjectId.is_valid(h["department_id"]):
        dp = await dept_repo.get(h["department_id"])
        dept_name = dp["name"] if dp else None
    for it in h.get("items") or []:
        if it.get("asset_id") and ObjectId.is_valid(it["asset_id"]) and not (it.get("tag_id") or it.get("serial_no")):
            a = await asset_repo.get(it["asset_id"])
            if a:
                it["tag_id"], it["serial_no"] = a.get("tag_id"), a.get("serial_no")
    pdf = build_handover_pdf(h, dept_name)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{h["slip_no"]}.pdf"'})


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
    docs = await asset_repo.find(q, sort=[("assigned_to", 1), ("assigned_at", 1)], limit=5000)
    # Used-up consumables (e.g. pens) are issued by quantity with no serial/tag, so they can't be
    # listed as individually identifiable inventory.
    qty_names = {_skey(p["name"]) for p in await prod_repo.list_all(product_type="consumable")}
    docs = [a for a in docs if not (_skey(a.get("name")) in qty_names and not (a.get("tag_id") or a.get("serial_no")))]
    enriched = [await _enrich_asset(a) for a in docs]
    employees = len({(a.get("assigned_to_user_id") or a.get("assigned_to") or "").lower() for a in enriched})
    return Response(content=build_assets_summary_pdf(enriched, employees), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="assigned-assets-register.pdf"'})