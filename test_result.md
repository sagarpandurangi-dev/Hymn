#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  Hierarchical Knowledge engine.
  - Do NOT modify Health / Finance / Projects / Timeline / Reviews.
  - Do NOT modify the Goal / Task / Check-in engines. They remain the execution engine.
  - Do NOT add journey_type or has_stages to Goal — those live on a new
    KnowledgeJourney row that REFERENCES exactly one Goal.
  - Three new collections: knowledge_journeys, knowledge_stages, knowledge_components.
  - Wizard now runs in this order (9 steps if stages, 8 if not):
      1) journey_type (one of 6 tiles, no free text)
      2) journey name
      3) has_stages? (Yes/No)
      4) [if Yes] stages list (free-text names, up/down reorder)
      5) why
      6) target completion date
      7) first Expected Outcome (required)
      8) first Task (required)
      9) check-in cadence (daily|weekly|monthly|manual — persisted, no reminders)
    Atomic on POST /api/knowledge/journeys — all rows created together or none.
  - Hierarchy: Journey → Stage (optional) → Component (unlimited nested) → Goal
    (title/why/deadline/cadence) → Expected Outcome → Task → Check-in.
  - Tasks and Check-ins gained an optional nullable component_id. Their core CRUD
    is unchanged; the new field is a foreign key only.
  - Tree UI: expand / collapse / add child / edit / delete / reorder (Up/Down
    buttons — no drag-drop).
  - Legacy Knowledge Journeys (pre-existing Goals in the Knowledge domain) are
    kept: on any list/detail read we idempotently backfill a knowledge_journeys
    row (journey_type="", has_stages=False) so they continue to open.

backend:
  - task: "New Knowledge collections + atomic 9-step wizard"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Three new collections (knowledge_journeys, knowledge_stages,
          knowledge_components) with full CRUD. POST /api/knowledge/journeys now
          accepts journey_type, has_stages, stages, why, target_completion_date,
          first_outcome, first_task, checkin_cadence. journey_type must be one of
          {professional_qualification, skill, course, subject, book, custom}.
          has_stages=true requires a non-empty stages list. All docs (Goal,
          KnowledgeJourney, N stages, first EO, first Task) insert atomically —
          on any failure the created rows are rolled back in reverse order.

  - task: "Stage CRUD + Up/Down move endpoint"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          GET/POST/PUT/DELETE /api/knowledge/stages plus
          POST /api/knowledge/stages/{id}/move?direction=up|down which swaps the
          sequence with its neighbour. Delete cascades to all components in that
          stage (and their descendants).

  - task: "Component CRUD (recursive) + Up/Down move + task/checkin detach on delete"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          GET/POST/PUT/DELETE /api/knowledge/components plus
          POST /api/knowledge/components/{id}/move. A component may reference a
          stage_id and/or a parent_component_id (unlimited depth). Deleting a
          component recursively deletes its descendants and DETACHES (sets to
          null) any tasks/checkins that were linked to any of them — the
          execution engine data is never destroyed by Knowledge operations.

  - task: "Legacy backfill for pre-existing Knowledge Goals"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          _backfill_legacy_journeys is called at the top of list_knowledge_journeys
          and get_knowledge_journey. For every Goal in the user's Knowledge domain
          that lacks a knowledge_journeys row, we insert a default one
          (journey_type="", has_stages=False). Idempotent.

  - task: "Task/Check-in component_id foreign key + optional query filters"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Task and Check-in models gained an optional nullable component_id.
          POST /api/tasks validates that a supplied component_id belongs to the
          user; same for POST /api/checkins. GET /api/tasks now accepts
          ?goal_id=X and ?component_id=Y (combinable via $or when both are
          provided). GET /api/checkins accepts ?goal_id=X and ?component_id=Y.
          Existing tasks/checkins are untouched.

