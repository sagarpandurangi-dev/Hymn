"""Pure test-environment validator.

Given an explicit environment mapping, verify that every constraint
required to run the integration test suite is satisfied and return
the canonicalised values. Any deviation raises
:class:`TestEnvironmentError`.

Design invariants
-----------------
* No I/O of any kind. No filesystem, no DNS, no sockets.
* No imports of ``pytest``, ``dotenv``, ``motor``, ``pymongo``,
  ``requests``, ``httpx``, or any other HTTP / DB client. Callers wrap
  the raised error into their runner's native failure type (e.g.
  ``pytest.UsageError``).
* The validator reads ONLY the mapping it is given. Ambient
  ``os.environ`` is not consulted here so the module can be unit-
  tested deterministically.
* Rules are additive: every check gets a distinct, actionable error
  message referring to the offending variable name; secrets are never
  echoed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Vocabulary — kept explicit so ``in`` checks are cheap and audit-friendly.
# ---------------------------------------------------------------------------
LOOPBACK_HOSTS: frozenset = frozenset({"localhost", "127.0.0.1"})
BACKEND_SCHEMES: frozenset = frozenset({"http", "https"})
MONGO_SCHEME: str = "mongodb"
REQUIRED_MODE: str = "test"
REQUIRED_DB_NAME: str = "hymn_test"

# Explicit block-list to short-circuit obvious lookalikes / private-net
# masquerades that would otherwise slip past the hostname check.
_FORBIDDEN_HOSTS: frozenset = frozenset({
    "0.0.0.0",
    "0",
    "localhost.localdomain",
    "loca1host",
    "127.0.0.2",
})

# CIDR-style prefixes for private / link-local IPv4 ranges. We keep this
# in-line as a string tuple to avoid an ``ipaddress`` import — the
# validator must remain trivially auditable.
_PRIVATE_IPV4_PREFIXES = (
    "10.",
    "192.168.",
    "169.254.",       # link-local
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "100.64.",        # CGNAT
)
# The IPv6 unspecified address is also refused.
_FORBIDDEN_IPV6 = frozenset({"::", "::0"})


class TestEnvironmentError(ValueError):
    """Raised when the supplied environment fails any constraint."""


@dataclass(frozen=True)
class ValidatedTestEnv:
    """Canonicalised values returned by :func:`validate`."""

    runtime_mode: str
    db_name: str
    mongo_url: str
    backend_url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require(env: Mapping[str, Any], key: str) -> str:
    val = env.get(key)
    if val is None:
        raise TestEnvironmentError(f"{key} is required but was not supplied.")
    s = str(val).strip()
    if not s:
        raise TestEnvironmentError(f"{key} must be a non-empty value.")
    return s


def _reject_forbidden_host(host: str, var: str) -> None:
    """Refuse hosts that lookalike loopback but aren't. Also refuses
    private / link-local IPv4 ranges and the IPv6 unspecified address."""
    h = host.strip().lower()
    if not h:
        raise TestEnvironmentError(f"{var} has an empty hostname.")
    if h in _FORBIDDEN_HOSTS:
        raise TestEnvironmentError(
            f"{var} hostname {host!r} is refused; only exact "
            f"{sorted(LOOPBACK_HOSTS)} are accepted."
        )
    if h in _FORBIDDEN_IPV6:
        raise TestEnvironmentError(
            f"{var} hostname {host!r} is refused."
        )
    if any("*" in h or "?" in h or "[" in h for _ in (0,)):
        raise TestEnvironmentError(
            f"{var} hostname {host!r} contains wildcard characters."
        )
    # Reject private-network IPv4 ranges outright.
    for prefix in _PRIVATE_IPV4_PREFIXES:
        if h.startswith(prefix):
            raise TestEnvironmentError(
                f"{var} hostname {host!r} is in a private-network range; "
                f"only {sorted(LOOPBACK_HOSTS)} are accepted."
            )


def _parse_url(value: str, var: str):
    try:
        parsed = urlparse(value)
    except (ValueError, TypeError) as exc:  # pragma: no cover
        raise TestEnvironmentError(f"{var} is not a parseable URL.") from exc
    if not parsed.scheme:
        raise TestEnvironmentError(f"{var} must include a scheme.")
    return parsed


# ---------------------------------------------------------------------------
# Per-variable validators
# ---------------------------------------------------------------------------
def _validate_runtime_mode(env: Mapping[str, Any]) -> str:
    raw = _require(env, "HYMN_RUNTIME_MODE").lower()
    if raw != REQUIRED_MODE:
        raise TestEnvironmentError(
            f"HYMN_RUNTIME_MODE must equal {REQUIRED_MODE!r}; got {raw!r}. "
            "Preview and production modes are refused."
        )
    return raw


def _validate_db_name(env: Mapping[str, Any]) -> str:
    raw = _require(env, "DB_NAME")
    if raw != REQUIRED_DB_NAME:
        raise TestEnvironmentError(
            f"DB_NAME must equal {REQUIRED_DB_NAME!r}; got {raw!r}. "
            "Alternate database names are refused."
        )
    return raw


def _validate_mongo_url(env: Mapping[str, Any]) -> str:
    raw = _require(env, "MONGO_URL")
    parsed = _parse_url(raw, "MONGO_URL")
    scheme = parsed.scheme.lower()
    if scheme != MONGO_SCHEME:
        raise TestEnvironmentError(
            f"MONGO_URL scheme must be exactly {MONGO_SCHEME!r}; "
            f"got {scheme!r}. mongodb+srv and Atlas URLs are refused."
        )
    host = (parsed.hostname or "").lower()
    _reject_forbidden_host(host, "MONGO_URL")
    if host not in LOOPBACK_HOSTS:
        raise TestEnvironmentError(
            f"MONGO_URL hostname must be one of {sorted(LOOPBACK_HOSTS)}; "
            f"got {host!r}. Remote MongoDB hosts are refused."
        )
    return raw


def _validate_backend_url(env: Mapping[str, Any]) -> str:
    raw = _require(env, "EXPO_PUBLIC_BACKEND_URL")
    parsed = _parse_url(raw, "EXPO_PUBLIC_BACKEND_URL")
    scheme = parsed.scheme.lower()
    if scheme not in BACKEND_SCHEMES:
        raise TestEnvironmentError(
            f"EXPO_PUBLIC_BACKEND_URL scheme must be one of "
            f"{sorted(BACKEND_SCHEMES)}; got {scheme!r}."
        )
    host = (parsed.hostname or "").lower()
    _reject_forbidden_host(host, "EXPO_PUBLIC_BACKEND_URL")
    if host not in LOOPBACK_HOSTS:
        raise TestEnvironmentError(
            f"EXPO_PUBLIC_BACKEND_URL hostname must be one of "
            f"{sorted(LOOPBACK_HOSTS)}; got {host!r}. Public / preview / "
            "production URLs are refused."
        )
    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def validate(env: Mapping[str, Any]) -> ValidatedTestEnv:
    """Validate ``env`` and return canonicalised values.

    Raises :class:`TestEnvironmentError` on the first violation. Callers
    may translate this to their runner's native failure type
    (e.g. ``pytest.UsageError``).
    """
    if env is None:
        raise TestEnvironmentError("A mapping of environment variables is required.")

    runtime_mode = _validate_runtime_mode(env)
    db_name = _validate_db_name(env)
    mongo_url = _validate_mongo_url(env)
    backend_url = _validate_backend_url(env).rstrip("/")

    return ValidatedTestEnv(
        runtime_mode=runtime_mode,
        db_name=db_name,
        mongo_url=mongo_url,
        backend_url=backend_url,
    )


__all__ = [
    "LOOPBACK_HOSTS",
    "BACKEND_SCHEMES",
    "MONGO_SCHEME",
    "REQUIRED_MODE",
    "REQUIRED_DB_NAME",
    "TestEnvironmentError",
    "ValidatedTestEnv",
    "validate",
]
