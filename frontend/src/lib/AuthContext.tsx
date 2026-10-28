import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { clearToken, getToken, saveToken } from "./tokenStorage";

const AUTH_STARTUP_TIMEOUT_MS = 10_000;
const AUTH_STARTUP_TIMEOUT_CODE = "AUTH_STARTUP_TIMEOUT";
const AUTH_STARTUP_ERROR_MESSAGE =
  "Hymn could not verify your session. Check your connection and try again.";

function withAuthStartupTimeout<T>(operation: Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      reject(new Error(AUTH_STARTUP_TIMEOUT_CODE));
    }, AUTH_STARTUP_TIMEOUT_MS);

    operation.then(
      (value) => {
        clearTimeout(timeoutId);
        resolve(value);
      },
      (error) => {
        clearTimeout(timeoutId);
        reject(error);
      },
    );
  });
}

export type PostCreationDecompositionPreference =
  | "always_ask"
  | "always_decompose"
  | "always_skip";

export type User = {
  id: string;
  email: string;
  name?: string | null;
  portfolio_setup_completed_at?: string | null;
  portfolio_reporting_currency?: string | null;
  post_creation_decomposition_preference?: PostCreationDecompositionPreference;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  startupError: string | null;
  retryStartup: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string, securityQuestion: string, securityAnswer: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  updateName: (name: string) => Promise<User>;
  setPostCreationDecompositionPreference: (preference: PostCreationDecompositionPreference) => Promise<User>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);

  const hydrateAuth = useCallback(async () => {
    setLoading(true);
    setStartupError(null);

    try {
      const hydratedUser = await withAuthStartupTimeout(
        (async () => {
          const token = await getToken();

          if (!token) {
            return null;
          }

          return api.me();
        })(),
      );

      setUser(hydratedUser);
    } catch (error: unknown) {
      const status =
        error &&
        typeof error === "object" &&
        "status" in error
          ? (error as { status?: unknown }).status
          : null;

      if (status === 401 || status === 403) {
        await clearToken();
        setUser(null);
        return;
      }

      setStartupError(AUTH_STARTUP_ERROR_MESSAGE);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void hydrateAuth();
  }, [hydrateAuth]);

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    await saveToken(res.access_token);
    setUser(res.user);
  }, []);

  const signUp = useCallback(
    async (name: string, email: string, password: string, securityQuestion: string, securityAnswer: string) => {
      const res = await api.signup({
        name,
        email,
        password,
        security_question: securityQuestion,
        security_answer: securityAnswer,
      });
      await saveToken(res.access_token);
      setUser(res.user);
    },
    [],
  );

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // ignore
    }
    await clearToken();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      // Silently ignore — the caller decides how to react.
    }
  }, []);

  const updateName = useCallback(async (name: string): Promise<User> => {
    const updated = await api.updateProfile(name);
    setUser(updated);
    return updated;
  }, []);

  const setPostCreationDecompositionPreference = useCallback(
    async (preference: PostCreationDecompositionPreference): Promise<User> => {
      const updated = await api.updatePostCreationDecompositionPreference(preference);
      setUser(updated);
      return updated;
    },
    [],
  );

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        startupError,
        retryStartup: hydrateAuth,
        signIn,
        signUp,
        signOut,
        refreshUser,
        updateName,
        setPostCreationDecompositionPreference,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
