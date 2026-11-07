"""Fixtures for in-process API tests.

``server`` is imported with a test-mode environment and its ``db`` is
swapped for an in-memory mongomock-motor database before any request,
so nothing here opens a socket or needs a running MongoDB.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ["HYMN_RUNTIME_MODE"] = "test"
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1")  # never contacted
os.environ.setdefault("DB_NAME", "hymn_unit_tests")


@pytest.fixture()
def server(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient

    import server as server_module

    monkeypatch.setattr(server_module, "db", AsyncMongoMockClient()["hymn_unit_tests"])
    return server_module


@pytest.fixture()
def client(server):
    from fastapi.testclient import TestClient

    # Not used as a context manager: startup hooks (index creation,
    # finance backfill) are not needed by these tests.
    return TestClient(server.app)
