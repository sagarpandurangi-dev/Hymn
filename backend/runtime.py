"""Backend runtime-mode configuration.

Single place that answers "which mode are we in?" and enforces the
JWT secret policy per mode. Callers are expected to consume the
helper functions rather than reading ``os.environ`` directly.

Modes
-----
* ``preview``     — Emergent preview / local dev. Requires JWT_SECRET.
* ``production``  — Production. Requires JWT_SECRET.
* ``test``        — Test runner. May use a deterministic secret when
                    JWT_SECRET is absent. The deterministic secret is
                    NEVER returned when the mode is anything else.

Environment variable
--------------------
``HYMN_RUNTIME_MODE`` — one of the three accepted modes. Absent value
resolves to ``preview`` for backward compatibility. Any other value
must fail loudly at startup (``RuntimeError``).

Design invariants
-----------------
1. Never print or log the JWT secret. Errors reference the variable
   *name* only.
2. ``get_jwt_secret`` is the only sanctioned way to read the secret;
   it fails fast in preview/production when the env var is missing.
3. All helpers are pure — no side-effects, no I/O — so unit tests can
   set ``os.environ`` and assert deterministic behaviour.
"""

from __future__ import annotations

import os
from typing import Literal

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
RuntimeMode = Literal["preview", "production", "test"]
VALID_MODES: frozenset = frozenset({"preview", "production", "test"})

# The deterministic secret used when running the test suite without an
# externally-provided JWT_SECRET. It is intentionally recognisable so a
# leak into preview/production is easy to spot in review.
_TEST_ONLY_JWT_SECRET = "hymn-test-only-jwt-secret-not-for-any-other-mode"


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------
def get_runtime_mode() -> RuntimeMode:
    """Return the current runtime mode.

    * Absent value → ``preview`` (backward compatibility).
    * Any value not in :data:`VALID_MODES` → ``RuntimeError`` with a
      message that names the offending value but not the secret.
    """
    raw = (os.environ.get("HYMN_RUNTIME_MODE") or "").strip().lower()
    if not raw:
        return "preview"
    if raw not in VALID_MODES:
        raise RuntimeError(
            f"HYMN_RUNTIME_MODE={raw!r} is not recognised. "
            f"Accepted values: {sorted(VALID_MODES)}."
        )
    # `cast` via cheap conditional — mypy-friendly without importing typing.cast.
    if raw == "test":
        return "test"
    if raw == "production":
        return "production"
    return "preview"


def is_test() -> bool:
    return get_runtime_mode() == "test"


def is_preview() -> bool:
    return get_runtime_mode() == "preview"


def is_production() -> bool:
    return get_runtime_mode() == "production"


# ---------------------------------------------------------------------------
# JWT secret
# ---------------------------------------------------------------------------
def get_jwt_secret() -> str:
    """Return the JWT secret enforced per mode.

    * ``preview`` / ``production`` — ``JWT_SECRET`` must be present and
      non-empty. Missing or blank raises ``RuntimeError`` (message never
      contains the secret itself).
    * ``test`` — returns the env-provided value when present, otherwise
      falls back to a deterministic test-only secret. The test-only
      secret is only ever returned when the current mode is ``test``.
    """
    mode = get_runtime_mode()
    provided = (os.environ.get("JWT_SECRET") or "").strip()
    if mode == "test":
        return provided or _TEST_ONLY_JWT_SECRET
    if not provided:
        raise RuntimeError(
            f"JWT_SECRET must be set when HYMN_RUNTIME_MODE={mode!r}; "
            "refusing to start."
        )
    if provided == _TEST_ONLY_JWT_SECRET:
        # Defensive: even if the operator copied the constant into a
        # non-test .env, refuse to accept it. Never mention the value.
        raise RuntimeError(
            f"The deterministic test JWT secret must never be used in "
            f"{mode!r} mode; refusing to start."
        )
    return provided


__all__ = [
    "RuntimeMode",
    "VALID_MODES",
    "get_runtime_mode",
    "is_test",
    "is_preview",
    "is_production",
    "get_jwt_secret",
]
