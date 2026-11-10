"""Real foreign keys between the people tables and the requisition tables.

They are NOT part of schema.sql on purpose: a foreign key can only exist when both tables live in MySQL and every value already
points at something real. So they are added as a separate, checked step:

    python -m migration.mysql.migrate foreign-keys check     # lists every dangling reference (changes nothing)
    python -m migration.mysql.migrate foreign-keys add       # refuses if anything dangles, otherwise adds all of them
    python -m migration.mysql.migrate foreign-keys drop      # removes them again (e.g. while copying data in)

All keys are ON DELETE RESTRICT / ON UPDATE RESTRICT: a user or department that records point at cannot be deleted
(the application checks first and explains; the key is the last line of defence).
"""
from typing import Dict, List

#          table             constraint name           column                         parent table   parent column
FOREIGN_KEYS = [
    ("users",          "fk_users_department",     "department_id",               "departments", "public_id"),
    ("users",          "fk_users_delegate",       "delegate_user_id",            "users",       "public_id"),
    ("requisitions",   "fk_req_requisitioner",    "requisitioner_id",            "users",       "public_id"),
    ("requisitions",   "fk_req_department",       "requisitioner_department_id", "departments", "public_id"),
    ("requisitions",   "fk_req_pr_filer",         "pr_filed_by_id",              "users",       "public_id"),
    ("requisitions",   "fk_req_assignee",         "service_assigned_to_id",      "users",       "public_id"),
    ("approval_steps", "fk_steps_approver",       "approver_id",                 "users",       "public_id"),
    ("approval_steps", "fk_steps_actor",          "acted_by_id",                 "users",       "public_id"),
    ("approval_steps", "fk_steps_department",     "department_id",               "departments", "public_id"),
]


def _existing(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE constraint_schema = DATABASE() AND constraint_type = 'FOREIGN KEY'")
        return {r[0] for r in cur.fetchall()}


def check(conn, sample: int = 10) -> Dict:
    """Every value that points at a user / department that does not exist."""
    problems: List[dict] = []
    with conn.cursor() as cur:
        for table, name, col, parent, pcol in FOREIGN_KEYS:
            cur.execute(f"SELECT c.`{col}`, COUNT(*) FROM `{table}` c LEFT JOIN `{parent}` p ON p.`{pcol}` = c.`{col}` "
                        f"WHERE c.`{col}` IS NOT NULL AND p.`{pcol}` IS NULL GROUP BY c.`{col}` ORDER BY COUNT(*) DESC LIMIT {int(sample)}")
            rows = cur.fetchall()
            if rows:
                cur.execute(f"SELECT COUNT(*) FROM `{table}` c LEFT JOIN `{parent}` p ON p.`{pcol}` = c.`{col}` "
                            f"WHERE c.`{col}` IS NOT NULL AND p.`{pcol}` IS NULL")
                problems.append({"constraint": name, "table": table, "column": col, "points_at": parent,
                                 "rows_affected": cur.fetchone()[0], "missing_values_sample": [{"value": v, "rows": n} for v, n in rows]})
    return {"orphans": problems, "clean": not problems, "constraints_present": sorted(_existing(conn) & {k[1] for k in FOREIGN_KEYS})}


def add(conn) -> Dict:
    rep = check(conn)
    if not rep["clean"]:
        rep["added"] = []
        rep["refused"] = "some values point at users/departments that do not exist - fix or clear them, then run again"
        return rep
    have = _existing(conn)
    added = []
    with conn.cursor() as cur:
        for table, name, col, parent, pcol in FOREIGN_KEYS:
            if name in have:
                continue
            cur.execute(f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` FOREIGN KEY (`{col}`) REFERENCES `{parent}` (`{pcol}`) "
                        "ON DELETE RESTRICT ON UPDATE RESTRICT")
            added.append(name)
    conn.commit()
    rep["added"] = added
    rep["constraints_present"] = sorted(_existing(conn) & {k[1] for k in FOREIGN_KEYS})
    return rep


def drop(conn) -> Dict:
    have = _existing(conn)
    dropped = []
    with conn.cursor() as cur:
        for table, name, *_ in reversed(FOREIGN_KEYS):
            if name in have:
                cur.execute(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{name}`")
                dropped.append(name)
    conn.commit()
    return {"dropped": dropped}
