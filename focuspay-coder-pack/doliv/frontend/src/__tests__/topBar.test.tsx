import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import { TopBar } from '../components/layout/TopBar';
import { AuthProvider } from '../context/AuthContext';

const mockAdmin = {
  id: 1,
  login: 'admin',
  full_name: 'Admin User',
  role: 'admin' as const,
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

function renderTopBar(props: Partial<React.ComponentProps<typeof TopBar>> = {}) {
  server.use(
    http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockAdmin)),
    http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <TopBar
            title="Реквизиты"
            onMenuClick={() => {}}
            search=""
            onSearchChange={() => {}}
            searchPlaceholder="Поиск по реквизитам..."
            {...props}
          />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('TopBar mobile UX', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('shows page title on all screen sizes', () => {
    renderTopBar();
    expect(screen.getByRole('heading', { name: 'Реквизиты' })).toBeInTheDocument();
  });

  it('shows mobile search input when onSearchChange is provided', () => {
    renderTopBar();
    const inputs = screen.getAllByPlaceholderText('Поиск по реквизитам...');
    expect(inputs.length).toBeGreaterThanOrEqual(2);
  });
});
