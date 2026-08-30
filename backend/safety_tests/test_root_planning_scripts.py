"""Static + subprocess proofs for the four root executable planning scripts.

For each of:
    tests/test_planning.py
    tests/test_planning_approval.py
    tests/test_planning_direct.py
    tests/test_planning_flow.py

we assert BOTH:

1.  **Static ordering.** The line that imports the shared validator
    and the line that calls it (`validate(os.environ)`) appear before
    any of the forbidden client imports / constructors in the file
    (`motor`, `AsyncIOMotorClient`, `httpx`, `requests`). This proves
    the guard is textually first.

2.  **Runtime guard.** Executing the script with a deliberately bad
    environment (no HYMN_RUNTIME_MODE) exits with a
    ``[hymn-test-guard]`` message and does NOT reach any client
    construction. We use ``env -i`` semantics via ``env={...}`` on the
    subprocess so nothing leaks from the parent shell.

The subprocesses are network-free by construction: the very first thing
the target script does is call the pure validator on ``os.environ``.
When the environment is bad, ``SystemExit`` fires before ``motor`` or
``httpx`` is even imported.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path("/app")
_TARGETS = [
    _REPO_ROOT / "tests" / "test_planning.py",
    _REPO_ROOT / "tests" / "test_planning_approval.py",
    _REPO_ROOT / "tests" / "test_planning_direct.py",
    _REPO_ROOT / "tests" / "test_planning_flow.py",
]

_CLIENT_TOKENS = (
    "AsyncIOMotorClient(",
    "motor.motor_asyncio",
    "import httpx",
    "httpx.AsyncClient",
    "httpx.Client",
    "import requests",
    "requests.get(",
    "requests.post(",
)


def _first_index(text: str, token: str) -> int:
    idx = text.find(token)
    return idx if idx >= 0 else 10**9


# ---------------------------------------------------------------------------
# 1. Static ordering
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_target_imports_shared_validator(path: Path):
    text = path.read_text(encoding="utf-8")
    assert "from test_environment import" in text, (
        f"{path} must import the shared validator from test_environment."
    )
    assert "validate(os.environ)" in text, (
        f"{path} must call validate(os.environ) to run the guard."
    )


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_target_calls_validator_before_any_client(path: Path):
    text = path.read_text(encoding="utf-8")
    validator_call_idx = _first_index(text, "validate(os.environ)")
    assert validator_call_idx < 10**9, f"validate(os.environ) not found in {path}"
    for token in _CLIENT_TOKENS:
        client_idx = _first_index(text, token)
        if client_idx == 10**9:
            continue  # token absent — nothing to order
        assert validator_call_idx < client_idx, (
            f"{path}: shared validator must run before {token!r} "
            f"(validator@{validator_call_idx}, client@{client_idx})."
        )


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_target_does_not_load_dotenv(path: Path):
    text = path.read_text(encoding="utf-8")
    # Match the CALL specifically, not incidental mentions in comments.
    assert "load_dotenv(" not in text, (
        f"{path} must not call load_dotenv() — the runner exports env vars."
    )
    assert "from dotenv" not in text, (
        f"{path} must not import from dotenv."
    )


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_target_has_no_hardcoded_backend_url(path: Path):
    text = path.read_text(encoding="utf-8")
    # BASE constants should be derived from the validated ValidatedTestEnv.
    hardcoded = re.findall(r"BASE\s*=\s*\"http[s]?://localhost:\d+", text)
    assert not hardcoded, (
        f"{path}: found hard-coded BASE URL {hardcoded!r}; must use "
        "the validated backend_url from the shared validator."
    )


# ---------------------------------------------------------------------------
# 2. Runtime guard proof
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_target_refuses_bad_environment(path: Path):
    """Running the script with an empty env must exit non-zero with the
    guard's tag and must NOT construct any client along the way."""
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(_REPO_ROOT),
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, (
        f"{path.name} should have refused an empty environment; "
        f"combined output:\n{combined}"
    )
    assert "hymn-test-guard" in combined, (
        f"{path.name} did not surface the guard tag. Output:\n{combined}"
    )


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_target_refuses_public_backend_url(path: Path):
    """Public preview URL must be rejected even when other vars are correct."""
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(_REPO_ROOT),
        env={
            "PATH": os.environ.get("PATH", ""),
            "HYMN_RUNTIME_MODE": "test",
            "DB_NAME": "hymn_test",
            "MONGO_URL": "mongodb://127.0.0.1:27017",
            "EXPO_PUBLIC_BACKEND_URL": "https://personal-os-app-8.preview.emergentagent.com",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, (
        f"{path.name} should have refused a public preview URL; "
        f"combined output:\n{combined}"
    )
    assert "hymn-test-guard" in combined
