"""Development helper: delete all business data (requisitions, stock, slips, POs, notifications, files ...) from the
MySQL database named in backend/.env and keep the accounts, departments, catalog and settings.

    python clear_db.py            # asks you to type the database name before it deletes anything
"""
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Children first. Users, departments, categories, products, counters, sidebar_permissions and
# system_settings are deliberately NOT listed.
TABLES = [
    "requisition_history", "approval_steps", "requisition_items", "requisitions",
    "asset_history", "paper_records", "report_access", "saved_reports", "import_batches",
    "correction_cases", "handovers", "assets", "grns", "purchase_orders", "notifications", "files",
]


def main() -> None:
    url = os.environ.get("MYSQL_URL")
    if not url:
        sys.exit("MYSQL_URL is not set in backend/.env")
    u = urlparse(url.replace("mysql+aiomysql://", "mysql://").replace("mysql+pymysql://", "mysql://"))
    database = u.path.lstrip("/")
    print(f"This deletes ALL requisitions, stock, handovers, POs, notifications and files in database '{database}'.")
    if input("Type the database name to continue: ").strip() != database:
        sys.exit("Cancelled - nothing was deleted.")
    import pymysql
    conn = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""),
                           password=unquote(u.password or ""), database=database, charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            for t in TABLES:
                cur.execute(f"DELETE FROM `{t}`")
                print(f"cleared {cur.rowcount} rows from {t}")
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()
    finally:
        conn.close()
    print("Done. User accounts, departments, catalog and settings are untouched.")


if __name__ == "__main__":
    main()
