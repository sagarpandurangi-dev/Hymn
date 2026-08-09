#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================
# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK
#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: |
  Reform the Decomposition Engine into ONE conversational planning engine
  that enriches the existing Goal / Project (no parallel journeys, routes,
  workflows, or duplicate planning objects). User locked choices:

  1) Migrate knowledge_journeys → Goals (stages → outcomes, components → tasks),
     destructive delete of the parallel collections.
  2) Use Anthropic Claude Sonnet 4.5 with the built-in `web_search` tool via
     the Emergent LLM key.
  3) Reuse /planning/{targetType}/{targetId} but replace per-field confirmation
     with a chat thread.
  4) Slice 1 + compressed Slice 2: conversational engine, atomic
     materialization, Day/Week/Month grouping on detail pages, virtualized
     lists (SectionList with initial/maxToRender/window tuning), bulk
     reschedule + complete + archive + delete.
  5) Archive plan_proposals + remove old per-field UI.
  Response streaming: request-response (non-streaming) turns.

backend:
  - task: "One-shot migration: knowledge_journeys → goals; archive plan_proposals"
    implemented: true
    working: true
    file: "backend/migrations/reform_decomposition.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Ran successfully — {'journeys': 54, 'outcomes': 40, 'tasks': 6,
          'archived_proposals': 16}. All three parallel collections
          (knowledge_journeys/stages/components) now empty. Goal counts
          increased with migrated outcomes and tasks.

  - task: "Remove /api/knowledge/* routes + models + validation"
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
          Deleted lines 1885–2543 (Knowledge Engine block: models,
          helpers, journey/stage/component routes). Removed
          knowledge_components lookups from task/checkin create paths.
          Added optional journey_type to Goal for the migrated tag.
          Added project_id filter to /api/tasks and /api/checkins.

  - task: "Conversational Planning Engine (Claude Sonnet 4.5 + web_search)"
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
          Full rewrite. New endpoints:
            GET  /api/planning/{target_type}/{target_id}/conversation
            POST /api/planning/{target_type}/{target_id}/messages
            POST /api/planning/{target_type}/{target_id}/reset
            POST /api/planning/conversations/{id}/materialize
          Uses emergentintegrations.LlmChat + Anthropic web_search
          provider-hosted tool (max_uses=3). Structured proposal block
          HYMN_PROPOSAL is parsed server-side and stripped from the
          message content sent to the UI. Materialization atomically
          creates outcomes/tasks and optionally updates target cadence /
          deadline / notes with compensating rollback on failure.
          Live end-to-end test with test@hymn.app on a Knowledge goal —
          LLM proposed 5 tasks + weekly cadence and materialization
          created them successfully.

frontend:
  - task: "Delete /app/frontend/app/knowledge/{new,[id]}.tsx routes"
    implemented: true
    working: true
    file: "frontend/app/knowledge/*"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Deleted both files and the directory. Removed corresponding
          Stack.Screen entries from /app/frontend/app/_layout.tsx.

  - task: "Knowledge tab now lists Goals in the Knowledge domain"
    implemented: true
    working: true
    file: "frontend/app/(tabs)/knowledge.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Rewritten to filter listGoals() by domain_name === "Knowledge".
          Tag shows JOURNEY type label from the migrated `journey_type`
          field, or "LEARNING JOURNEY" fallback. Cards route to
          /goals/{id}. Add button routes to /goals/add?domain=Knowledge.
          Verified via screenshot: 5 Knowledge goals shown, including
          migrated legacy Guitar / Master Kubernetes / Learn Python.

  - task: "Conversational chat UI on /planning/[targetType]/[targetId].tsx"
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
          Full rewrite as a chat thread — user + assistant bubbles,
          "Hymn is thinking…" indicator, opener chips on empty state,
          message input with send button, reset button in header.
          Assistant messages that carry a proposal render a card with
          summary + outcome/task counts + Apply button. After apply the
          card shows a green "Added X outcomes and Y tasks." confirmation.
          Verified via screenshot end-to-end with LLM.

  - task: "Goal detail — virtualized SectionList grouping + bulk actions"
    implemented: true
    working: true
    file: "frontend/app/goals/[id].tsx + src/components/TaskListWithGrouping.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          New TaskListWithGrouping component groups tasks by
          Today / This week / This month / Later / No due date / Completed
          buckets with sticky section headers, uses SectionList with
          initialNumToRender=20, maxToRenderPerBatch=30, windowSize=7 for
          virtualization. Long-press enters bulk-select mode; action bar
          exposes Reschedule (Tomorrow / +7 days / +30 days / Custom),
          Complete, Archive, Delete. Verified via screenshot.

  - task: "Project detail — Tasks + Check-ins with grouping + bulk actions"
    implemented: true
    working: true
    file: "frontend/app/projects/[id].tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Added Tasks and Check-ins sections. Tasks use the same
          TaskListWithGrouping. listTasks/listCheckins now accept a
          projectId filter (added to backend and api client).

  - task: "Api client cleanup + new planning endpoints"
    implemented: true
    working: true
    file: "frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Removed listStages/createStage/…/moveComponent (old Knowledge
          CRUD). Rewrote listLearningJourneys as a compat wrapper over
          listGoals filtered by Knowledge. Replaced planningAnalyze /
          planningConfirm / planningGenerate / planningApprove /
          planningReject / planningPause / planningSelectTradeoff /
          planningReassess with planningGetConversation /
          planningSendMessage / planningReset / planningMaterialize.

metadata:
  created_by: "main_agent"
  version: "3.0"
  test_sequence: 16
  run_ui: false

test_plan:
  current_focus:
    - "Conversational Planning Engine (Claude Sonnet 4.5 + web_search)"
    - "Goal detail — virtualized SectionList grouping + bulk actions"
    - "Knowledge tab now lists Goals in the Knowledge domain"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Reform of the Decomposition Engine is complete and smoke-tested
      end-to-end (login, Knowledge list, goal detail, chat, LLM reply,
      Apply changes, verify tasks appear).
      Credentials for automated tests: /app/memory/test_credentials.md.
      Key smoke-test scenarios to verify:
        1. Log in with test@hymn.app / TestPass123!.
        2. Knowledge tab lists Goals in the Knowledge domain (5 cards on
           this test account — migrated journeys show as goals).
        3. Open a Knowledge goal → tap "Plan with Hymn" → chat opens.
        4. Send an opener like "Suggest 5 concrete next tasks." → LLM
           replies with prose + a Proposed Changes card.
        5. Tap "Apply these changes" → card shows "Added X outcomes and
           Y tasks."; back on the goal, tasks appear grouped by
           Today / This week / This month / Later / No due date /
           Completed with sticky headers.
        6. Long-press a task to enter bulk-select mode; verify all four
           bulk actions (Reschedule, Complete, Archive, Delete) work.
        7. Open a Project detail → tap "Plan with Hymn" → chat works;
           tasks materialize onto the project.
        8. Verify old routes are gone:
             GET /api/knowledge/journeys        → 404
             GET /api/planning/proposals        → 404
             GET /api/planning/goal/{id}/conversation → 200
