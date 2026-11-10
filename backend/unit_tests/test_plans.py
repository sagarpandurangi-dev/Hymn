"""Plans: free by default; statement upload is Premium."""
from __future__ import annotations

import asyncio
import io

import pytest
from pypdf import PdfWriter

import plans


def _signup(client, email="free@example.com"):
    r = client.post("/api/auth/signup", json={
        "name": "Plan", "email": email, "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "plan": body["user"]["plan"],
            "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _upload(client, user):
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    return client.post("/api/statements", headers=user["headers"],
                       files={"file": ("s.pdf", buf.getvalue(), "application/pdf")})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("HYMN_PREMIUM_EMAILS", raising=False)
    monkeypatch.delenv("HYMN_DEFAULT_PLAN", raising=False)


def test_new_users_are_free_and_cannot_upload_statements(client):
    user = _signup(client)
    assert user["plan"] == "free"
    r = _upload(client, user)
    assert r.status_code == 403
    assert "Premium" in r.json()["detail"]


def test_free_users_can_still_list_and_delete_documents(client):
    user = _signup(client)
    assert client.get("/api/statements", headers=user["headers"]).status_code == 200
    assert client.delete("/api/statements", headers=user["headers"]).status_code == 200


def test_premium_by_email_list(client, monkeypatch, server):
    monkeypatch.setenv("HYMN_PREMIUM_EMAILS", "someone@x.com, Owner@Example.com")
    user = _signup(client, "owner@example.com")
    assert user["plan"] == "premium"
    assert client.get("/api/auth/me", headers=user["headers"]).json()["plan"] == "premium"
    assert _upload(client, user).status_code != 403


def test_stored_plan_wins_over_email_list(monkeypatch):
    monkeypatch.setenv("HYMN_PREMIUM_EMAILS", "a@b.com")
    assert plans.user_plan({"email": "a@b.com", "plan": "free"}) == "free"


@pytest.mark.parametrize("default, expected", [("premium", "premium"), ("free", "free"), ("gold", "free")])
def test_default_plan_setting(monkeypatch, default, expected):
    monkeypatch.setenv("HYMN_DEFAULT_PLAN", default)
    assert plans.user_plan({"email": "x@y.com"}) == expected
