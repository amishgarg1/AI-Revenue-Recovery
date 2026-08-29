"""
RecoverOS.

Importing anything under `app` loads `.env` from the repository root first, so
every entry point behaves the same: uvicorn, the CLI scripts, and the test
suite all see the same configuration.

This exists because `.env.example` told people to copy it to `.env` and fill it
in, and nothing read the file. Keys were accepted, ignored, and the run
silently stayed on fallbacks — no error, no warning, just three integrations
that quietly did not happen.
"""

import os
from pathlib import Path

# backend/app/__init__.py -> backend/app -> backend -> repo root
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_env(path: Path) -> None:
    """
    Minimal .env reader.

    Deliberately does not override variables that are already set. On Render
    and Vercel the platform supplies the environment, and a stale committed
    file must never win over it.
    """
    if not path.is_file():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Strip one layer of matching quotes, the way a shell would.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        if key and key not in os.environ:
            os.environ[key] = value


_load_env(_ENV_FILE)
