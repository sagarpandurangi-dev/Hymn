"""Pytest configuration.

Ensures the backend .env file is loaded so tests can rely on
``EXPO_PUBLIC_BACKEND_URL``, ``MONGO_URL`` and ``DB_NAME`` regardless of how
pytest was invoked.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env", override=False)

# The public backend URL lives in the frontend .env, not backend/.env.
if "EXPO_PUBLIC_BACKEND_URL" not in os.environ:
    _frontend_env = _BACKEND_DIR.parent / "frontend" / ".env"
    if _frontend_env.exists():
        load_dotenv(_frontend_env, override=False)
