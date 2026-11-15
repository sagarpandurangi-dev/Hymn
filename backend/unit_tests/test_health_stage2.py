"""Health stage 2: any-watch sync, lab reports (optional), check-up calendar,
90-day progress and the doctor summary."""
from __future__ import annotations

import base64
from datetime import date, timedelta

import pytest

import health_labs
from claude_client import AssistantUnavailable
from health_checkups import add_months, calendar_for
from health_labs import PrintedResult, Report, recognise, to_hymn_unit
from health_reports import progress

TODAY = date.today()
B64 = base64.b64encode(b"%PDF-1.4 fake").decode()


def _day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _signup(client, email, profile=None):
    b = client.post("/api/auth/signup", json={"name": "Asha", "email": email, "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"}).json()
    h = {"Authorization": f"Bearer {b['access_token']}"}
    client.put("/api/health/profile", headers=h, json={"consent": True, **(profile or {})})
    return h


@pytest.fixture()
def h(client):
    return _signup(client, "s2@example.com", {"date_of_birth": "1990-05-01", "sex": "female",
                                              "medicines": ["Metformin 500"], "family_history": ["diabetes"],
                                              "doctor_questions": ["Should I check vitamin D?"]})


# --- Watch sync -------------------------------------------------------------

def test_any_watch_syncs_and_your_own_entry_wins(client, h):
    r = client.post("/api/health/sync", headers=h, json={"source_app": "Fitbit", "readings": [
        {"metric": "steps", "value": 6000, "date": _day(1)},
        {"metric": "steps", "value": 9000, "date": _day(0)},
        {"metric": "weight_kg", "value": 154, "unit": "lb", "date": _day(0)},
        {"metric": "sleep_hours", "value": 420, "unit": "minutes", "date": _day(0)},
        {"metric": "steps", "value": -5, "date": _day(0)},                 # bad
        {"metric": "hba1c", "value": 5.5, "date": _day(0)},                # not something a watch sends
    ]}).json()
    assert (r["saved"], r["skipped"]) == (4, 2)
    # Re-sync of today replaces, never duplicates.
    client.post("/api/health/sync", headers=h, json={"source_app": "Fitbit", "device": "Charge 6", "readings": [
        {"metric": "steps", "value": 9500, "date": _day(0)}]})
    rows = client.get("/api/health/measurements?metric=steps", headers=h).json()
    assert sorted(r["value"] for r in rows) == [6000, 9500]
    w = client.get("/api/health/measurements?metric=weight_kg", headers=h).json()[0]
    assert abs(w["value"] - 69.85) < 0.01 and w["source"] == "watch" and w["note"] == "Fitbit"
    # A second brand works the same way.
    client.post("/api/health/sync", headers=h, json={"source_app": "Apple Health", "readings": [
        {"metric": "resting_hr", "value": 64, "date": _day(0)}]})
    status = client.get("/api/health/sync", headers=h).json()
    assert {s["source_app"] for s in status["sources"]} == {"Fitbit", "Apple Health"}
    assert any(x["hub"] == "No watch" for x in status["hubs"])
    # What you type for a day beats the watch for that day.
    client.post("/api/health/daily", headers=h, json={"date": _day(0), "sleep_hours": 5})
    dash = client.get("/api/health/dashboard", headers=h).json()
    sleep = next(i for d in dash["domains"] for i in d["indicators"] if i["metric"] == "sleep_hours")
    assert sleep["value"] == "5.0" and sleep["source"] == "you"
    # Disconnect can take its data with it.
    r = client.post("/api/health/sync/disconnect", headers=h, json={"source_app": "Fitbit", "delete_data": True})
    assert r.json()["readings_deleted"] == 4
    assert client.get("/api/health/measurements?metric=steps", headers=h).json() == []


# --- Lab reports --------------------------------------------------------------

def test_lab_names_and_units_are_recognised_safely():
    assert recognise("Glucose (Fasting)") == "fasting_glucose" and recognise("HbA1c (Glycated Haemoglobin)") == "hba1c"
    assert recognise("LDL Cholesterol (Direct)") == "ldl" and recognise("Non-HDL Cholesterol") is None
    assert recognise("Cholesterol/HDL Ratio") is None and recognise("VLDL") is None
    assert recognise("Urine Albumin Creatinine Ratio") == "uacr" and recognise("TSH") is None
    assert str(to_hymn_unit("fasting_glucose", "5.6", "mmol/L")) == "100.8"
    assert str(to_hymn_unit("hba1c", "48", "mmol/mol")) == "6.5"
    assert str(to_hymn_unit("triglycerides", "1.7", "mmol/L")) == "150.6"
    assert to_hymn_unit("fasting_glucose", "98", "mg%") is None            # unexpected unit: don't guess
    assert to_hymn_unit("ldl", "9999", "mg/dL") is None                     # implausible


