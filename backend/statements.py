"""Statement upload: read any bank, card or wallet statement PDF.

Flow
----
1. ``POST /statements`` takes a PDF and, if it is locked, its password. The
   password opens the file in memory only; it is never stored or logged. The
   original file is kept as uploaded (still locked by the bank's password).
2. Reading runs in the background, a few pages per Claude call. The app polls
   ``GET /statements/{id}``.
3. Every statement is checked with arithmetic: the running balance on each
   line, and opening + money in − money out = closing. A statement that
   doesn't add up is marked ``needs_review`` instead of being trusted.
4. Nothing reaches the ledger here; confirming imports into it is the next
   step (classification, duplicate matching, opening balances).

Uploading is a Premium feature; listing and deleting stay open to everyone,
so a user who leaves Premium can still remove their documents.

The one reading rule, for every institution: the debit column is money out
of the account, the credit column is money into it.
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import date as date_type, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bson.binary import Binary
from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
                     Response, UploadFile)
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

import statements_ai
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db
from plans import require_feature

logger = logging.getLogger(__name__)

statements_router = APIRouter(prefix="/statements", tags=["statements"])

MAX_BYTES = 10 * 1024 * 1024
PAGES_PER_CHUNK = 4
# Accounts where a credit raises what you hold (vs. lowers what you owe).
HOLDING_KINDS = frozenset({"bank", "wallet", "investment", "other"})
# Banks round interest and charges; a gap this small is the statement's own
# rounding, not a missed transaction.
ROUNDING_TOLERANCE = Decimal("1.00")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# PDF handling (pure)
# ---------------------------------------------------------------------------

class StatementFileError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def open_pdf(data: bytes, password: Optional[str]) -> PdfReader:
    if not data.startswith(b"%PDF"):
        raise StatementFileError("not_pdf", "That file isn't a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, ValueError) as exc:
        raise StatementFileError("unreadable", "That PDF couldn't be opened.") from exc
    if reader.is_encrypted:
        if not password:
            raise StatementFileError("password_required", "This PDF is password-protected. Enter its password.")
        try:
            ok = reader.decrypt(password)
        except Exception:  # noqa: BLE001 - never echo password-related errors
            ok = 0
        if not ok:
            raise StatementFileError("wrong_password", "That password didn't open the PDF.")
    return reader


def split_pages(reader: PdfReader, per_chunk: Optional[int] = None) -> List[bytes]:
    """Unencrypted PDF bytes, ``per_chunk`` pages each, in memory only."""
    per_chunk = per_chunk or PAGES_PER_CHUNK
    chunks = []
    pages = list(reader.pages)
    for start in range(0, len(pages), per_chunk):
        writer = PdfWriter()
        for page in pages[start:start + per_chunk]:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append(buf.getvalue())
    return chunks


# ---------------------------------------------------------------------------
# Merging and verification (pure)
# ---------------------------------------------------------------------------

def _amount(value: Any) -> Optional[Decimal]:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _valid_date(value: Any) -> bool:
    try:
        date_type.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def merge_chunks(chunks: List[statements_ai.StatementChunk]) -> Dict[str, Any]:
    """Statement fields from the first chunk that has them (closing from the
    last), and every line in order."""
    def first(field: str) -> str:
        return next((getattr(c, field) for c in chunks if getattr(c, field)), "")

    def last(field: str) -> str:
        return next((getattr(c, field) for c in reversed(chunks) if getattr(c, field)), "")

    lines = []
    for chunk in chunks:
        for line in chunk.lines:
            lines.append({"n": len(lines) + 1, **line.model_dump()})
    return {
        "metadata": {
            "institution": first("institution"),
            "account_kind": next((c.account_kind for c in chunks if c.account_kind != "other"), "other"),
            "account_last4": first("account_last4"),
            "currency": first("currency"),
            "period_start": first("period_start"),
            "period_end": last("period_end"),
            "opening_balance": first("opening_balance"),
            "closing_balance": last("closing_balance"),
        },
        "lines": lines,
    }


def verify(statement: Dict[str, Any]) -> Dict[str, Any]:
    """Arithmetic checks that catch misread numbers.

    For accounts that hold money a credit raises the balance; for cards and
    loans (balance = amount owed) a debit raises it.
    """
    meta, lines = statement["metadata"], statement["lines"]
    holds = meta["account_kind"] in HOLDING_KINDS
    problems: List[Dict[str, Any]] = []
    total_debit = total_credit = Decimal(0)

    def change(debit: Decimal, credit: Decimal) -> Decimal:
        return (credit - debit) if holds else (debit - credit)

    prev_balance: Optional[Decimal] = _amount(meta["opening_balance"])
    running_checked = 0
    for line in lines:
        # Many statements print 0.00 in the unused column; treat it as empty.
        debit, credit = (_amount(line["debit"]) or None), (_amount(line["credit"]) or None)
        if (debit is None) == (credit is None) or (debit or credit) <= 0:
            problems.append({"line": line["n"], "issue": "needs exactly one positive debit or credit"})
            prev_balance = _amount(line["balance"])
            continue
        if not _valid_date(line["date"]):
            problems.append({"line": line["n"], "issue": "date is not YYYY-MM-DD"})
        debit, credit = debit or Decimal(0), credit or Decimal(0)
        total_debit += debit
        total_credit += credit
        printed = _amount(line["balance"])
        if printed is not None and prev_balance is not None:
            running_checked += 1
            if prev_balance + change(debit, credit) != printed:
                problems.append({"line": line["n"], "issue": "running balance doesn't add up",
                                 "expected": format(prev_balance + change(debit, credit), "f"),
                                 "printed": format(printed, "f")})
        prev_balance = printed if printed is not None else (
            prev_balance + change(debit, credit) if prev_balance is not None else None)

    opening, closing = _amount(meta["opening_balance"]), _amount(meta["closing_balance"])
    notes: List[str] = []
    if opening is not None and closing is not None:
        expected = opening + change(total_debit, total_credit)
        gap = abs(closing - expected)
        if gap == 0:
            totals = "ok"
        elif gap <= ROUNDING_TOLERANCE:
            totals = "rounding"
            notes.append(f"The statement's own closing balance differs from its transactions by "
                         f"{money(gap, meta['currency'])}, a rounding difference in the statement.")
        else:
            totals = "mismatch"
            problems.append({"line": None, "issue": "opening + movements ≠ closing",
                             "expected": format(expected, "f"), "printed": format(closing, "f"),
                             "difference": format(gap, "f")})
    else:
        totals = "not_available"
    line_problems = [p for p in problems if p["line"] is not None]
    # The app reads `message` and `line_number`; keep both spellings.
    for p in problems:
        p["message"] = p["issue"]
        p["line_number"] = p["line"]
    # Nothing to cross-check means a person must look before it's used.
    trusted = not problems and (totals in ("ok", "rounding") or running_checked == len(lines) > 0)
    if trusted and running_checked:
        notes.insert(0, f"All {running_checked} line balances add up.")
    return {
        "totals_check": totals,
        "running_balance_lines_checked": running_checked,
        "line_count": len(lines),
        "total_debit": format(total_debit, "f"),
        "total_credit": format(total_credit, "f"),
        "problems": problems,
        "trusted": trusted,
        "reasons": [] if trusted else review_reasons(
            problems, totals, running_checked, len(lines), meta["currency"],
            every_line_adds_up=bool(lines) and running_checked == len(lines) and not line_problems,
        ),
        "notes": notes,
    }


def money(amount: Decimal, currency: str) -> str:
    """₹1,23,456.78 for INR (Indian grouping), else e.g. "USD 123,456.78"."""
    amount = amount.quantize(Decimal("0.01"))
    sign, whole, frac = ("-" if amount < 0 else ""), *format(abs(amount), "f").split(".")
    if currency == "INR":
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + groups + [tail])
        return f"{sign}₹{whole}.{frac}"
    return f"{sign}{currency or ''} {int(whole):,}.{frac}".strip()


def review_reasons(problems: List[Dict[str, Any]], totals: str, running_checked: int,
                   line_count: int, currency: str, *, every_line_adds_up: bool = False) -> List[str]:
    """Why a statement needs review: what was checked, how big the gap is,
    and the most likely cause."""
    reasons = []
    for p in problems:
        if p["issue"] == "opening + movements ≠ closing":
            gap = money(Decimal(p["difference"]), currency)
            if every_line_adds_up:
                reasons.append(
                    f"All {running_checked} line balances add up, but the statement's closing balance "
                    f"differs from them by {gap}. The statement's own summary looks inconsistent; "
                    f"check its closing balance."
                )
            else:
                reasons.append(
                    f"{gap} is unaccounted for: the transactions give {money(Decimal(p['expected']), currency)}, "
                    f"the statement's closing balance is {money(Decimal(p['printed']), currency)}. "
                    f"Look for a missing or misread transaction of about {gap}."
                )
        elif p["issue"] == "running balance doesn't add up":
            expected, printed = Decimal(p["expected"]), Decimal(p["printed"])
            reasons.append(
                f"Line {p['line']}: the balance should be {money(expected, currency)} but the statement "
                f"shows {money(printed, currency)} (off by {money(abs(expected - printed), currency)}). "
                f"This line's amount was probably misread."
            )
        elif p["issue"] == "date is not YYYY-MM-DD":
            reasons.append(f"Line {p['line']}: the date couldn't be read.")
        else:
            reasons.append(f"Line {p['line']}: the amount couldn't be read as a single debit or credit.")
    if not problems and line_count == 0:
        reasons.append("No transactions were found in this statement.")
    elif not problems and totals == "not_available" and running_checked < line_count:
        reasons.append(
            "This statement shows no opening/closing balance or running balance, so Hymn couldn't "
            "double-check the amounts. Please look through them once."
        )
    return reasons


# ---------------------------------------------------------------------------
# Background reading
# ---------------------------------------------------------------------------

async def read_statement(db, import_id: str, chunks: List[bytes]) -> None:
    try:
        results = [await statements_ai.extract_chunk(c, i + 1, len(chunks)) for i, c in enumerate(chunks)]
    except AssistantUnavailable as exc:
        logger.warning("statement %s: reading failed: %s", import_id, exc)
        await db.statement_imports.update_one(
            {"id": import_id},
            {"$set": {"status": "failed", "error": "Couldn't read this statement right now. Try again later.",
                      "updated_at": _now()}},
        )
        return
    statement = merge_chunks(results)
    checks = verify(statement)
    await db.statement_imports.update_one(
        {"id": import_id},
        {"$set": {**statement, "verification": checks,
                  "status": "ready" if checks["trusted"] else "needs_review",
                  "error": None, "updated_at": _now()}},
    )
    logger.info("statement %s: %d lines, %s", import_id, len(statement["lines"]),
                "trusted" if checks["trusted"] else f"{len(checks['problems'])} problems")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _summary(doc: dict) -> dict:
    return {k: doc.get(k) for k in (
        "id", "filename", "status", "error", "metadata", "verification", "created_at", "updated_at",
    )}


@statements_router.post("", status_code=202)
async def upload_statement(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    password: Optional[str] = Form(default=None),
    current_user: dict = Depends(get_current_user),
):
    require_feature(current_user, "statements",
                    "Reading statements is part of Hymn Premium. On the free plan, enter your "
                    "account balances by hand.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Statements must be 10 MB or smaller.")
    try:
        reader = open_pdf(data, password)
        chunks = split_pages(reader)
    except StatementFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not chunks:
        raise HTTPException(status_code=400, detail="That PDF has no pages.")

    db = get_db()
    now = _now()
    file_id, import_id = str(uuid.uuid4()), str(uuid.uuid4())
    await db.statement_files.insert_one({
        "id": file_id, "user_id": current_user["id"], "filename": file.filename or "statement.pdf",
        "size": len(data), "data": Binary(data), "uploaded_at": now,
    })
    doc = {
        "id": import_id, "user_id": current_user["id"], "file_id": file_id,
        "filename": file.filename or "statement.pdf", "pages": len(reader.pages),
        "status": "reading", "error": None, "metadata": None, "lines": [], "verification": None,
        "created_at": now, "updated_at": now,
    }
    await db.statement_imports.insert_one(doc)
    background.add_task(read_statement, db, import_id, chunks)
    return _summary(doc)


async def _rechecked(db, doc: dict) -> dict:
    """Re-run the arithmetic (no AI call) so statements read earlier get
    today's checks, explanations and status; persist a changed status."""
    if not doc.get("metadata") or doc.get("status") not in ("ready", "needs_review"):
        return doc
    checks = verify({"metadata": doc["metadata"], "lines": doc.get("lines", [])})
    status = "ready" if checks["trusted"] else "needs_review"
    if status != doc["status"] or checks != doc.get("verification"):
        await db.statement_imports.update_one(
            {"id": doc["id"]}, {"$set": {"verification": checks, "status": status, "updated_at": _now()}},
        )
    return {**doc, "verification": checks, "status": status}


