import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, type UserResponse } from "./api";
import { clearToken, getToken, saveToken } from "./tokenStorage";

export type PostCreationDecompositionPreference =
  | "always_ask"
  | "always_decompose"
  | "always_skip";

export type User = UserResponse;

type AuthState = {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (
    displayName: string,
    email: string,
    password: string,
    securityQuestion: string,
    securityAnswer: string,
  ) => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  updateDisplayName: (displayName: string) => Promise<User>;
  setPostCreationDecompositionPreference: (preference: PostCreationDecompositionPreference) => Promise<User>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        if (!token) {
          setUser(null);
          return;
        }
        const me = await api.me();
        setUser(me);
      } catch {
        await clearToken();
        setUser(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    await saveToken(res.access_token);
    setUser(res.user);
  }, []);

  const signUp = useCallback(
    async (
      displayName: string,
      email: string,
      password: string,
      securityQuestion: string,
      securityAnswer: string,
    ) => {
      const res = await api.signup({
        display_name: displayName,
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

  const updateDisplayName = useCallback(async (displayName: string): Promise<User> => {
    const updated = await api.updateMe({ display_name: displayName });
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
    <AuthContext.Provider value={{
      user,
      loading,
      signIn,
      signUp,
      signOut,
      refreshUser,
      updateDisplayName,
      setPostCreationDecompositionPreference,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
