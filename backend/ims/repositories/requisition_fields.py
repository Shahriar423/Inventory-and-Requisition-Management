"""Which fields each requisition write stores - ONE definition used by the requisitions repository.

Every function returns the plain {field: value} dict for one operation. The route code decides every value (permissions,
status, history); these functions only fix the *shape*, so a field can never be stored by one backend and forgotten by the
other. Extras win over the named values, exactly like a dict merge, because routing steps may hand back a newer chain/history.
"""
from typing import Any, Dict, Optional


def progress(status: str, history: list, updated_at: str, extra: Optional[dict], fields: dict) -> Dict[str, Any]:
    return {"status": status, "history": history, "updated_at": updated_at, **fields, **(extra or {})}


def approval_chain(chain: list) -> Dict[str, Any]:
    return {"approval_chain": chain}


def pr_number(pr_no: str) -> Dict[str, Any]:
    return {"purchase_pr_no": pr_no}


def handover_link(handover_id: str, status: str) -> Dict[str, Any]:
    return {"handover_id": handover_id, "status": status}


def decision(approval_chain: list, status: str, history: list, updated_at: str, extra: Optional[dict]) -> Dict[str, Any]:
    return {"approval_chain": approval_chain, "status": status, "history": history, "updated_at": updated_at, **(extra or {})}


def pr_filing(items: list, approval_chain: list, status: str, history: list, updated_at: str,
              overall_business_justification, required_by_date, urgency_level, delivery_location,
              pr_attachment_file_ids: list, pr_filed_by: str, pr_filed_by_id: str) -> Dict[str, Any]:
    return {
        "items": items, "total_amount": 0, "approval_chain": approval_chain, "pr_flow": True, "po_flow": True,
        "status": status, "history": history, "updated_at": updated_at,
        "overall_business_justification": overall_business_justification,
        "required_by_date": required_by_date, "urgency_level": urgency_level,
        "delivery_location": delivery_location, "pr_attachment_file_ids": pr_attachment_file_ids,
        "pr_needs_refile": False, "pr_filed_by": pr_filed_by, "pr_filed_by_id": pr_filed_by_id}


def stock_allocation(status: str, approval_chain: list, fulfillment_type: str, allocated_item_details: list,
                     procurement_notes: Optional[str], allocated_by: str, history: list, updated_at: str) -> Dict[str, Any]:
    return {
        "status": status, "approval_chain": approval_chain, "fulfillment_type": fulfillment_type,
        "allocated_item_details": allocated_item_details, "procurement_notes": procurement_notes,
        "allocated_by": allocated_by, "pr_flow": False, "po_flow": False,
        "history": history, "updated_at": updated_at}


def stock_bypass(fulfillment_type: str, reason: str, bypassed_by: str, history: list, updated_at: str) -> Dict[str, Any]:
    return {"fulfillment_type": fulfillment_type, "procurement_notes": reason, "stock_bypassed_by": bypassed_by,
            "allocated_item_details": None, "history": history, "updated_at": updated_at}


def pr_cancellation(history: list, updated_at: str, closed_at: str, note: str, cancelled_by: str) -> Dict[str, Any]:
    return {"status": "pr_cancelled", "history": history, "updated_at": updated_at, "closed_at": closed_at,
            "pr_cancel_note": note, "pr_cancelled_by": cancelled_by}


def creation_routing(status: str, approval_chain: list, extra: Optional[dict]) -> Dict[str, Any]:
    return {"status": status, "approval_chain": approval_chain, **(extra or {})}


def requester_cancellation(approval_chain: list, history: list, cancelled_by: str, note: str, at: str) -> Dict[str, Any]:
    return {"status": "cancelled", "approval_chain": approval_chain, "history": history,
            "cancelled_by": cancelled_by, "cancel_note": note, "cancelled_at": at, "updated_at": at}
