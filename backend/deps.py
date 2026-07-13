"""Shared dependency wrapper.

Extracted from server.py so extension modules (portfolio_manager, etc.) can
use ``Depends(get_current_user)`` at decorator time without importing server
directly - which would cause a circular import when a test loads the
extension before server has finished loading.

At request time the wrapper resolves the real implementation from server via
a lazy import. Server is fully loaded by then.
"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

# Must match the tokenUrl declared in server.py so that OpenAPI/Swagger and
# the runtime bearer extraction remain consistent across modules.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Resolve the authenticated user by delegating to server.get_current_user.

    The real implementation lives in ``server.py``. We import it lazily so this
    module can be imported by extension modules before server has finished
    initializing (which would otherwise create a circular import).
    """
    from server import get_current_user as _real  # lazy import
    return await _real(token)


def get_db():
    """Return the AsyncIOMotorDatabase from server. Lazy to avoid circular import."""
    from server import db
    return db
