"""Lab reports: optional, never required.

Upload a PDF or a photo → the AI copies the results exactly as printed (it
never interprets) → code recognises the tests Hymn tracks (glucose, HbA1c,
lipids, kidney), converts units, checks they're plausible → the person
confirms → values are saved with source "lab" and the report date. Every
other result is kept as printed for the doctor summary. The file itself is
never stored.

Each plan has a monthly allowance of reports read (``HYMN_LAB_READS_FREE``,
default 3; ``HYMN_LAB_READS_PREMIUM``, default 20). Typing values in by hand
is always free.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Literal, Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

import claude_client
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db
from health import METRICS, _d, _date, _profile, _store, rate, subject
from plans import user_plan

labs_router = APIRouter(prefix="/health/labs", tags=["health"])

MODEL = os.environ.get("HYMN_LAB_MODEL") or "claude-haiku-5-5"
MAX_BYTES = 10 * 1024 * 1024

# Hymn metric → names labs print (lower-case, matched as whole phrases).
TEST_NAMES: Dict[str, tuple] = {
    "fasting_glucose": ("fasting blood sugar", "fasting blood glucose", "fasting plasma glucose", "glucose fasting",
                        "glucose, fasting", "fbs", "fpg", "blood sugar fasting", "glucose (fasting)"),
    "hba1c": ("hba1c", "hb a1c", "glycated haemoglobin", "glycated hemoglobin", "glycosylated haemoglobin",
              "glycosylated hemoglobin", "a1c"),
    "ldl": ("ldl cholesterol", "ldl-c", "ldl", "ldl direct", "low density lipoprotein", "ldl cholesterol direct"),
    "hdl": ("hdl cholesterol", "hdl-c", "hdl", "high density lipoprotein", "hdl cholesterol direct"),
    "triglycerides": ("triglycerides", "triglyceride", "tg", "serum triglycerides"),
    "egfr": ("egfr", "estimated gfr", "e-gfr", "estimated glomerular filtration rate"),
    "uacr": ("uacr", "urine albumin creatinine ratio", "albumin/creatinine ratio", "microalbumin/creatinine ratio",
             "acr", "urine acr", "microalbumin creatinine ratio"),
}
# (metric, printed unit) → multiplier into Hymn's unit.
CONVERT = {
    ("fasting_glucose", "mmol/l"): Decimal(18),
    ("ldl", "mmol/l"): Decimal("38.67"), ("hdl", "mmol/l"): Decimal("38.67"),
    ("triglycerides", "mmol/l"): Decimal("88.57"),
    ("uacr", "mg/mmol"): Decimal("8.84"),
    ("hba1c", "mmol/mol"): None,       # IFCC: % = mmol/mol × 0.0915 + 2.15
}
EXPECTED_UNITS = {"fasting_glucose": ("mg/dl",), "hba1c": ("%",), "ldl": ("mg/dl",), "hdl": ("mg/dl",),
                  "triglycerides": ("mg/dl",), "egfr": ("ml/min/1.73m2", "ml/min/1.73 m2", "ml/min"),
                  "uacr": ("mg/g", "mcg/mg", "µg/mg", "ug/mg")}

_SYSTEM = """You copy medical lab reports into structured data. Copy exactly what is
printed: the test name, the result, its unit, the reference range and any
flag printed next to it (H, L, High, Low, *). Never interpret, explain,
correct or add anything. Skip headers, doctor signatures and method notes.
`report_date` is the sample collection or report date (YYYY-MM-DD), `lab` the
laboratory's name; leave a field empty when it isn't printed. If the file
is not a lab report, set `is_lab_report` to false."""


class PrintedResult(BaseModel):
    test_name: str
    value: str
    unit: str
    reference_range: str
    flag: str


class Report(BaseModel):
    is_lab_report: bool
    report_date: str
    lab: str
    results: List[PrintedResult]


async def read_report(data: bytes, media_type: str) -> Report:
    """Raises AssistantUnavailable."""
    client = claude_client.get_client().with_options(timeout=90.0)
    b64 = base64.standard_b64encode(data).decode("ascii")
    block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
             if media_type == "application/pdf" else
             {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
    try:
        response = await client.beta.messages.parse(
            model=MODEL, max_tokens=8000, system=_SYSTEM,
            messages=[{"role": "user", "content": [block, {"type": "text", "text": "Copy this report."}]}],
            output_format=Report, output_config={"effort": "low"}, **claude_client.fallback_kwargs(MODEL))
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc
    except ValidationError as exc:
        raise AssistantUnavailable("malformed output") from exc
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
    return response.parsed_output


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().replace("²", "2")).strip(" :.-")


def recognise(test_name: str) -> Optional[str]:
    """Which Hymn metric a printed test name is, if any. Whole names only,
    so "Non-HDL", "VLDL" and ratios never match by accident."""
    full = _norm(test_name)
    for n in (full, re.sub(r"\s*\(.*?\)\s*$", "", full)):   # "LDL Cholesterol (Direct)"
        for metric, names in TEST_NAMES.items():
            if n in names:
                return metric
    return None


def to_hymn_unit(metric: str, value: str, unit: str) -> Optional[Decimal]:
    v = _d(re.sub(r"[^\d.]", "", value or ""))
    if v is None:
        return None
    u = _norm(unit).replace(" ", "")
    if (metric, u) in CONVERT:
        factor = CONVERT[(metric, u)]
        v = v * Decimal("0.0915") + Decimal("2.15") if factor is None else v * factor
    elif u and u not in {e.replace(" ", "") for e in EXPECTED_UNITS[metric]}:
        return None                                  # an unexpected unit: don't guess
    spec = METRICS[metric]
    v = v.quantize(Decimal("0.1"))
    return v if spec[2] <= v <= spec[3] else None


def allowance(user: dict) -> int:
    key, default = (("HYMN_LAB_READS_PREMIUM", 20) if user_plan(user) == "premium" else ("HYMN_LAB_READS_FREE", 3))
    try:
        return max(0, int(os.environ.get(key, default)))
    except ValueError:
        return default


class Upload(BaseModel):
    file_base64: str
    media_type: Literal["application/pdf", "image/jpeg", "image/png", "image/webp"]


@labs_router.post("/read")
async def read(body: Upload, current_user: dict = Depends(get_current_user),
        for_: Optional[str] = Query(default=None, alias="for")):
    """Read a report into draft results to confirm. Nothing is saved yet and
    the file is not kept. Password-protected PDFs: unlock first."""
    uid = await subject(get_db(), current_user, for_)
    db = get_db()
    profile = await _profile(db, uid)
    try:
        data = base64.b64decode(body.file_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="That file couldn't be read.")
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Please use a file under 10 MB.")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    used = (await db.lab_read_uses.find_one({"user_id": current_user["id"], "month": month}) or {}).get("count", 0)
    if used >= allowance(current_user):
        raise HTTPException(status_code=429, detail="You've used this month's report readings. You can still type "
                                                    "the values in.")
    try:
        report = await read_report(data, body.media_type)
    except AssistantUnavailable:
        raise HTTPException(status_code=503, detail="Hymn couldn't read the report right now. You can type the "
                                                    "values in instead.")
    await db.lab_read_uses.update_one({"user_id": current_user["id"], "month": month}, {"$inc": {"count": 1}},
                                      upsert=True)
    if not report.is_lab_report:
        return {"is_lab_report": False, "results": []}
    results = []
    for r in report.results:
        metric = recognise(r.test_name)
        value = to_hymn_unit(metric, r.value, r.unit) if metric else None
        line = {"test_name": r.test_name, "value": r.value, "unit": r.unit, "reference_range": r.reference_range,
                "flag": r.flag, "metric": metric if value is not None else None}
        if metric and value is None:
            line["check"] = "Hymn couldn't read this value or unit safely; please check it or type it in."
        if value is not None:
            status, why = rate(metric, value, profile, None)
            line |= {"hymn_value": format(value, "f"), "hymn_unit": METRICS[metric][1], "status": status, "why": why}
        results.append(line)
    return {"is_lab_report": True, "report_date": report.report_date, "lab": report.lab, "results": results,
            "note": "Check these against your report before saving. The doctor who asked for the test is the "
                    "best person to explain it."}


class SavedResult(BaseModel):
    test_name: str = Field(max_length=120)
    value: str = Field(max_length=40)
    unit: str = Field(default="", max_length=30)
    reference_range: str = Field(default="", max_length=60)
    flag: str = Field(default="", max_length=20)
    metric: Optional[str] = None             # set for tests Hymn tracks (from /read)


class SaveReport(BaseModel):
    report_date: str
    lab: str = Field(default="", max_length=120)
    results: List[SavedResult] = Field(min_length=1, max_length=300)


@labs_router.post("", status_code=201)
async def save(body: SaveReport, current_user: dict = Depends(get_current_user),
        for_: Optional[str] = Query(default=None, alias="for")):
    uid = await subject(get_db(), current_user, for_)
    db = get_db()
    await _profile(db, uid)
    day = _date(body.report_date)
    tracked = []
    for r in body.results:
        if not r.metric:
            continue
        if r.metric not in TEST_NAMES:
            raise HTTPException(status_code=400, detail=f"Unknown test: {r.metric}")
        v = to_hymn_unit(r.metric, r.value, r.unit)
        if v is None:
            raise HTTPException(status_code=400, detail=f"Please check {r.test_name}: {r.value} {r.unit}")
        tracked.append({"metric": r.metric, "value": float(v), "taken_on": day, "source": "lab",
                        "note": body.lab or "lab report"})
    report_id = str(uuid.uuid4())
    await db.health_lab_reports.insert_one({
        "id": report_id, "user_id": uid, "report_date": day, "lab": body.lab,
        "results": [r.model_dump() for r in body.results], "created_at": datetime.now(timezone.utc).isoformat()})
    await _store(db, uid, tracked)
    return {"id": report_id, "tracked_saved": len(tracked), "kept_as_printed": len(body.results)}


@labs_router.get("")
async def list_reports(current_user: dict = Depends(get_current_user),
        for_: Optional[str] = Query(default=None, alias="for")):
    uid = await subject(get_db(), current_user, for_)
    return await get_db().health_lab_reports.find({"user_id": uid}, {"_id": 0, "user_id": 0}) \
        .sort("report_date", -1).to_list(length=200)


@labs_router.delete("/{report_id}")
async def delete_report(report_id: str, current_user: dict = Depends(get_current_user),
        for_: Optional[str] = Query(default=None, alias="for")):
    uid = await subject(get_db(), current_user, for_)
    db = get_db()
    rep = await db.health_lab_reports.find_one({"id": report_id, "user_id": uid})
    if not rep:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.health_lab_reports.delete_one({"id": report_id})
    await db.health_measurements.delete_many({"user_id": uid, "source": "lab",
                                              "taken_on": rep["report_date"],
                                              "note": rep.get("lab") or "lab report"})
    return {"detail": "Deleted"}