@statements_router.get("")
async def list_statements(current_user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.statement_imports.find(
        {"user_id": current_user["id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(length=500)
    return [_summary(await _rechecked(db, d)) for d in docs]


async def _get(db, user_id: str, import_id: str) -> dict:
    doc = await db.statement_imports.find_one({"id": import_id, "user_id": user_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return doc


@statements_router.get("/{import_id}")
async def get_statement(import_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _rechecked(db, await _get(db, current_user["id"], import_id))
    return {**_summary(doc), "pages": doc.get("pages"), "lines": doc.get("lines", [])}


@statements_router.get("/{import_id}/file")
async def download_statement(import_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _get(db, current_user["id"], import_id)
    f = await db.statement_files.find_one({"id": doc["file_id"], "user_id": current_user["id"]})
    if f is None:
        raise HTTPException(status_code=404, detail="File was deleted")
    return Response(content=bytes(f["data"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'})


@statements_router.delete("/{import_id}")
async def delete_statement(import_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _get(db, current_user["id"], import_id)
    await db.statement_files.delete_one({"id": doc["file_id"], "user_id": current_user["id"]})
    await db.statement_imports.delete_one({"id": import_id, "user_id": current_user["id"]})
    return {"detail": "Statement deleted"}


@statements_router.delete("")
async def delete_all_documents(current_user: dict = Depends(get_current_user)):
    """'Delete my documents': every uploaded file and what was read from it."""
    db = get_db()
    files = await db.statement_files.delete_many({"user_id": current_user["id"]})
    await db.statement_imports.delete_many({"user_id": current_user["id"]})
    return {"detail": "All statements deleted", "files_deleted": files.deleted_count}


async def ensure_statement_indexes(db) -> None:
    await db.statement_files.create_index("id", unique=True)
    await db.statement_files.create_index("user_id")
    await db.statement_imports.create_index("id", unique=True)
    await db.statement_imports.create_index([("user_id", 1), ("created_at", -1)])
