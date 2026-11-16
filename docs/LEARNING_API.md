# Learning journeys — API notes for the app

Any learning goal: CA, CFA, 10th boards, a driving licence, a language. The AI understands the goal and looks facts up on the web (with sources); code checks everything and does every number; the person confirms before anything is scheduled.

## 1. Start — `POST /api/learning` `{goal, for_what, for_person}`
→ `{id, title, shape: exam|skill|fluency|project, status: "asking", questions: [{key, question, options[]}]}`
Show the questions one at a time (chips when `options` is not empty). Hymn always adds "hours a week" and, for exams, "weeks of study leave". 503 = try again (nothing saved).

## 2. Answer — `POST /api/learning/{id}/answers` `{answers: {key: "value"}}`
Takes up to a minute (web lookups): show "Checking the facts…". → the journey with:
- `structure`: `facts[{key,label,value,source_url,sources_disagree,alternatives}]`, `stages[{key,name,exam_date,exam_date_source,subjects[{key,name,class_hours,self_study_hours,hours_source,exam_hours,chapters[{key,name,weight}]}]}]`, `requirements[{what,due,source_url,fee}]`, `techniques[]`. Show sources as links.
- `checks[{key, level: confirm|error, what, options?}]`: show these first. **confirm** → "Looks right" button (send its key in `confirmed`) or pick an option (send `fact_choices`). **error** → must be fixed (e.g. set the exam date).
- `plan`: `{total_hours, weekly_hours, verdict: fits|short, stages[{name, exam_date, hours, capacity_hours, fits, short_by_hours?, needs_weekly_hours?, would_fit_by?, phases{learning_from, practice_from, revision_1_from, revision_2_from, study_leave_from?}, subjects[{key, name, status, learning, reviews, practice, final_revision, total, source}]}], options[{option, what}], assumptions, free_week_hours?, warning?}`.
- `can_start`.

## 3. Adjust — `PATCH /api/learning/{id}`
Any of: `confirmed[]`, `fact_choices{}`, `stage_dates{stage: date}`, `estimates{"stage.subject": {class_hours, self_study_hours}}`, `subject_status{"stage.subject": not_started|attending_classes|classes_done|first_reading_done|revising|done}`, `weekly_hours`, `leave_weeks`, `leave_weekly_hours`. Recomputed instantly (no AI).
**Ask each subject's status** on a "Where are you in each subject?" screen right after step 2 — it changes the hours a lot.

## 4. Start — `POST /api/learning/{id}/accept`
400 with `detail.checks` if anything is left to confirm. Adds tasks for requirements (articleship, registration…) and fees to planned money. Status `active`.

## 5. Every day
- `GET /api/learning/{id}/today?date=` → `{sessions: [{kind: review|learn|practice|revision, chapter_key, subject_key?, subject, chapter, minutes, overdue_days?}], minutes, pace{learned_hours, expected_hours, status: on_track|behind|ahead, behind_hours}}`. Revisions come first.
- For a revision: `GET /api/learning/{id}/chapters/{chapter_key}/questions` → `{questions: [{question, answer}]}` — show the question, the person answers in their head, then reveals the answer. 503 → "revise from your notes".
- When done: `POST /api/learning/{id}/sessions` `{kind, chapter_key | subject_key, minutes, date, rating: easy|ok|hard (revisions)}` → `{chapter: {learned, learned_on, step, next_review}, pace}`. Buttons after a revision: **Easy / OK / Hard**.
- `GET /api/learning` → journeys with `pace` and `today_minutes`. `GET /api/learning/{id}` → everything. `DELETE /api/learning/{id}` stops it (open tasks and planned fees go; history stays).

## Elsewhere
- Study time counts as **Learning** in the weekly time statements, and (with the health consent) as Health's "Learning something new".
- Nudge setting `learning` (`{enabled, time}`, default 07:00): "CA: 70 min today — FR: Leases (revise) · …"; requirement deadlines 14 and 3 days before. Push `data`: `{screen: "learning", journey_id}`.
