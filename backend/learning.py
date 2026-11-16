"""Learning journeys: any goal — CA, CFA, 10th boards, driving, a language.

The flow (the AI understands; code decides every number):

1. ``POST /api/learning {goal}`` — the AI names the goal, picks its shape
   (exam / skill / fluency / project) and asks 3–5 starting-point questions
   ("Which level are you at?"). Hymn always adds: hours a week, and for
   exams, weeks of study leave before the exam.
2. ``POST /{id}/answers`` — the AI looks up the structure on the web with
   sources (stages → subjects → chapters, exam dates, requirements such as
   articleship, fees), only for what's left. Code then **checks** it: every
   hard fact needs a source; sources that disagree, estimates without a
   source and missing exam dates are marked "please confirm"; past dates,
   dates out of order and requirements due after the exam are errors.
3. Code computes the hours left per subject from where the person is
   (``subject_status``), adds spaced revision (1 day, 1 week, 1 month, 3
   months, 6 months after learning, each shorter), practice and mock
   exams, and final revisions; checks it against their hours a week (and
   their free time) up to each exam; and works out the phases backwards
   from each exam. If it doesn't fit, it gives options: more hours a week,
   a later attempt (the date it would fit), or one stage at a time.
4. ``PATCH /{id}`` — the person answers the checks, sets subject status,
   edits estimates, hours, dates. Recomputed in code (no AI).
5. ``POST /{id}/accept`` — only when nothing is left to confirm: tasks for
   requirements, fees into planned money, the journey goes active.
6. Every day, code (free) builds the day's sessions: due revisions first,
   then new chapters, two subjects interleaved; then practice and
   revision. After each revision the person rates it Easy / OK / Hard:
   Hard brings the next one sooner, Easy pushes it further. Missed
   sessions simply stay due. Recall questions per chapter come from the
   AI once and are kept. Study time counts in time statements and (with
   the health consent) Health's "Learning something new".

DRAFT defaults (``STATUS_REMAINING``, ``REVIEW_LADDER``, shares) are Hymn's
assumptions, shown to the person and editable through their estimates.
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import learning_ai
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db

learning_router = APIRouter(prefix="/learning", tags=["learning"])

# Share of class hours / self-study hours still ahead, by where the person is.
STATUS_REMAINING = {"not_started": (1.0, 1.0), "attending_classes": (0.5, 1.0), "classes_done": (0.0, 1.0),
                    "first_reading_done": (0.0, 0.4), "revising": (0.0, 0.15), "done": (0.0, 0.0)}
# Revisions after a chapter is learned: (days after, share of its learning minutes).
REVIEW_LADDER = [(1, 0.20), (7, 0.12), (30, 0.08), (90, 0.06), (180, 0.04)]
MIN_SESSION, MAX_REVIEW, MAX_LEARN = 5, 45, 60
PRACTICE_SHARE = 0.10            # question practice, share of self-study left
MOCKS_PER_PAPER = 2              # full mock papers (each: write + check = 2 × the paper's length)
FINAL_REVISION_SHARE = (0.20, 0.10)   # first and second revision, shares of self-study
DEFAULT_WEEKLY_HOURS = 10
LEAVE_WEEKLY_HOURS = 40
STUDY_DAYS = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(s: str) -> Optional[date_type]:
    try:
        return date_type.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def _h(minutes: float) -> float:
    return round(minutes / 60, 1)


# ---------------------------------------------------------------------------
# Checks (pure)
# ---------------------------------------------------------------------------

def stage_date(j: dict, stage: dict) -> Optional[date_type]:
    return _d((j.get("stage_dates") or {}).get(stage["key"]) or stage.get("exam_date"))


def checks(j: dict, today: date_type) -> List[dict]:
    """What must be confirmed (``confirm``) or fixed (``error``) before the
    journey can start. A confirm is cleared by listing its key in
    ``confirmed`` (or, for a fact, choosing a value)."""
    out = []
    s = j["structure"]
    chosen = j.get("fact_choices") or {}
    for f in s.get("facts", []):
        key = f"fact:{f['key']}"
        if f.get("sources_disagree") and f["key"] not in chosen:
            out.append({"key": key, "level": "confirm", "what": f"Sources disagree on {f['label']}",
                        "options": [f["value"]] + list(f.get("alternatives") or [])})
        elif not f.get("source_url") and f["key"] not in chosen:
            out.append({"key": key, "level": "confirm", "what": f"{f['label']}: {f['value']} (no source found)"})
    prev = None
    for st in s.get("stages", []):
        when = stage_date(j, st)
        if j["shape"] == "exam" and when is None:
            out.append({"key": f"date:{st['key']}", "level": "error",
                        "what": f"Exam date for {st['name']} isn't known yet; please set it"})
        elif when is not None:
            if when <= today:
                out.append({"key": f"date:{st['key']}", "level": "error",
                            "what": f"{st['name']}: {when.isoformat()} has already passed"})
            if prev and when < prev:
                out.append({"key": f"date:{st['key']}", "level": "error",
                            "what": f"{st['name']} is dated before the stage before it"})
            if not st.get("exam_date_source") and not (j.get("stage_dates") or {}).get(st["key"]):
                out.append({"key": f"datesrc:{st['key']}", "level": "confirm",
                            "what": f"{st['name']} on {when.isoformat()} (no source found)"})
            prev = when
        for sub in st.get("subjects", []):
            k = f"{st['key']}.{sub['key']}"
            edited = k in (j.get("estimates") or {})
            if not edited and (sub.get("class_hours", 0) + sub.get("self_study_hours", 0)) <= 0:
                out.append({"key": f"hours:{k}", "level": "error", "what": f"{sub['name']}: how many hours?"})
            elif not edited and not sub.get("hours_source"):
                out.append({"key": f"hours:{k}", "level": "confirm",
                            "what": f"{sub['name']}: about {sub.get('class_hours', 0):g} class + "
                                    f"{sub.get('self_study_hours', 0):g} self-study hours (Hymn's estimate)"})
    last = max((d for d in (stage_date(j, st) for st in s.get("stages", [])) if d), default=None)
    for i, r in enumerate(s.get("requirements", [])):
        due = _d(r.get("due"))
        if due and due < today:
            out.append({"key": f"req:{i}", "level": "confirm", "what": f"{r['what']}: due {due} (already past — done?)"})
        elif due and last and due > last:
            out.append({"key": f"req:{i}", "level": "error",
                        "what": f"{r['what']} is due after the exam ({due}); the exam may need to move"})
        elif r.get("what") and not r.get("source_url"):
            out.append({"key": f"req:{i}", "level": "confirm", "what": f"{r['what']} (no source found)"})
    done = set(j.get("confirmed") or [])
    return [c for c in out if c["level"] == "error" or c["key"] not in done]


# ---------------------------------------------------------------------------
# Hours, fit and phases (pure)
# ---------------------------------------------------------------------------

def subject_hours(j: dict, stage: dict, sub: dict, exam: Optional[date_type], today: date_type) -> dict:
    k = f"{stage['key']}.{sub['key']}"
    est = (j.get("estimates") or {}).get(k) or {}
    cls = float(est.get("class_hours", sub.get("class_hours", 0)) or 0)
    selfh = float(est.get("self_study_hours", sub.get("self_study_hours", 0)) or 0)
    status = (j.get("subject_status") or {}).get(k, "not_started")
    cf, sf = STATUS_REMAINING[status]
    learn = cls * cf + selfh * sf
    days_left = (exam - today).days if exam else None
    review_share = sum(f for off, f in REVIEW_LADDER if days_left is None or off < days_left / 2)
    review = learn * review_share
    practice = 0.0 if status == "done" else selfh * sf * PRACTICE_SHARE
    if j["shape"] == "exam" and status != "done":
        practice += float(sub.get("exam_hours") or 0) * 2 * MOCKS_PER_PAPER
    revision = selfh * sum(FINAL_REVISION_SHARE) if (j["shape"] == "exam" and status != "done") else 0.0
    return {"key": k, "name": sub["name"], "status": status, "learning": learn, "reviews": review,
            "practice": practice, "final_revision": revision, "total": learn + review + practice + revision,
            "source": "you" if est else (sub.get("hours_source") or "Hymn's estimate")}


def _capacity(weekly: float, leave_weeks: int, leave_hours: float, start: date_type, end: date_type) -> float:
    """Study hours available from start to end (exam day), with study leave
    in the last weeks."""
    weeks = max((end - start).days, 0) / 7
    leave = min(leave_weeks, weeks)
    return weekly * (weeks - leave) + leave_hours * leave


def compute(j: dict, today: date_type, free_week_hours: Optional[float] = None) -> dict:
    s = j["structure"]
    weekly = float(j.get("weekly_hours") or DEFAULT_WEEKLY_HOURS)
    leave_weeks = int(j.get("leave_weeks") or 0)
    leave_hours = float(j.get("leave_weekly_hours") or LEAVE_WEEKLY_HOURS)
    stages, cumulative, verdict = [], 0.0, "fits"
    window_start = today
    for st in s.get("stages", []):
        exam = stage_date(j, st)
        subs = [subject_hours(j, st, sub, exam, today) for sub in st.get("subjects", [])]
        need = sum(x["total"] for x in subs)
        cumulative += need
        row = {"key": st["key"], "name": st["name"], "exam_date": exam.isoformat() if exam else None,
               "hours": round(need, 1), "subjects": [{**x, **{f: round(x[f], 1) for f in
                                                               ("learning", "reviews", "practice",
                                                                "final_revision", "total")}} for x in subs]}
        if exam:
            cap = _capacity(weekly, leave_weeks, leave_hours, today, exam)
            row["capacity_hours"] = round(cap, 1)
            row["fits"] = cap >= cumulative
            if not row["fits"]:
                verdict = "short"
                row["short_by_hours"] = round(cumulative - cap, 1)
                weeks = max((exam - today).days / 7 - min(leave_weeks, (exam - today).days / 7), 0.1)
                row["needs_weekly_hours"] = round((cumulative - leave_hours * min(leave_weeks, (exam - today).days / 7))
                                                  / weeks, 1)
                more = math.ceil((cumulative - cap) / weekly) if weekly else 0
                row["would_fit_by"] = (exam + timedelta(weeks=more)).isoformat()
            row["phases"] = phases(subs, exam, window_start, weekly, leave_weeks, leave_hours)
            window_start = exam
        stages.append(row)
    same_day = defaultdict(list)
    for r in stages:
        if r["exam_date"]:
            same_day[r["exam_date"]].append(r)
    options = []
    if verdict == "short":
        worst = next(r for r in stages if r.get("fits") is False)
        options.append({"option": "study_more", "what": f"Study about {worst['needs_weekly_hours']:g} hours a week"})
        options.append({"option": "later", "what": f"Aim for an attempt after {worst['would_fit_by']}"})
        for day, rows in same_day.items():
            if len(rows) > 1 and rows[0].get("capacity_hours", 0) >= rows[0]["hours"]:
                options.append({"option": "one_stage", "what": f"Take {rows[0]['name']} on {day} and the rest "
                                                              f"at a later attempt"})
    out = {"total_hours": round(cumulative, 1), "weekly_hours": weekly, "leave_weeks": leave_weeks,
           "verdict": verdict, "stages": stages, "options": options,
           "assumptions": {"status_remaining": STATUS_REMAINING, "review_ladder_days": [o for o, _ in REVIEW_LADDER],
                           "review_shares": [f for _, f in REVIEW_LADDER], "mocks_per_paper": MOCKS_PER_PAPER,
                           "final_revision_shares": list(FINAL_REVISION_SHARE)}}
    if free_week_hours is not None:
        out["free_week_hours"] = round(free_week_hours, 1)
        if weekly > free_week_hours:
            out["warning"] = (f"Your time blocks leave about {free_week_hours:.0f} free hours a week; "
                              f"{weekly:g} hours of study won't fit unless something gives.")
    return out


def phases(subs: List[dict], exam: date_type, start: date_type, weekly: float, leave_weeks: int,
           leave_hours: float) -> dict:
    """Work backwards from the exam: second revision, first revision,
    practice, then learning (with its revisions), at the hours available
    each week."""
    buckets = [("revision_2", sum(x["final_revision"] for x in subs) * FINAL_REVISION_SHARE[1] /
                max(sum(FINAL_REVISION_SHARE), 1e-9)),
               ("revision_1", sum(x["final_revision"] for x in subs) * FINAL_REVISION_SHARE[0] /
                max(sum(FINAL_REVISION_SHARE), 1e-9)),
               ("practice", sum(x["practice"] for x in subs)),
               ("learning", sum(x["learning"] + x["reviews"] for x in subs))]
    out, day = {}, exam
    leave_from = exam - timedelta(weeks=leave_weeks)
    for name, hours in buckets:
        while hours > 0 and day > start - timedelta(days=3650):
            rate = (leave_hours if day > leave_from else weekly) / 7
            hours -= rate
            day -= timedelta(days=1)
        out[f"{name}_from"] = day.isoformat()
    out["starts_before_today"] = date_type.fromisoformat(out["learning_from"]) < start
    if leave_weeks:
        out["study_leave_from"] = leave_from.isoformat()
    return out


# ---------------------------------------------------------------------------
# Daily sessions (pure)
# ---------------------------------------------------------------------------

def chapters_of(j: dict, today: date_type) -> List[dict]:
    """Every chapter with its learning minutes, in plan order."""
    out = []
    for st in j["structure"].get("stages", []):
        exam = stage_date(j, st)
        for sub in st.get("subjects", []):
            hrs = subject_hours(j, st, sub, exam, today)
            chs = sub.get("chapters") or [{"key": "all", "name": sub["name"], "weight": 1}]
            total_w = sum(max(float(c.get("weight") or 1), 0.01) for c in chs)
            for c in chs:
                out.append({"key": f"{st['key']}.{sub['key']}.{c['key']}", "stage": st["key"],
                            "subject": f"{st['key']}.{sub['key']}", "subject_name": sub["name"],
                            "name": c["name"], "exam": exam,
                            "learn_minutes": hrs["learning"] * 60 * max(float(c.get("weight") or 1), 0.01) / total_w,
                            "practice_minutes": hrs["practice"] * 60 / len(chs),
                            "revision_minutes": hrs["final_revision"] * 60 / len(chs)})
    return out


def review_minutes(ch: dict, step: int) -> int:
    share = REVIEW_LADDER[min(step, len(REVIEW_LADDER) - 1)][1]
    return int(min(max(ch["learn_minutes"] * share, MIN_SESSION), MAX_REVIEW))


def day_sessions(j: dict, day: date_type) -> List[dict]:
    prog = j.get("progress") or {}
    chs = [c for c in chapters_of(j, day) if not c["exam"] or c["exam"] >= day]
    if not chs:
        return []
    current = min(chs, key=lambda c: c["exam"] or date_type.max)["stage"]
    exam = next(c["exam"] for c in chs if c["stage"] == current)
    leave = int(j.get("leave_weeks") or 0)
    in_leave = bool(exam and leave and day >= exam - timedelta(weeks=leave))
    weekly = float(j.get("leave_weekly_hours") or LEAVE_WEEKLY_HOURS) if in_leave else \
        float(j.get("weekly_hours") or DEFAULT_WEEKLY_HOURS)
    budget = weekly * 60 / STUDY_DAYS
    out = []
    # 1. Revisions that are due (oldest first) — they're short and they're what makes it stick.
    due = sorted((c for c in chs if (prog.get(c["key"]) or {}).get("next_review")
                  and prog[c["key"]]["next_review"] <= day.isoformat()),
                 key=lambda c: prog[c["key"]]["next_review"])
    for c in due:
        p = prog[c["key"]]
        m = review_minutes(c, p.get("step", 0))
        out.append({"kind": "review", "chapter_key": c["key"], "subject": c["subject_name"], "chapter": c["name"],
                    "minutes": m, "overdue_days": (day - date_type.fromisoformat(p["next_review"])).days})
        budget -= m
    # 2. New chapters of the current stage, two subjects interleaved.
    learning = [c for c in chs if c["stage"] == current and
                (prog.get(c["key"]) or {}).get("learned", 0) < c["learn_minutes"] * 0.95 and c["learn_minutes"] > 0]
    by_subject: Dict[str, List[dict]] = defaultdict(list)
    for c in learning:
        by_subject[c["subject"]].append(c)

    def done_share(subject):
        all_ch = [c for c in chs if c["subject"] == subject]
        total = sum(c["learn_minutes"] for c in all_ch) or 1
        return sum(min((prog.get(c["key"]) or {}).get("learned", 0), c["learn_minutes"]) for c in all_ch) / total
    picks = sorted(by_subject, key=done_share)[:2]
    chunk = max(MIN_SESSION, min(MAX_LEARN, budget / max(len(picks), 1)))   # share the day between the two
    while budget >= MIN_SESSION and picks:
        progressed = False
        for subj in picks:
            if budget < MIN_SESSION or not by_subject[subj]:
                continue
            c = by_subject[subj][0]
            left = c["learn_minutes"] - (prog.get(c["key"]) or {}).get("learned", 0) - \
                sum(s["minutes"] for s in out if s["chapter_key"] == c["key"] and s["kind"] == "learn")
            m = int(min(left, chunk, budget))
            if m >= MIN_SESSION:
                out.append({"kind": "learn", "chapter_key": c["key"], "subject": c["subject_name"],
                            "chapter": c["name"], "minutes": m})
                budget -= m
                progressed = True
            if left - m < MIN_SESSION:
                by_subject[subj].pop(0)
        if not progressed:
            break
    # 3. When the stage's learning is done: practice, then final revision.
    if not learning and j["shape"] == "exam":
        sp = j.get("subject_progress") or {}
        for kind, field in (("practice", "practice_minutes"), ("revision", "revision_minutes")):
            for subj in sorted({c["subject"] for c in chs if c["stage"] == current}):
                if budget < MIN_SESSION:
                    break
                need = sum(c[field] for c in chs if c["subject"] == subj)
                left = need - (sp.get(subj) or {}).get(kind, 0)
                if left >= MIN_SESSION:
                    m = int(min(left, MAX_LEARN, budget))
                    name = next(c["subject_name"] for c in chs if c["subject"] == subj)
                    out.append({"kind": kind, "chapter_key": None, "subject_key": subj, "subject": name,
                                "chapter": "Mock papers and questions" if kind == "practice" else "Revision",
                                "minutes": m})
                    budget -= m
    return out


def after_review(step: int, rating: str, day: date_type) -> tuple:
    """(next step, next review date or None when the ladder is done)."""
    if rating == "hard":
        nxt = step
        gap = REVIEW_LADDER[max(step - 1, 0)][0] if step else 1
    else:
        nxt = step + (2 if rating == "easy" else 1)
        if nxt >= len(REVIEW_LADDER):
            return nxt, None
        gap = REVIEW_LADDER[nxt][0]
    return nxt, (day + timedelta(days=gap)).isoformat()


def pace(j: dict, today: date_type) -> dict:
    """Learning done against where an even pace would be by now."""
    chs = chapters_of(j, today)
    prog = j.get("progress") or {}
    started = _d((j.get("accepted_at") or "")[:10]) or today
    total = sum(c["learn_minutes"] for c in chs)
    done = sum(min((prog.get(c["key"]) or {}).get("learned", 0), c["learn_minutes"]) for c in chs)
    plan = j.get("plan") or {}
    ends = [_d((s.get("phases") or {}).get("practice_from")) for s in plan.get("stages", [])]
    end = max((e for e in ends if e), default=None)
    if not total or not end or end <= started:
        return {"learned_hours": _h(done), "status": "on_track"}
    expected = total * min(max((today - started).days / (end - started).days, 0), 1)
    gap = expected - done
    day_budget = float(j.get("weekly_hours") or DEFAULT_WEEKLY_HOURS) * 60 / STUDY_DAYS
    status = "behind" if gap > day_budget else "ahead" if gap < -day_budget else "on_track"
    return {"learned_hours": _h(done), "expected_hours": _h(expected), "status": status,
            "behind_hours": _h(max(gap, 0)), "learning_hours_total": _h(total)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class Start(BaseModel):
    goal: str = Field(min_length=2, max_length=300)
    for_what: str = Field(default="", max_length=300)
    for_person: Optional[str] = None           # a person (People) or care profile this is for, e.g. a child


async def _own(db, uid: str, jid: str) -> dict:
    j = await db.learning_journeys.find_one({"id": jid, "user_id": uid}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Journey not found")
    return j


async def _free_week_hours(db, uid: str) -> Optional[float]:
    import time_reports
    blocks = await db.time_commitments.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    if not blocks:
        return None
    monday = date_type.today() - timedelta(days=date_type.today().weekday())
    plan = time_reports.planned(blocks, [], [monday + timedelta(days=i) for i in range(7)])
    committed = sum(sum(v.values()) for v in plan["lines"].values())
    return (time_reports.WEEK - committed) / 60


async def _view(db, j: dict) -> dict:
    today = date_type.today()
    out = {k: v for k, v in j.items() if k not in ("user_id", "questions_cache")}
    if j.get("structure"):
        out["checks"] = checks(j, today)
        out["plan"] = compute(j, today, await _free_week_hours(db, j["user_id"]))
        out["can_start"] = not out["checks"]
        if j["status"] == "active":
            out["pace"] = pace(j, today)
    return out


@learning_router.post("", status_code=201)
async def start(body: Start, current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        intake = await learning_ai.intake(body.goal)
    except AssistantUnavailable:
        raise HTTPException(status_code=503, detail="Hymn couldn't think this through right now. Please try again.")
    questions = [q.model_dump() for q in intake.questions][:5]
    questions.append({"key": "weekly_hours", "question": "How many hours a week can you study?", "options": []})
    if intake.shape == "exam":
        questions.append({"key": "leave_weeks", "question": "Will you take study leave before the exam? "
                                                            "How many weeks?", "options": ["0", "4", "8", "12"]})
    j = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "goal": body.goal.strip(), "title": intake.title,
         "shape": intake.shape, "for_what": body.for_what, "for_person": body.for_person, "status": "asking",
         "questions": questions, "answers": {}, "structure": None, "created_at": _now(), "updated_at": _now()}
    await db.learning_journeys.insert_one(dict(j))
    return await _view(db, j)


class Answers(BaseModel):
    answers: Dict[str, str]


def _num(v, default):
    try:
        return float(str(v).strip().split()[0])
    except (ValueError, IndexError, AttributeError):
        return default


@learning_router.post("/{jid}/answers")
async def answer(jid: str, body: Answers, current_user: dict = Depends(get_current_user)):
    """Save the starting point and build the structure (AI with web search,
    then checked and computed in code)."""
    db = get_db()
    j = await _own(db, current_user["id"], jid)
    if j["status"] not in ("asking", "draft"):
        raise HTTPException(status_code=409, detail="This journey has already started.")
    answers = {k: str(v)[:300] for k, v in body.answers.items()}
    try:
        st = await learning_ai.structure(j["goal"], j["title"], j["shape"],
                                         {k: v for k, v in answers.items() if k not in ("weekly_hours", "leave_weeks")},
                                         date_type.today().isoformat())
    except AssistantUnavailable:
        raise HTTPException(status_code=503, detail="Hymn couldn't look this up right now. Please try again.")
    changes = {"answers": answers, "structure": st.model_dump(), "status": "draft",
               "weekly_hours": _num(answers.get("weekly_hours"), DEFAULT_WEEKLY_HOURS),
               "leave_weeks": int(_num(answers.get("leave_weeks"), 0)), "confirmed": [], "fact_choices": {},
               "stage_dates": {}, "estimates": {}, "subject_status": {}, "updated_at": _now()}
    await db.learning_journeys.update_one({"id": jid}, {"$set": changes})
    return await _view(db, {**j, **changes})


class Update(BaseModel):
    confirmed: List[str] = Field(default_factory=list)          # check keys
    fact_choices: Dict[str, str] = Field(default_factory=dict)   # fact key → chosen value
    stage_dates: Dict[str, str] = Field(default_factory=dict)    # stage key → YYYY-MM-DD
    estimates: Dict[str, Dict[str, float]] = Field(default_factory=dict)   # "stage.subject" → hours
    subject_status: Dict[str, Literal[tuple(STATUS_REMAINING)]] = Field(default_factory=dict)
    weekly_hours: Optional[float] = Field(default=None, gt=0, le=100)
    leave_weeks: Optional[int] = Field(default=None, ge=0, le=52)
    leave_weekly_hours: Optional[float] = Field(default=None, gt=0, le=100)


@learning_router.patch("/{jid}")
async def update(jid: str, body: Update, current_user: dict = Depends(get_current_user)):
    db = get_db()
    j = await _own(db, current_user["id"], jid)
    if not j.get("structure"):
        raise HTTPException(status_code=409, detail="Answer the questions first.")
    for k, v in body.stage_dates.items():
        if _d(v) is None:
            raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    for k, v in body.estimates.items():
        if any(x < 0 or x > 5000 for x in v.values()):
            raise HTTPException(status_code=400, detail="Hours must be between 0 and 5000.")
    changes = {"confirmed": sorted(set(j.get("confirmed") or []) | set(body.confirmed)),
               "fact_choices": {**(j.get("fact_choices") or {}), **body.fact_choices},
               "stage_dates": {**(j.get("stage_dates") or {}), **body.stage_dates},
               "estimates": {**(j.get("estimates") or {}), **body.estimates},
               "subject_status": {**(j.get("subject_status") or {}), **body.subject_status},
               "updated_at": _now()}
    for f in ("weekly_hours", "leave_weeks", "leave_weekly_hours"):
        if getattr(body, f) is not None:
            changes[f] = getattr(body, f)
    await db.learning_journeys.update_one({"id": jid}, {"$set": changes})
    return await _view(db, {**j, **changes})


@learning_router.post("/{jid}/accept")
async def accept(jid: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    j = await _own(db, uid, jid)
    if j["status"] != "draft":
        raise HTTPException(status_code=409, detail="Only a journey being planned can start.")
    today = date_type.today()
    left = checks(j, today)
    if left:
        raise HTTPException(status_code=400, detail={"message": "Please confirm these first.", "checks": left})
    plan = compute(j, today)
    tasks, planned = [], []
    for r in j["structure"].get("requirements", []):
        due = r.get("due") or None
        tasks.append({"id": str(uuid.uuid4()), "user_id": uid, "title": r["what"][:200], "due_date": due,
                      "priority": "high", "status": "todo", "notes": f"For: {j['title']}", "origin": "standalone",
                      "expected_outcome_id": None, "project_id": None, "component_id": None,
                      "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
                      "commitment_type": "postponable", "deferred_until": None, "original_due_date": due,
                      "defer_count": 0, "recurrence": None, "series_id": None, "occurrence_index": 1,
                      "learning_journey_id": jid, "created_at": _now(), "updated_at": _now()})
        if r.get("fee"):
            when = due or next((s["exam_date"] for s in plan["stages"] if s["exam_date"]), today.isoformat())
            planned.append({"id": str(uuid.uuid4()), "user_id": uid, "title": f"{j['title']}: {r['what']}"[:200],
                            "direction": "out", "purpose": "spend", "amount": Decimal128(Decimal(str(r["fee"]))),
                            "currency": "INR", "repeat": "once", "date": when, "start_month": None,
                            "end_month": None, "certainty": "sure", "set_aside": False, "category": "expense:education",
                            "account_id": None, "goal_id": None, "notes": "From your learning journey",
                            "status": "active", "done_amount": Decimal128(Decimal(0)), "learning_journey_id": jid,
                            "created_at": _now(), "updated_at": _now()})
    if tasks:
        await db.tasks.insert_many(tasks)
    if planned:
        await db.planned_money.insert_many(planned)
    changes = {"status": "active", "accepted_at": _now(), "plan": plan, "progress": {}, "subject_progress": {},
               "updated_at": _now()}
    await db.learning_journeys.update_one({"id": jid}, {"$set": changes})
    return await _view(db, {**j, **changes})


@learning_router.get("")
async def list_journeys(current_user: dict = Depends(get_current_user)):
    db = get_db()
    rows = await db.learning_journeys.find({"user_id": current_user["id"], "status": {"$ne": "dropped"}},
                                           {"_id": 0}).sort("created_at", -1).to_list(length=100)
    today = date_type.today()
    out = []
    for j in rows:
        item = {k: j.get(k) for k in ("id", "title", "goal", "shape", "status", "for_what", "for_person")}
        if j["status"] == "active":
            item["pace"] = pace(j, today)
            item["today_minutes"] = sum(s["minutes"] for s in day_sessions(j, today))
        out.append(item)
    return out


@learning_router.get("/{jid}")
async def get_journey(jid: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _view(db, await _own(db, current_user["id"], jid))


@learning_router.get("/{jid}/today")
async def today_sessions(jid: str, date: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    db = get_db()
    j = await _own(db, current_user["id"], jid)
    if j["status"] != "active":
        raise HTTPException(status_code=409, detail="Start the journey first.")
    day = _d(date) if date else date_type.today()
    if day is None:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    sessions = day_sessions(j, day)
    return {"date": day.isoformat(), "sessions": sessions, "minutes": sum(s["minutes"] for s in sessions),
            "pace": pace(j, day)}


class SessionDone(BaseModel):
    kind: Literal["learn", "review", "practice", "revision"]
    chapter_key: Optional[str] = None
    subject_key: Optional[str] = None          # practice / revision
    minutes: int = Field(ge=1, le=600)
    date: str
    rating: Optional[Literal["easy", "ok", "hard"]] = None   # reviews


@learning_router.post("/{jid}/sessions", status_code=201)
async def session_done(jid: str, body: SessionDone, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    j = await _own(db, uid, jid)
    if j["status"] != "active":
        raise HTTPException(status_code=409, detail="Start the journey first.")
    day = _d(body.date)
    if day is None:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    chs = {c["key"]: c for c in chapters_of(j, day)}
    prog = dict(j.get("progress") or {})
    sp = dict(j.get("subject_progress") or {})
    if body.kind in ("learn", "review"):
        c = chs.get(body.chapter_key or "")
        if not c:
            raise HTTPException(status_code=400, detail="Unknown chapter.")
        p = dict(prog.get(c["key"]) or {"learned": 0})
        if body.kind == "learn":
            p["learned"] = p.get("learned", 0) + body.minutes
            if p["learned"] >= c["learn_minutes"] * 0.95 and not p.get("learned_on"):
                p.update(learned_on=day.isoformat(), step=0,
                         next_review=(day + timedelta(days=REVIEW_LADDER[0][0])).isoformat())
        else:
            if not body.rating:
                raise HTTPException(status_code=400, detail="How did the revision go: easy, ok or hard?")
            if not p.get("learned_on"):
                p.update(learned_on=day.isoformat(), step=0)
            p["step"], p["next_review"] = after_review(p.get("step", 0), body.rating, day)
            p["reviews"] = p.get("reviews", 0) + 1
        prog[c["key"]] = p
    else:
        subj = body.subject_key or ""
        if not any(c["subject"] == subj for c in chs.values()):
            raise HTTPException(status_code=400, detail="Unknown subject.")
        s = dict(sp.get(subj) or {})
        s[body.kind] = s.get(body.kind, 0) + body.minutes
        sp[subj] = s
    await db.learning_journeys.update_one({"id": jid}, {"$set": {"progress": prog, "subject_progress": sp,
                                                                 "updated_at": _now()}})
    await db.learning_sessions.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "journey_id": jid,
                                           "title": j["title"], "date": day.isoformat(), "kind": body.kind,
                                           "chapter_key": body.chapter_key, "minutes": body.minutes,
                                           "rating": body.rating, "created_at": _now()})
    await _sync_health(db, uid, day)
    j = {**j, "progress": prog, "subject_progress": sp}
    return {"saved": True, "chapter": prog.get(body.chapter_key or ""), "pace": pace(j, day)}


async def _sync_health(db, uid: str, day: date_type) -> None:
    """With the health consent, the week's study hours become Health's
    "Learning something new" (one value per week)."""
    if not await db.health_profiles.find_one({"user_id": uid, "consent": True}, {"_id": 1}):
        return
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    minutes = 0
    async for s in db.learning_sessions.find({"user_id": uid, "date": {"$gte": start.isoformat(),
                                                                         "$lte": end.isoformat()}}, {"_id": 0}):
        minutes += s["minutes"]
    await db.health_measurements.delete_many({"user_id": uid, "metric": "learning_hours",
                                              "taken_on": start.isoformat(), "note": "from Learning"})
    if minutes:
        await db.health_measurements.insert_one({
            "id": str(uuid.uuid4()), "user_id": uid, "metric": "learning_hours",
            "value": min(round(minutes / 60, 1), 100), "unit": "hours/week", "taken_on": start.isoformat(),
            "source": "you", "note": "from Learning", "created_at": _now()})


@learning_router.get("/{jid}/chapters/{chapter_key}/questions")
async def questions(jid: str, chapter_key: str, current_user: dict = Depends(get_current_user)):
    """A few closed-book recall questions for this chapter (written once, kept)."""
    db = get_db()
    j = await _own(db, current_user["id"], jid)
    cache = j.get("questions_cache") or {}
    slot = chapter_key.replace(".", "|")          # keys hold dots; stored flat
    if slot in cache:
        return {"questions": cache[slot]}
    c = next((c for c in chapters_of(j, date_type.today()) if c["key"] == chapter_key), None)
    if not c:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        qs = [q.model_dump() for q in await learning_ai.recall_questions(j["title"], c["subject_name"], c["name"])]
    except AssistantUnavailable:
        raise HTTPException(status_code=503, detail="No questions right now — revise from your notes and rate it.")
    await db.learning_journeys.update_one({"id": jid}, {"$set": {f"questions_cache.{slot}": qs}})
    return {"questions": qs}


@learning_router.delete("/{jid}")
async def drop(jid: str, current_user: dict = Depends(get_current_user)):
    """Stop the journey: its open tasks and planned fees go; study history stays."""
    db = get_db()
    uid = current_user["id"]
    await _own(db, uid, jid)
    await db.tasks.delete_many({"user_id": uid, "learning_journey_id": jid, "status": {"$ne": "done"}})
    await db.planned_money.delete_many({"user_id": uid, "learning_journey_id": jid})
    await db.learning_journeys.update_one({"id": jid}, {"$set": {"status": "dropped", "updated_at": _now()}})
    return {"detail": "Stopped"}


async def ensure_learning_indexes(db) -> None:
    await db.learning_journeys.create_index([("user_id", 1), ("id", 1)], unique=True)
    await db.learning_sessions.create_index([("user_id", 1), ("date", 1)])


# ---------------------------------------------------------------------------
# Nudges (called by the nudge scheduler; setting ``learning``)
# ---------------------------------------------------------------------------

DEADLINE_WARNINGS = (14, 3)


async def learning_nudges(db, user: dict, settings: dict, now: datetime) -> List[dict]:
    from nudges import _claim, _due, _tz, hhmm_to_minute, in_quiet_hours

    cfg = settings.get("learning") or {}
    if not cfg.get("enabled", True):
        return []
    local = now.astimezone(_tz(user.get("timezone")))
    quiet = settings["quiet_hours"]
    if in_quiet_hours(local.hour * 60 + local.minute, quiet["start"], quiet["end"]):
        return []
    at = _due(local, hhmm_to_minute(cfg.get("time") or "07:00"))
    if at is None:
        return []
    today = local.date()
    out = []
    async for j in db.learning_journeys.find({"user_id": user["id"], "status": "active"}, {"_id": 0}):
        sessions = day_sessions(j, today)
        if sessions:
            mins = sum(s["minutes"] for s in sessions)
            parts = []
            for s in sessions[:3]:
                parts.append(f"{s['subject']}: {s['chapter']} ({'revise' if s['kind'] == 'review' else s['kind']})")
            n = await _claim(db, user["id"], "learning_today", f"learning_today:{j['id']}:{today.isoformat()}",
                             f"{j['title']}: {mins} min today", " · ".join(parts),
                             {"screen": "learning", "journey_id": j["id"]}, at)
            if n:
                out.append(n)
        for i, r in enumerate(j["structure"].get("requirements", [])):
            due = _d(r.get("due"))
            if not due:
                continue
            left = (due - today).days
            if left in DEADLINE_WARNINGS:
                n = await _claim(db, user["id"], "learning_deadline",
                                 f"learning_deadline:{j['id']}:{i}:{left}",
                                 f"In {left} days: {r['what']}", f"For {j['title']} — due {due.isoformat()}.",
                                 {"screen": "learning", "journey_id": j["id"]}, at)
                if n:
                    out.append(n)
    return out
