"""SQLAlchemy Core definitions of the requisition tables.

The columns are generated from the same specs the row converter uses (rows.REQ_COLS / ITEM_COLS / ...), so the two cannot
disagree about names or kinds. `migration/mysql/schema.sql` stays the source of truth for the real DDL (collations,
indexes, comments); tests/test_mysql_tables.py compares this metadata with a database built from schema.sql, so any drift
fails a test.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from . import people as P
from . import rows as R

metadata = sa.MetaData()

_TYPES = {
    "code": lambda n: sa.String(n or 255), "str": lambda n: sa.String(n or 255), "text": lambda n: sa.Text(),
    "dt": lambda n: mysql.DATETIME(fsp=6), "date": lambda n: sa.Date(), "bool": lambda n: sa.Integer(), "int": lambda n: sa.Integer(), "bigint": lambda n: sa.BigInteger(),
    "dec": lambda n: sa.Numeric(14, 2), "json": lambda n: sa.JSON(none_as_null=True),
}


def _cols(specs, key_to_col=None):
    key_to_col = key_to_col or {}
    return [sa.Column(key_to_col.get(name, name), _TYPES[kind](maxlen), nullable=True) for name, kind, maxlen in specs]


requisitions = sa.Table(
    "requisitions", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *[c for c in _cols(R.REQ_COLS)],
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
# columns that schema.sql declares NOT NULL
requisitions.c.requisition_no.nullable = False
requisitions.c.status.nullable = False
requisitions.c.total_amount.nullable = False

requisition_items = sa.Table(
    "requisition_items", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("requisition_id", sa.BigInteger, sa.ForeignKey("requisitions.id", ondelete="CASCADE"), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    *_cols(R.ITEM_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)

approval_steps = sa.Table(
    "approval_steps", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("requisition_id", sa.BigInteger, sa.ForeignKey("requisitions.id", ondelete="CASCADE"), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    *_cols(R.STEP_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
approval_steps.c.status.nullable = False

requisition_history = sa.Table(
    "requisition_history", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("requisition_id", sa.BigInteger, sa.ForeignKey("requisitions.id", ondelete="CASCADE"), nullable=False),
    *_cols(R.HIST_COLS, R.HIST_COLUMN_OF),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)

CHILD_TABLES = {"items": requisition_items, "steps": approval_steps, "history": requisition_history}


# ------------------------------------------------------------------------------------------------ people tables
departments = sa.Table(
    "departments", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(P.DEPT_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
departments.c.name.nullable = False

users = sa.Table(
    "users", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(P.USER_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
for _c in ("name", "email", "role"):
    users.c[_c].nullable = False

sidebar_permissions = sa.Table(
    "sidebar_permissions", metadata,
    sa.Column("role", sa.String(32), primary_key=True),
    sa.Column("items", sa.JSON(none_as_null=True), nullable=False),
)

password_resets = sa.Table(
    "password_resets", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    *_cols(P.RESET_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)


# ------------------------------------------------------------------------------------------------ catalog + supporting tables
from . import catalog as C

categories = sa.Table(
    "categories", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.CAT_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
categories.c.name.nullable = False

products = sa.Table(
    "products", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.PRODUCT_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
for _c in ("name", "name_key", "product_type"):
    products.c[_c].nullable = False

counters = sa.Table(
    "counters", metadata,
    sa.Column("counter_key", sa.String(40), primary_key=True),
    *_cols(C.COUNTER_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
counters.c.seq.nullable = False

files = sa.Table(
    "files", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(40), nullable=False),
    *_cols(C.FILE_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
files.c.storage_path.nullable = False
files.c.is_deleted.nullable = False

notifications = sa.Table(
    "notifications", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.NOTIF_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
for _c in ("user_id", "status"):
    notifications.c[_c].nullable = False

purchase_orders = sa.Table(
    "purchase_orders", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.PO_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
for _c in ("po_number", "status"):
    purchase_orders.c[_c].nullable = False


assets = sa.Table(
    "assets", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.ASSET_COLS, C.ASSET_COLUMN_OF),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
assets.c.name.nullable = False
assets.c.status.nullable = False

handovers = sa.Table(
    "handovers", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.HANDOVER_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
handovers.c.slip_no.nullable = False
handovers.c.status.nullable = False

correction_cases = sa.Table(
    "correction_cases", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.CORRECTION_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
correction_cases.c.case_no.nullable = False
correction_cases.c.status.nullable = False


system_settings = sa.Table(
    "system_settings", metadata,
    sa.Column("setting_key", sa.String(64), primary_key=True),
    sa.Column("payload", sa.JSON(none_as_null=True), nullable=False),
)

grns = sa.Table(
    "grns", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.GRN_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
grns.c.grn_no.nullable = False

asset_history = sa.Table(
    "asset_history", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.AH_COLS, C.AH_COLUMN_OF),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
asset_history.c.asset_id.nullable = False


paper_records = sa.Table(
    "paper_records", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.PAPER_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)

saved_reports = sa.Table(
    "saved_reports", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.SAVED_REPORT_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)

report_access = sa.Table(
    "report_access", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.REPORT_ACCESS_COLS),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
for _c in ("report_id", "user_id", "status"):
    report_access.c[_c].nullable = False

import_batches = sa.Table(
    "import_batches", metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("public_id", sa.String(24), nullable=False),
    *_cols(C.IMPORT_BATCH_COLS, C.IMPORT_BATCH_COLUMN_OF),
    sa.Column("extra", sa.JSON(none_as_null=True), nullable=True),
)
