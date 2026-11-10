"""Column specs for the "people" tables: departments, users, sidebar_permissions, password_resets.

Same idea as rows.py for requisitions: the specs drive both the SQLAlchemy table definitions and the document <-> row
conversion, and tests compare them with a database built from schema.sql.
"""
DEPT_COLS = [("name", "str", 150), ("code", "str", 40), ("description", "text", None), ("created_at", "dt", None)]
DEPT_ALWAYS = {"name", "code", "description", "created_at"}

USER_COLS = [
    ("name", "str", 150), ("email", "str", 190), ("password_hash", "code", 255), ("role", "code", 32),
    ("role_label", "str", 64), ("department_id", "code", 40),
    ("can_raise_pr", "bool", None), ("can_create_po", "bool", None), ("can_process_requisition", "bool", None),
    ("it_team", "str", 40),
    ("must_change_password", "bool", None), ("password_changed_at", "dt", None), ("sessions_valid_from", "bigint", None),
    ("delegate_user_id", "code", 40), ("delegate_from", "date", None), ("delegate_until", "date", None),
    ("created_at", "dt", None),
]
USER_ALWAYS = {"name", "email", "password_hash", "role", "role_label", "department_id"}
USER_MUST_FIT = {"email", "name", "role"}          # NOT NULL columns: refuse instead of parking in `extra`

SIDEBAR_COLS = [("items", "json", None)]

RESET_COLS = [("user_id", "code", 40), ("user_email", "str", 190), ("reset_by", "code", 40), ("reset_by_name", "str", 150), ("at", "dt", None)]
RESET_ALWAYS = {"user_id", "user_email", "reset_by", "reset_by_name", "at"}
