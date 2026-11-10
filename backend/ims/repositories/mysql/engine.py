"""The async SQLAlchemy engine for the MySQL requisition repository.

Settings (environment / backend/.env):
    MYSQL_URL        mysql://user:password@127.0.0.1:3307/ims        (the "+aiomysql" driver part is added for you)
    MYSQL_POOL_SIZE  connections kept open (default 10)             MYSQL_POOL=null  -> no pooling (used by the tests)
"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

_engine: Optional[AsyncEngine] = None
_engine_url: Optional[str] = None


def async_url(url: str) -> str:
    for prefix in ("mysql+aiomysql://", "mysql+pymysql://", "mysql://"):
        if url.startswith(prefix):
            url = "mysql+aiomysql://" + url[len(prefix):]
            break
    else:
        raise RuntimeError("MYSQL_URL must look like mysql://user:password@host:3306/database")
    return url + ("&" if "?" in url else "?") + "charset=utf8mb4" if "charset=" not in url else url


def get_engine() -> AsyncEngine:
    global _engine, _engine_url
    url = os.environ.get("MYSQL_URL")
    if not url:
        raise RuntimeError("MYSQL_URL is not set - the application needs MYSQL_URL in backend/.env (mysql://user:password@host:3306/database)")
    if _engine is None or _engine_url != url:
        kw = {"poolclass": NullPool} if os.environ.get("MYSQL_POOL", "").lower() == "null" else {
            "pool_size": int(os.environ.get("MYSQL_POOL_SIZE", "10")), "max_overflow": 10, "pool_recycle": 1800}
        _engine = create_async_engine(async_url(url), pool_pre_ping=True, json_serializer=_dumps, **kw)
        _engine_url = url
    return _engine


def _dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


async def ping() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def require_tables(*names: str) -> None:
    """Fail early, with instructions, when MySQL is unreachable or these tables have not been created."""
    import sqlalchemy as sa
    await ping()
    async with get_engine().connect() as conn:
        have = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
    missing = sorted(set(names) - have)
    if missing:
        raise RuntimeError(f"MySQL is reachable but these tables are missing: {missing}. "
                           "Create them with:  python -m migration.mysql.migrate schema")


async def dispose() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def transaction():
    """One write transaction at READ COMMITTED (a locking read then always sees the latest committed data)."""
    async with get_engine().connect() as conn:
        await conn.execution_options(isolation_level="READ COMMITTED")
        async with conn.begin():
            yield conn
