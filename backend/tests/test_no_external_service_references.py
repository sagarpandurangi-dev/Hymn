"""Repository-level safety assertions for active authentication code."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_AUTH_FILES = (
    "backend/server.py",
    "backend/planning_engine.py",
    "backend/intent_engine.py",
    "frontend/src/lib/AuthContext.tsx",
    "frontend/src/lib/api.ts",
    "frontend/app/(auth)/sign-in.tsx",
    "frontend/app/(auth)/sign-up.tsx",
)
FORBIDDEN_AUTH_MARKERS = (
    "emergentintegrations",
    "EMERGENT_LLM_KEY",
    "auth.emergentagent.com",
    "demobackend.emergentagent.com",
    "/auth/google-session",
    "session_id",
    "session_token",
    "user_sessions",
)


def test_active_authentication_has_no_external_provider_callbacks():
    for relative_path in ACTIVE_AUTH_FILES:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for marker in FORBIDDEN_AUTH_MARKERS:
            assert marker not in source, f"{marker!r} remains in {relative_path}"


def test_universal_intent_engine_has_no_outbound_client_or_remote_url():
    source = (REPO_ROOT / "backend/intent_engine.py").read_text(encoding="utf-8")
    for marker in (
        "import httpx",
        "from httpx",
        "import requests",
        "from requests",
        "import aiohttp",
        "from aiohttp",
        "urllib.request",
        "http://",
        "https://",
    ):
        assert marker not in source, f"{marker!r} would permit an outbound intent request"
