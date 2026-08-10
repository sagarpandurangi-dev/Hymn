#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: |
  Give the planning chat full write capabilities across Projects, Tasks,
  and Check-ins. Concrete examples:
    * "Check in 6-7am every day of this month as studies against Become
       CA goal" → Hymn auto-creates the daily check-ins.
    * If two or more Goals or Projects appear to be duplicates, the chat
      should propose consolidating them. On Apply, Hymn deterministically
      picks the richest survivor by metadata density and merges the rest
      into it.
  Locked user choices for this iteration:
    (1) Consolidation: single-tap Apply; server picks the richest survivor.
    (2) Recurring check-ins: materialize creates a real check-in document
        per day within [start_date, end_date] (backfill allowed).

backend:
  - task: "Recurring check-in expansion (checkin_recurrences → per-day docs)"
    implemented: true
    working: true
    file: "backend/planning_engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          New _iter_dates helper walks [start_date, end_date] inclusive,
          filtered by an optional days_of_week set (empty list = every day).
          Materialize resolves the anchor (goal via expected_outcome_title,
          project via project_id, life = free-floating) and inserts one
          checkin doc per matching date with source="system". Live test:
          7-day recurrence emitted by Claude → 7 documents persisted.

  - task: "One-off check-in creation from proposals.checkins"
    implemented: true
    working: true
    file: "backend/planning_engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Validates type ∈ {goal, project, life}, resolves anchor
          (expected_outcome for goal, project_id for project), inserts
          checkins docs with source="system" and outcome_type stamped
          from the EO for goal check-ins.

  - task: "existing_item_updates — free-form patches on goals/projects/tasks"
    implemented: true
    working: true
    file: "backend/planning_engine.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Accepts patches for {title, notes, priority, status, due_date,
          deadline}. Rejects unknown keys and invalid enum values.
          Refuses to touch items with commitment_type="exclusive"
          (server-side backstop, matches existing_item_changes rule).
          Never applied to the target the user is currently planning.

  - task: "Duplicate consolidation with richness-based survivor"
    implemented: true
    working: true
    file: "backend/planning_engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          _richness_score sums field completeness (2 pts per non-empty
          metadata field) + attached artifact counts (3 pts per EO,
          1 pt per task, 1 pt per check-in). Highest wins; tie-break by
          older created_at.
          Materialize reparents child docs BEFORE deleting losers:
            * Goals: expected_outcomes.goal_id + checkins.goal_id → survivor
            * Projects: tasks.project_id + checkins.project_id → survivor
          Notes / descriptions merged (append loser content if not
          already present). Losers deleted. Exclusive items are removed
          from the candidate set BEFORE scoring — never destroyed.
          Live test: 2 pairs of dups collapsed to 1 survivor each on
          Apply. Smoke test with programmatically-injected proposal
          confirmed EO/task reparenting works.

  - task: "Duplicate hints injected into the LLM context prelude"
    implemented: true
    working: true
    file: "backend/planning_engine.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Naive title-similarity clustering (normalized title + 4-word
          prefix). Any cluster of 2+ items is emitted as a
          "POSSIBLE DUPLICATES" line the assistant can act on.
          Confirmed live: LLM read the hints and proposed
          consolidations without user prompting.

  - task: "Extended materialize summary + result payload"
    implemented: true
    working: true
    file: "backend/planning_engine.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Response now returns created_checkins, applied_existing_updates,
          applied_consolidations arrays. Summary string enumerates every
          non-empty bucket. Live example: "Added 7 check-ins,
          consolidated 2 duplicates in 2 groups."

frontend:
  - task: "Chat proposal card — new sections"
    implemented: true
    working: true
    file: "frontend/app/planning/[targetType]/[targetId].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Proposal type + card extended with:
            * "N check-ins" section (one-off) with date + time
            * "Recurring check-ins" section listing rule with day filter
              or "(every day)"
            * "N updates" section listing kind + which fields
            * "Consolidations" section — cyan MERGE badge per group with
              "Hymn will keep the richest and merge the rest." caption
          Verified via screenshot on test@hymn.app: 7-day recurrence
          rendered + 2 consolidation cards rendered.

metadata:
  created_by: "main_agent"
  version: "3.2"
  test_sequence: 18
  run_ui: false

test_plan:
  current_focus:
    - "Recurring check-in expansion"
    - "Duplicate consolidation with richness-based survivor"
    - "existing_item_updates safety on exclusive items"
    - "Chat proposal card — new sections"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Chat now has full write access across Tasks / Check-ins /
      Goals-Projects updates + duplicate consolidation, per user request.
      Live end-to-end smoke on test@hymn.app / TestPass123!:
        * Assistant emitted 7-day 06:00 recurrence + spotted duplicate
          Goal + Project pairs (from context duplicate hints) and
          proposed consolidations.
        * Apply → "Added 7 check-ins, consolidated 2 duplicates in
          2 groups." DB confirmed: 7 system checkins persisted, dup
          goal + dup project each reduced 2 → 1.
        * Programmatic smoke test (throwaway) confirmed all three code
          paths (recurring checkins, existing_item_updates, consolidation
          with EO+task reparenting) work.
      Recommended additional coverage from testing_agent:
        1. Direct 400 tests for badly-formed proposal fields.
        2. Consolidation with EXCLUSIVE dup — that candidate should be
           dropped from the score set and never deleted.
        3. Recurrence spanning multiple days_of_week filter (e.g.
           weekdays only) → correct number of check-ins created.
        4. Update targeting an exclusive item → no-op (silent skip).
        5. Frontend: cadence line, "Update" section render, MERGE badge
           colour, count display.
