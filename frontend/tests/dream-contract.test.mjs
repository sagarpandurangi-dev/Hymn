import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  acceptedPlanNodes,
  canPlaceNode,
  factDisplayValue,
  mapMainSurfaceText,
  nodeDepth,
  researchActionLabel,
  siblingMoveOperation,
  sourceLabel,
  suggestedAddKind,
  visiblePlanNodes,
} from "../src/lib/dreams.ts";

const task = {
  id: "task-1",
  kind: "task",
  parent_id: "milestone-1",
  rank: 1024,
  display_number: "2.1.1",
  title: "Do the work",
  description: "A readable task",
  origin: "hymn",
  decision_state: "proposed",
  dependencies: [],
  evidence_ids: [],
  assumptions: [],
  checkin: null,
  revision: 1,
};

const proposal = {
  id: "dream-1",
  schema_version: 1,
  source: { type: "intent", id: null, title: "Buy an iPad" },
  status: "review",
  revision: 1,
  original_text: "Buy an iPad",
  interpretation: {
    version: 1,
    primary: {
      journey_shape: "purchase",
      label: "Make a purchase",
      reason: "The words describe buying something.",
      confidence: "clear",
    },
    alternatives: [],
    facts: [
      {
        key: "desired_object",
        value: "iPad",
        value_type: "text",
        origin: "inferred",
      },
    ],
    uncertainties: ["What price should Hymn use?"],
    why: { summary: "Purchase words", evidence: ["Buy an iPad"] },
  },
  context: {
    source: null,
    finance: {
      requested_currency: null,
      compatible_liquid_accounts: [],
      recorded_liquid_total: null,
      recorded_liquid_account_count: 0,
      unresolved_movements: {},
      balance_label: "Recorded liquid balance",
      freshness_warning: null,
    },
    commitments: {
      other_active_goals: [],
      other_active_projects: [],
      open_task_count: 0,
      recorded_checkin_count: 0,
    },
    domains_queried: ["financial_accounts"],
    domains_with_data: [],
    honesty: "Only recorded domains were used.",
    why: { evidence: [] },
  },
  scale: {
    version: 1,
    recommended_depth: "moderate",
    user_selected_depth: null,
    summary: "Moderate planning depth is suggested.",
    axes: [
      { id: "financial", level: null, summary: "No price was supplied." },
    ],
    calculations: [],
    missing: ["financial"],
  },
  research: {
    state: "research_not_needed",
    message: "No web research is required.",
    questions: [],
    evidence: [],
    provider_enabled: false,
  },
  map: {
    version: 1,
    revision: 1,
    nodes: [task],
    can_undo: false,
  },
  creation_preview: {
    summary: "Nothing has been created yet.",
    counts: { phase: 0, milestone: 0, task: 0, checkin_requirement: 0 },
    source_effect: "Create one owned active Dream plan",
  },
  applied_plan: null,
  return_to: {
    route: "/dreams/dream-1",
    label: "View this intention",
    target_type: "intent",
    target_id: "dream-1",
  },
  updated_at: "2026-07-27T00:00:00Z",
};

test("hierarchy placement contract matches the canonical map", () => {
  assert.equal(canPlaceNode("phase", null), true);
  assert.equal(canPlaceNode("phase", "phase"), false);
  assert.equal(canPlaceNode("milestone", "phase"), true);
  assert.equal(canPlaceNode("task", "milestone"), true);
  assert.equal(canPlaceNode("checkin_requirement", "task"), true);
  assert.equal(canPlaceNode("checkin_requirement", "milestone"), false);
  assert.equal(suggestedAddKind({ kind: "phase" }), "milestone");
  assert.equal(suggestedAddKind({ kind: "milestone" }), "task");
  assert.equal(suggestedAddKind({ kind: "task" }), "checkin_requirement");
});

test("display numbering controls indentation, never identity", () => {
  assert.equal(nodeDepth(task), 2);
  const changedNumber = { ...task, display_number: "5.3.2" };
  assert.equal(changedNumber.id, task.id);
  assert.equal(nodeDepth(changedNumber), 2);
});

