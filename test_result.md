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
  Architectural correction: ONE learning workflow. Delete the parallel Learn/LearningJourney
  workflow and unify with Knowledge domain + Goal/Expected Outcome/Task/Check-in engine.
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
  version: "1.1"
  test_sequence: 8
  run_ui: false

test_plan:
  current_focus:
    - "Removed /api/learning-journeys endpoints"
    - "Atomic Knowledge wizard endpoint (POST /api/knowledge/journeys)"
    - "GET /api/knowledge/journeys (Knowledge-scoped Goal list)"
    - "checkin_cadence field on Goal + idempotent default-domain seeding"
    - "Optional goal_id filter on /api/tasks and /api/checkins"
    - "Knowledge tab replaces Learn tab; wizard is the only entry"
    - "6-step Learning Journey creation wizard"
    - "Unified Goal detail shows Journey → Expected Outcomes → Tasks → Check-ins"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      This is an architectural refactor, not a new feature. Please verify:

      BACKEND:
      1. /api/learning-journeys/* is fully gone (any verb → 404). No response should
         include LearningJourney model fields.
      2. POST /api/knowledge/journeys with a full valid body creates a Goal, one
         Expected Outcome and one Task in one shot; the returned goal has domain_name
         "Knowledge" and checkin_cadence set. Subsequent
         GET /api/goals/{id}, GET /api/goals/{id}/expected-outcomes,
         GET /api/tasks?goal_id={id} must reflect the created rows.
      3. Rejection cases (400/422): missing why, missing title, missing first_outcome.title,
         missing first_task.title, missing cadence, invalid cadence, invalid outcome_type,
         invalid task priority. NO Goal, EO or Task should be persisted on any rejection.
      4. GET /api/knowledge/journeys returns only Knowledge-domain goals with
         checkin_cadence and completion stats.
      5. Existing endpoints (goals CRUD, expected-outcomes CRUD, tasks CRUD, checkins CRUD,
         domains CRUD, outcome-types, auth) still work. In particular, POST /api/goals
         still accepts an omitted checkin_cadence (defaults to ""), and updateGoal accepts
         a checkin_cadence patch. Invalid cadence on either → 400.
      6. GET /api/tasks?goal_id=<id> and /api/checkins?goal_id=<id> filter correctly.
      7. Existing user (test@hymn.app / TestPass123!) — verify the Knowledge domain now
         exists in their /api/domains (idempotent seeding).

      FRONTEND (http://localhost:3000):
      1. Bottom nav has tab-knowledge; tab-learn does NOT exist.
      2. Knowledge home lists Learning Journeys with LEARNING JOURNEY tag and progress
         meta. Tap card → routes to /goals/{id} (unified detail).
      3. Tapping + on Knowledge OR the empty-state CTA opens knowledge-wizard.
      4. Wizard cannot advance past step 4 without first outcome title, cannot advance
         past step 5 without first task title, cannot finish without a cadence choice.
      5. Cancel prompts a confirm modal only when the form is dirty; discarding does not
         create anything on the backend (verify GET /api/knowledge/journeys unchanged).
      6. Finishing the wizard opens Goal detail with sections in order: header (Learning
         Journey tag, chips), Progress, Why This Matters, Expected Outcomes, Tasks,
         Check-ins. All three sections are present even if empty.
      7. Non-Knowledge goals still show the classic domain name (e.g. HEALTH) as the tag,
         and the notes block reads "NOTES", not "WHY THIS MATTERS".

      Credentials: /app/memory/test_credentials.md (test@hymn.app / TestPass123!).
      Report path: /app/test_reports/iteration_8.json.

