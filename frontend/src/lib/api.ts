import { getToken } from "./tokenStorage";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL as string;

export type ApiError = { status: number; message: string };

function _stringifyDetail(d: any): string {
  if (!d) return "Request failed";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((e: any) => (e && typeof e === "object" ? e.msg || JSON.stringify(e) : String(e))).join("; ");
  }
  if (typeof d === "object") return d.msg || JSON.stringify(d);
  return String(d);
}

async function request<T>(
  path: string,
  options: { method?: string; body?: any; auth?: boolean } = {},
): Promise<T> {
  const { method = "GET", body, auth = false } = options;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const token = await getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE_URL}/api${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" ? data.detail ?? data.message : data;
    const message = _stringifyDetail(detail);
    throw { status: res.status, message } as ApiError;
  }
  return data as T;
}

export const api = {
  signup: (payload: {
    email: string;
    password: string;
    security_question: string;
    security_answer: string;
  }) => request<{ access_token: string; user: { id: string; email: string } }>("/auth/signup", { method: "POST", body: payload }),

  login: (payload: { email: string; password: string }) =>
    request<{ access_token: string; user: { id: string; email: string } }>("/auth/login", { method: "POST", body: payload }),

  me: () => request<{ id: string; email: string }>("/auth/me", { auth: true }),

  logout: () => request<{ detail: string }>("/auth/logout", { method: "POST", auth: true }),

  googleSession: (session_token: string) =>
    request<{ access_token: string; user: { id: string; email: string } }>("/auth/google-session", {
      method: "POST",
      body: { session_token },
    }),

  getSecurityQuestion: (email: string) =>
    request<{ security_question: string }>("/auth/security-question", { method: "POST", body: { email } }),

  forgotPassword: (payload: { email: string; security_answer: string; new_password: string }) =>
    request<{ detail: string }>("/auth/forgot-password", { method: "POST", body: payload }),

  listDomains: () =>
    request<{ id: string; name: string; is_default: boolean; created_at: string }[]>("/domains", { auth: true }),
  createDomain: (name: string) =>
    request<{ id: string; name: string; is_default: boolean }>("/domains", { method: "POST", body: { name }, auth: true }),
  updateDomain: (id: string, name: string) =>
    request<{ id: string; name: string }>(`/domains/${id}`, { method: "PUT", body: { name }, auth: true }),
  deleteDomain: (id: string) =>
    request<{ detail: string }>(`/domains/${id}`, { method: "DELETE", auth: true }),

  listGoals: () =>
    request<
      { id: string; title: string; domain_id: string; domain_name: string; target_outcome: string; deadline: string; status: string; notes: string; checkin_cadence: string; created_at: string; updated_at: string }[]
    >("/goals", { auth: true }),
  createGoal: (payload: { title: string; domain_id: string; target_outcome: string; deadline: string; status: string; notes: string; checkin_cadence?: string }) =>
    request<{ id: string }>("/goals", { method: "POST", body: payload, auth: true }),
  getGoal: (id: string) =>
    request<{ id: string; title: string; domain_id: string; domain_name: string; target_outcome: string; deadline: string; status: string; notes: string; checkin_cadence: string; created_at: string; updated_at: string; expected_outcomes_total: number; expected_outcomes_completed: number; completion_pct: number }>(
      `/goals/${id}`,
      { auth: true },
    ),
  updateGoal: (id: string, payload: { title?: string; domain_id?: string; target_outcome?: string; deadline?: string; status?: string; notes?: string; checkin_cadence?: string }) =>
    request<{ id: string }>(`/goals/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteGoal: (id: string) =>
    request<{ detail: string }>(`/goals/${id}`, { method: "DELETE", auth: true }),

  listExpectedOutcomes: (goalId: string) =>
    request<
      { id: string; goal_id: string; title: string; target_value: string; current_value: string; unit: string; deadline: string; status: string; notes: string }[]
    >(`/goals/${goalId}/expected-outcomes`, { auth: true }),
  createExpectedOutcome: (payload: { goal_id: string; title: string; target_value?: string; current_value?: string; unit?: string; deadline?: string; status?: string; notes?: string }) =>
    request<{ id: string }>("/expected-outcomes", { method: "POST", body: payload, auth: true }),
  getExpectedOutcome: (id: string) =>
    request<{ id: string; goal_id: string; title: string; target_value: string; current_value: string; unit: string; deadline: string; status: string; notes: string }>(
      `/expected-outcomes/${id}`,
      { auth: true },
    ),
  updateExpectedOutcome: (id: string, payload: { title?: string; target_value?: string; current_value?: string; unit?: string; deadline?: string; status?: string; notes?: string }) =>
    request<{ id: string }>(`/expected-outcomes/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteExpectedOutcome: (id: string) =>
    request<{ detail: string }>(`/expected-outcomes/${id}`, { method: "DELETE", auth: true }),

  listProjects: () =>
    request<
      { id: string; title: string; description: string; status: string; start_date: string; target_end_date: string; notes: string }[]
    >("/projects", { auth: true }),
  createProject: (payload: { title: string; description?: string; status?: string; start_date?: string; target_end_date?: string; notes?: string }) =>
    request<{ id: string }>("/projects", { method: "POST", body: payload, auth: true }),
  getProject: (id: string) =>
    request<{ id: string; title: string; description: string; status: string; start_date: string; target_end_date: string; notes: string }>(
      `/projects/${id}`,
      { auth: true },
    ),
  updateProject: (id: string, payload: { title?: string; description?: string; status?: string; start_date?: string; target_end_date?: string; notes?: string }) =>
    request<{ id: string }>(`/projects/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteProject: (id: string) =>
    request<{ detail: string }>(`/projects/${id}`, { method: "DELETE", auth: true }),

  listTasks: (params?: { goalId?: string; includeCompleted?: boolean }) => {
    const parts: string[] = [];
    if (params?.goalId) parts.push(`goal_id=${encodeURIComponent(params.goalId)}`);
    if (params?.includeCompleted === false) parts.push("include_completed=false");
    const qs = parts.length ? `?${parts.join("&")}` : "";
    return request<
      { id: string; title: string; due_date: string; priority: string; status: string; notes: string; origin: string; expected_outcome_id: string | null; project_id: string | null; deferred_until: string | null; original_due_date: string | null; defer_count: number }[]
    >(`/tasks${qs}`, { auth: true });
  },
  createTask: (payload: { title: string; due_date?: string; priority?: string; status?: string; notes?: string; origin: string; expected_outcome_id?: string | null; project_id?: string | null }) =>
    request<{ id: string }>("/tasks", { method: "POST", body: payload, auth: true }),
  getTask: (id: string) =>
    request<{ id: string; title: string; due_date: string; priority: string; status: string; notes: string; origin: string; expected_outcome_id: string | null; project_id: string | null; deferred_until: string | null; original_due_date: string | null; defer_count: number }>(
      `/tasks/${id}`,
      { auth: true },
    ),
  updateTask: (id: string, payload: { title?: string; due_date?: string; priority?: string; status?: string; notes?: string }) =>
    request<{ id: string }>(`/tasks/${id}`, { method: "PUT", body: payload, auth: true }),
  deferTask: (id: string, deferred_until: string) =>
    request<{ id: string; deferred_until: string | null; defer_count: number }>(
      `/tasks/${id}/defer`, { method: "POST", body: { deferred_until }, auth: true },
    ),
  deleteTask: (id: string) =>
    request<{ detail: string }>(`/tasks/${id}`, { method: "DELETE", auth: true }),

  listCheckins: (params?: { goalId?: string; q?: string }) => {
    const bits: string[] = [];
    if (params?.goalId) bits.push(`goal_id=${encodeURIComponent(params.goalId)}`);
    if (params?.q && params.q.trim()) bits.push(`q=${encodeURIComponent(params.q.trim())}`);
    const qs = bits.length ? `?${bits.join("&")}` : "";
    return request<
      { id: string; type: string; title: string; date: string; time: string; notes: string; attachment: string; expected_outcome_id: string | null; goal_id: string | null; project_id: string | null; task_id: string | null; follow_up_task_id: string | null; money_spent: string | null; money_currency: string | null }[]
    >(`/checkins${qs}`, { auth: true });
  },
  getSpending: (date: string) =>
    request<{
      date: string;
      groups: { currency: string; total: string; entries: { id: string; title: string; time: string; amount: string; notes: string; goal_id: string | null; task_id: string | null; expected_outcome_id: string | null }[] }[];
    }>(`/spending?date=${encodeURIComponent(date)}`, { auth: true }),
  listRequiredCheckins: (date: string) =>
    request<
      { goal_id: string; goal_title: string; domain_name: string; checkin_cadence: string; completed_for_period: boolean }[]
    >(`/checkins/required?date=${encodeURIComponent(date)}`, { auth: true }),

  // ---------- Portfolio: setup status ----------
  getPortfolioSetupStatus: () =>
    request<{
      completed: boolean;
      completed_at: string | null;
      reporting_currency: string | null;
      has_time_commitments: boolean;
      has_financial_accounts: boolean;
      has_monthly_money_commitments: boolean;
    }>("/portfolio/setup-status", { auth: true }),
  updatePortfolioSetupStatus: (payload: { reporting_currency?: string | null; completed?: boolean }) =>
    request<{
      completed: boolean;
      completed_at: string | null;
      reporting_currency: string | null;
      has_time_commitments: boolean;
      has_financial_accounts: boolean;
      has_monthly_money_commitments: boolean;
    }>("/portfolio/setup-status", { method: "PUT", body: payload, auth: true }),

  // ---------- Portfolio: time_commitments ----------
  listTimeCommitments: () =>
    request<
      { id: string; user_id: string; title: string; day_of_week: string; start_time: string; end_time: string; commitment_type: string; flexibility: string; effective_from: string; effective_until: string | null; source_type: string; source_id: string | null; notes: string; created_at: string; updated_at: string }[]
    >("/portfolio/time-commitments", { auth: true }),
  createTimeCommitment: (payload: { title: string; day_of_week: string; start_time: string; end_time: string; commitment_type: string; flexibility: string; effective_from: string; effective_until?: string | null; source_type?: string; source_id?: string | null; notes?: string }) =>
    request<{ id: string }>("/portfolio/time-commitments", { method: "POST", body: payload, auth: true }),
  updateTimeCommitment: (id: string, payload: Partial<{ title: string; day_of_week: string; start_time: string; end_time: string; commitment_type: string; flexibility: string; effective_from: string; effective_until: string | null; notes: string }>) =>
    request<{ id: string }>(`/portfolio/time-commitments/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteTimeCommitment: (id: string) =>
    request<{ detail: string }>(`/portfolio/time-commitments/${id}`, { method: "DELETE", auth: true }),

  // ---------- Portfolio: financial_accounts ----------
  listFinancialAccounts: () =>
    request<
      { id: string; user_id: string; account_type: string; name: string; currency: string; current_value: string; liquidity_type: string; fixed_or_flexible: string; notes: string; created_at: string; updated_at: string }[]
    >("/portfolio/financial-accounts", { auth: true }),
  createFinancialAccount: (payload: { account_type: string; name: string; currency: string; current_value: string | number; liquidity_type: string; fixed_or_flexible: string; notes?: string }) =>
    request<{ id: string }>("/portfolio/financial-accounts", { method: "POST", body: payload, auth: true }),
  updateFinancialAccount: (id: string, payload: Partial<{ account_type: string; name: string; currency: string; current_value: string | number; liquidity_type: string; fixed_or_flexible: string; notes: string }>) =>
    request<{ id: string }>(`/portfolio/financial-accounts/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteFinancialAccount: (id: string) =>
    request<{ detail: string }>(`/portfolio/financial-accounts/${id}`, { method: "DELETE", auth: true }),

  // ---------- Portfolio: monthly_money_commitments ----------
  listMonthlyMoneyCommitments: () =>
    request<
      { id: string; user_id: string; title: string; currency: string; amount: string; commitment_type: string; fixed_or_flexible: string; start_month: string; end_month: string | null; source_type: string; source_id: string | null; notes: string; created_at: string; updated_at: string }[]
    >("/portfolio/monthly-money-commitments", { auth: true }),
  createMonthlyMoneyCommitment: (payload: { title: string; currency: string; amount: string | number; commitment_type: string; fixed_or_flexible: string; start_month: string; end_month?: string | null; source_type?: string; source_id?: string | null; notes?: string }) =>
    request<{ id: string }>("/portfolio/monthly-money-commitments", { method: "POST", body: payload, auth: true }),
  updateMonthlyMoneyCommitment: (id: string, payload: Partial<{ title: string; currency: string; amount: string | number; commitment_type: string; fixed_or_flexible: string; start_month: string; end_month: string | null; notes: string }>) =>
    request<{ id: string }>(`/portfolio/monthly-money-commitments/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteMonthlyMoneyCommitment: (id: string) =>
    request<{ detail: string }>(`/portfolio/monthly-money-commitments/${id}`, { method: "DELETE", auth: true }),

  // ---------- Portfolio: derived ----------
  getWeeklyTimeCapacity: (weekStartDate: string) =>
    request<{
      week_start_date: string;
      days: { date: string; day_of_week: string; total_minutes: number; committed_minutes: number; available_minutes: number; overlapping_minutes: number; commitments: { id: string; title: string; start_time: string; end_time: string; commitment_type: string; flexibility: string }[] }[];
    }>(`/portfolio/time-capacity/week?week_start_date=${encodeURIComponent(weekStartDate)}`, { auth: true }),
  getMonthlyMoneyPosition: (month: string, currency: string) =>
    request<{
      month: string; currency: string;
      opening_liquid_assets: string; planned_income: string;
      fixed_outflows: string; flexible_outflows: string;
      planned_savings: string; planned_investments: string;
      actual_spending: string;
      available_for_flexible_spending: string;
    }>(`/portfolio/money-position?month=${encodeURIComponent(month)}&currency=${encodeURIComponent(currency)}`, { auth: true }),
  createCheckin: (payload: any) =>
    request<{ id: string }>("/checkins", { method: "POST", body: payload, auth: true }),
  getCheckin: (id: string) =>
    request<any>(`/checkins/${id}`, { auth: true }),
  updateCheckin: (id: string, payload: { title?: string; date?: string; time?: string; notes?: string; attachment?: string }) =>
    request<{ id: string }>(`/checkins/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteCheckin: (id: string) =>
    request<{ detail: string }>(`/checkins/${id}`, { method: "DELETE", auth: true }),

  getOutcomeTypes: () =>
    request<{ types: Record<string, { label: string; description: string; checkin_fields: { key: string; label: string; type: string; required?: boolean; options?: string[] }[]; units: string[]; progress: string }> }>(
      "/outcome-types",
      { auth: true },
    ),

  listLearningJourneys: () =>
    request<
      { id: string; goal_id: string; journey_type: string; has_stages: boolean; title: string; notes: string; deadline: string; status: string; checkin_cadence: string; domain_id: string; domain_name: string; expected_outcomes_total: number; expected_outcomes_completed: number; completion_pct: number; created_at: string; updated_at: string }[]
    >("/knowledge/journeys", { auth: true }),

  getLearningJourney: (id: string) =>
    request<
      { id: string; goal_id: string; journey_type: string; has_stages: boolean; title: string; notes: string; deadline: string; status: string; checkin_cadence: string; domain_id: string; domain_name: string; expected_outcomes_total: number; expected_outcomes_completed: number; completion_pct: number; created_at: string; updated_at: string }
    >(`/knowledge/journeys/${id}`, { auth: true }),

  updateLearningJourney: (id: string, payload: { journey_type?: string; has_stages?: boolean }) =>
    request<any>(`/knowledge/journeys/${id}`, { method: "PUT", body: payload, auth: true }),

  deleteLearningJourney: (id: string) =>
    request<{ detail: string }>(`/knowledge/journeys/${id}`, { method: "DELETE", auth: true }),

  createLearningJourney: (payload: {
    journey_type: "professional_qualification" | "skill" | "course" | "subject" | "book" | "custom";
    title: string;
    has_stages: boolean;
    stages: { name: string }[];
    why: string;
    target_completion_date: string;
    first_outcome: { title: string; target_value?: string; unit?: string; outcome_type?: string };
    first_task: { title: string; due_date?: string; priority?: string };
    checkin_cadence: "daily" | "weekly" | "monthly" | "manual";
  }) =>
    request<{ id: string; goal_id: string; journey_type: string; has_stages: boolean; title: string; deadline: string; status: string; checkin_cadence: string }>(
      "/knowledge/journeys",
      { method: "POST", body: payload, auth: true },
    ),

  // ---------- Stages ----------
  listStages: (journeyId: string) =>
    request<{ id: string; journey_id: string; name: string; sequence: number }[]>(
      `/knowledge/journeys/${journeyId}/stages`,
      { auth: true },
    ),
  createStage: (payload: { journey_id: string; name: string }) =>
    request<{ id: string; journey_id: string; name: string; sequence: number }>(
      "/knowledge/stages",
      { method: "POST", body: payload, auth: true },
    ),
  updateStage: (id: string, payload: { name?: string }) =>
    request<any>(`/knowledge/stages/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteStage: (id: string) =>
    request<{ detail: string }>(`/knowledge/stages/${id}`, { method: "DELETE", auth: true }),
  moveStage: (id: string, direction: "up" | "down") =>
    request<{ detail: string }>(`/knowledge/stages/${id}/move?direction=${direction}`, { method: "POST", auth: true }),

  // ---------- Components ----------
  listComponents: (journeyId: string) =>
    request<
      { id: string; journey_id: string; stage_id: string | null; parent_component_id: string | null; name: string; type: string; sequence: number; status: string; progress: number; notes: string }[]
    >(`/knowledge/journeys/${journeyId}/components`, { auth: true }),
  createComponent: (payload: { journey_id: string; stage_id?: string | null; parent_component_id?: string | null; name: string; type?: string; status?: string; progress?: number; notes?: string }) =>
    request<{ id: string; journey_id: string; stage_id: string | null; parent_component_id: string | null; name: string; type: string; sequence: number; status: string; progress: number; notes: string }>(
      "/knowledge/components",
      { method: "POST", body: payload, auth: true },
    ),
  updateComponent: (id: string, payload: { name?: string; type?: string; status?: string; progress?: number; notes?: string }) =>
    request<any>(`/knowledge/components/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteComponent: (id: string) =>
    request<{ detail: string }>(`/knowledge/components/${id}`, { method: "DELETE", auth: true }),
  moveComponent: (id: string, direction: "up" | "down") =>
    request<{ detail: string }>(`/knowledge/components/${id}/move?direction=${direction}`, { method: "POST", auth: true }),

  // ============================================================================
  // FINANCE ENGINE
  // ============================================================================
  getFinanceDashboard: () => request<any>("/finance/dashboard", { auth: true }),
  getFinancePosition: () => request<any>("/finance/position", { auth: true }),
  getFinanceMonthly: (month: string, currency: string) =>
    request<any>(`/finance/monthly?month=${encodeURIComponent(month)}&currency=${encodeURIComponent(currency)}`, { auth: true }),
  getFinanceReserved: () => request<any>("/finance/reserved", { auth: true }),
  getFinanceAvailableLiquidity: () => request<any>("/finance/available-liquidity", { auth: true }),
  getFinanceForecast: () => request<any>("/finance/forecast", { auth: true }),
  runFinanceScenario: (payload: { currency: string; additional_monthly_expense?: string | number; additional_monthly_income?: string | number; additional_reservation?: string | number; reservation_due_month?: string }) =>
    request<any>("/finance/scenarios", { method: "POST", body: payload, auth: true }),

  listFinancialCommitments: (params?: { state?: string; currency?: string; include_terminal?: boolean }) => {
    const parts: string[] = [];
    if (params?.state) parts.push(`state=${encodeURIComponent(params.state)}`);
    if (params?.currency) parts.push(`currency=${encodeURIComponent(params.currency)}`);
    if (params?.include_terminal !== undefined) parts.push(`include_terminal=${params.include_terminal}`);
    const qs = parts.length ? `?${parts.join("&")}` : "";
    return request<any[]>(`/finance/commitments${qs}`, { auth: true });
  },
  createFinancialCommitment: (payload: {
    title: string; description?: string; amount: string | number; currency: string;
    due_date: string; priority: string;
    domain_id?: string | null; goal_id?: string | null; project_id?: string | null;
    create_task?: boolean; task_title?: string; task_due_date?: string;
  }) => request<any>("/finance/commitments", { method: "POST", body: payload, auth: true }),
  getFinancialCommitment: (id: string) =>
    request<any>(`/finance/commitments/${id}`, { auth: true }),
  updateFinancialCommitment: (id: string, payload: Partial<{ title: string; description: string; amount: string | number; currency: string; due_date: string; priority: string }>) =>
    request<any>(`/finance/commitments/${id}`, { method: "PUT", body: payload, auth: true }),
  reserveFinancialCommitment: (id: string) =>
    request<any>(`/finance/commitments/${id}/reserve`, { method: "POST", auth: true }),
  completeFinancialCommitment: (id: string, payload: { actual_amount?: string | number; actual_event_id?: string; event_date?: string }) =>
    request<any>(`/finance/commitments/${id}/complete`, { method: "POST", body: payload, auth: true }),
  cancelFinancialCommitment: (id: string) =>
    request<any>(`/finance/commitments/${id}/cancel`, { method: "POST", auth: true }),
  postponeFinancialCommitment: (id: string, new_due_date: string) =>
    request<any>(`/finance/commitments/${id}/postpone`, { method: "POST", body: { new_due_date }, auth: true }),
  keepActiveFinancialCommitment: (id: string) =>
    request<any>(`/finance/commitments/${id}/keep-active`, { method: "POST", auth: true }),
  reviewFinancialCommitment: (id: string, payload: { decision: "keep" | "complete" | "cancel" | "postpone"; new_due_date?: string; actual_amount?: string | number; actual_event_id?: string }) =>
    request<any>(`/finance/commitments/${id}/review`, { method: "POST", body: payload, auth: true }),
  getTaskLinkedCommitment: (taskId: string) =>
    request<any>(`/finance/task-linked-commitment/${taskId}`, { auth: true }),
  getCommitmentsDueForReview: () =>
    request<any[]>("/finance/commitments-due-for-review", { auth: true }),

  listFinancialEvents: (params?: { currency?: string; confirmation_status?: string; limit?: number }) => {
    const parts: string[] = [];
    if (params?.currency) parts.push(`currency=${encodeURIComponent(params.currency)}`);
    if (params?.confirmation_status) parts.push(`confirmation_status=${encodeURIComponent(params.confirmation_status)}`);
    if (params?.limit) parts.push(`limit=${params.limit}`);
    const qs = parts.length ? `?${parts.join("&")}` : "";
    return request<any[]>(`/finance/events${qs}`, { auth: true });
  },
  createFinancialEvent: (payload: { amount: string | number; currency: string; direction: "outflow" | "inflow"; event_date: string; description?: string; source?: string; source_reference?: string; confirmation_status?: string; checkin_id?: string; commitment_id?: string }) =>
    request<any>("/finance/events", { method: "POST", body: payload, auth: true }),
  confirmFinancialEvent: (id: string) =>
    request<any>(`/finance/events/${id}/confirm`, { method: "POST", auth: true }),
  rejectFinancialEvent: (id: string) =>
    request<any>(`/finance/events/${id}/reject`, { method: "POST", auth: true }),

  listDedupeCandidates: () => request<any[]>("/finance/dedupe-candidates", { auth: true }),
  resolveDedupe: (candidateId: string, resolution: "same" | "different", canonical_event_id?: string) =>
    request<any>(`/finance/dedupe-candidates/${candidateId}/resolve`, { method: "POST", body: { resolution, canonical_event_id }, auth: true }),

  getFinancialAudit: (recordType: string, recordId: string) =>
    request<any>(`/finance/audit/${encodeURIComponent(recordType)}/${encodeURIComponent(recordId)}`, { auth: true }),
};