frontend:
  - task: "9-step wizard rewrite (journey_type tiles, name, stages Y/N, stages list, why, target, EO, task, cadence)"
    implemented: true
    working: "NA"
    file: "frontend/app/knowledge/new.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Steps enforced in strict order. Continue button disabled until each
          step is valid. Step 4 auto-skipped when hasStages=false. Stages step
          lets the user add many stages, rename inline, and reorder via
          wizard-stage-up-{i} / wizard-stage-down-{i}. Progress bar shows the
          right total (8 or 9). Cancel prompts a confirm modal only when dirty.

  - task: "Knowledge journey detail with tree UI"
    implemented: true
    working: "NA"
    file: "frontend/app/knowledge/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Route /knowledge/{id} loads the KnowledgeJourney and its Goal in one
          screen. Sections in order: header (type tag + chips), Progress, Why,
          STRUCTURE (stages with components, or components directly if no
          stages), Expected Outcomes, Tasks, Check-ins. Recursive ComponentNode
          supports expand/collapse, add-child (opens ComponentSheet), edit,
          delete (with cascade confirmation), and up/down move. Same for
          stages. Bottom-sheet modals for stage and component add/edit reset
          via useEffect (Modal onShow is unreliable on web).

  - task: "API client: knowledge/stage/component + task/checkin filters, better error stringification"
    implemented: true
    working: "NA"
    file: "frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Added listStages/createStage/updateStage/deleteStage/moveStage and the
          equivalents for components. listTasks/listCheckins now accept goalId
          and componentId. Response type for LearningJourney changed to the
          KnowledgeJourneyResponse shape (journey_type, has_stages, etc.).
          request() now stringifies FastAPI's 422 detail array so an error
          object never lands inside a <Text>.

metadata:
  created_by: "main_agent"
  version: "2.0"
  test_sequence: 9
  run_ui: false

