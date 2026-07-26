export type ReconciliationEvent = {
  id: string;
  amount: string;
  currency: string;
  direction: "outflow" | "inflow";
  event_date: string;
  description: string;
  source: string;
  source_reference?: string | null;
  confirmation_status: string;
  reconciliation_status?: string | null;
  checkin_id?: string | null;
  commitment_id?: string | null;
};

export type ReconciliationCommitment = {
  id: string;
  title: string;
  amount: string;
  currency: string;
  due_date: string;
  priority: string;
};

export type ReconciliationMatch = {
  commitment: ReconciliationCommitment;
  score: number;
  reasons: string[];
};

export type ReconciliationSuggestion = {
  event: ReconciliationEvent;
  matches: ReconciliationMatch[];
  single_strong_match: ReconciliationMatch | null;
};

export type UnplannedResolutionResult = {
  detail: string;
  resolution: "resolved_unplanned";
  already_resolved: boolean;
  event: {
    id: string;
    amount: string;
    currency: string;
    checkin_id?: string | null;
    source_reference?: string | null;
    reconciliation_status: "resolved_unplanned";
  };
  canonical_actual: {
    record_type: "financial_event";
    record_id: string;
    source: string;
  };
  balance_adjustment: {
    status: "not_applied";
    reason: string;
  };
  refresh: {
    finance_summary_endpoint: string;
    pending_reconciliation_endpoint: string;
  };
  navigation: {
    route: "/(tabs)/finance";
    label: string;
  };
};

export type ResolutionUiState =
  | { phase: "idle" }
  | { phase: "submitting"; eventId: string }
  | { phase: "saved_refreshing"; eventId: string; message: string }
  | { phase: "success"; eventId: string; message: string }
  | {
      phase: "saved_refresh_failed";
      eventId: string;
      message: string;
      refreshError: string;
    }
  | { phase: "failed"; eventId: string; message: string };

export const idleResolutionState = (): ResolutionUiState => ({ phase: "idle" });

export const beginResolution = (eventId: string): ResolutionUiState => ({
  phase: "submitting",
  eventId,
});

export const resolutionSaved = (
  result: UnplannedResolutionResult,
): ResolutionUiState => ({
  phase: "saved_refreshing",
  eventId: result.event.id,
  message: unplannedSuccessMessage(result),
});

export const resolutionSucceeded = (
  result: UnplannedResolutionResult,
): ResolutionUiState => ({
  phase: "success",
  eventId: result.event.id,
  message: unplannedSuccessMessage(result),
});

export const resolutionRefreshFailed = (
  result: UnplannedResolutionResult,
  refreshError: string,
): ResolutionUiState => ({
  phase: "saved_refresh_failed",
  eventId: result.event.id,
  message: unplannedSuccessMessage(result),
  refreshError,
});

export const resolutionFailed = (
  eventId: string,
  message: string,
): ResolutionUiState => ({
  phase: "failed",
  eventId,
  message,
});

export function isResolutionBusy(
  state: ResolutionUiState,
  eventId?: string,
): boolean {
  const busy =
    state.phase === "submitting" || state.phase === "saved_refreshing";
  return busy && (!eventId || state.eventId === eventId);
}

export function canSubmitResolution(
  state: ResolutionUiState,
  eventId: string,
): boolean {
  if (state.phase === "submitting" || state.phase === "saved_refreshing") {
    return false;
  }
  if (
    state.phase === "success" ||
    state.phase === "saved_refresh_failed"
  ) {
    return state.eventId !== eventId;
  }
  return true;
}

export function removeResolvedSuggestion(
  items: ReconciliationSuggestion[],
  eventId: string,
): ReconciliationSuggestion[] {
  return items.filter((item) => item.event.id !== eventId);
}

function displayAmount(value: string): string {
  const [integer, decimal = ""] = value.split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const meaningfulDecimal = decimal.replace(/0+$/, "");
  return meaningfulDecimal ? `${grouped}.${meaningfulDecimal}` : grouped;
}

function currencyPrefix(currency: string): string {
  if (currency === "INR") return "₹";
  if (currency === "USD") return "$";
  if (currency === "GBP") return "£";
  if (currency === "EUR") return "€";
  return `${currency} `;
}

export function unplannedSuccessMessage(
  result: UnplannedResolutionResult,
): string {
  return `${currencyPrefix(result.event.currency)}${displayAmount(
    result.event.amount,
  )} recorded as an unplanned expense.`;
}

export function reconciliationEmptyCopy(
  hasSavedResolution: boolean,
): { title: string; body: string } {
  return hasSavedResolution
    ? {
        title: "All caught up",
        body: "That expense is resolved and no other confirmed events need your attention.",
      }
    : {
        title: "Nothing to reconcile",
        body: "No confirmed expenses are waiting for a decision.",
      };
}

export function usefulError(error: unknown, fallback: string): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string" &&
    error.message.trim()
  ) {
    return error.message;
  }
  return fallback;
}

export const financeReturnRoute = "/(tabs)/finance" as const;
