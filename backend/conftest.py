"""Pytest configuration — strict test-mode guard.

Refuses to run the integration test suite unless every one of the
following holds *before* any test module is collected:

    HYMN_RUNTIME_MODE=test
    DB_NAME=hymn_test
    MONGO_URL is set (any non-empty string)
    EXPO_PUBLIC_BACKEND_URL is set and its host is loopback
      (exactly "localhost" or "127.0.0.1")

Any deviation raises ``pytest.UsageError`` from :func:`pytest_configure`
so no user, record, HTTP client, or database connection is ever
constructed against the wrong target.

Notes
-----
* This module does NOT read ``frontend/.env`` — the tests must be
  invoked with the correct environment variables already exported.
* Loading ``backend/.env`` is preserved because the local dev
  environment expects it; the guard runs *after* the load so a
  ``.env`` cannot silently satisfy the checks (test-mode explicitly
  requires ``HYMN_RUNTIME_MODE=test`` which the default backend .env
  does not provide).
* No network calls, no HTTP clients, no database connections are made
  in this file.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent

# Load backend/.env non-destructively so pre-existing exports win. This
# is preserved to keep local `pytest` invocations working; the guard
# below still fires when the loaded values are the wrong ones.
load_dotenv(_BACKEND_DIR / ".env", override=False)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}


def _fail(msg: str) -> None:
    """Raise a pytest usage error with a stable, actionable message."""
    raise pytest.UsageError(f"[hymn-test-guard] {msg}")


def _validate_test_environment() -> None:
    """Verify the four required conditions. Fail fast on any violation.

    Called from ``pytest_configure`` so the failure aborts collection
    before any test module runs. Every check emits a distinct message
    so operators know exactly which variable is wrong.
    """
    mode = (os.environ.get("HYMN_RUNTIME_MODE") or "").strip().lower()
    if mode != "test":
        _fail(
            "Integration tests refuse to run unless "
            "HYMN_RUNTIME_MODE=test is set explicitly."
        )

    db_name = (os.environ.get("DB_NAME") or "").strip()
    if db_name != "hymn_test":
        _fail(
            "DB_NAME must be 'hymn_test' when running the integration "
            "suite; refusing to touch a non-test database."
        )

    mongo_url = (os.environ.get("MONGO_URL") or "").strip()
    if not mongo_url:
        _fail("MONGO_URL must be provided explicitly.")

    backend_url = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").strip()
    if not backend_url:
        _fail(
            "EXPO_PUBLIC_BACKEND_URL must be provided explicitly. "
            "Set it to http://localhost:<port> or http://127.0.0.1:<port>."
        )

    parsed = urlparse(backend_url)
    if not parsed.scheme or not parsed.hostname:
        _fail(
            "EXPO_PUBLIC_BACKEND_URL must be a valid URL with a scheme "
            "and hostname."
        )
    if parsed.hostname not in _LOOPBACK_HOSTS:
        _fail(
            "EXPO_PUBLIC_BACKEND_URL must resolve to a loopback host "
            "(localhost or 127.0.0.1). Public / preview / production "
            "URLs are prohibited for the integration suite."
        )


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """Pytest hook — runs before any test module is collected."""
    _validate_test_environment()


__all__ = ["pytest_configure"]
