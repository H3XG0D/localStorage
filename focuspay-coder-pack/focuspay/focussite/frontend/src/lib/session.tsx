// Buyer session context: bootstraps from bearer token or cookie session,
// exposes the current user and auth actions to the whole public SPA.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, getGuestSession, getToken, setToken, clearToken } from "@/lib/api";
import { fetchMe, logoutRequest, type LoginSuccess, type User } from "@/lib/auth";

function isLoggedOutStatus(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

interface SessionState {
  user: User | null;
  loading: boolean;
  isAuthed: boolean;
  /** Adopt a successful login/register/2fa/telegram result. */
  adopt: (result: LoginSuccess) => void;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Ensure a guest-session UUID exists before any request fires.
  useEffect(() => {
    getGuestSession();
  }, []);

  const refresh = useCallback(async () => {
    // A cookie session works without a bearer token, so always probe /me.
    try {
      const { user } = await fetchMe();
      setUser(user);
    } catch (error) {
      if (!isLoggedOutStatus(error)) return;
      setUser(null);
      if (getToken("user")) clearToken("user");
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { user } = await fetchMe();
        if (alive) setUser(user);
      } catch (error) {
        if (alive && isLoggedOutStatus(error)) setUser(null);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const adopt = useCallback((result: LoginSuccess) => {
    if (result.access_token) setToken("user", result.access_token);
    setUser(result.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } catch {
      /* ignore network errors on logout */
    }
    clearToken("user");
    setUser(null);
  }, []);

  const value = useMemo<SessionState>(
    () => ({ user, loading, isAuthed: !!user, adopt, refresh, logout }),
    [user, loading, adopt, refresh, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within <SessionProvider>");
  return ctx;
}
