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
  Build the first version of the Learn module (Learning Journeys) and wire it end-to-end.
  Add Learn to the bottom nav bar, move "Me" out to a header avatar (top right of every tab),
  keep the existing Goals/Projects/Tasks/Check-ins/Domains modules untouched, and use the
  native DateTimeField for the target completion date.

backend:
  - task: "Learning Journeys CRUD (/api/learning-journeys)"
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
          Endpoints: GET/POST /api/learning-journeys, GET/PUT/DELETE /api/learning-journeys/{id}.
          Auth: JWT/session bearer via get_current_user. Model has title, description,
          target_completion_date (YYYY-MM-DD), status (active|archived), created_at, updated_at.
          Needs end-to-end backend testing including 401 without token, 404 for missing/other-user
          journey, status validation (must be active|archived), and user isolation.

frontend:
  - task: "Learn tab, list, add, detail, edit screens (native DateTimeField)"
    implemented: true
    working: "NA"
    file: "frontend/app/(tabs)/learn.tsx, frontend/app/learn/*.tsx, frontend/src/components/HeaderAvatar.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Replaced the "Me" tab with a "Learn" tab in (tabs)/_layout.tsx. Moved Me to /me and
          exposed it via a HeaderAvatar rendered on Today, Timeline, Finance, and Learn tab
          headers. Learn list uses cards (LEARNING tag + status pill + description + target
          date meta). Add/Edit forms use DateTimeField for target_completion_date. Detail
          screen supports Edit and Delete with ConfirmModal.
          Manual web smoke test passed (created "Master Rust programming" journey with
          target Dec 31, 2026 and detail rendered correctly).

metadata:
  created_by: "main_agent"
  version: "1.0"
  test_sequence: 7
  run_ui: false

test_plan:
  current_focus:
    - "Learning Journeys CRUD (/api/learning-journeys)"
    - "Learn tab, list, add, detail, edit screens (native DateTimeField)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Please test the new Learn module end-to-end.
      Backend: /api/learning-journeys CRUD, ensure auth required, status validation
      (active|archived), 404 handling, and user isolation (two users cannot see each
      other's journeys). Existing endpoints (goals, projects, tasks, checkins, domains,
      expected-outcomes, outcome-types, auth) must remain unbroken.
      Frontend: The Me tab has been replaced by a Learn tab; Me is now reachable through
      a small circular header avatar (testID header-avatar) present on Today, Timeline,
      Finance, and Learn. Verify tab-learn navigates to the Learn list, empty state has
      "Start a journey" CTA (learn-empty-add-button), add form (add-learn-title-input,
      add-learn-description-input, add-learn-target-date-input, add-learn-save-button)
      creates a journey, list shows it, detail renders (learn-detail-title,
      learn-detail-description, learn-detail-target-date), edit and delete both work,
      and the header avatar opens /me (which still has domains/goals/projects/tasks/
      overlay + logout).
      Credentials: /app/memory/test_credentials.md (test@hymn.app / TestPass123!).
