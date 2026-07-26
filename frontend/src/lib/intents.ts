export type AffordabilityStatus =
  | "affordable"
  | "borderline"
  | "not_affordable"
  | "insufficient_data";

export type PurchaseInputs = {
  expected_price?: string;
  currency?: string;
  desired_date?: string;
  price_unknown?: boolean;
  timing_unknown?: boolean;
};

export type IntentAnalyzePayload = {
  text: string;
  purchase?: PurchaseInputs;
  reference_date?: string;
};

export type IntentFieldSource =
  | "inferred_from_text"
  | "user_edited"
  | "known_profile"
  | "marked_unknown"
  | "missing";

export type IntentEvidence = {
  id: string;
  kind: "known_fact" | "user_provided";
  label: string;
  value: string;
  source?: string;
};

export type IntentOption = {
  id: string;
  title: string;
  description: string;
  downstream_effect: "none" | "draft_financial_commitment";
};

export type FinancialSnapshot = {
  currency: string | null;
  purchase_month: string | null;
  liquid_assets: string | null;
  planned_income: string | null;
  planned_outflows: string | null;
  planned_savings_and_investments: string | null;
  actual_spending: string | null;
  reserved_commitments_due: string | null;
  available_before_purchase: string | null;
  projected_after_purchase: string | null;
  calculation: string | null;
  has_financial_data: boolean;
  has_liquid_balance: boolean;
};

export type IntentAnalysis = {
  schema_version: number;
  assessment_version: string;
  original_text: string;
  intent_type: "purchase" | "unsupported";
  classification: {
    intent_type: "purchase" | "unsupported";
    confidence: string;
    item: string | null;
    extracted_price: string | null;
    extracted_currency: string | null;
    extracted_date: string | null;
    extracted_timing_text?: string | null;
    timing_precision?: "exact_date" | "relative_date" | null;
    timing_resolution?: string | null;
    timing_ambiguity_reason?: string | null;
    ambiguities?: string[];
  };
  reference_date?: string;
  result_status: "unsupported" | "needs_input" | "review_ready";
  supported_intent_types: string[];
  message: string | null;
  purchase: {
    item: string | null;
    expected_price: string | null;
    currency: string | null;
    desired_date: string | null;
    timing_text?: string | null;
    timing_precision?: "exact_date" | "relative_date" | null;
    timing_resolution?: string | null;
    field_sources?: {
      item: IntentFieldSource;
      expected_price: IntentFieldSource;
      currency: IntentFieldSource;
      desired_date: IntentFieldSource;
    };
    price_unknown: boolean;
    timing_unknown: boolean;
    summary: string;
  } | null;
  missing_data: string[];
  clarification_questions: { field: string; question: string }[];
  affordability_status: AffordabilityStatus;
  financial_snapshot: FinancialSnapshot | null;
  impacted_goals_or_commitments: {
    type: "goal" | "project";
    id: string;
    title: string;
    reason: string;
    evidence_id: string;
  }[];
  risks_and_tradeoffs: string[];
  options: IntentOption[];
  recommended_option_id: string | null;
  recommended_next_action: string;
  evidence: IntentEvidence[];
  contexts_queried: string[];
  can_confirm: boolean;
  disclaimer?: string;
};

export type SavedIntent = {
  id: string;
  schema_version: number;
  assessment_version: string;
  intent_type: "purchase";
  status: "confirmed";
  original_text: string;
  purchase: NonNullable<IntentAnalysis["purchase"]>;
  assessment: IntentAnalysis;
  selected_option_id: string;
  downstream_records: {
    type: "financial_commitment";
    id: string;
    state: "draft";
  }[];
  created_at: string;
  updated_at: string;
};

export const affordabilityLabel = (status: AffordabilityStatus): string => {
  if (status === "affordable") return "Affordable";
  if (status === "borderline") return "Borderline";
  if (status === "not_affordable") return "Not affordable";
  return "Insufficient data";
};

export const affordabilityTone = (
  status: AffordabilityStatus,
): "success" | "warning" | "error" | "neutral" => {
  if (status === "affordable") return "success";
  if (status === "borderline") return "warning";
  if (status === "not_affordable") return "error";
  return "neutral";
};

export const intentConfirmationKey = (): string =>
  `intent-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;

export const missingDataLabel = (field: string): string => {
  const labels: Record<string, string> = {
    item: "What you want to buy",
    expected_price: "Expected price",
    desired_date: "Desired purchase timing",
    currency: "Purchase currency",
    financial_context: "Recorded financial context",
  };
  return labels[field] || field.replaceAll("_", " ");
};

export const intentFieldSourceLabel = (source: IntentFieldSource): string => {
  if (source === "inferred_from_text") return "Inferred from your sentence";
  if (source === "user_edited") return "Edited by you";
  if (source === "known_profile") return "From your Hymn profile";
  if (source === "marked_unknown") return "Marked as unknown";
  return "Still needed";
};

export const formatIntentAmount = (
  amount: string | null,
  currency: string | null,
): string => {
  if (!amount) return "Not provided";
  const numeric = Number(amount);
  const formatted = Number.isFinite(numeric)
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(numeric)
    : amount;
  return `${currency || ""} ${formatted}`.trim();
};

export type IntentUnderstandingFact = {
  key: "intent" | "item" | "amount" | "timing";
  label: string;
  value: string;
  source: string;
  missing: boolean;
};

export type PurchaseUnderstanding = {
  facts: IntentUnderstandingFact[];
  missingEssentials: string[];
  timingResolution: string | null;
};

export const buildPurchaseUnderstanding = (
  analysis: IntentAnalysis,
): PurchaseUnderstanding | null => {
  const purchase = analysis.purchase;
  if (analysis.intent_type !== "purchase" || !purchase) return null;

  const missingEssentials = analysis.missing_data.filter((field) =>
    ["item", "expected_price", "currency", "desired_date"].includes(field),
  );
  const timingValue = purchase.desired_date
    ? purchase.timing_text
      ? `${purchase.timing_text} → ${purchase.desired_date}`
      : purchase.desired_date
    : "Not provided";

  return {
    facts: [
      {
        key: "intent",
        label: "Intent",
        value: "Purchase",
        source: "Detected locally",
        missing: false,
      },
      {
        key: "item",
        label: "Item",
        value: purchase.item || "Not provided",
        source: intentFieldSourceLabel(purchase.field_sources?.item || "missing"),
        missing: !purchase.item,
      },
      {
        key: "amount",
        label: "Amount",
        value: formatIntentAmount(purchase.expected_price, purchase.currency),
        source: intentFieldSourceLabel(
          purchase.field_sources?.expected_price || "missing",
        ),
        missing: !purchase.expected_price,
      },
      {
        key: "timing",
        label: "Timing",
        value: timingValue,
        source: intentFieldSourceLabel(
          purchase.field_sources?.desired_date || "missing",
        ),
        missing: !purchase.desired_date,
      },
    ],
    missingEssentials,
    timingResolution: purchase.timing_resolution || null,
  };
};
