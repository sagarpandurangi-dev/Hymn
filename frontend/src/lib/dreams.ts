export type DreamSourceType = "intent" | "learning" | "goal" | "project" | "journey";
export type JourneyShape =
  | "professional_qualification"
  | "learn_skill"
  | "complete_course"
  | "learn_subject"
  | "read_book"
  | "purchase"
  | "trip"
  | "meeting_event"
  | "financial_target"
  | "health_wellbeing"
  | "custom";
export type PlanningDepth = "light" | "moderate" | "major" | "transformational";
export type DreamNodeKind = "phase" | "milestone" | "task" | "checkin_requirement";
export type DreamNodeOrigin = "hymn" | "user";
export type DreamDecisionState =
  | "proposed"
  | "accepted"
  | "modified"
  | "rejected"
  | "deferred";
export type CheckinScheduleType =
  | "one_time"
  | "recurring"
  | "milestone_triggered"
  | "manual";
export type ResearchState =
  | "research_not_needed"
  | "research_recommended"
  | "research_in_progress"
  | "research_ready"
  | "research_stale"
  | "research_failed"
  | "manual_input_required";

export type JourneyShapeOption = {
  id: JourneyShape;
  label: string;
  description: string;
  match_score: number;
};

export type JourneyShapeResponse = {
  shapes: JourneyShapeOption[];
  reduced_motion_contract: {
    effect: "materialize_text";
    duration_ms: number;
    reduced_motion_duration_ms: number;
    interaction_delay_ms: number;
  };
};

export type DreamFact = {
  key: string;
  value: unknown;
  value_type: "text" | "money" | "date" | "person" | "choice" | "list";
  origin: "inferred" | "user_provided" | "user_corrected";
  uncertainty?: string | null;
};

export type DreamClarificationQuestion = {
  id: string;
  kind: "money" | "date" | "text";
  prompt: string;
  why: string;
  fact_keys: string[];
  status: "missing" | "answered" | "unknown";
  value: unknown;
};

export type DreamCandidate = {
  journey_shape: JourneyShape;
  label: string;
  reason: string;
  confidence: "clear" | "likely" | "ambiguous";
};

export type RequiredCheckinDefinition = {
  schedule_type: CheckinScheduleType;
  due_date?: string | null;
  cadence?: string | null;
  trigger_node_id?: string | null;
  question: string;
  evidence_type?: string;
};

export type DreamNode = {
  id: string;
  kind: DreamNodeKind;
  parent_id?: string | null;
  rank: number;
  display_number: string;
  title: string;
  description: string;
  origin: DreamNodeOrigin;
  decision_state: DreamDecisionState;
  timing?: { target_date?: string | null } | null;
  dependencies: string[];
  evidence_ids: string[];
  assumptions: string[];
  checkin?: RequiredCheckinDefinition | null;
  revision: number;
};

export type DreamScaleAxis = {
  id: string;
  level: PlanningDepth | null;
  summary: string;
};

export type DreamProposal = {
  id: string;
  schema_version: number;
  source: { type: DreamSourceType; id?: string | null; title: string };
  status: "review" | "applying" | "applied";
  revision: number;
  original_text: string;
  interpretation: {
    version: number;
    primary: DreamCandidate;
    alternatives: DreamCandidate[];
    facts: DreamFact[];
    uncertainties: string[];
    questions: DreamClarificationQuestion[];
    why: { summary: string; evidence: string[] };
  };
  context: {
    source?: { type: string; id: string; title?: string; deadline?: string } | null;
    finance: {
      requested_currency?: string | null;
      profile_currency?: string | null;
      recorded_currency?: string | null;
      compatible_liquid_accounts: {
        id: string;
        name: string;
        currency: string;
        recorded_value: string;
        updated_at?: string | null;
      }[];
      recorded_liquid_total?: string | null;
      recorded_liquid_account_count: number;
      unresolved_movements: Record<string, string>;
      balance_label: string;
      freshness_warning?: string | null;
    };
    commitments: {
      other_active_goals: { id: string; title?: string }[];
      other_active_projects: { id: string; title?: string }[];
      open_task_count: number;
      recorded_checkin_count: number;
    };
    domains_queried: string[];
    domains_with_data: string[];
    honesty: string;
    why: { evidence: string[] };
  };
  scale: {
    version: number;
    recommended_depth: PlanningDepth;
    user_selected_depth?: PlanningDepth | null;
    summary: string;
    axes: DreamScaleAxis[];
    calculations: { label: string; value: string; evidence_kind: string }[];
    missing: string[];
  };
  research: {
    state: ResearchState;
    message: string;
    questions: { id: string; question: string; why_needed: string }[];
    evidence: unknown[];
    provider_enabled: boolean;
  };
  map: {
    version: number;
    revision: number;
    nodes: DreamNode[];
    can_undo: boolean;
  };
  creation_preview: {
    summary: string;
    counts: Record<DreamNodeKind, number>;
    source_effect: string;
  };
  applied_plan?: {
    plan_map_id: string;
    proposal_revision: number;
    accepted_node_ids?: string[];
    created_counts?: {
      plan: number;
      phase: number;
      milestone: number;
      task: number;
      checkin_requirement: number;
    };
    return_to: DreamReturnTo;
    applied_at: string;
    already_applied?: boolean;
  } | null;
  return_to: DreamReturnTo;
  updated_at: string;
};

