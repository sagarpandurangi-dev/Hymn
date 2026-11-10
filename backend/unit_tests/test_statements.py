"""Statement upload: locked PDFs, chunked reading, arithmetic checks, deletion."""
from __future__ import annotations

import asyncio
import io

import pytest
from pypdf import PdfWriter

import statements
import statements_ai
from claude_client import AssistantUnavailable
from statements_ai import StatementChunk, StatementLine


def _pdf(pages=1, password=None) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _line(date, debit="", credit="", balance="", desc="x"):
    return StatementLine(date=date, description=desc, reference="", debit=debit, credit=credit, balance=balance)


def _chunk(lines, kind="bank", opening="", closing="", **kw):
    fields = dict(institution="HDFC Bank", account_kind=kind, account_last4="1234", currency="INR",
                  period_start="2026-10-01", period_end="2026-10-31",
                  opening_balance=opening, closing_balance=closing, lines=lines)
    fields.update(kw)
    return StatementChunk(**fields)


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Docs", "email": "docs@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture()
def reader(monkeypatch):
    """Claude stand-in: returns queued chunks and records how it was called."""
    calls, queue = [], []

    async def extract_chunk(pdf_bytes, part, parts):
        calls.append((part, parts, pdf_bytes[:4]))
        return queue.pop(0)

    monkeypatch.setattr(statements_ai, "extract_chunk", extract_chunk)
    return {"calls": calls, "queue": queue}


def _upload(client, user, data, password=None, name="oct.pdf"):
    form = {"password": password} if password is not None else {}
    return client.post("/api/statements", headers=user["headers"],
                       files={"file": (name, data, "application/pdf")}, data=form)


# ---------------------------------------------------------------------------
# Locked PDFs
# ---------------------------------------------------------------------------

def test_locked_pdf_needs_its_password(client, user, reader):
    locked = _pdf(password="01011990")
    r = _upload(client, user, locked)
    assert r.status_code == 400 and "password-protected" in r.json()["detail"]
    r = _upload(client, user, locked, password="wrong")
    assert r.status_code == 400 and "didn't open" in r.json()["detail"]
    assert reader["calls"] == []


def test_locked_pdf_opens_and_is_stored_still_locked(client, user, reader, server):
    locked = _pdf(password="01011990")
    reader["queue"].append(_chunk([_line("2026-10-02", debit="500")], opening="1000", closing="500"))
    r = _upload(client, user, locked, password="01011990")
    assert r.status_code == 202, r.text
    stored = asyncio.run(server.db.statement_files.find_one({}))
    assert bytes(stored["data"]) == locked                   # original, still locked
    assert "01011990" not in str(asyncio.run(server.db.statement_imports.find_one({})))
    assert reader["calls"][0][2] == b"%PDF"                   # Claude got an unlocked copy


@pytest.mark.parametrize("data, message", [
    (b"hello", "isn't a PDF"),
    (b"%PDF-1.7 garbage", "couldn't be opened"),
])
def test_bad_files_are_rejected(client, user, reader, data, message):
    r = _upload(client, user, data)
    assert r.status_code == 400 and message in r.json()["detail"]


# ---------------------------------------------------------------------------
# Reading and merging
# ---------------------------------------------------------------------------

def test_long_statements_are_read_in_chunks_and_merged(client, user, reader, monkeypatch):
    monkeypatch.setattr(statements, "PAGES_PER_CHUNK", 2)
    reader["queue"].extend([
        _chunk([_line("2026-10-02", debit="300", balance="700")], opening="1000", closing=""),
        _chunk([_line("2026-10-10", credit="50000", balance="50700")], opening="", closing="",
               institution="", period_end=""),
        _chunk([_line("2026-10-20", debit="700", balance="50000")], opening="", closing="50000",
               period_end="2026-10-31"),
    ])
    r = _upload(client, user, _pdf(pages=5))
    import_id = r.json()["id"]
    assert [(c[0], c[1]) for c in reader["calls"]] == [(1, 3), (2, 3), (3, 3)]
    doc = client.get(f"/api/statements/{import_id}", headers=user["headers"]).json()
    assert doc["status"] == "ready"
    assert [(l["n"], l["date"]) for l in doc["lines"]] == [(1, "2026-10-02"), (2, "2026-10-10"), (3, "2026-10-20")]
    assert doc["metadata"]["institution"] == "HDFC Bank"
    assert (doc["metadata"]["opening_balance"], doc["metadata"]["closing_balance"]) == ("1000", "50000")
    assert doc["verification"]["running_balance_lines_checked"] == 3


