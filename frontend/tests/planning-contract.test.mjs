import assert from "node:assert/strict";
import test from "node:test";

import {
  canonicalTargetPath,
  contextUpdateFor,
  createDraftItem,
  errorMessage,
  mainSurfaceText,
  moveDraftItem,
  nextActionSummary,
  orderedContextSections,
  planningEmptyState,
  removeDraftItem,
  replaceDraftItem,
  toggleDraftItemDeferred,
  validateDraftItems,
} from "../src/lib/planning.ts";

function response(overrides = {}) {
  return {
    id: "proposal-1",
    target_type: "goal",
    target_id: "goal-1",
    stage: "review",
    next_action: {
      action: "review_context",
      label: "Review what Hymn understands",
      method: "PATCH",
      endpoint: "/api/planning/proposals/proposal-1/context",
    },
    context_review: {
      title: "Build a six-month emergency fund",
      intro: "Review the facts Hymn can support before preparing a plan.",
      sections: [
        {
          key: "where_things_stand",
          title: "Where things stand",
          items: [
            {
              key: "current_balance",
              label: "Current recorded balance",
              value: "INR 125,000",
              status: "known",
              editable: true,
              editor: "money",
              why: {
                summary: "Hymn used the account linked to this goal.",
                evidence: ["Primary savings account, updated 25 July 2026"],
              },
            },
          ],
        },
        {
          key: "what_you_want",
          title: "What you want",
          items: [
            {
              key: "objective",
              label: "Desired result",
              value: "Build a six-month emergency fund",
              status: "known",
              editable: true,
              editor: "text",
              why: {
                summary: "This comes from the goal.",
                evidence: ["Goal title"],
              },
            },
          ],
        },
      ],
      questions: [],
      feasibility: {
        status: "appears_feasible",
        summary: "The recorded balance and target date support a useful calculation.",
        appears_feasible: ["There is time remaining before the target date."],
        difficulties: [],
        calculations: [
          {
            label: "Remaining gap",
            value: "INR 475,000",
            explanation: "Target minus the linked current balance.",
          },
        ],
        unknowns: [],
      },
    },
    draft_plan: {
      version: 1,
      can_apply: false,
      items: [],
    },
    return_to: {
      route: "/goals/goal-1",
      target_type: "goal",
      target_id: "goal-1",
      label: "Return to goal",
    },
    ...overrides,
  };
}

test("main planning surface is human-readable and excludes internal tokens", () => {
  const contract = response();
  const text = mainSurfaceText(contract);

  assert.match(text, /Does Hymn understand your situation/);
  assert.match(text, /Current recorded balance/);
  assert.doesNotMatch(text, /verified_structured_field/);
  assert.doesNotMatch(text, /current_balance_account_id/);
  assert.doesNotMatch(text, /\[object Object\]/);
  assert.doesNotMatch(text, /\{"|":"/);
});

test("four review sections are always present in the intended order", () => {
  const sections = orderedContextSections(response().context_review.sections);
  assert.deepEqual(
    sections.map((section) => section.title),
    [
      "What you want",
      "Where things stand",
      "What may affect this",
      "What Hymn still needs",
    ],
  );
});

test("stage and next action explain a useful path forward", () => {
  assert.equal(nextActionSummary(response()), "Review what Hymn understands");
  const questions = response({
    stage: "questions",
    context_review: {
      ...response().context_review,
      questions: [
        {
          id: "balance",
          field: "current_balance_account_id",
          prompt: "Which account balance applies?",
          help_text: "Choose only the account linked to this goal.",
          input_type: "select",
          required: true,
          options: [{ value: "account-1", label: "Primary savings" }],
        },
      ],
    },
  });
  assert.equal(nextActionSummary(questions), "Answer the questions below to continue.");
});

test("context corrections map only to supported authoritative fields", () => {
  assert.deepEqual(contextUpdateFor("target_date", "2030-12-31"), {
    target_date: "2030-12-31",
  });
  assert.deepEqual(contextUpdateFor("current_balance", "250000"), {
    current_balance: "250000",
  });
  assert.equal(contextUpdateFor("verified_structured_field", "unsafe"), null);
});

test("canonical return routes lead back to the owned target", () => {
  assert.equal(
    canonicalTargetPath(response().return_to),
    "/goals/goal-1",
  );
  assert.equal(
    canonicalTargetPath({
      route: "/projects/project 1",
      target_type: "project",
      target_id: "project 1",
      label: "Return to project",
    }),
    "/projects/project%201",
  );
  assert.equal(
    canonicalTargetPath({
      route: "/knowledge/journey-1",
      target_type: "journey",
      target_id: "journey-1",
      label: "Return to learning journey",
    }),
    "/knowledge/journey-1",
  );
});

test("proposal operations add, edit, reorder, defer, and remove safely", () => {
  const first = {
    ...createDraftItem("milestone", "m1", 0),
    title: "Reach the halfway point",
  };
  const second = {
    ...createDraftItem("task", "t1", 1),
    title: "Set the first transfer",
  };

  let items = [first, second];
  items = moveDraftItem(items, "t1", "up");
  assert.deepEqual(items.map((item) => item.id), ["t1", "m1"]);
  assert.deepEqual(items.map((item) => item.position), [0, 1]);

  items = toggleDraftItemDeferred(items, "t1");
  assert.equal(items[0].status, "deferred");

  items = replaceDraftItem(items, { ...items[1], title: "Reach 50%" });
  assert.equal(items[1].title, "Reach 50%");

  items = removeDraftItem(items, "t1");
  assert.deepEqual(items.map((item) => item.id), ["m1"]);
  assert.equal(items[0].position, 0);
  assert.equal(validateDraftItems(items), null);
  assert.equal(validateDraftItems([]), null);
});

test("empty, invalid, and error states always explain a next step", () => {
  assert.match(planningEmptyState("review"), /prepare a draft/i);
  assert.match(planningEmptyState("questions"), /answer/i);
  assert.match(planningEmptyState("proposal"), /try/i);
  assert.match(planningEmptyState("applied"), /added/i);
  assert.equal(
    errorMessage({ message: "Please retry" }, "Fallback"),
    "Please retry",
  );
  assert.equal(errorMessage(new Error(), "Fallback"), "Fallback");
  assert.equal(errorMessage("network", "Fallback"), "Fallback");
});