export type DreamReturnTo = {
  route: string;
  label: string;
  target_type: DreamSourceType;
  target_id: string;
};

export type ActiveDreamPlan =
  | { attached: false; message: string }
  | {
      attached: true;
      id: string;
      proposal_id: string;
      version: number;
      original_text: string;
      nodes: DreamNode[];
      updated_at: string;
    };

export type DreamAnalyzePayload = {
  source_type: DreamSourceType;
  source_id?: string;
  text?: string;
  selected_shape?: JourneyShape;
  reference_date: string;
  user_plan_nodes?: Omit<DreamNode, "display_number" | "revision">[];
};

export type DreamTreeOperation =
  | { type: "accept_all" }
  | {
      type: "add";
      node: Partial<DreamNode> & Pick<DreamNode, "kind" | "title">;
      parent_id?: string | null;
      relative_id?: string;
      placement?: "before" | "after" | "inside_end";
    }
  | { type: "update"; node_id: string; patch: Partial<DreamNode> }
  | { type: "decide"; node_id: string; decision_state: DreamDecisionState }
  | {
      type: "move";
      node_id: string;
      parent_id?: string | null;
      relative_id?: string;
      placement?: "before" | "after" | "inside_end";
    }
  | {
      type: "delete";
      node_id: string;
      delete_mode: "remove_subtree" | "reparent_children";
      destination_parent_id?: string | null;
    }
  | { type: "duplicate"; node_id: string; parent_id?: string | null }
  | { type: "undo" };

const parentKinds: Record<DreamNodeKind, (DreamNodeKind | null)[]> = {
  phase: [null],
  milestone: [null, "phase"],
  task: [null, "phase", "milestone"],
  checkin_requirement: ["task"],
};

export function canPlaceNode(
  kind: DreamNodeKind,
  parentKind: DreamNodeKind | null,
): boolean {
  return parentKinds[kind].includes(parentKind);
}

export function nodeDepth(node: DreamNode): number {
  return Math.max(0, node.display_number.split(".").length - 1);
}

export function visiblePlanNodes(nodes: DreamNode[]): DreamNode[] {
  return nodes.filter(
    (node) => node.decision_state !== "rejected",
  );
}

export function acceptedPlanNodes(nodes: DreamNode[]): DreamNode[] {
  return nodes.filter(
    (node) => node.decision_state === "accepted" || node.decision_state === "modified",
  );
}

export function suggestedAddKind(parent?: DreamNode): DreamNodeKind {
  if (!parent) return "phase";
  if (parent.kind === "phase") return "milestone";
  if (parent.kind === "milestone") return "task";
  return "checkin_requirement";
}

export function siblingMoveOperation(
  nodes: DreamNode[],
  nodeId: string,
  direction: "up" | "down",
): DreamTreeOperation | null {
  const node = nodes.find((row) => row.id === nodeId);
  if (!node) return null;
  const siblings = nodes
    .filter((row) => row.parent_id === node.parent_id)
    .sort((a, b) => a.rank - b.rank);
  const index = siblings.findIndex((row) => row.id === nodeId);
  const destination = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || destination < 0 || destination >= siblings.length) return null;
  const relative = siblings[destination];
  return {
    type: "move",
    node_id: nodeId,
    parent_id: node.parent_id,
    relative_id: relative.id,
    placement: direction === "up" ? "before" : "after",
  };
}

export function factDisplayValue(fact: DreamFact): string {
  if (fact.value === null || fact.value === undefined || fact.value === "") {
    return "Not known yet";
  }
  if (Array.isArray(fact.value)) return fact.value.join(", ");
  if (typeof fact.value === "object") return "Structured detail available";
  return String(fact.value);
}

export function sourceLabel(origin: DreamFact["origin"]): string {
  if (origin === "user_corrected") return "You corrected this";
  if (origin === "user_provided") return "From your words";
  return "Hymn inferred this";
}

