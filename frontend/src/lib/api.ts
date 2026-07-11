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

  listTasks: (params?: { goalId?: string }) => {
    const qs = params?.goalId ? `?goal_id=${encodeURIComponent(params.goalId)}` : "";
    return request<
      { id: string; title: string; due_date: string; priority: string; status: string; notes: string; origin: string; expected_outcome_id: string | null; project_id: string | null }[]
    >(`/tasks${qs}`, { auth: true });
  },
  createTask: (payload: { title: string; due_date?: string; priority?: string; status?: string; notes?: string; origin: string; expected_outcome_id?: string | null; project_id?: string | null }) =>
    request<{ id: string }>("/tasks", { method: "POST", body: payload, auth: true }),
  getTask: (id: string) =>
    request<{ id: string; title: string; due_date: string; priority: string; status: string; notes: string; origin: string; expected_outcome_id: string | null; project_id: string | null }>(
      `/tasks/${id}`,
      { auth: true },
    ),
  updateTask: (id: string, payload: { title?: string; due_date?: string; priority?: string; status?: string; notes?: string }) =>
    request<{ id: string }>(`/tasks/${id}`, { method: "PUT", body: payload, auth: true }),
  deleteTask: (id: string) =>
    request<{ detail: string }>(`/tasks/${id}`, { method: "DELETE", auth: true }),

  listCheckins: (params?: { goalId?: string }) => {
    const qs = params?.goalId ? `?goal_id=${encodeURIComponent(params.goalId)}` : "";
    return request<
      { id: string; type: string; title: string; date: string; time: string; notes: string; attachment: string; expected_outcome_id: string | null; goal_id: string | null; project_id: string | null; task_id: string | null; follow_up_task_id: string | null }[]
    >(`/checkins${qs}`, { auth: true });
  },
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
};
