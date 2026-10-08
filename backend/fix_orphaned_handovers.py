"""
One-off repair script for the "Handover confirmed but requisition stuck at
Stock Received in IT" bug (ad-hoc handovers created via the Handover Module
with no requisition_id, so the deliver/confirm flow had nothing to close out).

The code fix (create_handover linking/auto-detecting the requisition) only
prevents this from happening again — it does NOT retroactively fix handovers
that were already created and confirmed before the fix. This script finds and
fixes those.

What it does, for every `handovers` doc with type=="handover", status=="confirmed",
and no valid requisition_id:
  1. Looks for an unambiguous match: a requisition whose requisitioner_name or
     requisition_for equals the handover's employee_name (case-insensitive), with
     status in ("stock_received_in_it", "pending_handover", "awaiting_requester_confirmation"),
     that shares at least one item name with the handover.
  2. If found, sets that requisition's status to "handover_done" and links the
     handover's requisition_id to it. If not found (or ambiguous — more than one
     candidate), it's left alone and printed under "COULD NOT AUTO-FIX" for manual
     review.

Nothing is changed until you confirm — run with --dry-run first (default), then
run again with --apply to actually write the changes.

Usage:
    cd backend
    python3 fix_orphaned_handovers.py            # dry run — prints what it WOULD do
    python3 fix_orphaned_handovers.py --apply     # actually writes the fix
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime, timezone

OPEN_STATUSES = ["stock_received_in_it", "pending_handover", "awaiting_requester_confirmation"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main():
    apply_changes = "--apply" in sys.argv

    mongo_url = os.environ["MONGO_URL"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ["DB_NAME"]]

    orphans = await db.handovers.find({
        "type": "handover",
        "status": "confirmed",
        "$or": [{"requisition_id": None}, {"requisition_id": {"$exists": False}}],
    }).to_list(1000)

    if not orphans:
        print("No orphaned confirmed handovers found. Nothing to do.")
        return

    print(f"Found {len(orphans)} confirmed handover(s) with no requisition link.\n")

    fixed, skipped = 0, 0
    for h in orphans:
        emp = (h.get("employee_name") or "").strip()
        item_names = {(it.get("item") or "").strip().lower() for it in h.get("items", [])}
        item_names.discard("")

        candidates = await db.requisitions.find({
            "status": {"$in": OPEN_STATUSES},
            "$or": [
                {"requisitioner_name": {"$regex": f"^{emp}$", "$options": "i"}},
                {"requisition_for": {"$regex": f"^{emp}$", "$options": "i"}},
            ],
        }).to_list(20) if emp else []

        matches = [
            c for c in candidates
            if any((it.get("product_name") or "").strip().lower() in item_names for it in c.get("items", []))
        ]

        print(f"Slip {h['slip_no']}  |  employee: {emp!r}  |  items: {sorted(item_names)}")
        if len(matches) == 1:
            req = matches[0]
            print(f"  -> MATCH: {req['requisition_no']} (currently '{req['status']}')"
                  f"{'  [WOULD FIX]' if not apply_changes else '  [FIXING]'}")
            if apply_changes:
                req.setdefault("history", []).append({
                    "at": now_iso(), "by": "system (fix_orphaned_handovers.py)",
                    "action": "receipt_confirmed",
                    "note": f"Repaired: handover slip {h['slip_no']} was already delivered and "
                             "confirmed, but wasn't linked to this requisition at the time.",
                })
                await db.requisitions.update_one({"_id": req["_id"]}, {"$set": {
                    "status": "handover_done", "history": req["history"],
                    "closed_at": now_iso(), "updated_at": now_iso(),
                }})
                await db.handovers.update_one({"_id": h["_id"]}, {"$set": {
                    "requisition_id": str(req["_id"]),
                }})
            fixed += 1
        elif len(matches) > 1:
            print(f"  -> AMBIGUOUS ({len(matches)} candidates) — COULD NOT AUTO-FIX, review manually:")
            for c in matches:
                print(f"       {c['requisition_no']} ({c['status']})")
            skipped += 1
        else:
            print("  -> No matching open requisition found — COULD NOT AUTO-FIX (may not need one).")
            skipped += 1
        print()

    print(f"Done. {fixed} fixed{' (applied)' if apply_changes else ' (dry run — nothing written)'}, {skipped} need manual review.")
    if not apply_changes and fixed:
        print("\nRe-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(main())