test_plan:
  current_focus:
    - "New Knowledge collections + atomic 9-step wizard"
    - "Stage CRUD + Up/Down move endpoint"
    - "Component CRUD (recursive) + Up/Down move + task/checkin detach on delete"
    - "Legacy backfill for pre-existing Knowledge Goals"
    - "Task/Check-in component_id foreign key + optional query filters"
    - "9-step wizard rewrite"
    - "Knowledge journey detail with tree UI"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      New hierarchical Knowledge engine. Please verify comprehensively.

      BACKEND:
      1. POST /api/knowledge/journeys with a full valid body (journey_type=skill,
         has_stages=true, stages=[{name:"Beginner"},{name:"Advanced"}], why,
         target_completion_date, first_outcome, first_task, checkin_cadence=weekly):
         → 201, Goal + KnowledgeJourney + 2 stages + 1 EO + 1 Task all created.
         Verify by follow-up GETs.
      2. Rejection tests (400/422). None of these must leave any Goal/EO/Task/
         stage/journey persisted (compare counts before and after):
         - journey_type="bogus"
         - has_stages=true with empty stages list
         - missing why / title / first_outcome.title / first_task.title / cadence
         - invalid cadence, invalid outcome_type, invalid task priority
      3. Stage CRUD: POST /api/knowledge/stages, PUT rename, POST /move?direction=up
         and down (verify sequence values swap), DELETE cascades to any components
         in that stage.
      4. Component CRUD: create top-level (parent_component_id=null), create child
         (parent_component_id set — child inherits stage_id from parent). PUT to
         change status/progress (invalid status → 400, progress>100 → 400). DELETE
         must recursively delete descendants AND detach any tasks/checkins that
         referenced any of them (their component_id is set to null but they are
         NOT deleted). POST /move?direction=up|down swaps with the immediate
         sibling. Attempting to move past the ends is a no-op (200 with "No move").
      5. GET /api/tasks?component_id=X and GET /api/checkins?component_id=X filter
         correctly. GET /api/tasks?goal_id=X&component_id=Y returns tasks matching
         EITHER (union). POST /api/tasks with component_id="bogus" → 400.
      6. Legacy backfill: test@hymn.app should already have Knowledge domain and
         at least the legacy Guitar journey. GET /api/knowledge/journeys must
         return every KJ, each with valid goal_id, has_stages, etc.
      7. Regressions: /api/auth/*, /api/goals CRUD, /api/expected-outcomes CRUD,
         /api/projects CRUD, /api/tasks CRUD, /api/checkins CRUD, /api/domains
         CRUD, /api/outcome-types — all must remain green. Legacy tasks and
         check-ins (no component_id column) must still deserialize (null).
      8. Delete a KnowledgeJourney (DELETE /api/knowledge/journeys/{id}) —
         cascades: all its components, stages, journey row, its goal, its EOs.
         Attached tasks/checkins are detached (not deleted).

      FRONTEND (http://localhost:3000):
      1. Sign in with test@hymn.app / TestPass123!. tab-knowledge exists;
         tab-learn does not.
      2. Knowledge home lists journeys, sorted by created_at desc. Card shows
         the correct journey type tag (SKILL / QUALIFICATION / …) or generic
         "LEARNING JOURNEY" for a legacy row (journey_type="").
      3. Tap knowledge-add-button → wizard opens (testID knowledge-wizard).
      4. Advance Continue MUST be disabled until each step is valid. Verify:
         step 1 requires a wizard-type-* selection, step 2 requires text in
         wizard-title-input, step 3 requires wizard-has-stages-yes or -no,
         step 4 (only when Yes) requires at least one stage added via
         wizard-stage-add, step 5 requires wizard-why-input, step 6 skippable,
         step 7 requires wizard-outcome-title-input, step 8 requires
         wizard-task-title-input, step 9 requires a wizard-cadence-* choice.
      5. Complete the wizard (skill, "Chess", yes, ["Beginner","Advanced"],
         "for fun", 2027-01-31, "Learn 20 openings", "Study 3 openings", weekly).
         Verify redirect to /knowledge/{journey_id} — the detail screen shows
         header tag SKILL, 2 stages, 1 outcome, 1 task, chips for date and
         Weekly.
      6. Tree UI on the new journey:
         - Under "Beginner" tap kj-stage-add-comp-{id} → sheet opens →
           fill comp-sheet-name "Openings", comp-sheet-type "Section" → Save →
           node appears with status pill "Not started".
         - On that node tap comp-add-child-{id} → sheet opens → add "Ruy Lopez"
           → Save → parent node shows a chevron → tapping the node expands and
           the child is visible with a deeper indent.
         - Move stage Advanced up → order swaps (Advanced now first). Then
           move down → swaps back.
         - Move component sibling up/down works.
      7. Delete a mid-tree component with children → confirm modal — after
         confirm, the parent and all descendants disappear but tasks in
         /api/tasks with those component_ids now have component_id=null.
      8. Legacy journey (any pre-existing Knowledge card, e.g. Learn Python):
         - Card shows "LEARNING JOURNEY" tag (empty journey_type).
         - Detail opens without crash; STRUCTURE section says "No stages yet"
           (because has_stages=false in the backfill).
         - The Structure "Add" button shows "Component" (flat mode).
      9. Non-Knowledge goals unaffected: from Me → Goals, open any Health or
         Money goal — its detail is unchanged, no journey-type tag, no
         STRUCTURE section.

      Report path: /app/test_reports/iteration_9.json.
      Credentials: /app/memory/test_credentials.md.

  - Learn tab → Knowledge tab (Knowledge is the domain, a Learning Journey IS a Goal in that
    domain — no separate CRUD, no separate collection, no parallel engine).
  - Replace the flat Learning Journey creation screen with a guided 6-step wizard:
      1) title  2) why  3) target completion date  4) first Expected Outcome (required)
      5) first Task (required)  6) check-in cadence (daily|weekly|monthly|manual, persisted).
    Cadence is persisted only. No reminders, no recurring tasks, no AI, no roadmap.
  - Goal (Learning Journey) detail SHALL render in this exact order:
      Learning Journey → Expected Outcomes → Tasks → Check-ins.
  - The old /api/learning-journeys endpoints and `learning_journeys` collection have been
    fully removed. The new atomic wizard endpoint is POST /api/knowledge/journeys.
  - Outside the Knowledge domain, Goal behaviour is unchanged.

backend:
  - task: "Removed /api/learning-journeys endpoints"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          All /api/learning-journeys/* routes and LearningJourney models were removed.
          Any request to /api/learning-journeys (GET/POST/PUT/DELETE) or its /{id} form
          must now return 404 (or 405). No other endpoint should reference this path.

  - task: "Atomic Knowledge wizard endpoint (POST /api/knowledge/journeys)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          POST /api/knowledge/journeys creates Goal + first Expected Outcome + first Task
          atomically in the Knowledge domain. On any partial failure the Goal and EO are
          rolled back. Required body: {title, why, target_completion_date, first_outcome:
          {title, target_value?, unit?, outcome_type?}, first_task: {title, due_date?,
          priority?}, checkin_cadence in {daily|weekly|monthly|manual}}.
          Validation: cadence must be one of the four; invalid outcome_type or priority
          must 400; missing why/title/first_outcome.title/first_task.title must 400/422.

  - task: "GET /api/knowledge/journeys (Knowledge-scoped Goal list)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Returns Goals whose domain is "Knowledge" for the current user. Auto-seeds the
          Knowledge domain if missing (idempotent). Same shape as GoalResponse including
          checkin_cadence and expected_outcomes_total/completed/completion_pct.

  - task: "checkin_cadence field on Goal + idempotent default-domain seeding"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Goal model now has optional checkin_cadence ("" | daily | weekly | monthly | manual).
          Create/Update validate the value. ensure_default_domains now adds only missing
          default domains (Knowledge/Health/Money/Soul) so existing users get Knowledge
          without a manual migration.

  - task: "Optional goal_id filter on /api/tasks and /api/checkins"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          GET /api/tasks?goal_id=<id> returns only tasks whose expected_outcome belongs
          to that goal. GET /api/checkins?goal_id=<id> returns only check-ins for that
          goal. Both are backward-compatible when the query param is omitted.

frontend:
  - task: "Knowledge tab replaces Learn tab; wizard is the only entry"
    implemented: true
    working: "NA"
    file: "frontend/app/(tabs)/knowledge.tsx, frontend/app/(tabs)/_layout.tsx, frontend/app/_layout.tsx, frontend/app/knowledge/new.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Tab bar exposes tab-knowledge (school icon, label "Knowledge"). tab-learn has
          been REMOVED. The old /learn/* screens have been deleted. The + button on the
          Knowledge home routes to /knowledge/new (the guided wizard). Tapping a
          Learning Journey card routes to /goals/{id} — same unified detail as any goal.

  - task: "6-step Learning Journey creation wizard"
    implemented: true
    working: "NA"
    file: "frontend/app/knowledge/new.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Steps enforced in strict order: 1) title (wizard-title-input),
          2) why (wizard-why-input), 3) target date (wizard-target-date-input),
          4) first outcome (wizard-outcome-title-input required + optional target/unit),
          5) first task (wizard-task-title-input required + optional due date),
          6) cadence (wizard-cadence-{daily|weekly|monthly|manual}). The Continue
          button (wizard-next-button) is disabled until each step is valid, ensuring
          the user cannot leave the wizard without a first EO and first Task. Cancel
          shows a confirm modal only if the form is dirty. Finish (wizard-finish-button)
          calls POST /api/knowledge/journeys atomically and redirects to /goals/{id}.

  - task: "Unified Goal detail shows Journey → Expected Outcomes → Tasks → Check-ins"
    implemented: true
    working: "NA"
    file: "frontend/app/goals/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Goal detail now always renders sections in the required order. For Knowledge
          goals the header tag reads "LEARNING JOURNEY" and the notes block is titled
          "WHY THIS MATTERS"; cadence appears as a chip. Tasks section lists all tasks
          linked via expected outcomes belonging to this goal. Check-ins section lists
          check-ins scoped by goal_id.

metadata:
  created_by: "main_agent"
  version: "1.2"
  test_sequence: 15
  run_ui: false

test_plan:
  current_focus:
    - "Portfolio Onboarding Wizard — no auto-navigation between steps"
    - "Cross-midnight time blocks (23:30 → 06:30) save as split records"
    - "Copy day's blocks to multiple other days"
    - "Weekly capacity math updates immediately after adding a block (effective_from = current Monday)"
    - "TimeBlockEditor re-seeds state each time the modal opens (add vs edit)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      RETEST FOCUS — Portfolio Onboarding bug fixes. Prior features
      (Knowledge wizard, Portfolio Manager foundation, Timeline search,
      task completion via check-in) were already verified in earlier runs
      and do NOT need retesting.

      What was fixed in this session:
      1. /app/frontend/app/portfolio/setup.tsx — reload() no longer moves
         `step`. Auto-resume to the first incomplete step now runs only on
         the initial mount via a `didInitialResumeRef` guard. Selecting a
         currency, saving a time block, or adding an account/commitment
         must NOT advance the wizard automatically. Advance only via the
         Continue button (disabled until the step's requirement is met).
      2. /app/frontend/src/components/portfolio/TimeBlockEditor.tsx — added
         useEffect that reseeds title/start/end/category/flex/selectedDays
         whenever the modal reopens with a different `initial`. Fixes
         stale state when switching add ↔ edit ↔ new-day.
      3. Cross-midnight (already coded, needs verification): entering
         start 23:30 / end 06:30 shows a "Crosses midnight" hint and, on
         Save, calls POST /api/portfolio/time-commitments twice: (day D,
         23:30→24:00) and (day D+1, 00:00→06:30). Backend accepts 24:00
         as an end_time sentinel.
      4. Multi-day copy (already coded, needs verification): Copy-to modal
         clones every block on the source day onto every selected target
         day.
      5. Weekly capacity refresh (already coded, needs verification):
         new blocks use `effective_from = current local Monday`, so
         GET /api/portfolio/time-capacity/week returns updated totals for
         this week on the very next reload.

      BACKEND tests (auth: test@hymn.app / TestPass123!):
        - POST /api/portfolio/time-commitments with end_time=24:00 succeeds.
        - POST with end_time <= start_time (and end_time != 24:00) is 400.
        - After creating a 30-min block today, GET /api/portfolio/time-capacity/week
          shows committed_minutes >= 30 on that weekday.

      FRONTEND tests (http://localhost:3000):
        1. Log in, navigate to /portfolio/setup (or run through onboarding).
        2. STEP 0: pick a currency in the modal. Wizard MUST stay on step 0.
           Continue button becomes enabled; user taps Continue to advance.
        3. STEP 1: tap "+" on Monday. In the modal: title "Sleep",
           start 23:30, end 06:30. Verify the "Crosses midnight" hint
           appears. Save. Wizard MUST stay on step 1 (no auto-advance).
           Verify two blocks now render: Monday 23:30–24:00 and Tuesday
           00:00–06:30. Verify the "Weekly available" total decreased.
        4. STEP 1 (copy): with Monday populated, tap the "Copy to…" chip,
           select Tuesday + Wednesday, submit. Both target days get the
           cloned blocks and the weekly-total updates.
        5. STEP 1 (edit): tap an existing block. Modal shows THAT block's
           values (not the previous add-modal's). Change start to 22:00,
           save, wizard stays on step 1.
        6. STEP 2/3: same anti-auto-advance behaviour when adding an
           account or a monthly commitment.
        7. Complete Setup button on step 3 is enabled only when all four
           gates pass.

      Report path: /app/test_reports/iteration_15.json.