def test_reading_failure_is_reported_and_file_kept(client, user, monkeypatch, server):
    async def down(*_):
        raise AssistantUnavailable("connection error")

    monkeypatch.setattr(statements_ai, "extract_chunk", down)
    import_id = _upload(client, user, _pdf()).json()["id"]
    doc = client.get(f"/api/statements/{import_id}", headers=user["headers"]).json()
    assert doc["status"] == "failed"
    assert asyncio.run(server.db.statement_files.count_documents({})) == 1


# ---------------------------------------------------------------------------
# Arithmetic checks (pure)
# ---------------------------------------------------------------------------

def _verify(chunk):
    return statements.verify(statements.merge_chunks([chunk]))


def test_bank_statement_that_adds_up_is_trusted():
    v = _verify(_chunk([
        _line("2026-10-02", debit="1,500.00", balance="8500"),
        _line("2026-10-05", credit="2000", debit="0.00", balance="10500"),
    ], opening="10000", closing="10500"))
    assert (v["totals_check"], v["problems"], v["trusted"]) == ("ok", [], True)
    assert (v["total_debit"], v["total_credit"]) == ("1500.00", "2000")


def test_one_misread_number_is_caught():
    v = _verify(_chunk([
        _line("2026-10-02", debit="1500", balance="8500"),
        _line("2026-10-05", credit="2900", balance="10500"),   # misread: should be 2000
    ], opening="10000", closing="10500"))
    assert v["trusted"] is False
    assert {p["issue"] for p in v["problems"]} == {"running balance doesn't add up", "opening + movements ≠ closing"}
    assert v["problems"][0]["line"] == 2


def test_card_statement_balances_are_amounts_owed():
    v = _verify(_chunk([
        _line("2026-10-03", debit="2000"),          # purchase raises what's owed
        _line("2026-10-15", credit="18000"),        # payment lowers it
    ], kind="credit_card", opening="18000", closing="2000"))
    assert (v["totals_check"], v["trusted"]) == ("ok", True)


@pytest.mark.parametrize("line, issue", [
    (_line("2026-10-02"), "needs exactly one positive debit or credit"),
    (_line("2026-10-02", debit="5", credit="5"), "needs exactly one positive debit or credit"),
    (_line("2026-10-02", debit="-5"), "needs exactly one positive debit or credit"),
    (_line("02/10/2026", debit="5"), "date is not YYYY-MM-DD"),
])
def test_bad_lines_are_flagged(line, issue):
    v = _verify(_chunk([line]))
    assert v["problems"][0]["issue"] == issue
    assert v["trusted"] is False


def test_nothing_to_cross_check_means_review():
    v = _verify(_chunk([_line("2026-10-02", debit="5")]))   # no balances printed at all
    assert (v["totals_check"], v["running_balance_lines_checked"], v["trusted"]) == ("not_available", 0, False)


# ---------------------------------------------------------------------------
# Listing, download, deletion, privacy
# ---------------------------------------------------------------------------

def test_statements_are_private_and_deletable(client, user, reader, server):
    reader["queue"].extend([_chunk([_line("2026-10-02", debit="5")]) for _ in range(2)])
    first = _upload(client, user, _pdf()).json()["id"]
    _upload(client, user, _pdf(), name="nov.pdf")
    assert len(client.get("/api/statements", headers=user["headers"]).json()) == 2
    assert "lines" not in client.get("/api/statements", headers=user["headers"]).json()[0]

    other = client.post("/api/auth/signup", json={
        "name": "Other", "email": "other@example.com", "password": "another-long-password",
        "security_question": "Q?", "security_answer": "A",
    }).json()
    other_h = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/api/statements", headers=other_h).json() == []
    assert client.get(f"/api/statements/{first}", headers=other_h).status_code == 404
    assert client.get(f"/api/statements/{first}/file", headers=other_h).status_code == 404

    pdf = client.get(f"/api/statements/{first}/file", headers=user["headers"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    assert client.delete(f"/api/statements/{first}", headers=user["headers"]).status_code == 200
    assert len(client.get("/api/statements", headers=user["headers"]).json()) == 1
    r = client.delete("/api/statements", headers=user["headers"])
    assert r.json()["files_deleted"] == 1
    assert asyncio.run(server.db.statement_files.count_documents({})) == 0
