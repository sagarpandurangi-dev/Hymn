"""Network-free safety tests for the runtime module.

These tests exercise the pure helpers in `backend/runtime.py`:

  * Invalid runtime mode is rejected at read time.
  * Preview mode without JWT_SECRET is rejected.
  * Production mode without JWT_SECRET is rejected.
  * Test mode receives the deterministic test-only secret when
    JWT_SECRET is not set — and only in test mode.
  * The test-only constant is refused if it appears in preview /
    production env.

The suite MUST NOT import server.py, connect to MongoDB, open sockets,
or reach any external service. It has its own conftest sentinel to
prove the point.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Ensure `backend/` is on sys.path so we can `import runtime` without
# triggering the integration-test conftest guard (which lives one level up).
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every variable the runtime module reads."""
    for key in ("HYMN_RUNTIME_MODE", "JWT_SECRET"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def runtime(clean_env):  # noqa: ARG001 — clean_env is a setup fixture
    """Fresh import so `runtime` reads the current environment."""
    if "runtime" in sys.modules:
        return importlib.reload(sys.modules["runtime"])
    return importlib.import_module("runtime")


# ---------------------------------------------------------------------------
# Runtime mode
# ---------------------------------------------------------------------------
def test_absent_mode_defaults_to_preview(runtime):
    """Backward compatibility: unset variable → preview."""
    assert runtime.get_runtime_mode() == "preview"
    assert runtime.is_preview() is True
    assert runtime.is_test() is False
    assert runtime.is_production() is False


@pytest.mark.parametrize("mode", ["preview", "production", "test"])
def test_valid_modes_are_accepted(runtime, monkeypatch, mode):
    monkeypatch.setenv("HYMN_RUNTIME_MODE", mode)
    assert runtime.get_runtime_mode() == mode


@pytest.mark.parametrize("bogus", ["staging", "dev", "PROD ", "developpment"])
def test_invalid_mode_is_rejected(runtime, monkeypatch, bogus):
    """Any recognisable-but-unsupported value fails loudly."""
    monkeypatch.setenv("HYMN_RUNTIME_MODE", bogus)
    with pytest.raises(RuntimeError) as exc:
        runtime.get_runtime_mode()
    assert "HYMN_RUNTIME_MODE" in str(exc.value)


@pytest.mark.parametrize("blank_ish", ["", "  ", "\n"])
def test_blank_mode_falls_back_to_preview(runtime, monkeypatch, blank_ish):
    """Whitespace-only value keeps the backward-compat fallback."""
    monkeypatch.setenv("HYMN_RUNTIME_MODE", blank_ish)
    assert runtime.get_runtime_mode() == "preview"


# ---------------------------------------------------------------------------
# JWT secret policy
# ---------------------------------------------------------------------------
def test_preview_without_jwt_secret_is_rejected(runtime, monkeypatch):
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "preview")
    with pytest.raises(RuntimeError) as exc:
        runtime.get_jwt_secret()
    msg = str(exc.value)
    assert "JWT_SECRET" in msg
    # The secret value must never appear in the error message.
    assert "hymn-test-only" not in msg


def test_production_without_jwt_secret_is_rejected(runtime, monkeypatch):
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "production")
    with pytest.raises(RuntimeError) as exc:
        runtime.get_jwt_secret()
    assert "JWT_SECRET" in str(exc.value)


def test_test_mode_returns_deterministic_secret(runtime, monkeypatch):
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "test")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    secret = runtime.get_jwt_secret()
    assert isinstance(secret, str) and len(secret) > 0
    # Test-only secret must be an obvious sentinel, never something an
    # operator could confuse with a real secret.
    assert "test-only" in secret


def test_test_mode_prefers_explicit_secret(runtime, monkeypatch):
    """When JWT_SECRET is set in test mode, use it verbatim."""
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "test")
    monkeypatch.setenv("JWT_SECRET", "explicit-test-secret")
    assert runtime.get_jwt_secret() == "explicit-test-secret"


def test_test_only_constant_is_refused_in_preview(runtime, monkeypatch):
    """Copy-pasting the sentinel into a non-test env must fail."""
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "preview")
    monkeypatch.setenv("JWT_SECRET", runtime._TEST_ONLY_JWT_SECRET)  # noqa: SLF001
    with pytest.raises(RuntimeError) as exc:
        runtime.get_jwt_secret()
    assert "preview" in str(exc.value).lower()


def test_test_only_constant_is_refused_in_production(runtime, monkeypatch):
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "production")
    monkeypatch.setenv("JWT_SECRET", runtime._TEST_ONLY_JWT_SECRET)  # noqa: SLF001
    with pytest.raises(RuntimeError):
        runtime.get_jwt_secret()


def test_valid_secret_in_production_is_accepted(runtime, monkeypatch):
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "production")
    monkeypatch.setenv("JWT_SECRET", "a-real-long-random-string")
    assert runtime.get_jwt_secret() == "a-real-long-random-string"
