"""Column specs for catalog tables: categories, products, counters, files, notifications, purchase_orders.

Same idea as people.py / rows.py: the specs drive both the SQLAlchemy table definitions and the
document <-> row conversion.
"""
from typing import List, Optional, Tuple

# (column, kind, max_len)
CAT_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("name", "str", 150), ("department_id", "code", 40), ("description", "text", None),
    ("created_at", "dt", None),
]
CAT_ALWAYS = {"name", "department_id", "description", "created_at"}
CAT_MUST_FIT = {"name"}

PRODUCT_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("name", "str", 255), ("name_key", "code", 255), ("product_type", "code", 24),
    ("brand", "str", 150), ("created_by", "str", 150), ("created_at", "dt", None),
]
PRODUCT_ALWAYS = {"name", "name_key", "product_type", "brand", "created_by", "created_at"}
PRODUCT_MUST_FIT = {"name", "name_key", "product_type"}

COUNTER_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("seq", "int", None),
]
COUNTER_ALWAYS = {"seq"}

FILE_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("storage_path", "str", 500), ("original_filename", "str", 255), ("content_type", "str", 120),
    ("size", "bigint", None), ("is_deleted", "bool", None), ("uploaded_by", "code", 40),
    ("created_at", "dt", None),
]
FILE_ALWAYS = {"storage_path", "original_filename", "content_type", "size", "is_deleted", "uploaded_by", "created_at"}
FILE_MUST_FIT = {"storage_path"}

NOTIF_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("user_id", "code", 40), ("type", "code", 40), ("status", "code", 24),
    ("title", "str", 255), ("message", "text", None),
    ("asset_id", "code", 40), ("asset_name", "str", 255),
    ("requisition_id", "code", 40), ("handover_id", "code", 40),
    ("created_at", "dt", None), ("acted_at", "dt", None),
]
NOTIF_ALWAYS = {"user_id", "type", "status", "created_at"}
NOTIF_MUST_FIT = {"user_id", "status"}

PO_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("po_number", "str", 40), ("requisition_id", "code", 40),
    ("vendor_id", "code", 40), ("vendor_name", "str", 200), ("contact_person", "str", 150),
    ("vendor_email", "str", 190), ("bin_tin", "str", 80),
    ("delivery_location", "str", 255), ("attention_to", "str", 150),
    ("delivery_date", "date", None), ("payment_terms", "str", 120), ("po_date", "date", None),
    ("cs_reference_no", "str", 80), ("cs_attachment_file_ids", "json", None),
    ("items", "json", None), ("special_terms_notes", "text", None),
    ("sub_total", "dec", None), ("tax_percent", "dec", None), ("total_tax", "dec", None),
    ("discount_amount", "dec", None), ("transport_charge", "dec", None), ("grand_total", "dec", None),
    ("status", "code", 48), ("approval_comments", "json", None),
    ("created_by", "str", 150), ("created_by_id", "code", 40),
    ("submitted_by", "str", 150), ("submitted_at", "dt", None),
    ("threshold_at_submission", "dec", None), ("reminder", "json", None),
    ("created_at", "dt", None), ("updated_at", "dt", None),
]
PO_ALWAYS = {
    "po_number", "requisition_id", "vendor_name", "status", "created_by", "created_by_id",
    "created_at", "updated_at", "items", "approval_comments", "cs_attachment_file_ids",
}
PO_MUST_FIT = {"po_number", "status"}


# ------------------------------------------------------------------------------------------------ inventory
ASSET_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("name", "str", 255), ("brand", "str", 150), ("serial_no", "str", 120), ("tag_id", "str", 120),
    ("category_id", "code", 40), ("specification", "text", None), ("status", "code", 40),
    ("condition", "str", 40),  # maps to condition_label in SQL
    ("assigned_to", "str", 150), ("assigned_to_user_id", "code", 40),
    ("assigned_department_id", "code", 40), ("assigned_at", "dt", None),
    ("assigned_slip_no", "str", 40), ("receipt_confirmed", "bool", None),
    ("receipt_confirmed_at", "dt", None), ("pending_receipt", "bool", None),
    ("pending_handover_id", "code", 40), ("pending_return_handover_id", "code", 40),
    ("pending_return_slip_no", "str", 40), ("assigned_to_tentative", "str", 150),
    ("source_grn_id", "code", 40), ("source", "code", 40), ("remarks", "text", None),
    ("added_by", "str", 150), ("created_at", "dt", None),
]
ASSET_ALWAYS = {"name", "status", "created_at"}
ASSET_MUST_FIT = {"name", "status"}
ASSET_COLUMN_OF = {"condition": "condition_label"}  # SQL reserved word

