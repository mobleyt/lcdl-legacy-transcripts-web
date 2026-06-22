"""Runtime configuration, read from environment variables.

All secrets (Aviary API key, the shared admin password, the cookie signing
secret) come from the environment so they never live in the codebase or in the
browser. See ``.env.example`` for the full list.
"""

import os
import secrets
from pathlib import Path

# Project root (one level up from this package).
BASE_DIR = Path(__file__).resolve().parent.parent

# Where per-job working directories and output zips are written.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
JOBS_DIR = DATA_DIR / "jobs"

# Aviary API key used for every request. Users never see or enter this.
AVIARY_API_KEY = os.getenv("AVIARY_API_KEY", "")

# Single shared password gating the whole app. If empty, the app refuses to
# start (fail closed) unless ALLOW_NO_AUTH is set.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").lower() in ("1", "true", "yes")

# Secret used to sign the session cookie. Generated per-process if unset, which
# means restarts invalidate sessions — fine for a small internal tool, but set
# it explicitly in production so logins survive restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)

# Cap on uploaded CSV size (bytes) to avoid accidental huge uploads.
MAX_CSV_BYTES = int(os.getenv("MAX_CSV_BYTES", str(10 * 1024 * 1024)))


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
