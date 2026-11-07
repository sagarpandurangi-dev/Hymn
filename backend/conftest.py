"""Pytest configuration — strict test-mode guard.

Delegates validation to the pure :mod:`test_environment` module. The
guard runs at ``pytest_configure`` time so no test module can create
a user, record, HTTP client, or database connection before the checks
have passed.

This file deliberately:
  * Does NOT call ``load_dotenv`` — the runner must export the
    required variables. Reading ``backend/.env`` here would allow a
    developer's local defaults to silently satisfy the guard.
  * Does NOT read ``frontend/.env`` — the backend URL must be supplied
    directly by the test runner.
  * Does NOT construct any Mongo / HTTP client at import time.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

# Make the pure validator importable when pytest is invoked from the
# repo root. The module lives in backend/ next to this file.
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from test_environment import TestEnvironmentError, validate  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """Fail collection when the environment is not test-safe."""
    try:
        validate(os.environ)
    except TestEnvironmentError as exc:
        raise pytest.UsageError(f"[hymn-test-guard] {exc}") from exc


__all__ = ["pytest_configure"]
