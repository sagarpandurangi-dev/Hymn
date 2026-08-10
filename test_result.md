#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: |
  Add a manual "Merge Goals" wizard. The user picks 2+ goals; Hymn
  proposes a plan showing which outcomes to Keep, Nest (as tasks under
  a parent outcome), or Delete (duplicate). User approves or overrides
  via drag-and-drop reordering + explicit action chips + a nest-picker.
  If merging would leave the portfolio over-capacity, Hymn blocks Apply
  until the user adds trade-offs (postpone / cancel) inside the wizard.
  Locked choices:
    (1) Drag-and-drop reordering via react-native-draggable-flatlist.
    (2) Block Apply until conflicts are resolved.

backend:
  - task: "POST /planning/merge/preview — analyze + LLM-plan"
    implemented: true
    working: true
    file: "backend/goal_merge.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Loads full bundles for each requested goal (outcomes + tasks +
          checkin counts). Rejects exclusive goals (400). Scores each by
          richness (existing _richness_score helper) and picks the top-
          scoring goal as the fallback survivor. Then calls Claude
          Sonnet 4.5 (non-streaming) with a strict JSON-only system
          prompt to propose a per-outcome plan (keep / nest / delete).
          If the LLM fails or returns nonsense, falls back to the
          deterministic "keep everything" scaffold. Every rule is
          validated: unknown outcome ids dropped, "nest" without a
          valid parent downgraded to "keep". Duplicate hints emitted
          via naive title-clustering across all outcomes. Capacity
          snapshot + advisory conflicts included.

  - task: "POST /planning/merge/apply — atomic merge execution"
    implemented: true
    working: true
    file: "backend/goal_merge.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Applies user tradeoffs first (postpone/cancel on postponable
          items only). Refuses (409) if capacity_conflicts present but
          tradeoffs empty. Then per outcome:
            * "delete" → detach tasks (set standalone) + retarget
              checkins to survivor + delete outcome
            * "nest"  → create a Task under the parent outcome + move
              child tasks to the parent + retarget checkins to survivor
              on the parent outcome + delete the source outcome
            * "keep"  → reparent goal_id to survivor if not already
          Then apply explicit user-approved duplicate deletions (retarget
          to same-title survivor outcome if one exists, else null-out).
          Mop up any leftover outcomes/checkins still pointing at losers
          by force-moving them to survivor. Merge notes across losers
          into survivor. Delete losers. Rejects exclusive goals (400).

frontend:
  - task: "Knowledge tab multi-select + Merge action"
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
          Long-press a Knowledge card enters select mode; tap toggles
          selection. When 2+ selected, header shows a "Merge" button
          (disabled at <2). Tapping it routes to
          /goals/merge?ids=id1,id2,….

  - task: "Merge wizard with drag-and-drop"
    implemented: true
    working: true
    file: "frontend/app/goals/merge.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Uses react-native-draggable-flatlist for the outcome list.
          Each card shows source goal, tasks count, DUPLICATE? badge if
          title-cluster matched, and 3 action chips (Keep / Nest under…
          / Delete). Nest opens a picker of eligible parent outcomes.
          Survivor selector row lets the user override Hymn's pick.
          Capacity conflict banner surfaces when the LLM/heuristic
          detects one, with an inline tradeoff picker (postpone/cancel
          with custom date). Apply is disabled until conflicts are
          resolved.
          Live end-to-end test on test@hymn.app: TEST_UI_Chess + Guitar
          merged into Guitar (richer, score 32). LLM auto-nested
          "Learn 20 openings" under Intermediate; "Master open chord
          shapes" + "Smooth chord transitions" under Beginner;
          duplicate Beginner/Advanced flagged + auto-Delete.
          Capacity gate required 1 tradeoff; picker showed 42 items;
          Apply → navigated to Guitar goal detail showing merged
          outcomes + 14 tasks + 7 reparented Chess check-ins.

  - task: "API client — mergePreview + mergeApply"
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
          Simple typed methods on the shared api object.

metadata:
  created_by: "main_agent"
  version: "3.3"
  test_sequence: 19
  run_ui: false

test_plan:
  current_focus:
    - "POST /planning/merge/preview — analyze + LLM-plan"
    - "POST /planning/merge/apply — atomic merge execution"
    - "Merge wizard with drag-and-drop"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Manual Goal Merge wizard shipped end-to-end. Recommended test
      coverage from testing_agent:
        * Backend: exclusive-goal safety on both merge/preview + apply
          (should 400 on preview and apply). Nesting under a
          to-be-deleted parent → 400. Capacity conflict with no
          tradeoffs → 409. Apply with valid plan → goal survives,
          losers 404, expected_outcomes reparented, nested outcomes
          converted to tasks, checkins retargeted to survivor.
        * Frontend: multi-select from Knowledge tab → Merge button
          enables at 2+ selected; wizard renders survivor row +
          outcome cards + capacity banner + tradeoff picker; Apply
          navigates to survivor goal.
