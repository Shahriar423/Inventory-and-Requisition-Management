"""Application wiring: FastAPI app, CORS, error handlers, startup/shutdown and /api/health."""

import os
import asyncio
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from typing import List
import logging
from fastapi.responses import JSONResponse
from ims.repositories import departments as dept_repo
from ims.repositories import requisitions as req_repo
from ims.repositories import sidebar_permissions as sidebar_repo
from ims.repositories import users as users_repo
from ims.repositories import purchase_orders as po_repo
from ims.repositories import products as prod_repo
from ims.repositories import categories as cat_repo
from ims.repositories import counters as counter_repo
from ims.repositories import files_repo
from ims.repositories import notifications_repo as notif_repo
from ims.repositories import assets as asset_repo
from ims.repositories import handovers as handover_repo
from ims.repositories import correction_cases as case_repo
from ims.repositories import grns as grn_repo
from ims.repositories import asset_history as ah_repo
from ims.repositories import system_settings as settings_repo
from ims.repositories import paper_records as paper_repo
from ims.repositories import saved_reports as saved_reports_repo
from ims.repositories import report_access as report_access_repo
from ims.repositories import import_batches as import_batches_repo
from ims.repositories.mysql.engine import ping as mysql_ping
from ims.common import (
    LOCAL_STORAGE_DIR,
    _JWT_SECRET,
    _WEAK_SECRETS,
    _env,
    _pkey,
    api_router,
    init_storage,
    now_iso,
    run_reminder_sweep,
)

APP_ENV = (_env("APP_ENV", default="development") or "development").lower()

# Importing a module registers its routes on api_router (order = route-matching order).
from ims.modules import auth  # noqa: F401
from ims.modules import settings  # noqa: F401
from ims.modules import users  # noqa: F401
from ims.modules import catalog  # noqa: F401
from ims.modules import requisitions  # noqa: F401
from ims.modules import files  # noqa: F401
from ims.modules import inventory  # noqa: F401
from ims.modules import notifications  # noqa: F401
from ims.modules import purchase_orders  # noqa: F401
from ims.modules import it_service  # noqa: F401
from ims.modules import reports  # noqa: F401
from ims.modules import imports  # noqa: F401
from ims.modules import corrections  # noqa: F401


IS_PROD = APP_ENV == "production"


if len(_JWT_SECRET) < 32 or _JWT_SECRET.lower() in _WEAK_SECRETS:
    if IS_PROD:
        raise RuntimeError("JWT_SECRET must be a random string of at least 32 characters in production "
                           "(generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\")")
    logging.getLogger("ims").warning("JWT_SECRET is short/weak - acceptable for development only")


app = FastAPI(title="IRM - IT Requisition & Asset Management")


logger = logging.getLogger("ims")


async def reminder_loop():
    minutes = max(int(os.environ.get("REMINDER_SWEEP_MINUTES", "15")), 1)
    await asyncio.sleep(30)
    while True:
        try:
            res = await run_reminder_sweep()
            if res["requisitions_reminded"] or res["purchase_orders_reminded"] or any((res.get("corrections") or {}).values()):
                logger.info(f"Reminder sweep: {res}")
        except Exception as e:
            logger.error(f"Reminder sweep failed: {e}")
        await asyncio.sleep(minutes * 60)


PRODUCT_TYPES = ("asset", "consumable", "it_accessories", "network", "furniture")


async def seed_products_if_empty():
    """One-time: build the catalog from names already used by requisitions and stock, so
    nothing existing is left un-pickable. Case variants collapse to one entry."""
    if await prod_repo.list_all(limit=1):
        return
    seen: dict = {}
    for r in await req_repo.list_product_items():
        for it in r.get("items", []):
            k = _pkey(it.get("product_name"))
            if k and k not in seen and it.get("product_type") in PRODUCT_TYPES:
                seen[k] = (" ".join(it["product_name"].split()), it["product_type"])
    for a in await asset_repo.list_all(limit=50000):
        k = _pkey(a.get("name"))
        if k and k not in seen:
            seen[k] = (" ".join(a["name"].split()), "asset")
    for k, (name, ptype) in seen.items():
        await prod_repo.insert({"name": name, "name_key": k, "product_type": ptype,
                                      "created_by": "system", "created_at": now_iso()})


@app.on_event("startup")
async def on_startup():
    for label, repo in (
        ("Requisitions", req_repo),
        ("Users", users_repo),
        ("Departments", dept_repo),
        ("Sidebar permissions", sidebar_repo),
        ("Categories", cat_repo),
        ("Products", prod_repo),
        ("Counters", counter_repo),
        ("Purchase orders", po_repo),
        ("Notifications", notif_repo),
        ("Files", files_repo),
        ("Assets", asset_repo),
        ("Handovers", handover_repo),
        ("Correction cases", case_repo),
        ("GRNs", grn_repo),
        ("Asset history", ah_repo),
        ("System settings", settings_repo),
        ("Paper records", paper_repo),
        ("Saved reports", saved_reports_repo),
        ("Report access", report_access_repo),
        ("Import batches", import_batches_repo),
    ):
        await repo.startup_check()
        logger.info(f"{label}: MySQL table ready")
    try:
        await seed_products_if_empty()
    except Exception as e:
        logger.error(f"Product seed failed: {e}")
    if LOCAL_STORAGE_DIR:
        logger.info(f"File storage: local disk ({LOCAL_STORAGE_DIR})")
    else:
        try:
            await asyncio.to_thread(init_storage)          # blocking HTTP call - keep it off the event loop
            logger.info("Object storage initialized")
        except Exception as e:
            logger.error(f"Storage init failed: {e}")
    app.state.reminder_task = asyncio.create_task(reminder_loop())


@app.on_event("shutdown")
async def on_shutdown():
    for repo in (req_repo, users_repo, dept_repo, sidebar_repo, cat_repo, prod_repo, counter_repo, po_repo, notif_repo, files_repo, asset_repo, handover_repo, case_repo, grn_repo, ah_repo, settings_repo, paper_repo, saved_reports_repo, report_access_repo, import_batches_repo):
        await repo.close()


app.include_router(api_router)


# --- CORS: only the origins listed in CORS_ORIGINS (comma separated), e.g. https://ims.yourcompany.com ---
def _cors_origins() -> List[str]:
    raw = _env("CORS_ORIGINS", "FRONTEND_URL", default="") or ""
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    if any(o == "*" for o in origins):
        raise RuntimeError("CORS_ORIGINS must list explicit origins - a wildcard (*) is not allowed with cookies/credentials")
    if IS_PROD:
        if not origins:
            raise RuntimeError("CORS_ORIGINS is required in production (e.g. https://ims.yourcompany.com)")
        bad = [o for o in origins if not o.startswith("https://")]
        if bad:
            raise RuntimeError(f"Production CORS origins must use https: {bad}")
    elif not origins:
        origins = ["http://localhost:3000"]                       # development convenience only
    return origins


CORS_ALLOWED_ORIGINS = _cors_origins()


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    expose_headers=["X-Total-Count", "Content-Disposition"],
    max_age=600,
)


from sqlalchemy.exc import SQLAlchemyError

@app.exception_handler(SQLAlchemyError)
async def _mysql_error_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"MySQL error on {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please try again in a moment."},
                        headers={"Retry-After": "5"})


@app.get("/api/health")
async def health():
    """Liveness + database check for the load balancer / uptime monitor. No auth, no data."""
    try:
        await asyncio.wait_for(mysql_ping(), timeout=3)
        return {"status": "ok", "database": "up"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "down"})
