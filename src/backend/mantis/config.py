"""Environment and filesystem locations shared by every backend module.

Settings come from the process environment first, then from the ``.env`` file at
the repository root. Values already set in the process are never overwritten.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]

# The compiler and base SQL schemas are shared with the rest of the repository.
COMPILER_ROOT = REPO_ROOT / "dev" / "software" / "compiler"
DATABASE_SQL_DIR = REPO_ROOT / "dev" / "software" / "database" / "sql"

_env_loaded = False


def load_env(path: Path | None = None) -> None:
    """Load the repo-root ``.env`` once per process (or ``path`` when given)."""
    global _env_loaded
    if path is not None:
        load_dotenv(path)
        return
    if not _env_loaded:
        load_dotenv(REPO_ROOT / ".env")
        _env_loaded = True


def env(name: str, default: str = "") -> str:
    """A stripped environment value, or ``default`` when unset or blank."""
    load_env()
    value = (os.environ.get(name) or "").strip()
    return value or default


def env_port(name: str, default: int) -> int:
    """A TCP port from the environment. Blank uses ``default``; anything else must be 1-65535."""
    raw = env(name)
    if not raw:
        return default
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise ValueError(f"{name} must be an integer from 1 to 65535, got {raw!r}")
    return int(raw)
