"""Pytest configuration.

Ensures the backend .env file is loaded so tests can rely on
``EXPO_PUBLIC_BACKEND_URL``, ``MONGO_URL`` and ``DB_NAME`` regardless of how
pytest was invoked.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env", override=False)

# The public backend URL lives in the frontend .env, not backend/.env.
if "EXPO_PUBLIC_BACKEND_URL" not in os.environ:
    _frontend_env = _BACKEND_DIR.parent / "frontend" / ".env"
    if _frontend_env.exists():
        load_dotenv(_frontend_env, override=False)


def _require_local_test_configuration() -> None:
    required = ("EXPO_PUBLIC_BACKEND_URL", "MONGO_URL", "DB_NAME", "HYMN_RUNTIME_MODE")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Local tests require explicit configuration for: " + ", ".join(missing)
        )

    backend = urlparse(os.environ["EXPO_PUBLIC_BACKEND_URL"])
    mongo = urlparse(os.environ["MONGO_URL"])
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if backend.scheme != "http" or backend.hostname not in local_hosts:
        raise RuntimeError("Tests refuse non-local EXPO_PUBLIC_BACKEND_URL")
    if mongo.hostname not in local_hosts:
        raise RuntimeError("Tests refuse non-local MONGO_URL")
    if os.environ["DB_NAME"] != "hymn_test":
        raise RuntimeError("Tests require DB_NAME=hymn_test")
    if os.environ["HYMN_RUNTIME_MODE"] != "test":
        raise RuntimeError("Tests require HYMN_RUNTIME_MODE=test")


_require_local_test_configuration()
