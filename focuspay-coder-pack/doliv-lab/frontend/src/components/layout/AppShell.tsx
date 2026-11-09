import { ReactNode, useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { UserRole } from '../../api/client';
import { getHomePath } from '../../config/navigation';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function ProtectedRoute({ children, roles }: { children: ReactNode; roles?: UserRole[] }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-base">
        <div className="text-muted text-sm">Загрузка...</div>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  if (roles && !roles.includes(user.role)) {
    return <Navigate to={getHomePath(user.role)} replace />;
  }

  return <>{children}</>;
}

interface AppShellProps {
  title: string;
  children: ReactNode;
  search?: string;
  onSearchChange?: (v: string) => void;
  searchPlaceholder?: string;
}

export function AppShell({ title, children, search, onSearchChange, searchPlaceholder }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!sidebarOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [sidebarOpen]);

  const closeSidebar = () => setSidebarOpen(false);

  return (
    <div className="min-h-screen bg-base">
      <Sidebar open={sidebarOpen} onClose={closeSidebar} />
      <div className="lg:pl-60">
        <TopBar
          title={title}
          onMenuClick={() => setSidebarOpen(true)}
          search={search}
          onSearchChange={onSearchChange}
          searchPlaceholder={searchPlaceholder}
        />
        <main
          className="p-4 lg:p-6 text-[#fafafa]"
          onClick={() => {
            if (sidebarOpen) closeSidebar();
          }}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
