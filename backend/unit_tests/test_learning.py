"""Learning journeys: the AI understands, code checks, computes, schedules and revises."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import learning
import learning_ai
import nudges
from claude_client import AssistantUnavailable
from learning_ai import Chapter, Fact, Intake, QA, Question, Requirement, Stage, Structure, Subject

TODAY = date.today()
EXAM = (TODAY + timedelta(days=400)).isoformat()


def _day(n):
    return (TODAY + timedelta(days=n)).isoformat()


def ca_structure(exam=EXAM):
    def sub(key, name, cls, selfh, src="https://example.org/hours", chapters=2):
        return Subject(key=key, name=name, class_hours=cls, self_study_hours=selfh, hours_source=src, exam_hours=3,
                       chapters=[Chapter(key=f"c{i}", name=f"{name} ch {i}", weight=1) for i in range(1, chapters + 1)])
    return Structure(
        facts=[Fact(key="windows", label="Exam windows", value="May and November",
                    source_url="https://icai.org/notice", sources_disagree=True, alternatives=["Jan, May, Sep"]),
               Fact(key="pass", label="Passing", value="40 per paper, 50% aggregate", source_url="https://icai.org")],
        stages=[Stage(key="g1", name="Group I", exam_date=exam, exam_date_source="https://icai.org/dates",
                      subjects=[sub("fr", "Financial Reporting", 250, 200), sub("afm", "AFM", 150, 150),
                                sub("audit", "Audit", 150, 120, src="")]),
                Stage(key="g2", name="Group II", exam_date=exam, exam_date_source="https://icai.org/dates",
                      subjects=[sub("dt", "Direct Tax", 250, 200), sub("idt", "Indirect Tax", 120, 120),
                                sub("ibs", "IBS", 0, 60)])],
        requirements=[Requirement(what="Finish articleship", due=_day(300), source_url="https://icai.org/art"),
                      Requirement(what="Register for the exam", due=_day(330), source_url="https://icai.org/reg",
                                  fee=3300)],
        techniques=["Close the book and recall before checking"])


def driving_structure():
    return Structure(
        facts=[Fact(key="ll", label="Learner's licence", value="Hold for 30 days before the test",
                    source_url="https://transport.example.gov.in")],
        stages=[Stage(key="road", name="Driving", exam_date=_day(120), exam_date_source="https://transport.example",
                      subjects=[Subject(key="rules", name="Road rules", class_hours=0, self_study_hours=2,
                                        hours_source="https://transport.example",
                                        chapters=[Chapter(key="signs", name="Signs", weight=1),
                                                  Chapter(key="rules", name="Rules", weight=1)]),
                                Subject(key="drive", name="Driving practice", class_hours=10, self_study_hours=0,
                                        hours_source="https://school.example",
                                        chapters=[Chapter(key="controls", name="Controls", weight=1)])])],
        requirements=[])


@pytest.fixture()
def user(client):
    b = client.post("/api/auth/signup", json={"name": "Asha", "email": "learn@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"}).json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


@pytest.fixture()
def ai(monkeypatch):
    calls = {"structure": 0, "recall": 0, "shape": "exam", "structure_fn": ca_structure}

    async def intake(goal):
        return Intake(title="CA", shape=calls["shape"], questions=[
            Question(key="level", question="Which level are you at?", options=["Foundation", "Intermediate", "Final"]),
            Question(key="attempt", question="Which attempt are you aiming for?")])

    async def structure(goal, title, shape, answers, today):
        calls["structure"] += 1
        calls["answers"] = answers
        return calls["structure_fn"]()

    async def recall(journey, subject, chapter, n=3):
        calls["recall"] += 1
        return [QA(question=f"What is the key idea of {chapter}?", answer="…")]

    monkeypatch.setattr(learning_ai, "intake", intake)
    monkeypatch.setattr(learning_ai, "structure", structure)
    monkeypatch.setattr(learning_ai, "recall_questions", recall)
    return calls


def _start(client, user, answers=None):
    h = user["headers"]
    j = client.post("/api/learning", headers=h, json={"goal": "CA"}).json()
    r = client.post(f"/api/learning/{j['id']}/answers", headers=h,
                    json={"answers": answers or {"level": "Final", "attempt": "next", "weekly_hours": "10",
                                                 "leave_weeks": "0"}})
    assert r.status_code == 200, r.text
    return j, r.json()


# --- 1. Asking ------------------------------------------------------------------

def test_starting_asks_where_you_are_and_adds_hours(client, user, ai, monkeypatch):
    j = client.post("/api/learning", headers=user["headers"], json={"goal": "CA"}).json()
    keys = [q["key"] for q in j["questions"]]
    assert keys == ["level", "attempt", "weekly_hours", "leave_weeks"] and j["status"] == "asking"
    _, plan = _start(client, user)
    assert ai["answers"] == {"level": "Final", "attempt": "next"}        # hours stay with Hymn, not the AI

    async def down(goal):
        raise AssistantUnavailable("x")
    monkeypatch.setattr(learning_ai, "intake", down)
    before = len(client.get("/api/learning", headers=user["headers"]).json())
    assert client.post("/api/learning", headers=user["headers"], json={"goal": "CFA"}).status_code == 503
    assert len(client.get("/api/learning", headers=user["headers"]).json()) == before   # nothing kept


# --- 2. Checking -------------------------------------------------------------------

def test_disagreements_and_unsourced_estimates_must_be_confirmed(client, user, ai):
    h = user["headers"]
    j, v = _start(client, user)
    keys = {c["key"]: c for c in v["checks"]}
    assert keys["fact:windows"]["options"] == ["May and November", "Jan, May, Sep"]
    assert "hours:g1.audit" in keys and "Hymn's estimate" in keys["hours:g1.audit"]["what"]
    assert v["can_start"] is False
    r = client.post(f"/api/learning/{j['id']}/accept", headers=h)
    assert r.status_code == 400 and len(r.json()["detail"]["checks"]) == 2
    v = client.patch(f"/api/learning/{j['id']}", headers=h, json={
        "fact_choices": {"windows": "May and November"}, "confirmed": ["hours:g1.audit"]}).json()
    assert v["checks"] == [] and v["can_start"] is True


def test_impossible_dates_are_errors_not_confirmations(client, user, ai):
    h = user["headers"]
    ai["structure_fn"] = lambda: ca_structure(exam=_day(-5))
    j, v = _start(client, user)
    errors = [c for c in v["checks"] if c["level"] == "error"]
    assert any("already passed" in c["what"] for c in errors)
    v = client.patch(f"/api/learning/{j['id']}", headers=h, json={"confirmed": [c["key"] for c in errors]}).json()
    assert any(c["level"] == "error" for c in v["checks"])                 # can't wave an error away
    v = client.patch(f"/api/learning/{j['id']}", headers=h, json={"stage_dates": {"g1": _day(400), "g2": _day(400)}}).json()
    assert not any("already passed" in c["what"] for c in v["checks"])
    unknown = ca_structure()
    unknown.stages[1].exam_date = ""
    assert any(c["key"] == "date:g2" and c["level"] == "error"
               for c in learning.checks({"shape": "exam", "structure": unknown.model_dump()}, TODAY))
    assert not any(c["key"] == "date:g2" for c in learning.checks(
        {"shape": "exam", "structure": unknown.model_dump(), "stage_dates": {"g2": _day(400)}}, TODAY))
    late = ca_structure()
    late.requirements[0].due = _day(500)                                    # articleship after the exam
    jj = {"shape": "exam", "structure": late.model_dump()}
    assert any(c["level"] == "error" and "after the exam" in c["what"] for c in learning.checks(jj, TODAY))


# --- 3. Hours, fit and phases ----------------------------------------------------------

def test_hours_follow_where_you_are_and_include_revision(client, user, ai):
    h = user["headers"]
    j, v = _start(client, user)
    v = client.patch(f"/api/learning/{j['id']}", headers=h, json={
        "subject_status": {"g1.fr": "classes_done", "g2.ibs": "done"}}).json()
    fr = next(s for s in v["plan"]["stages"][0]["subjects"] if s["key"] == "g1.fr")
    # classes done: 200 self-study left; revisions 1d/1w/1m/3m/6m = 50% of it; practice 10% + 2 mocks × 3h × 2;
    # final revisions 30% of self-study.
    assert (fr["learning"], fr["reviews"], fr["practice"], fr["final_revision"]) == (200.0, 100.0, 32.0, 60.0)
    ibs = next(s for s in v["plan"]["stages"][1]["subjects"] if s["key"] == "g2.ibs")
    assert ibs["total"] == 0
    assert v["plan"]["verdict"] == "short"                                  # 10 h/week isn't enough
    opts = {o["option"] for o in v["plan"]["options"]}
    assert {"study_more", "later"} <= opts
    g2 = v["plan"]["stages"][1]
    assert g2["short_by_hours"] > 0 and g2["needs_weekly_hours"] > 10
    v = client.patch(f"/api/learning/{j['id']}", headers=h, json={"weekly_hours": 50, "leave_weeks": 12,
                                                                 "leave_weekly_hours": 70}).json()
    assert v["plan"]["verdict"] == "fits"
    ph = v["plan"]["stages"][0]["phases"]
    assert ph["learning_from"] <= ph["practice_from"] <= ph["revision_1_from"] <= ph["revision_2_from"] <= EXAM
    assert ph["study_leave_from"] == (date.fromisoformat(EXAM) - timedelta(weeks=12)).isoformat()


def test_one_stage_at_a_time_is_offered_when_both_dont_fit(client, user, ai):
    h = user["headers"]
    j, v = _start(client, user)
    v = client.patch(f"/api/learning/{j['id']}", headers=h, json={"weekly_hours": 40}).json()
    g1, g2 = v["plan"]["stages"]
    assert g1["fits"] and not g2["fits"]
    assert any(o["option"] == "one_stage" and "Group I" in o["what"] for o in v["plan"]["options"])


# --- 4. Starting -------------------------------------------------------------------------

def _accept(client, user, j):
    h = user["headers"]
    client.patch(f"/api/learning/{j['id']}", headers=h, json={
        "fact_choices": {"windows": "May and November"}, "confirmed": ["hours:g1.audit"]})
    r = client.post(f"/api/learning/{j['id']}/accept", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_accepting_adds_requirements_and_fees(client, server, user, ai):
    j, _ = _start(client, user)
    v = _accept(client, user, j)
    assert v["status"] == "active" and "pace" in v
    tasks = asyncio.run(server.db.tasks.find({"learning_journey_id": j["id"]}, {"_id": 0}).to_list(None))
    assert sorted(t["title"] for t in tasks) == ["Finish articleship", "Register for the exam"]
    fee = asyncio.run(server.db.planned_money.find_one({"learning_journey_id": j["id"]}, {"_id": 0}))
    assert fee["amount"].to_decimal() == 3300 and fee["date"] == _day(330)
    assert client.post(f"/api/learning/{j['id']}/accept", headers=user["headers"]).status_code == 409
    other = client.post("/api/auth/signup", json={"name": "O", "email": "ol@example.com",
                                                  "password": "correct-horse-battery", "security_question": "Q?",
                                                  "security_answer": "A"}).json()
    assert client.get(f"/api/learning/{j['id']}",
                      headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 404
    client.delete(f"/api/learning/{j['id']}", headers=user["headers"])
    assert asyncio.run(server.db.planned_money.count_documents({"learning_journey_id": j["id"]})) == 0


# --- 5. Every day ---------------------------------------------------------------------------

def test_review_ladder_moves_with_how_it_went():
    d = date(2026, 1, 1)
    assert learning.after_review(0, "ok", d) == (1, "2026-01-08")          # 1 day → 1 week
    assert learning.after_review(1, "easy", d) == (3, "2026-04-01")        # skip a step: 3 months
    assert learning.after_review(2, "hard", d) == (2, "2026-01-08")        # stay, sooner (1 week)
    assert learning.after_review(0, "hard", d) == (0, "2026-01-02")
    assert learning.after_review(4, "ok", d) == (5, None)                  # learned for good


def test_days_learn_then_revise_then_practise(client, server, user, ai):
    h = user["headers"]
    ai["shape"], ai["structure_fn"] = "skill", driving_structure
    j, v = _start(client, user, {"level": "Never driven", "weekly_hours": "6"})
    assert v["checks"] == []
    client.post(f"/api/learning/{j['id']}/accept", headers=h)
    t = client.get(f"/api/learning/{j['id']}/today?date={_day(0)}", headers=h).json()
    # 6 h/week over 6 days = 60 min: two subjects interleaved.
    assert t["minutes"] == 60 and {s["subject"] for s in t["sessions"]} == {"Road rules", "Driving practice"}
    signs = next(s for s in t["sessions"] if s["chapter"] == "Signs")
    r = client.post(f"/api/learning/{j['id']}/sessions", headers=h, json={
        "kind": "learn", "chapter_key": signs["chapter_key"], "minutes": 60, "date": _day(0)}).json()
    assert r["chapter"]["learned_on"] == _day(0) and r["chapter"]["next_review"] == _day(1)
    t2 = client.get(f"/api/learning/{j['id']}/today?date={_day(1)}", headers=h).json()
    first = t2["sessions"][0]
    assert (first["kind"], first["chapter"], first["minutes"]) == ("review", "Signs", 12)   # 20% of 60, revision first
    assert client.post(f"/api/learning/{j['id']}/sessions", headers=h, json={
        "kind": "review", "chapter_key": first["chapter_key"], "minutes": 12, "date": _day(1)}).status_code == 400
    r = client.post(f"/api/learning/{j['id']}/sessions", headers=h, json={
        "kind": "review", "chapter_key": first["chapter_key"], "minutes": 12, "date": _day(1), "rating": "ok"}).json()
    assert r["chapter"]["next_review"] == _day(8)
    # Missed: a review not done stays due, marked overdue.
    t3 = client.get(f"/api/learning/{j['id']}/today?date={_day(10)}", headers=h).json()
    assert t3["sessions"][0]["overdue_days"] == 2


def test_after_learning_comes_practice_and_revision(client, server, user, ai):
    h = user["headers"]
    j, _ = _start(client, user)
    _accept(client, user, j)
    doc = asyncio.run(server.db.learning_journeys.find_one({"id": j["id"]}, {"_id": 0}))
    chs = learning.chapters_of(doc, TODAY)
    asyncio.run(server.db.learning_journeys.update_one({"id": j["id"]}, {"$set": {
        "progress": {c["key"]: {"learned": c["learn_minutes"]} for c in chs if c["stage"] == "g1"}}}))
    s = client.get(f"/api/learning/{j['id']}/today", headers=h).json()["sessions"]
    assert {x["kind"] for x in s} == {"practice"} and s[0]["chapter"] == "Mock papers and questions"
    r = client.post(f"/api/learning/{j['id']}/sessions", headers=h, json={
        "kind": "practice", "subject_key": s[0]["subject_key"], "minutes": 30, "date": _day(0)})
    assert r.status_code == 201


def test_recall_questions_are_written_once(client, user, ai, monkeypatch):
    h = user["headers"]
    j, _ = _start(client, user)
    key = "g1.fr.c1"
    q1 = client.get(f"/api/learning/{j['id']}/chapters/{key}/questions", headers=h).json()
    q2 = client.get(f"/api/learning/{j['id']}/chapters/{key}/questions", headers=h).json()
    assert q1 == q2 and ai["recall"] == 1

    async def down(*a, **k):
        raise AssistantUnavailable("x")
    monkeypatch.setattr(learning_ai, "recall_questions", down)
    r = client.get(f"/api/learning/{j['id']}/chapters/g1.fr.c2/questions", headers=h)
    assert r.status_code == 503 and "rate it" in r.json()["detail"]


# --- 6. Ties to time, health and nudges ---------------------------------------------------------

def test_study_counts_as_learning_time_and_health(client, server, user, ai):
    h = user["headers"]
    ai["shape"], ai["structure_fn"] = "skill", driving_structure
    j, _ = _start(client, user, {"weekly_hours": "6"})
    client.post(f"/api/learning/{j['id']}/accept", headers=h)
    client.post(f"/api/learning/{j['id']}/sessions", headers=h, json={
        "kind": "learn", "chapter_key": "road.rules.signs", "minutes": 20, "date": _day(0)})
    assert asyncio.run(server.db.health_measurements.count_documents({"user_id": user["id"]})) == 0   # no consent
    client.put("/api/health/profile", headers=h, json={"consent": True})
    client.post(f"/api/learning/{j['id']}/sessions", headers=h, json={
        "kind": "learn", "chapter_key": "road.rules.signs", "minutes": 25, "date": _day(0)})
    t = client.get(f"/api/reports/time?week_start={_day(0)}", headers=h).json()
    area = next(a for a in t["spent"]["areas"] if a["area"] == "learning")
    assert area["actual_hours"] == "0.8"
    rows = client.get("/api/health/measurements?metric=learning_hours", headers=h).json()
    assert [r["value"] for r in rows] == [0.8]


def test_daily_study_nudge_and_deadlines(client, server, user, ai):
    db = server.db
    asyncio.run(nudges.ensure_nudge_indexes(db))
    asyncio.run(db.users.update_one({"id": user["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    j, _ = _start(client, user)
    _accept(client, user, j)
    k = ZoneInfo("Asia/Kolkata")
    d = datetime.now(k).date()
    # Requirement "Finish articleship" is due in 300 days: warn at 14 days.
    asyncio.run(db.learning_journeys.update_one({"id": j["id"]}, {"$set": {
        "structure.requirements.0.due": (d + timedelta(days=14)).isoformat()}}))
    at = datetime(d.year, d.month, d.day, 7, 5, tzinfo=k).astimezone(timezone.utc)
    got = [n for n in asyncio.run(nudges.run_due_nudges(db, at)) if n["kind"].startswith("learning")]
    kinds = sorted(n["kind"] for n in got)
    assert kinds == ["learning_deadline", "learning_today"]
    today = next(n for n in got if n["kind"] == "learning_today")
    assert today["title"].startswith("CA: ") and "min today" in today["title"]
    assert [n for n in asyncio.run(nudges.run_due_nudges(db, at + timedelta(minutes=20)))
            if n["kind"].startswith("learning")] == []


def test_structure_reply_is_read_and_checked(monkeypatch):
    import json

    import claude_client
    good = ca_structure().model_dump()
    replies = iter(["Here you go:\n```json\n" + json.dumps(good) + "\n```"])

    async def fake(**kw):
        assert any(t.get("name") == "web_search" for t in kw["tools"])      # facts come from the web
        return next(replies)
    monkeypatch.setattr(claude_client, "complete_text", fake)
    st = asyncio.run(learning_ai.structure("CA", "CA", "exam", {"level": "Final"}, TODAY.isoformat()))
    assert st.stages[0].subjects[0].name == "Financial Reporting"
    calls = {"n": 0}

    async def broken(**kw):
        calls["n"] += 1
        return "Sorry, I couldn't find it."
    monkeypatch.setattr(claude_client, "complete_text", broken)
    with pytest.raises(AssistantUnavailable):
        asyncio.run(learning_ai.structure("CA", "CA", "exam", {}, TODAY.isoformat()))
    assert calls["n"] == 2                                                  # one retry, then give up
