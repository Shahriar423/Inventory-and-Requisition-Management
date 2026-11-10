"""Environment loading. All application data lives in MySQL (see ims/repositories/mysql/engine.py for MYSQL_URL)."""
from dotenv import load_dotenv
from pathlib import Path
import os
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent  # the backend/ folder

load_dotenv(ROOT_DIR / ".env")


def _env(*names: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    for n in names:
        v = os.environ.get(n)
        if v is not None and v.strip() != "":
            return v.strip()
    if required:
        raise RuntimeError(f"Missing required environment variable: {' or '.join(names)} (set it in backend/.env)")
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise RuntimeError(f"Environment variable {name} must be a whole number")
