/**
 * Tests for AdminUsers page:
 * - Renders user list from API
 * - Shows user roles in Russian
 * - Shows "Новый пользователь" button
 * - Opens modal when button is clicked
 * - Submits create user form successfully
 * - Shows error when create user API fails
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import AdminUsers from '../pages/admin/UsersPage';
import { AuthProvider } from '../context/AuthContext';
import { mockAdminUser } from './mocks/handlers';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

const mockUsers = [
  {
    id: 1,
    login: 'trader1',
    full_name: 'Иван Трейдер',
    role: 'trader' as const,
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 2,
    login: 'doliv1',
    full_name: 'Пётр Доливщик',
    role: 'dolivshchik' as const,
    is_active: false,
    created_at: '2024-02-01T00:00:00Z',
  },
  {
    id: 3,
    login: 'admin1',
    full_name: 'Сергей Админ',
    role: 'admin' as const,
    is_active: true,
    created_at: '2024-03-01T00:00:00Z',
  },
];

function setupAdminUserMocks() {
  server.use(
    http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockAdminUser)),
    http.get('http://localhost:8000/admin/users', () => HttpResponse.json(mockUsers)),
    http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
  );
}

function renderAdminUsers() {
  setupAdminUserMocks();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <AdminUsers />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

describe('AdminUsers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders page title', async () => {
    renderAdminUsers();
    await waitFor(() => {
      // Multiple "Пользователи" may exist (nav + header), ensure at least one
      expect(screen.getAllByText('Пользователи').length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });
  });

  it('renders user list from API', async () => {
    renderAdminUsers();
    await waitFor(() => {
      expect(screen.getByText('Иван Трейдер')).toBeInTheDocument();
      expect(screen.getByText('Пётр Доливщик')).toBeInTheDocument();
      expect(screen.getByText('Сергей Админ')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows Russian role labels', async () => {
    renderAdminUsers();
    await waitFor(() => {
      expect(screen.getByText('Трейдер')).toBeInTheDocument();
      expect(screen.getByText('Доливщик')).toBeInTheDocument();
      expect(screen.getByText('Админ')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows active/inactive status correctly', async () => {
    renderAdminUsers();
    await waitFor(() => {
      const activeElements = screen.getAllByText('Активен');
      const inactiveElements = screen.getAllByText('Неактивен');
      expect(activeElements.length).toBeGreaterThanOrEqual(2);
      expect(inactiveElements.length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });
  });

  it('shows "Новый пользователь" button', async () => {
    renderAdminUsers();
    await waitFor(() => {
      expect(screen.getByText(/новый пользователь/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('opens modal when "Новый пользователь" is clicked', async () => {
    renderAdminUsers();
    await waitFor(() => {
      const btn = screen.getByText(/новый пользователь/i);
      fireEvent.click(btn);
    }, { timeout: 3000 });

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Логин')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Пароль')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('ФИО')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('submits create user form and closes modal on success', async () => {
    server.use(
      http.post('http://localhost:8000/admin/users', () =>
        HttpResponse.json({
          id: 99,
          login: 'newuser',
          full_name: 'Новый Пользователь',
          role: 'trader',
          is_active: true,
          created_at: new Date().toISOString(),
        }, { status: 201 })
      )
    );

    renderAdminUsers();

    await waitFor(() => {
      const btn = screen.getByText(/новый пользователь/i);
      fireEvent.click(btn);
    }, { timeout: 3000 });

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Логин')).toBeInTheDocument();
    }, { timeout: 1000 });

    fireEvent.change(screen.getByPlaceholderText('Логин'), { target: { value: 'newuser' } });
    fireEvent.change(screen.getByPlaceholderText('Пароль'), { target: { value: 'pass123' } });
    fireEvent.change(screen.getByPlaceholderText('ФИО'), { target: { value: 'Новый Пользователь' } });
    fireEvent.click(screen.getByText('Создать'));

    await waitFor(() => {
      expect(screen.queryByPlaceholderText('Логин')).not.toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('keeps modal open when API returns error', async () => {
    server.use(
      http.post('http://localhost:8000/admin/users', () =>
        HttpResponse.json({ detail: 'Login already taken' }, { status: 400 })
      )
    );

    renderAdminUsers();

    await waitFor(() => {
      const btn = screen.getByText(/новый пользователь/i);
      fireEvent.click(btn);
    }, { timeout: 3000 });

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Логин')).toBeInTheDocument();
    }, { timeout: 1000 });

    fireEvent.change(screen.getByPlaceholderText('Логин'), { target: { value: 'existing' } });
    fireEvent.change(screen.getByPlaceholderText('Пароль'), { target: { value: 'pass123' } });
    fireEvent.change(screen.getByPlaceholderText('ФИО'), { target: { value: 'Test User' } });
    fireEvent.click(screen.getByText('Создать'));

    // Modal should still be open (API failed, no success)
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Логин')).toBeInTheDocument();
    }, { timeout: 2000 });
  });
});
