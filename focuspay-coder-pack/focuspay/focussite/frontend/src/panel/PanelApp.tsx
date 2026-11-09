import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { isLocalDevPanel } from "@/panel/lib/devHost";
import { PanelSessionProvider, usePanelSession } from "@/panel/lib/panelSession";
import { PanelLogin } from "@/panel/PanelLogin";
import { AdminRoutes } from "@/panel/admin/AdminRoutes";
import { OperatorRoutes } from "@/panel/operator/OperatorRoutes";

// panel.html backs both /x8 (admin) and /ops (operator). Scope is chosen by the
// path prefix; each subtree gets its own session provider + auth guard.
export function PanelApp() {
  return (
    <Routes>
      <Route
        path="/x8/*"
        element={
          <PanelSessionProvider scope="admin">
            <ScopeSwitch loginPath="/x8/login" home="/x8">
              <AdminRoutes />
            </ScopeSwitch>
          </PanelSessionProvider>
        }
      />
      <Route
        path="/ops/*"
        element={
          <PanelSessionProvider scope="operator">
            <ScopeSwitch loginPath="/ops/login" home="/ops">
              <OperatorRoutes />
            </ScopeSwitch>
          </PanelSessionProvider>
        }
      />
      <Route path="*" element={<Navigate to="/x8" replace />} />
    </Routes>
  );
}

// Handles the /login sub-route + auth guard for a scope subtree.
function ScopeSwitch({ loginPath, home, children }: { loginPath: string; home: string; children: React.ReactNode }) {
  const { isAuthed, loading } = usePanelSession();
  const loc = useLocation();
  const onLogin = loc.pathname === loginPath;
  const forceLogin = loc.search.includes("realLogin=1");
  const skipLogin = isLocalDevPanel() && !forceLogin;

  if (loading) {
    return <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--bg-base)] text-[var(--text-muted)]">Загрузка…</div>;
  }
  if (skipLogin) {
    if (onLogin) return <Navigate to={home} replace />;
    return <>{children}</>;
  }
  if (onLogin) {
    return isAuthed ? <Navigate to={home} replace /> : <PanelLogin redirectTo={home} />;
  }
  if (!isAuthed) return <Navigate to={loginPath} replace />;
  return <>{children}</>;
}