export function factByKey(
  proposal: DreamProposal,
  key: string,
): DreamFact | undefined {
  return proposal.interpretation.facts.find((fact) => fact.key === key);
}

export function purchaseConversationSummary(proposal: DreamProposal): string {
  const object = factDisplayValue(
    factByKey(proposal, "desired_object") || {
      key: "desired_object",
      value: null,
      value_type: "text",
      origin: "inferred",
    },
  );
  if (
    proposal.interpretation.primary.journey_shape === "purchase"
    && object !== "Not known yet"
  ) {
    const cleaned = object.trim();
    const lower = cleaned.toLowerCase();
    const alreadyQualified = /^(a|an|the|some|my|our)\s/.test(lower);
    const objectPhrase = alreadyQualified
      ? cleaned
      : `${/^[aeiou]/i.test(cleaned) ? "an" : "a"} ${cleaned}`;
    return `You want to buy ${objectPhrase}. Let’s work out what that would take for you.`;
  }
  return `You want to make “${proposal.original_text}” possible. Let’s work out a useful path together.`;
}

export function journeyChipLabel(shape: JourneyShape): string {
  const labels: Record<JourneyShape, string> = {
    professional_qualification: "Professional qualification",
    learn_skill: "Learn a skill",
    complete_course: "Complete a course",
    learn_subject: "Learn a subject",
    read_book: "Read a book",
    purchase: "Purchase",
    trip: "Trip",
    meeting_event: "Meeting or event",
    financial_target: "Financial target",
    health_wellbeing: "Health or wellbeing",
    custom: "Custom journey",
  };
  return labels[shape];
}

export type DreamApplyReadiness = {
  ready: boolean;
  reason: string | null;
  acceptedNodeIds: string[];
};

export function dreamApplyReadiness(nodes: DreamNode[]): DreamApplyReadiness {
  const accepted = acceptedPlanNodes(nodes);
  if (!accepted.length) {
    return {
      ready: false,
      reason: "Accept at least one plan item before applying.",
      acceptedNodeIds: [],
    };
  }
  const acceptedIds = new Set(accepted.map((node) => node.id));
  const orphan = accepted.find(
    (node) => node.parent_id && !acceptedIds.has(node.parent_id),
  );
  if (orphan) {
    return {
      ready: false,
      reason: `Accept the parent of “${orphan.title}” before applying.`,
      acceptedNodeIds: accepted.map((node) => node.id),
    };
  }
  const incompleteCheckin = accepted.find(
    (node) =>
      node.kind === "checkin_requirement"
      && (!node.checkin?.question.trim() || !node.parent_id),
  );
  if (incompleteCheckin) {
    return {
      ready: false,
      reason: `Finish the required check-in “${incompleteCheckin.title}” before applying.`,
      acceptedNodeIds: accepted.map((node) => node.id),
    };
  }
  return {
    ready: true,
    reason: null,
    acceptedNodeIds: accepted.map((node) => node.id),
  };
}

export function dreamDecisionCounts(nodes: DreamNode[]): Record<DreamDecisionState | "user_added", number> {
  return {
    proposed: nodes.filter((node) => node.decision_state === "proposed").length,
    accepted: nodes.filter((node) => node.decision_state === "accepted").length,
    modified: nodes.filter((node) => node.decision_state === "modified").length,
    rejected: nodes.filter((node) => node.decision_state === "rejected").length,
    deferred: nodes.filter((node) => node.decision_state === "deferred").length,
    user_added: nodes.filter((node) => node.origin === "user").length,
  };
}

export function researchActionLabel(state: ResearchState): string {
  if (state === "research_recommended") return "Add requirements manually";
  if (state === "research_failed") return "Continue without research";
  if (state === "research_stale") return "Review source freshness";
  if (state === "manual_input_required") return "Add what you know";
  return "No research action needed";
}

export function mapMainSurfaceText(proposal: DreamProposal): string {
  return [
    proposal.original_text,
    purchaseConversationSummary(proposal),
    journeyChipLabel(proposal.interpretation.primary.journey_shape),
    ...proposal.interpretation.questions.flatMap((question) => [
      question.prompt,
      question.status === "unknown" ? "Not sure yet" : "",
    ]),
    proposal.scale.summary,
    ...proposal.scale.axes.map((axis) => axis.summary),
    proposal.research.message,
    ...proposal.map.nodes.flatMap((node) => [
      node.display_number,
      node.title,
      node.description,
    ]),
  ].join(" ");
}

export function canonicalDreamReturnPath(proposal: DreamProposal): string {
  return proposal.applied_plan?.return_to.route || proposal.return_to.route;
}

export function localReferenceDate(now = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
