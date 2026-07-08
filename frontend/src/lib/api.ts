import { getToken } from "./tokenStorage";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL as string;

export type ApiError = { status: number; message: string };

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
    const message =
      (data && typeof data === "object" && (data.detail || data.message)) ||
      (typeof data === "string" ? data : "Request failed");
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

  listEvents: () =>
    request<
      { id: string; type: string; title: string; date: string; time: string; notes: string; created_at: string; updated_at: string }[]
    >("/events", { auth: true }),

  createEvent: (payload: { type: string; title: string; date: string; time: string; notes: string }) =>
    request<{ id: string }>("/events", { method: "POST", body: payload, auth: true }),

  getEvent: (id: string) =>
    request<{ id: string; type: string; title: string; date: string; time: string; notes: string; created_at: string; updated_at: string }>(
      `/events/${id}`,
      { auth: true },
    ),

  updateEvent: (
    id: string,
    payload: { type?: string; title?: string; date?: string; time?: string; notes?: string },
  ) => request<{ id: string }>(`/events/${id}`, { method: "PUT", body: payload, auth: true }),
};
