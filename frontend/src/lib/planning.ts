export type PlanningTargetType = "goal" | "project" | "journey";
export type PlanningStage = "review" | "questions" | "proposal" | "applied";
export type ContextItemStatus = "known" | "missing" | "user_edited";
export type ContextEditor = "text" | "date" | "money" | "account_select";
export type PlanningContextDecisionAction =
  | "looks_right"
  | "change"
  | "dont_know"
  | "not_right";
export type ContextSectionKey =
  | "what_you_want"
  | "where_things_stand"
  | "what_may_affect_this"
  | "what_hymn_still_needs";
export type DraftItemKind = "milestone" | "outcome" | "task";
export type DraftItemStatus = "active" | "deferred";

export type PlanningNextAction = {
  action: string;
  label: string;
  method: string;
  endpoint: string | null;
};

export type PlanningWhy = {
  summary: string;
  evidence: string[];
};

export type PlanningContextItem = {
  key: string;
  label: string;
  value: string | null;
  status: ContextItemStatus;
  editable: boolean;
  editor: ContextEditor;
  why: PlanningWhy;
};

export type PlanningContextSection = {
  key: ContextSectionKey;
  title: string;
  items: PlanningContextItem[];
};

export type PlanningQuestionOption = {
  value: string;
  label: string;
};

export type PlanningQuestion = {
  id: string;
  field: string;
  prompt: string;
  help_text: string;
  input_type: "text" | "date" | "money" | "select";
  required: boolean;
  options: PlanningQuestionOption[];
};

export type FeasibilityCalculation = {
  label: string;
  value: string;
  explanation: string;
};

export type PlanningFeasibility = {
  status:
    | "appears_feasible"
    | "may_be_difficult"
    | "insufficient_information";
  summary: string;
  appears_feasible: string[];
  difficulties: string[];
  calculations: FeasibilityCalculation[];
  unknowns: string[];
};

export type PlanningContextReview = {
  title: string;
  intro: string;
  sections: PlanningContextSection[];
  questions: PlanningQuestion[];
  feasibility: PlanningFeasibility;
};

export type PlanningDraftItem = {
  id: string;
  kind: DraftItemKind;
  title: string;
  notes: string;
  status: DraftItemStatus;
  position: number;
  parent_id?: string | null;
};

export type PlanningDraftPlan = {
  version: number;
  items: PlanningDraftItem[];
  can_apply: boolean;
};

export type PlanningReturnTo = {
  route: string;
  target_type: PlanningTargetType;
  target_id: string;
  label: string;
};

export type PlanningAppliedPlan = {
  draft_version: number;
  items: PlanningDraftItem[];
  created_outcome_ids: string[];
  created_task_ids: string[];
  applied_at: string;
};

export type PlanningAttachedPlan = {
  proposal_id: string;
  version: number;
  items: PlanningDraftItem[];
  applied_at: string;
};

export type PlanningContextResponse = {
  id: string;
  target_type: PlanningTargetType;
  target_id: string;
  stage: PlanningStage;
  next_action: PlanningNextAction;
  context_review: PlanningContextReview;
  draft_plan: PlanningDraftPlan;
  return_to: PlanningReturnTo;
  applied_plan: PlanningAppliedPlan | null;
};

export type PlanningContextUpdates = {
  objective?: string | null;
  success_criteria?: string | null;
  target_date?: string | null;
  current_balance?: string | null;
  current_balance_currency?: string | null;
  current_balance_account_id?: string | null;
  dependencies?: string | null;
  constraints?: string | null;
  plan_structure?: string | null;
};

export type PlanningApplyResult = {
  status: "applied";
  already_applied: boolean;
  proposal_id: string;
  created_outcome_ids: string[];
  created_task_ids: string[];
  return_to: PlanningReturnTo;
  attached_plan: PlanningAttachedPlan;
};

export type AttachedPlanResponse =
  | {
      attached: false;
      message: string;
      return_to: PlanningReturnTo;
    }
  | ({
      attached: true;
      return_to: PlanningReturnTo;
    } & PlanningAttachedPlan);

const SECTION_ORDER: ContextSectionKey[] = [
  "what_you_want",
  "where_things_stand",
  "what_may_affect_this",
  "what_hymn_still_needs",
];

const SECTION_TITLES: Record<ContextSectionKey, string> = {
  what_you_want: "What you want",
  where_things_stand: "Where things stand",
  what_may_affect_this: "What may affect this",
  what_hymn_still_needs: "What Hymn still needs",
};

