"""Shared dependency wrapper.

Extracted from server.py so extension modules (portfolio_manager, etc.) can
use ``Depends(get_current_user)`` at decorator time without importing server
directly — which would cause a circular import when a test loads the
extension before server has finished loading.

At request time the wrapper resolves the real implementation from server via
a lazy import. Server is fully loaded by then.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    from server import get_current_user as _real  # lazy import
    return await _real(request, credentials)


def get_db():
    """Return the AsyncIOMotorDatabase from server. Lazy to avoid circular import."""
    from server import db
    return db
