"""A per-request memo for expensive reads.

One screen load (e.g. the Finance tab) asks for balances, availability,
spending and the forecast, and each of those used to sync the ledger and
reload every transaction. Within one GET request the answers can't change
unless the request itself writes, so they are computed once and reused.
The memo lives only for that request; anything that writes clears it.
"""
from __future__ import annotations

import contextvars
from typing import Any, Optional

_memo: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("hymn_request_memo", default=None)


def begin():
    return _memo.set({})


def finish(token) -> None:
    _memo.reset(token)


def get(key) -> Any:
    memo = _memo.get()
    return None if memo is None else memo.get(key)


def put(key, value) -> None:
    memo = _memo.get()
    if memo is not None:
        memo[key] = value


def forget(user_id: str) -> None:
    """Drop everything remembered for this user (after a write)."""
    memo = _memo.get()
    if memo:
        for key in [k for k in memo if isinstance(k, tuple) and len(k) > 1 and k[1] == user_id]:
            del memo[key]
