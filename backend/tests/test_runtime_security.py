"""Focused runtime configuration hardening tests."""

import pytest

import server


def test_production_requires_explicit_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET is required"):
        server._resolve_jwt_secret("production", None)


def test_local_requires_explicit_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET is required"):
        server._resolve_jwt_secret("local", "")


def test_test_mode_has_isolated_deterministic_secret():
    assert server._resolve_jwt_secret("test", None) == (
        "hymn-foundation-deterministic-test-secret"
    )
    assert server._resolve_jwt_secret("test", "explicit-test-secret") == (
        "explicit-test-secret"
    )


def test_production_requires_explicit_cors_origins():
    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS is required"):
        server._resolve_cors_allowed_origins("production", None)


def test_wildcard_credentialed_cors_is_rejected():
    with pytest.raises(RuntimeError, match="explicit origins"):
        server._resolve_cors_allowed_origins("production", "*")


def test_local_cors_defaults_are_loopback_only():
    origins = server._resolve_cors_allowed_origins("local", None)
    assert origins
    assert all(
        origin.startswith(("http://127.0.0.1:", "http://localhost:"))
        for origin in origins
    )


def test_explicit_cors_origins_are_normalized():
    origins = server._resolve_cors_allowed_origins(
        "production",
        "https://app.hymn.example/,https://admin.hymn.example",
    )
    assert origins == [
        "https://app.hymn.example",
        "https://admin.hymn.example",
    ]
