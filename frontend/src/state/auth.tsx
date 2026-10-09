/**
 * Admin session.
 *
 * The token is kept in localStorage so a page reload does not log the admin
 * out, and dropped as soon as it expires or the server rejects it. Watching
 * the dashboard never needs it; only changing the house, ratings, tariff or
 * alert thresholds does.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setAuthToken, setUnauthorizedHandler } from "@/lib/api";

const TOKEN_KEY = "nilm-admin-session";

interface Session {
  token: string;
  username: string;
  /** Seconds since the epoch, as issued by the server. */
  expiresAt: number;
}

interface AuthContextValue {
  admin: { username: string; expiresAt: number } | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loadSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    if (!session.token || session.expiresAt * 1000 <= Date.now()) return null;
    return session;
  } catch {
    return null;
  }
}

function saveSession(session: Session | null) {
  try {
    if (session) window.localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* the session then lasts only as long as the page */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    const stored = loadSession();
    setAuthToken(stored?.token ?? null);
    return stored;
  });

  const logout = useCallback(() => {
    setAuthToken(null);
    saveSession(null);
    setSession(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Log out exactly when the token expires, rather than on the next failure.
  useEffect(() => {
    if (!session) return;
    const remaining = session.expiresAt * 1000 - Date.now();
    const timer = window.setTimeout(logout, Math.max(0, remaining));
    return () => window.clearTimeout(timer);
  }, [session, logout]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.login(username, password);
    const next: Session = {
      token: response.token,
      username: response.username,
      expiresAt: response.expires_at,
    };
    setAuthToken(next.token);
    saveSession(next);
    setSession(next);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      admin: session
        ? { username: session.username, expiresAt: session.expiresAt }
        : null,
      login,
      logout,
    }),
    [session, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an <AuthProvider>");
  return context;
}