HANDOVER_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("slip_no", "str", 40), ("type", "code", 24), ("employee_name", "str", 150),
    ("employee_user_id", "code", 40), ("department_id", "code", 40),
    ("items", "json", None), ("return_items", "json", None),
    ("return_received", "bool", None), ("remarks", "text", None), ("note", "text", None),
    ("handover_date", "dt", None), ("prepared_by", "str", 150),
    ("prepared_by_sign", "str", 150), ("received_by_sign", "str", 150),
    ("status", "code", 40), ("requisition_id", "code", 40),
    ("correction_case_ids", "json", None), ("confirmed_at", "dt", None),
    ("created_at", "dt", None),
]
HANDOVER_ALWAYS = {"slip_no", "status", "created_at", "items", "return_items"}
HANDOVER_MUST_FIT = {"slip_no", "status"}

CORRECTION_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("case_no", "str", 40), ("status", "code", 40), ("version", "int", None),
    ("requisition_id", "code", 40), ("requisition_no", "str", 40),
    ("original_handover_id", "code", 40), ("original_slip_no", "str", 40),
    ("employee_user_id", "code", 40), ("employee_name", "str", 150),
    ("department_id", "code", 40), ("notification_id", "code", 40),
    ("item", "json", None), ("reason", "code", 40), ("reason_label", "str", 120),
    ("note", "text", None), ("attachment_file_id", "code", 40), ("attachment_name", "str", 255),
    ("responsible_it_id", "code", 40), ("responsible_it_name", "str", 150),
    ("attempts", "json", None), ("failed_attempts", "int", None),
    ("clarifications", "json", None), ("notes", "json", None), ("events", "json", None),
    ("procurement", "json", None), ("rejections", "json", None), ("reminders", "json", None),
    ("escalated_at", "dt", None), ("escalations", "json", None),
    ("created_at", "dt", None), ("last_activity_at", "dt", None),
    ("closed_at", "dt", None), ("closure", "json", None), ("confirmed_at", "dt", None),
    ("status_before_clarification", "code", 40),
]
CORRECTION_ALWAYS = {"case_no", "status", "created_at", "item", "attempts", "events"}
CORRECTION_MUST_FIT = {"case_no", "status"}


GRN_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("grn_no", "str", 40), ("challan_no", "str", 80), ("vendor_name", "str", 200),
    ("received_date", "dt", None), ("delivery_location", "str", 255),
    ("requisition_id", "code", 40), ("items", "json", None),
    ("received_by", "str", 150), ("created_at", "dt", None),
]
GRN_ALWAYS = {"grn_no", "created_at", "items"}
GRN_MUST_FIT = {"grn_no"}

AH_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("asset_id", "code", 40), ("at", "dt", None), ("action", "code", 64),
    ("by", "str", 150), ("employee_name", "str", 150), ("employee_user_id", "code", 40),
    ("slip_no", "str", 40), ("handover_id", "code", 40), ("source", "code", 40),
    ("remarks", "text", None),
]
AH_ALWAYS = {"asset_id", "at", "action"}
AH_MUST_FIT = {"asset_id"}
AH_COLUMN_OF = {"by": "by_name"}


PAPER_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("employee_id", "code", 40), ("employee_name", "str", 150),
    ("asset_ids", "json", None), ("file_ids", "json", None),
    ("kind", "code", 40), ("notes", "text", None),
    ("created_by", "str", 150), ("created_at", "dt", None),
]
PAPER_ALWAYS = {"created_at"}
PAPER_MUST_FIT: tuple = ()

SAVED_REPORT_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("title", "str", 255), ("report_type", "code", 64),
    ("definition", "json", None), ("audit", "json", None),
    ("created_by", "str", 150), ("created_by_id", "code", 40),
    ("created_at", "dt", None), ("updated_at", "dt", None),
]
SAVED_REPORT_ALWAYS = {"created_at"}
SAVED_REPORT_MUST_FIT: tuple = ()

REPORT_ACCESS_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("report_id", "code", 40), ("user_id", "code", 40), ("status", "code", 24),
    ("permissions", "json", None), ("last_opened_at", "dt", None),
    ("granted_by", "str", 150), ("created_at", "dt", None),
]
REPORT_ACCESS_ALWAYS = {"report_id", "user_id", "status"}
REPORT_ACCESS_MUST_FIT = {"report_id", "user_id", "status"}

IMPORT_BATCH_COLS: List[Tuple[str, str, Optional[int]]] = [
    ("batch_id", "code", 64), ("kind", "code", 40), ("filename", "str", 255),
    ("by", "str", 150), ("created_at", "dt", None),
]
IMPORT_BATCH_ALWAYS = {"created_at"}
IMPORT_BATCH_MUST_FIT: tuple = ()
IMPORT_BATCH_COLUMN_OF = {"by": "by_name"}