test("sibling reorder creates an explicit stable-id move operation", () => {
  const siblings = [
    { ...task, id: "a", parent_id: "m", rank: 1024 },
    { ...task, id: "b", parent_id: "m", rank: 2048 },
    { ...task, id: "c", parent_id: "m", rank: 3072 },
  ];
  assert.deepEqual(siblingMoveOperation(siblings, "b", "up"), {
    type: "move",
    node_id: "b",
    parent_id: "m",
    relative_id: "a",
    placement: "before",
  });
  assert.equal(siblingMoveOperation(siblings, "a", "up"), null);
  assert.equal(siblingMoveOperation(siblings, "c", "down"), null);
});

test("review visibility and apply inclusion are separate", () => {
  const nodes = [
    { ...task, id: "proposed", decision_state: "proposed" },
    { ...task, id: "accepted", decision_state: "accepted" },
    { ...task, id: "modified", decision_state: "modified" },
    { ...task, id: "deferred", decision_state: "deferred" },
    { ...task, id: "rejected", decision_state: "rejected" },
  ];
  assert.deepEqual(
    visiblePlanNodes(nodes).map((node) => node.id),
    ["proposed", "accepted", "modified", "deferred"],
  );
  assert.deepEqual(
    acceptedPlanNodes(nodes).map((node) => node.id),
    ["accepted", "modified"],
  );
});

test("facts are readable and never stringify raw objects", () => {
  assert.equal(factDisplayValue(proposal.interpretation.facts[0]), "iPad");
  assert.equal(
    factDisplayValue({ ...proposal.interpretation.facts[0], value: { amount: 10 } }),
    "Structured detail available",
  );
  assert.equal(sourceLabel("inferred"), "Hymn inferred this");
  assert.equal(sourceLabel("user_corrected"), "You corrected this");
});

test("main surface contains human language and no internal provenance tokens", () => {
  const text = mapMainSurfaceText(proposal);
  assert.match(text, /Buy an iPad/);
  assert.match(text, /Make a purchase/);
  assert.match(text, /No price was supplied/);
  assert.doesNotMatch(text, /evidence_ids|verified_structured_field|active_goals_count/);
  assert.doesNotMatch(text, /\{"amount"/);
});

test("research states always provide a usable fallback label", () => {
  assert.equal(researchActionLabel("research_recommended"), "Add requirements manually");
  assert.equal(researchActionLabel("research_failed"), "Continue without research");
  assert.equal(researchActionLabel("manual_input_required"), "Add what you know");
});

test("composer honors reduced motion and never delays interaction", () => {
  const screen = readFileSync(
    new URL("../src/components/dreams/DreamMapScreen.tsx", import.meta.url),
    "utf8",
  );
  const backend = readFileSync(
    new URL("../../backend/dream_engine.py", import.meta.url),
    "utf8",
  );
  assert.match(screen, /AccessibilityInfo\.isReduceMotionEnabled/);
  assert.match(screen, /reduceMotionChanged/);
  assert.match(backend, /"reduced_motion_duration_ms": 0/);
  assert.match(backend, /"interaction_delay_ms": 0/);
});

test("all four visible entry surfaces converge on the Dream Engine", () => {
  const today = readFileSync(
    new URL("../app/(tabs)/today.tsx", import.meta.url),
    "utf8",
  );
  const learning = readFileSync(
    new URL("../app/(tabs)/knowledge.tsx", import.meta.url),
    "utf8",
  );
  const goal = readFileSync(
    new URL("../app/goals/[id].tsx", import.meta.url),
    "utf8",
  );
  const project = readFileSync(
    new URL("../app/projects/[id].tsx", import.meta.url),
    "utf8",
  );
  const compatibility = readFileSync(
    new URL("../app/planning/[targetType]/[targetId].tsx", import.meta.url),
    "utf8",
  );
  assert.match(today, /dreams\/new\?sourceType=intent/);
  assert.match(learning, /dreams\/new\?sourceType=learning/);
  assert.match(goal, /dreams\/new\?sourceType=goal/);
  assert.match(project, /dreams\/new\?sourceType=project/);
  assert.match(compatibility, /dreams\/new\?sourceType=/);
});

test("required check-ins remain definitions rather than actual check-in entries", () => {
  const screen = readFileSync(
    new URL("../src/components/dreams/DreamMapScreen.tsx", import.meta.url),
    "utf8",
  );
  assert.match(screen, /Required check-in/);
  assert.match(screen, /not fake completed updates/);
  assert.doesNotMatch(screen, /api\.createCheckin/);
});