export function isPlanningTargetType(value: string | undefined): value is PlanningTargetType {
  return value === "goal" || value === "project" || value === "journey";
}

export function orderedContextSections(
  sections: PlanningContextSection[],
): PlanningContextSection[] {
  const byKey = new Map(sections.map((section) => [section.key, section]));
  return SECTION_ORDER.map(
    (key) =>
      byKey.get(key) ?? {
        key,
        title: SECTION_TITLES[key],
        items: [],
      },
  );
}

export function contextUpdateFor(
  key: string,
  value: string | null,
): PlanningContextUpdates | null {
  switch (key) {
    case "objective":
      return { objective: value };
    case "success_criteria":
      return { success_criteria: value };
    case "target_date":
      return { target_date: value };
    case "current_balance":
      return { current_balance: value };
    case "current_balance_currency":
      return { current_balance_currency: value };
    case "current_balance_account_id":
      return { current_balance_account_id: value };
    case "dependencies":
      return { dependencies: value };
    case "constraints":
      return { constraints: value };
    case "plan_structure":
      return { plan_structure: value };
    default:
      return null;
  }
}

export function createDraftItem(
  kind: DraftItemKind,
  id: string,
  position: number,
): PlanningDraftItem {
  return {
    id,
    kind,
    title: "",
    notes: "",
    status: "active",
    position,
  };
}

export function replaceDraftItem(
  items: PlanningDraftItem[],
  nextItem: PlanningDraftItem,
): PlanningDraftItem[] {
  return items
    .map((item) => (item.id === nextItem.id ? nextItem : item))
    .map((item, position) => ({ ...item, position }));
}

export function removeDraftItem(
  items: PlanningDraftItem[],
  itemId: string,
): PlanningDraftItem[] {
  return items
    .filter((item) => item.id !== itemId)
    .map((item, position) => ({ ...item, position }));
}

export function moveDraftItem(
  items: PlanningDraftItem[],
  itemId: string,
  direction: "up" | "down",
): PlanningDraftItem[] {
  const index = items.findIndex((item) => item.id === itemId);
  const destination = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || destination < 0 || destination >= items.length) {
    return items;
  }
  const next = [...items];
  [next[index], next[destination]] = [next[destination], next[index]];
  return next.map((item, position) => ({ ...item, position }));
}

export function toggleDraftItemDeferred(
  items: PlanningDraftItem[],
  itemId: string,
): PlanningDraftItem[] {
  return items.map((item) =>
    item.id === itemId
      ? {
          ...item,
          status: item.status === "active" ? "deferred" : "active",
        }
      : item,
  );
}

export function validateDraftItems(items: PlanningDraftItem[]): string | null {
  if (items.some((item) => item.title.trim().length === 0)) {
    return "Give every plan item a clear title before saving.";
  }
  return null;
}

export function planningEmptyState(stage: PlanningStage): string {
  if (stage === "applied") {
    return "This plan has been added to the original goal or project.";
  }
  if (stage === "questions") {
    return "Answer the questions above so Hymn can prepare a useful draft.";
  }
  if (stage === "proposal") {
    return "No draft items are available yet. Try preparing the draft again.";
  }
  return "Review what Hymn understands, then prepare a draft plan.";
}

export function errorMessage(error: unknown, fallback: string): string {
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

export function mainSurfaceText(response: PlanningContextResponse): string {
  const sections = orderedContextSections(response.context_review.sections);
  return [
    "Does Hymn understand your situation?",
    response.context_review.title,
    response.context_review.intro,
    ...sections.flatMap((section) => [
      section.title,
      ...section.items.flatMap((item) => [item.label, item.value ?? "Not known yet"]),
    ]),
    response.context_review.feasibility.summary,
    ...response.context_review.questions.flatMap((question) => [
      question.prompt,
      question.help_text,
    ]),
    ...response.draft_plan.items.flatMap((item) => [item.title, item.notes]),
  ].join(" ");
}

export function nextActionSummary(response: PlanningContextResponse): string {
  if (response.stage === "applied") {
    return `Your plan is attached. ${response.return_to.label}`;
  }
  if (response.context_review.questions.length > 0) {
    return "Answer the questions below to continue.";
  }
  return response.next_action.label;
}

export function canonicalTargetPath(returnTo: PlanningReturnTo): string {
  const id = encodeURIComponent(returnTo.target_id);
  if (returnTo.target_type === "goal") return `/goals/${id}`;
  if (returnTo.target_type === "project") return `/projects/${id}`;
  return `/knowledge/${id}`;
}
