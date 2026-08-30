"""Network-free unit tests for the shared test-environment validator.

Exercises `backend/test_environment.py::validate` directly with an
in-memory mapping. No pytest, dotenv, Mongo, HTTP client, or filesystem
I/O is ever touched by the validator itself, and this suite mirrors
that: every test constructs its own dict and asserts on the pure result
or the ``TestEnvironmentError`` raised.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture()
def te():
    """Fresh import of test_environment for hermeticity."""
    if "test_environment" in sys.modules:
        return importlib.reload(sys.modules["test_environment"])
    return importlib.import_module("test_environment")


# ---------------------------------------------------------------------------
# Base helper — a fully valid environment. Individual tests mutate a copy.
# ---------------------------------------------------------------------------
def _valid() -> dict:
    return {
        "HYMN_RUNTIME_MODE": "test",
        "DB_NAME": "hymn_test",
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "EXPO_PUBLIC_BACKEND_URL": "http://localhost:8001",
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_valid_environment_returns_canonical_values(te):
    result = te.validate(_valid())
    assert result.runtime_mode == "test"
    assert result.db_name == "hymn_test"
    assert result.mongo_url == "mongodb://127.0.0.1:27017"
    assert result.backend_url == "http://localhost:8001"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_loopback_hosts_are_accepted(te, host):
    env = _valid()
    env["MONGO_URL"] = f"mongodb://{host}:27017"
    env["EXPO_PUBLIC_BACKEND_URL"] = f"http://{host}:8001"
    result = te.validate(env)
    assert result.mongo_url.endswith(f"{host}:27017")


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_backend_scheme_variants_are_accepted(te, scheme):
    env = _valid()
    env["EXPO_PUBLIC_BACKEND_URL"] = f"{scheme}://localhost:8001"
    result = te.validate(env)
    assert result.backend_url.startswith(f"{scheme}://")


def test_backend_url_trailing_slash_is_normalised(te):
    env = _valid()
    env["EXPO_PUBLIC_BACKEND_URL"] = "http://localhost:8001/"
    result = te.validate(env)
    assert result.backend_url == "http://localhost:8001"


# ---------------------------------------------------------------------------
# Runtime mode rejections
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["preview", "production", "staging", "dev"])
def test_non_test_modes_are_rejected(te, mode):
    env = _valid(); env["HYMN_RUNTIME_MODE"] = mode
    with pytest.raises(te.TestEnvironmentError, match="HYMN_RUNTIME_MODE"):
        te.validate(env)


@pytest.mark.parametrize("missing_key", ["HYMN_RUNTIME_MODE", "DB_NAME", "MONGO_URL", "EXPO_PUBLIC_BACKEND_URL"])
def test_missing_required_keys_are_rejected(te, missing_key):
    env = _valid(); env.pop(missing_key)
    with pytest.raises(te.TestEnvironmentError, match=missing_key):
        te.validate(env)


@pytest.mark.parametrize("missing_key", ["HYMN_RUNTIME_MODE", "DB_NAME", "MONGO_URL", "EXPO_PUBLIC_BACKEND_URL"])
def test_blank_required_keys_are_rejected(te, missing_key):
    env = _valid(); env[missing_key] = "   "
    with pytest.raises(te.TestEnvironmentError, match=missing_key):
        te.validate(env)


# ---------------------------------------------------------------------------
# Database name rejection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_db", ["hymn", "test_database", "hymn_test_db", "prod", "hymn_prod"])
def test_alternate_database_names_are_rejected(te, bad_db):
    env = _valid(); env["DB_NAME"] = bad_db
    with pytest.raises(te.TestEnvironmentError, match="DB_NAME"):
        te.validate(env)


# ---------------------------------------------------------------------------
# MongoDB URL rejections
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_url", [
    "mongodb+srv://cluster0.abcd.mongodb.net",           # Atlas SRV
    "mongodb+srv://user:pass@cluster.mongodb.net",       # authenticated Atlas
])
def test_mongo_atlas_srv_urls_are_rejected(te, bad_url):
    env = _valid(); env["MONGO_URL"] = bad_url
    with pytest.raises(te.TestEnvironmentError, match="scheme"):
        te.validate(env)


@pytest.mark.parametrize("bad_url", [
    "mongodb://mongo.internal:27017",
    "mongodb://db.example.com:27017",
    "mongodb://cluster0.mongodb.net",
])
def test_remote_mongo_hostnames_are_rejected(te, bad_url):
    env = _valid(); env["MONGO_URL"] = bad_url
    with pytest.raises(te.TestEnvironmentError, match="MONGO_URL"):
        te.validate(env)


@pytest.mark.parametrize("private_url", [
    "mongodb://10.0.0.5:27017",
    "mongodb://192.168.1.10:27017",
    "mongodb://172.16.0.5:27017",
    "mongodb://172.20.10.5:27017",
    "mongodb://169.254.169.254:27017",  # AWS metadata service — never touch
])
def test_private_ip_mongo_hosts_are_rejected(te, private_url):
    env = _valid(); env["MONGO_URL"] = private_url
    with pytest.raises(te.TestEnvironmentError, match="private-network"):
        te.validate(env)


def test_mongo_zero_host_is_rejected(te):
    env = _valid(); env["MONGO_URL"] = "mongodb://0.0.0.0:27017"
    with pytest.raises(te.TestEnvironmentError):
        te.validate(env)


@pytest.mark.parametrize("lookalike", [
    "mongodb://localhost.localdomain:27017",
    "mongodb://loca1host:27017",       # "loca1host" — number 1 instead of L
    "mongodb://127.0.0.2:27017",       # loopback range but not the exact host
])
def test_lookalike_hostnames_are_rejected(te, lookalike):
    env = _valid(); env["MONGO_URL"] = lookalike
    with pytest.raises(te.TestEnvironmentError):
        te.validate(env)


# ---------------------------------------------------------------------------
# Backend URL rejections
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("public_url", [
    "https://personal-os-app-8.preview.emergentagent.com",
    "https://api.hymn.app",
    "https://example.com",
])
def test_public_backend_urls_are_rejected(te, public_url):
    env = _valid(); env["EXPO_PUBLIC_BACKEND_URL"] = public_url
    with pytest.raises(te.TestEnvironmentError, match="EXPO_PUBLIC_BACKEND_URL"):
        te.validate(env)


@pytest.mark.parametrize("bad_url", [
    "http://0.0.0.0:8001",
    "http://10.0.0.5:8001",
    "http://192.168.1.100:8001",
])
def test_zero_and_private_backend_hosts_are_rejected(te, bad_url):
    env = _valid(); env["EXPO_PUBLIC_BACKEND_URL"] = bad_url
    with pytest.raises(te.TestEnvironmentError):
        te.validate(env)


def test_bad_scheme_backend_url_is_rejected(te):
    env = _valid(); env["EXPO_PUBLIC_BACKEND_URL"] = "ftp://localhost:8001"
    with pytest.raises(te.TestEnvironmentError, match="scheme"):
        te.validate(env)


# ---------------------------------------------------------------------------
# Purity assertions — the module must not import forbidden clients.
# ---------------------------------------------------------------------------
def test_test_environment_module_has_no_forbidden_imports():
    text = (_BACKEND_DIR / "test_environment.py").read_text(encoding="utf-8")
    forbidden = (
        "import pytest",
        "from pytest",
        "import dotenv",
        "from dotenv",
        "import motor",
        "from motor",
        "import pymongo",
        "from pymongo",
        "import requests",
        "import httpx",
        "from httpx",
    )
    for token in forbidden:
        assert token not in text, (
            f"test_environment.py must be pure — found forbidden import {token!r}"
        )