def _report():
    async def fake(data, media_type):
        return Report(is_lab_report=True, report_date=_day(3), lab="City Diagnostics", results=[
            PrintedResult(test_name="Glucose, Fasting", value="5.6", unit="mmol/L", reference_range="3.9-5.5", flag="H"),
            PrintedResult(test_name="HbA1c", value="6.1", unit="%", reference_range="<5.7", flag="H"),
            PrintedResult(test_name="Non-HDL Cholesterol", value="150", unit="mg/dL", reference_range="<130", flag=""),
            PrintedResult(test_name="TSH", value="2.1", unit="uIU/mL", reference_range="0.4-4.0", flag=""),
        ])
    return fake


def test_lab_report_read_confirm_save(client, h, monkeypatch):
    monkeypatch.setattr(health_labs, "read_report", _report())
    r = client.post("/api/health/labs/read", headers=h, json={"file_base64": B64,
                                                              "media_type": "application/pdf"}).json()
    glucose, a1c, nonhdl, tsh = r["results"]
    assert glucose["metric"] == "fasting_glucose" and glucose["hymn_value"] == "100.8" and glucose["status"] == "amber"
    assert a1c["status"] == "amber" and nonhdl["metric"] is None and tsh["metric"] is None
    assert "doctor" in r["note"]
    saved = client.post("/api/health/labs", headers=h, json={"report_date": r["report_date"], "lab": r["lab"],
                                                             "results": r["results"]}).json()
    assert (saved["tracked_saved"], saved["kept_as_printed"]) == (2, 4)
    rows = client.get("/api/health/measurements?metric=hba1c", headers=h).json()
    assert rows[0]["source"] == "lab" and rows[0]["taken_on"] == _day(3)
    # Deleting the report removes its values.
    client.delete(f"/api/health/labs/{saved['id']}", headers=h)
    assert client.get("/api/health/measurements?metric=hba1c", headers=h).json() == []


def test_lab_reading_allowance_and_outage(client, h, monkeypatch):
    monkeypatch.setenv("HYMN_LAB_READS_FREE", "1")

    async def down(data, media_type):
        raise AssistantUnavailable("x")
    monkeypatch.setattr(health_labs, "read_report", down)
    body = {"file_base64": B64, "media_type": "application/pdf"}
    assert client.post("/api/health/labs/read", headers=h, json=body).status_code == 503
    monkeypatch.setattr(health_labs, "read_report", _report())
    assert client.post("/api/health/labs/read", headers=h, json=body).status_code == 200
    r = client.post("/api/health/labs/read", headers=h, json=body)
    assert r.status_code == 429 and "type" in r.json()["detail"]


# --- Check-up calendar ----------------------------------------------------------

def test_checkups_fit_the_person():
    woman = {"date_of_birth": "1990-05-01", "sex": "female", "family_history": ["diabetes"]}
    keys = lambda cal: {c["key"]: c for c in cal["checks"]}
    cal = keys(calendar_for(woman, [], {}, TODAY))
    assert {"blood_pressure", "diabetes", "lipids", "dental", "cervical", "breast", "oral_cancer"} <= set(cal)
    assert cal["diabetes"]["every_months"] == 12 and cal["diabetes"]["status"] == "never"   # family history
    assert "kidney" not in cal and "bones" not in cal
    man = keys(calendar_for({"date_of_birth": "2000-01-01", "sex": "male"}, [], {}, TODAY))
    assert "cervical" not in man and "diabetes" not in man and man["lipids"]["every_months"] == 60
    diabetic = keys(calendar_for({"date_of_birth": "1970-01-01", "sex": "male", "conditions": ["diabetes"]},
                                 [], {}, TODAY))
    assert {"kidney", "diabetic_eye", "diabetes_review"} <= set(diabetic) and "diabetes" not in diabetic
    assert diabetic["blood_pressure"]["every_months"] == 6
    # A logged value counts as done.
    rows = [{"metric": "bp_systolic", "value": 118, "taken_on": _day(400), "source": "you"}]
    bp = keys(calendar_for(woman, rows, {}, TODAY))["blood_pressure"]
    assert bp["status"] == "overdue" and bp["last_done"] == _day(400)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_mark_a_checkup_done(client, h):
    cal = client.post("/api/health/checkups/dental/done", headers=h, json={"date": _day(10)}).json()
    dental = next(c for c in cal["checks"] if c["key"] == "dental")
    assert dental["status"] == "ok" and dental["last_done"] == _day(10)
    assert client.post("/api/health/checkups/dental/done", headers=h,
                       json={"date": (TODAY + timedelta(days=2)).isoformat()}).status_code == 400
    assert client.post("/api/health/checkups/nope/done", headers=h, json={"date": _day(1)}).status_code == 404


