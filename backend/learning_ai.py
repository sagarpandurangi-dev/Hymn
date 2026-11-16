"""The AI side of learning journeys: understand the goal, find the real
structure on the web (with sources), and write recall questions.

The AI never sets hours, dates or schedules by itself: every fact comes with
a source or is marked for the person to confirm, and ``learning`` (code)
checks the structure and does all the arithmetic and scheduling.
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Literal, Optional

import anthropic
from pydantic import BaseModel, Field, ValidationError

import claude_client
from claude_client import AssistantUnavailable

# Getting an exam's facts right matters more than cost (one call per
# journey); questions and recall questions are cheap model work.
STRUCTURE_MODEL = os.environ.get("HYMN_LEARNING_MODEL") or "claude-opus-5-5"
LIGHT_MODEL = os.environ.get("HYMN_LEARNING_LIGHT_MODEL") or "claude-haiku-5-5"
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
SHAPES = ("exam", "skill", "fluency", "project")


# ---------------------------------------------------------------------------
# 1. Understand the goal and ask about the starting point
# ---------------------------------------------------------------------------

class Question(BaseModel):
    key: str                                   # snake_case
    question: str
    options: List[str] = Field(default_factory=list)   # empty = free answer


class Intake(BaseModel):
    title: str                                 # "CA", "Driving licence"
    shape: Literal["exam", "skill", "fluency", "project"]
    questions: List[Question]


_INTAKE_SYSTEM = """You help someone start a learning journey in the Hymn app (India by default).
Given their goal, name it briefly (title), decide its shape:
- exam: a syllabus and exams (CA, CFA, 10th boards, JEE, UPSC, a certification)
- skill: hands-on practice towards a test or ability (driving, swimming, guitar)
- fluency: a little often (a language, typing)
- project: milestones (build an app, write a book)
and ask 3 to 5 short questions about their STARTING POINT and target — only what changes the plan.
Always ask the level/stage first if the goal has levels (e.g. "Which level are you at — Foundation,
Intermediate or Final?"), and the target exam attempt or date if there is one. Ask about requirements
outside study that the goal has (e.g. CA articleship, a driving learner's licence). For a retake, ask
for the last marks. Give options where the answers are a known set. Do not ask about weekly study
hours (Hymn asks that itself). Plain, warm words."""


async def intake(goal: str) -> Intake:
    return await _parse(LIGHT_MODEL, _INTAKE_SYSTEM, f"Goal: {goal}", Intake, 2000)


# ---------------------------------------------------------------------------
# 2. The structure, from the web, with sources
# ---------------------------------------------------------------------------

class Fact(BaseModel):
    key: str
    label: str
    value: str
    source_url: str = ""
    sources_disagree: bool = False
    alternatives: List[str] = Field(default_factory=list)


class Chapter(BaseModel):
    key: str
    name: str
    weight: float = 1.0                        # relative size within the subject


class Subject(BaseModel):
    key: str
    name: str
    class_hours: float = 0                     # guided hours (classes, instructor)
    self_study_hours: float = 0                # own study / practice
    hours_source: str = ""                     # URL, or "" when it's your estimate
    exam_hours: float = 0                      # length of its exam paper, if any
    chapters: List[Chapter] = Field(default_factory=list)


class Stage(BaseModel):
    key: str
    name: str                                  # "Group I", "Level I", "Learner's licence"
    exam_date: str = ""                        # YYYY-MM-DD of the target attempt, "" if unknown
    exam_date_source: str = ""
    subjects: List[Subject]


class Requirement(BaseModel):
    what: str                                  # "Complete articleship", "Hold learner's licence 30 days"
    due: str = ""                              # YYYY-MM-DD it must be done by, if known
    source_url: str = ""
    fee: float = 0


class Structure(BaseModel):
    facts: List[Fact]
    stages: List[Stage]
    requirements: List[Requirement] = Field(default_factory=list)
    techniques: List[str] = Field(default_factory=list)


_STRUCTURE_SYSTEM = """You build the structure of a learning journey for the Hymn app. Use web search
for every hard fact (exam windows and dates, registration deadlines, eligibility, papers/subjects,
syllabus chapters, fees, legal rules such as licence waiting periods) and give the source URL of an
official or reliable page. Prefer the official body (e.g. ICAI, CFA Institute, a state transport
department, CBSE). Never state a hard fact from memory. If sources disagree, set
sources_disagree=true and list the alternatives. Use today's date to pick future attempts.

Return ONLY one JSON object, no prose, matching:
{"facts":[{"key","label","value","source_url","sources_disagree","alternatives"}],
 "stages":[{"key","name","exam_date","exam_date_source",
            "subjects":[{"key","name","class_hours","self_study_hours","hours_source","exam_hours",
                         "chapters":[{"key","name","weight"}]}]}],
 "requirements":[{"what","due","source_url","fee"}],
 "techniques":["…"]}

Rules:
- Only include what is LEFT for this person given their answers (skip passed levels/groups/papers).
- stages are groups/levels/steps in order; subjects are papers/skills; chapters are the syllabus units
  (official chapter names where they exist) with a relative weight.
- class_hours and self_study_hours: typical effort for a fresh learner; cite hours_source if a source
  gives them, else leave hours_source empty (Hymn will ask the person to check your estimate).
- exam_date: the target attempt's exam date (first day) if known; else "" with the window in facts.
- techniques: up to 4 short, evidence-based study tips specific to this goal.
- Keys: short snake_case."""


def _first_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AssistantUnavailable("no JSON in answer")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise AssistantUnavailable("bad JSON") from exc


async def structure(goal: str, title: str, shape: str, answers: dict, today: str) -> Structure:
    prompt = (f"Today: {today}\nGoal: {goal}\nTitle: {title}\nShape: {shape}\n"
              f"Their answers (starting point): {json.dumps(answers, ensure_ascii=False)}")
    last: Optional[Exception] = None
    for _ in range(2):  # one retry if the JSON comes back malformed
        text = await claude_client.complete_text(model=STRUCTURE_MODEL, system=_STRUCTURE_SYSTEM,
                                                 messages=[{"role": "user", "content": prompt}],
                                                 max_tokens=16000, effort="medium", tools=[WEB_SEARCH])
        try:
            return Structure(**_first_json(text))
        except (AssistantUnavailable, ValidationError, TypeError) as exc:
            last = exc
    raise AssistantUnavailable(f"structure unreadable: {type(last).__name__}")


# ---------------------------------------------------------------------------
# 3. Recall questions for a revision session
# ---------------------------------------------------------------------------

class QA(BaseModel):
    question: str
    answer: str


class QASet(BaseModel):
    questions: List[QA]


_RECALL_SYSTEM = """Write short recall questions for a revision session: questions a learner answers
from memory, closed-book, before checking. Test understanding and application, not trivia. Keep answers
to 1–3 lines. Match the exam's level. If you're unsure of a fact, ask a conceptual question instead."""


async def recall_questions(journey: str, subject: str, chapter: str, n: int = 3) -> List[QA]:
    out = await _parse(LIGHT_MODEL, _RECALL_SYSTEM,
                       f"Journey: {journey}\nSubject: {subject}\nChapter: {chapter}\nWrite {n} questions.",
                       QASet, 2000)
    return out.questions[:n]


async def _parse(model: str, system: str, prompt: str, schema, max_tokens: int):
    client = claude_client.get_client().with_options(timeout=60.0)
    try:
        response = await client.beta.messages.parse(
            model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}],
            output_format=schema, output_config={"effort": "low"}, **claude_client.fallback_kwargs(model))
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc
    except ValidationError as exc:
        raise AssistantUnavailable("malformed output") from exc
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
    return response.parsed_output
