#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: |
  Enhance the planning chatbot (Goals + Projects) to be portfolio-aware:
  1) Take existing goals / projects / tasks / weekly time commitments into
     account. If capacity is tight, warn the user and propose specific
     items to postpone or cancel.
  2) Introduce commitment_type ("postponable" | "exclusive") on Goals,
     Projects, and Tasks. The assistant must never suggest postponing or
     cancelling an "exclusive" item (movie ticket, exam, surgery).
  3) When the user mentions a recurring life pattern (job, pilates,
     school pickup), auto-add it as a time commitment in the next
     Proposed Changes card if enough info; otherwise ask a single
     clarifying question.

backend:
  - task: "commitment_type field on Goal, Project, Task"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Added COMMITMENT_TYPES = {"postponable", "exclusive"} and:
            * GoalCreate/Update/Response + create + update endpoints
            * ProjectCreate/Update/Response + create + update endpoints
            * TaskCreate/Update/Response + create + update endpoints
          All default to "postponable". Update paths validate against the
          allowed set (400 on invalid).

  - task: "Portfolio-aware planning context"
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
          _read_context now pulls (in addition to the target's own
          outcomes/tasks/checkins):
            * All OTHER active/paused goals + projects with their
              commitment_type, deadlines, cadences.
            * Currently-effective weekly time commitments.
            * Rough weekly capacity: committed_hours/week and estimated
              free hours (168 - committed).
            * Total open task count with due dates (workload heat).
          _context_prelude serializes this into a compact system prelude.

  - task: "Expanded HYMN_PROPOSAL schema (time_commitments, existing_item_changes, feasibility_note, commitment_type on tasks/target)"
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
          Updated system prompt with CAPACITY & PORTFOLIO AWARENESS +
          LIFE PATTERNS sections. New proposal fields:
            * feasibility_note (short line if capacity is tight)
            * time_commitments (recurring weekly patterns)
            * existing_item_changes (postpone|cancel with new_due_date +
              reason). NEVER touches items whose commitment_type is
              "exclusive".
            * tasks[].commitment_type
            * target_updates.commitment_type

  - task: "Atomic materialization of new proposal fields"
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
          _materialize_proposal now also:
            * Creates time_commitments (validated day/hh:mm range) with
              source_type="system".
            * Applies postpone/cancel actions on other portfolio items
              — but ONLY if commitment_type != "exclusive". Postpone
              updates deadline/target_end_date and moves status to
              "paused"; cancel sets "abandoned" (or "cancelled" for
              tasks).
            * Persists task commitment_type and target commitment_type.
          Compensating cleanup restored on failure.
          Live smoke test confirmed 8 time commitments + 1 task created
          in a single atomic pass. materialized_summary now enumerates
          all touched item types.

  - task: "commitment_type validation in update endpoints"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          PUT /api/goals/{id}, /api/projects/{id}, /api/tasks/{id} now
          return 400 when commitment_type is anything other than
          "postponable" or "exclusive".

frontend:
  - task: "CommitmentTypeToggle component"
    implemented: true
    working: true
    file: "frontend/src/components/CommitmentTypeToggle.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Simple two-chip toggle (Postponable / Exclusive) with iconography
          (swap vs lock) and a one-line contextual help caption. Reused
          across all three forms.

  - task: "GoalForm + ProjectForm + TaskForm accept commitment_type"
    implemented: true
    working: true
    file: "frontend/app/goals/add.tsx, frontend/app/projects/add.tsx, frontend/app/tasks/add.tsx (+ edit screens)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Added CommitmentTypeToggle above the Notes field on all three
          forms. Edit screens pre-fill from the fetched entity's current
          commitment_type. Payloads flow through to the API. Types
          extended on api.ts (create/update Goal, Project, Task).

  - task: "Chat proposal card renders new sections"
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
          Extended Proposal type + MessageBubble to render:
            * feasibility_note (yellow warning banner with icon).
            * time_commitments section — "N life patterns" list.
            * existing_item_changes — "Trade-offs" section with colored
              POSTPONE / CANCEL badges + optional new due date + reason.
            * commitment_type=exclusive tasks marked with 🔒 icon.
          Live smoke test on test@hymn.app: assistant flagged 8-goal
          portfolio, proposed pausing 3 test/placeholder items, captured
          user's Job + Pilates schedule as 8 time commitments, asked one
          clarifying question about ceramics class timing. Apply worked.

metadata:
  created_by: "main_agent"
  version: "3.1"
  test_sequence: 17
  run_ui: false

test_plan:
  current_focus:
    - "Portfolio-aware planning context"
    - "Expanded HYMN_PROPOSAL schema"
    - "Atomic materialization of new proposal fields"
    - "commitment_type field on Goal, Project, Task"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Portfolio-aware Planning Copilot shipped. Smoke-tested end-to-end
      with test@hymn.app / TestPass123!.

      Backend flow validated live:
        * Chat context now includes other active goals/projects, time
          commitments, weekly capacity estimate, and open task count.
        * LLM responded with feasibility warning, named specific
          low-value items in the portfolio to consider pausing, extracted
          8 recurring life patterns (Job × 5 weekdays + Pilates × 3 days)
          from the user's message, and asked one clarifying question for
          missing info (ceramics class times).
        * Materialize atomically created 8 time_commitments +
          1 task in one apply.

      Suggested test coverage:
        1) POST /api/planning/{goal|project}/{id}/messages that includes
           a recurring life pattern → assistant emits time_commitments
           in the proposal.
        2) POST /api/planning/conversations/{id}/materialize on that
           proposal → time_commitments docs appear in
           db.time_commitments with source_type="system".
        3) Set commitment_type="exclusive" on a Goal → send a planning
           message describing tight capacity → assistant should NOT
           include an existing_item_change referencing that Goal.
        4) 400 on PUT /api/goals/{id} { "commitment_type": "invalid" }.
        5) UI: CommitmentTypeToggle renders on the add + edit forms of
           Goal, Project, and Task. On task detail / list, exclusive
           items surface visually.