# --- 90-day progress --------------------------------------------------------------

def _rows(metric, value, days):
    return [{"metric": metric, "value": value, "taken_on": _day(d), "source": "you"} for d in days]


def test_ninety_day_progress():
    start = TODAY - timedelta(days=95)
    early, late = range(95, 70, -2), range(35, 5, -2)          # days ago
    rows = (_rows("steps", 4000, early) + _rows("steps", 8000, late) + _rows("sugary_items", 3, early)
            + _rows("sugary_items", 1, late) + _rows("sleep_hours", 5.5, early) + _rows("sleep_hours", 7.5, late)
            + _rows("weight_kg", 80, [94]) + _rows("weight_kg", 77, [10]) + _rows("stress", 3, early)
            + _rows("stress", 3, late))
    p = progress(rows, start, TODAY)
    v = {l["metric"]: l for l in p["lines"]}
    assert p["complete"] and v["steps"]["verdict"] == "better" and v["steps"]["change"] == "4000.0"
    assert v["sugary_items"]["verdict"] == "better" and v["sleep_hours"]["verdict"] == "better"
    assert v["weight_kg"]["verdict"] == "changed" and v["stress"]["verdict"] == "steady"   # no verdict on weight
    early_only = progress(rows, TODAY - timedelta(days=10), TODAY)
    assert early_only["lines"] == [] and "Day 11 of 90" in early_only["note"]


# --- Doctor summary --------------------------------------------------------------------

def test_doctor_summary(client, h, monkeypatch):
    client.post("/api/health/daily", headers=h, json={"date": _day(2), "symptoms": ["fainting"], "sleep_hours": 6})
    client.post("/api/health/measurements", headers=h, json=[{"metric": "bp_systolic", "value": 138,
                                                               "taken_on": _day(5)}])
    client.post("/api/habits", headers=h, json={"kind": "tobacco", "goal": "quit", "baseline_per_day": 5})
    client.post("/api/habits", headers=h, json={"kind": "other", "label": "Nail biting", "goal": "quit",
                                                "baseline_per_day": 5})
    monkeypatch.setattr(health_labs, "read_report", _report())
    r = client.post("/api/health/labs/read", headers=h, json={"file_base64": B64,
                                                              "media_type": "application/pdf"}).json()
    client.post("/api/health/labs", headers=h, json={"report_date": r["report_date"], "lab": r["lab"],
                                                     "results": r["results"]})
    s = client.get("/api/health/doctor-summary", headers=h).json()
    assert s["medicines"] == ["Metformin 500"] and s["questions"] == ["Should I check vitamin D?"]
    assert s["symptoms_90_days"][0]["what"] == "Fainting"
    assert [x["habit"] for x in s["habits"]] == ["Smoking / tobacco"]                      # private habit left out
    assert len(s["latest_lab_report"]["results"]) == 4
    bp = next(x for x in s["readings"] if x["metric"] == "bp_systolic")
    assert (bp["value"], bp["date"], bp["source"]) == ("138.0", _day(5), "you")
    with_private = client.get("/api/health/doctor-summary?include_private=true", headers=h).json()
    assert len(with_private["habits"]) == 2
    text = client.get("/api/health/doctor-summary?format=text", headers=h).text
    assert "Metformin 500" in text and "TSH: 2.1 uIU/mL (ref 0.4-4.0)" in text and "Nail biting" not in text
    assert "not a diagnosis" in text
    # Delete-all removes the new kinds of health data too.
    client.delete("/api/health/all", headers=h)
    _ = client.put("/api/health/profile", headers=h, json={"consent": True})
    s = client.get("/api/health/doctor-summary", headers=h).json()
    assert s["symptoms_90_days"] == [] and s["latest_lab_report"] is None and s["readings"] == []
