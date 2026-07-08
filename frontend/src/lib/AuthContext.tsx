import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { clearToken, getToken, saveToken } from "./tokenStorage";
import {
  clearWebSessionIdFromUrl,
  extractSessionIdFromWebUrl,
  getInitialSessionIdMobile,
  startGoogleAuth,
} from "./googleAuth";

export type User = { id: string; email: string };

type AuthState = {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, securityQuestion: string, securityAnswer: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        // 1) Process a redirected Google session_id first (web on-load or mobile cold-start).
        const webSid = extractSessionIdFromWebUrl();
        const mobileSid = webSid ? null : await getInitialSessionIdMobile();
        const sid = webSid || mobileSid;
        if (sid) {
          try {
            const res = await api.googleSession(sid);
            await saveToken(res.access_token);
            setUser(res.user);
            clearWebSessionIdFromUrl();
            return;
          } catch {
            clearWebSessionIdFromUrl();
            // fall through to normal token check
          }
        }
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
    async (email: string, password: string, securityQuestion: string, securityAnswer: string) => {
      const res = await api.signup({
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

  const signInWithGoogle = useCallback(async () => {
    const sid = await startGoogleAuth();
    // On web, the browser has already navigated away; nothing more to do here.
    if (!sid) return;
    const res = await api.googleSession(sid);
    await saveToken(res.access_token);
    setUser(res.user);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signUp, signInWithGoogle, signOut }}>{children}</AuthContext.Provider>
  );
};

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
