import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ProtectedRoute } from './components/layout/AppShell';
import { getHomePath } from './config/navigation';
import { ApiError, NetworkError } from './api/client';
import LoginPage from './pages/auth/LoginPage';

// Owner
import OwnerDashboard from './pages/owner/OwnerDashboard';
import OwnerAdminsPage from './pages/owner/OwnerAdminsPage';
import { StatsPage } from './pages/admin/StatsPage';
import { RatingsPage } from './pages/admin/RatingsPage';

// Admin
import AdminDashboard from './pages/admin/Dashboard';
import AdminUsers from './pages/admin/UsersPage';
import AdminStats from './pages/admin/StatsPage';
import AdminRatings from './pages/admin/RatingsPage';
import {
  AdminDolivRequests, AdminDolivs, AdminReceipts, AdminAnalytics,
  AdminEmployees, AdminSalaries, AdminStatements, AdminRoles, AdminSettings,
} from './pages/admin/PlaceholderPages';

// Shared requisites
import { RequisitesListPage } from './pages/shared/RequisitesListPage';
import { RequisiteDetailPage } from './pages/shared/RequisiteDetailPage';

// Trader
import TraderDashboard from './pages/trader/TraderDashboard';
import TraderDolivRequests from './pages/trader/DolivRequests';

// Doliv
import DolivDashboard, { DolivHistory } from './pages/doliv/DolivPages';

import './index.css';

function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-base text-center px-4">
      <p className="text-8xl font-bold text-accent/30">404</p>
      <h1 className="mt-4 text-2xl font-bold">Страница не найдена</h1>
      <p className="mt-2 text-muted text-sm">Запрошенный адрес не существует или у вас нет доступа.</p>
      <a href="/" className="mt-6 btn-primary text-sm">На главную</a>
    </div>
  );
}

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status === 401) return false;
        if (error instanceof NetworkError) return failureCount < 2;
        return failureCount < 1;
      },
      staleTime: 30_000,
    },
  },
});

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" />;
  return <Navigate to={getHomePath(user.role)} />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<HomeRedirect />} />

            {/* Owner */}
            <Route path="/owner" element={<ProtectedRoute roles={['owner']}><OwnerDashboard /></ProtectedRoute>} />
            <Route path="/owner/admins" element={<ProtectedRoute roles={['owner']}><OwnerAdminsPage /></ProtectedRoute>} />
            <Route path="/owner/stats" element={<ProtectedRoute roles={['owner']}><StatsPage scope="owner" /></ProtectedRoute>} />
            <Route path="/owner/analytics" element={<ProtectedRoute roles={['owner']}><AdminAnalytics scope="owner" /></ProtectedRoute>} />
            <Route path="/owner/ratings" element={<ProtectedRoute roles={['owner']}><RatingsPage scope="owner" /></ProtectedRoute>} />
            <Route path="/owner/employees" element={<ProtectedRoute roles={['owner']}><AdminEmployees scope="owner" /></ProtectedRoute>} />

            {/* Admin */}
            <Route path="/admin" element={<ProtectedRoute roles={['admin']}><AdminDashboard /></ProtectedRoute>} />
            <Route path="/admin/requisites" element={<ProtectedRoute roles={['admin']}><RequisitesListPage role="admin" /></ProtectedRoute>} />
            <Route path="/admin/requisites/:id" element={<ProtectedRoute roles={['admin']}><RequisiteDetailPage role="admin" /></ProtectedRoute>} />
            <Route path="/admin/doliv-requests" element={<ProtectedRoute roles={['admin']}><AdminDolivRequests /></ProtectedRoute>} />
            <Route path="/admin/dolivs" element={<ProtectedRoute roles={['admin']}><AdminDolivs /></ProtectedRoute>} />
            <Route path="/admin/receipts" element={<ProtectedRoute roles={['admin']}><AdminReceipts /></ProtectedRoute>} />
            <Route path="/admin/employees" element={<ProtectedRoute roles={['admin']}><AdminEmployees /></ProtectedRoute>} />
            <Route path="/admin/stats" element={<ProtectedRoute roles={['admin']}><AdminStats /></ProtectedRoute>} />
            <Route path="/admin/analytics" element={<ProtectedRoute roles={['admin']}><AdminAnalytics /></ProtectedRoute>} />
            <Route path="/admin/ratings" element={<ProtectedRoute roles={['admin']}><AdminRatings /></ProtectedRoute>} />
            <Route path="/admin/salaries" element={<ProtectedRoute roles={['admin']}><AdminSalaries /></ProtectedRoute>} />
            <Route path="/admin/statements" element={<ProtectedRoute roles={['admin']}><AdminStatements /></ProtectedRoute>} />
            <Route path="/admin/users" element={<ProtectedRoute roles={['admin']}><AdminUsers /></ProtectedRoute>} />
            <Route path="/admin/roles" element={<ProtectedRoute roles={['admin']}><AdminRoles /></ProtectedRoute>} />
            <Route path="/admin/settings" element={<ProtectedRoute roles={['admin']}><AdminSettings /></ProtectedRoute>} />

            {/* Trader */}
            <Route path="/trader" element={<ProtectedRoute roles={['trader']}><TraderDashboard /></ProtectedRoute>} />
            <Route path="/trader/requisites" element={<ProtectedRoute roles={['trader']}><RequisitesListPage role="trader" /></ProtectedRoute>} />
            <Route path="/trader/requisites/:id" element={<ProtectedRoute roles={['trader']}><RequisiteDetailPage role="trader" /></ProtectedRoute>} />
            <Route path="/trader/doliv-requests" element={<ProtectedRoute roles={['trader']}><TraderDolivRequests /></ProtectedRoute>} />

            {/* Dolivshchik */}
            <Route path="/doliv" element={<ProtectedRoute roles={['dolivshchik']}><DolivDashboard /></ProtectedRoute>} />
            <Route path="/doliv/history" element={<ProtectedRoute roles={['dolivshchik']}><DolivHistory /></ProtectedRoute>} />

            {/* 404 */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
