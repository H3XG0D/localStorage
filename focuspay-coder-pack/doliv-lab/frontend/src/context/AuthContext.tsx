import { createContext, useContext, useEffect, useState, ReactNode, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, meWithRetry, setUnauthorizedHandler, User } from '../api/client';

const SESSION_REFRESH_MS = 10 * 60 * 1000;

export const ADMIN_QUERY_KEYS = [
  'admin-overview',
  'admin-dashboard-stats',
  'admin-requisites',
  'admin-activity',
  'admin-traders',
  'admin-dolivshchiks',
  'notifications',
  'notifications-unread-count',
] as const;

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (login: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const logoutRef = useRef<() => void>(() => {});
  const queryClient = useQueryClient();

  const logout = useCallback(() => {
    api.logout().catch(() => {});
    setUser(null);
  }, []);

  logoutRef.current = logout;

  useEffect(() => {
    setUnauthorizedHandler(() => logoutRef.current());
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    meWithRetry()
      .then(setUser)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    const refresh = () => {
      api.refresh().catch(() => {});
    };
    const id = window.setInterval(refresh, SESSION_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [user]);

  const login = async (loginStr: string, password: string) => {
    await api.login(loginStr.trim(), password.trim());
    const me = await api.me();
    setUser(me);
    queryClient.clear();
    await Promise.all(
      ADMIN_QUERY_KEYS.map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    );
    return me;
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
