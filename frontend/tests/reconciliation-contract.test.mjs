import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  beginResolution,
  canSubmitResolution,
  financeReturnRoute,
  idleResolutionState,
  isResolutionBusy,
  reconciliationEmptyCopy,
  removeResolvedSuggestion,
  resolutionFailed,
  resolutionRefreshFailed,
  resolutionSaved,
  resolutionSucceeded,
  unplannedSuccessMessage,
} from "../src/lib/reconciliation.ts";

const result = {
  detail: "Recorded as an unplanned actual expense.",
  resolution: "resolved_unplanned",
  already_resolved: false,
  event: {
    id: "event-1",
    amount: "700.00",
    currency: "INR",
    checkin_id: "checkin-1",
    source_reference: "checkin:checkin-1",
    reconciliation_status: "resolved_unplanned",
  },
  canonical_actual: {
    record_type: "financial_event",
    record_id: "event-1",
    source: "checkin",
  },
  balance_adjustment: {
    status: "not_applied",
    reason: "No paying account was selected.",
  },
  refresh: {
    finance_summary_endpoint: "/finance/dashboard",
    pending_reconciliation_endpoint: "/finance/reconciliation/suggestions",
  },
  navigation: {
    route: "/(tabs)/finance",
    label: "Back to Finance",
  },
};

const suggestions = [
  {
    event: {
      id: "event-1",
      amount: "700.00",
      currency: "INR",
      direction: "outflow",
      event_date: "2026-07-26",
      description: "Goal check-in",
      source: "checkin",
      confirmation_status: "confirmed",
    },
    matches: [],
    single_strong_match: null,
  },
  {
    event: {
      id: "event-2",
      amount: "20.00",
      currency: "USD",
      direction: "outflow",
      event_date: "2026-07-26",
      description: "Other event",
      source: "manual",
      confirmation_status: "confirmed",
    },
    matches: [],
    single_strong_match: null,
  },
];

test("first submission becomes busy immediately and prevents repeats", () => {
  const idle = idleResolutionState();
  const submitting = beginResolution("event-1");

  assert.equal(canSubmitResolution(idle, "event-1"), true);
  assert.equal(isResolutionBusy(submitting, "event-1"), true);
  assert.equal(canSubmitResolution(submitting, "event-1"), false);
  assert.equal(canSubmitResolution(submitting, "event-2"), false);
});

test("success removes the resolved card and produces owner-facing copy", () => {
  const saved = resolutionSaved(result);
  const success = resolutionSucceeded(result);
  const remaining = removeResolvedSuggestion(suggestions, "event-1");

  assert.equal(saved.phase, "saved_refreshing");
  assert.equal(success.phase, "success");
  assert.equal(unplannedSuccessMessage(result), "₹700 recorded as an unplanned expense.");
  assert.deepEqual(remaining.map((item) => item.event.id), ["event-2"]);
  assert.equal(canSubmitResolution(success, "event-1"), false);
});

test("partial success never encourages resubmission and offers refresh context", () => {
  const partial = resolutionRefreshFailed(
    result,
    "Finance summary could not refresh.",
  );

  assert.equal(partial.phase, "saved_refresh_failed");
  assert.equal(partial.message, "₹700 recorded as an unplanned expense.");
  assert.equal(partial.refreshError, "Finance summary could not refresh.");
  assert.equal(canSubmitResolution(partial, "event-1"), false);
});

test("failed persistence keeps the event retryable with the useful error", () => {
  const failed = resolutionFailed("event-1", "Database write failed. Try again.");

  assert.equal(failed.phase, "failed");
  assert.equal(failed.message, "Database write failed. Try again.");
  assert.equal(canSubmitResolution(failed, "event-1"), true);
});

test("empty states distinguish completed work from no pending work", () => {
  assert.deepEqual(reconciliationEmptyCopy(true), {
    title: "All caught up",
    body: "That expense is resolved and no other confirmed events need your attention.",
  });
  assert.deepEqual(reconciliationEmptyCopy(false), {
    title: "Nothing to reconcile",
    body: "No confirmed expenses are waiting for a decision.",
  });
});

test("backend contract provides Finance refresh and navigation metadata", () => {
  assert.equal(
    result.refresh.pending_reconciliation_endpoint,
    "/finance/reconciliation/suggestions",
  );
  assert.equal(result.refresh.finance_summary_endpoint, "/finance/dashboard");
  assert.equal(result.navigation.route, financeReturnRoute);
  assert.equal(result.canonical_actual.record_type, "financial_event");
  assert.equal(result.balance_adjustment.status, "not_applied");
});

test("screen implements loading, disabled, error, refresh, and focus refresh states", () => {
  const reconciliationScreen = readFileSync(
    new URL("../app/finance/reconciliation.tsx", import.meta.url),
    "utf8",
  );
  const financeScreen = readFileSync(
    new URL("../app/(tabs)/finance.tsx", import.meta.url),
    "utf8",
  );

  assert.match(reconciliationScreen, /disabled=\{anyBusy\}/);
  assert.match(reconciliationScreen, /Saving…/);
  assert.match(reconciliationScreen, /recon-saved-refreshing/);
  assert.match(reconciliationScreen, /Refreshing Finance totals…/);
  assert.match(reconciliationScreen, /recon-success/);
  assert.match(reconciliationScreen, /recon-partial-success/);
  assert.match(reconciliationScreen, /recon-error-/);
  assert.match(reconciliationScreen, /Refresh Finance/);
  assert.match(reconciliationScreen, /Back to Finance/);
  assert.match(financeScreen, /useFocusEffect/);
  assert.doesNotMatch(reconciliationScreen, /catch\s*\{\s*\/\*\s*ignore\s*\*\//);
});
