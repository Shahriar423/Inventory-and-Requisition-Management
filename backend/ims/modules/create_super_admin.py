"""First-run script: creates the base departments and the first Super Admin in the MySQL database named in backend/.env.
A brand-new database has no users, so nobody could sign in until this has been run once. Safe to run again.

    python create_super_admin.py
Reads ADMIN_NAME, ADMIN_EMAIL and ADMIN_PASSWORD from backend/.env, or asks for any that are missing.
"""
import asyncio
import getpass
import os
import sys

from ims import database  # noqa: F401  (loads backend/.env)

# (name, type). The app finds departments by TYPE, so they can be renamed later on the Departments screen.
BASE_DEPARTMENTS = [("IT", "it"), ("Purchase", "purchase"), ("Accounts", "accounts"), ("Admin", "admin"), ("Primitek Group", "head_company")]


def _ask(name: str, prompt: str, secret: bool = False) -> str:
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    return (getpass.getpass(prompt) if secret else input(prompt)).strip()


async def main() -> None:
    from ims.common import MIN_PASSWORD_LENGTH, ROLE_LABELS, hash_password, now_iso
    from ims.repositories import departments as dept_repo
    from ims.repositories import users as users_repo

    await dept_repo.startup_check()
    await users_repo.startup_check()

    dept_ids = {}
    for name, kind in BASE_DEPARTMENTS:
        d = await dept_repo.get_by_name(name)
        if d:
            dept_ids[name] = str(d["_id"])
            print(f"department exists : {name}")
        else:
            dept_ids[name] = str(await dept_repo.insert({"name": name, "dept_type": kind, "created_at": now_iso()}))
            print(f"department created: {name}")

    email = _ask("ADMIN_EMAIL", "Super Admin email: ").lower()
    if not email or "@" not in email:
        sys.exit("A valid email is required")
    if await users_repo.get_by_email(email):
        print(f"user {email} already exists - nothing to do")
    else:
        name = _ask("ADMIN_NAME", "Super Admin name: ") or "Super Admin"
        password = _ask("ADMIN_PASSWORD", "Super Admin password: ", secret=True)
        if len(password) < MIN_PASSWORD_LENGTH:
            sys.exit(f"The password must be at least {MIN_PASSWORD_LENGTH} characters")
        await users_repo.insert({
            "name": name, "email": email, "password_hash": hash_password(password),
            "department_id": dept_ids["Primitek Group"], "role": "super_admin", "role_label": ROLE_LABELS["super_admin"],
            "can_raise_pr": False, "can_create_po": False, "it_team": None, "created_at": now_iso()})
        print(f"Super Admin created: {email}")
    await users_repo.close()


if __name__ == "__main__":
    asyncio.run(main())
