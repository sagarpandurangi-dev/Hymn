"""Network-free safety tests for the integration-test guard.

The guard lives in `backend/conftest.py`. Because it runs at
`pytest_configure` time we can't unit-test it by simply importing the
module — instead we shell out to `pytest --collect-only` in a subprocess
with a controlled environment, and assert on the exit code + stderr.

CRITICAL: These tests must never construct a MongoDB client, an HTTP
client, or reach any external host. `--collect-only` guarantees that no
test bodies run; the guard fires strictly earlier than any user or
record creation.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = Path(__file__).resolve().parents[1]

# We run the guard against a *fake* test file so pytest has something to
# discover. Using --collect-only means the file body is never executed,
# but conftest.py fires regardless — which is exactly what we want.
_FAKE_TEST = textwrap.dedent(
    """
    def test_placeholder():
        assert True
    """
).strip()


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A directory containing conftest.py copied verbatim + one fake test."""
    (tmp_path / "conftest.py").write_bytes((_BACKEND_DIR / "conftest.py").read_bytes())
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fake.py").write_text(_FAKE_TEST, encoding="utf-8")
    return tmp_path


def _run(sandbox_dir: Path, env: dict) -> subprocess.CompletedProcess:
    """Run `pytest --collect-only` in the sandbox with the given env.

    The child process inherits nothing from the parent's environment,
    so a leaky HYMN_RUNTIME_MODE from the host cannot mask a bug.
    """
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        cwd=str(sandbox_dir),
        env={"PATH": os.environ.get("PATH", ""), **env},
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )


def _rejection(res: subprocess.CompletedProcess) -> str:
    return (res.stderr or "") + (res.stdout or "")


# ---------------------------------------------------------------------------
# Rejection cases — every one must fail collection with a hymn-test-guard
# message and no test body execution.
# ---------------------------------------------------------------------------
def test_missing_all_env_is_rejected(sandbox):
    res = _run(sandbox, {})
    assert res.returncode != 0
    assert "hymn-test-guard" in _rejection(res)


def test_missing_mode_is_rejected(sandbox):
    res = _run(sandbox, {
        "DB_NAME": "hymn_test",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "EXPO_PUBLIC_BACKEND_URL": "http://localhost:8001",
    })
    assert res.returncode != 0
    assert "HYMN_RUNTIME_MODE" in _rejection(res)


def test_wrong_db_name_is_rejected(sandbox):
    res = _run(sandbox, {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "production_db",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "EXPO_PUBLIC_BACKEND_URL": "http://localhost:8001",
    })
    assert res.returncode != 0
    assert "DB_NAME" in _rejection(res)


def test_missing_mongo_url_is_rejected(sandbox):
    res = _run(sandbox, {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "hymn_test",
        "EXPO_PUBLIC_BACKEND_URL": "http://localhost:8001",
    })
    assert res.returncode != 0
    assert "MONGO_URL" in _rejection(res)


def test_public_preview_backend_url_is_rejected(sandbox):
    res = _run(sandbox, {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "hymn_test",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "EXPO_PUBLIC_BACKEND_URL": "https://personal-os-app-8.preview.emergentagent.com",
    })
    assert res.returncode != 0
    out = _rejection(res)
    assert "loopback" in out.lower() or "public" in out.lower()


@pytest.mark.parametrize("bad", [
    "https://example.com",
    "https://api.hymn.app",
    "http://10.0.0.5:8001",
    "http://0.0.0.0:8001",
    "http://*.local:8001",
])
def test_any_non_loopback_url_is_rejected(sandbox, bad):
    res = _run(sandbox, {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "hymn_test",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "EXPO_PUBLIC_BACKEND_URL": bad,
    })
    assert res.returncode != 0, f"guard should have rejected {bad!r}"


def test_missing_backend_url_is_rejected(sandbox):
    res = _run(sandbox, {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "hymn_test",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
    })
    assert res.returncode != 0
    assert "EXPO_PUBLIC_BACKEND_URL" in _rejection(res)


# ---------------------------------------------------------------------------
# Acceptance cases
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_loopback_urls_are_accepted(sandbox, host):
    res = _run(sandbox, {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "hymn_test",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "EXPO_PUBLIC_BACKEND_URL": f"http://{host}:8001",
    })
    assert res.returncode == 0, (
        f"guard should have accepted {host!r}; got:\n{_rejection(res)}"
    )


# ---------------------------------------------------------------------------
# Static evidence: no HTTP/DB client is constructed in conftest.py.
# The guard's job is to fail *before* anything is built. This test is a
# lint-style check on the source itself so future edits can't quietly
# introduce a Motor client or an httpx.Client at import time.
# ---------------------------------------------------------------------------
def test_conftest_does_not_construct_clients():
    text = (_BACKEND_DIR / "conftest.py").read_text(encoding="utf-8")
    forbidden = (
        "AsyncIOMotorClient",
        "MongoClient",
        "httpx.Client",
        "httpx.AsyncClient",
        "requests.get(",
        "requests.post(",
    )
    for token in forbidden:
        assert token not in text, (
            f"conftest.py must not construct a client at import time "
            f"(found {token!r})."
        )
