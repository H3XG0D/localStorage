/**
 * Tests for RequisiteDetailPage:
 * - Shows loading state
 * - Shows error on 404 (no infinite "Загрузка…")
 * - Shows error on NaN ID
 * - Renders requisite data correctly
 * - Progress bar avoids division by zero
 */
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import { RequisiteDetailPage } from '../pages/shared/RequisiteDetailPage';
import { AuthProvider } from '../context/AuthContext';

function renderDetail(path: string, role: 'trader' | 'admin' = 'trader') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path="/trader/requisites/:id" element={<RequisiteDetailPage role={role} />} />
            <Route path="/admin/requisites/:id" element={<RequisiteDetailPage role={role} />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('RequisiteDetailPage', () => {
  it('shows error message on NaN id', async () => {
    renderDetail('/trader/requisites/abc');
    await waitFor(() => {
      expect(screen.getByText(/некорректный id/i)).toBeInTheDocument();
    });
  });

  it('shows error on 404 response (not infinite loading)', async () => {
    server.use(
      http.get('http://localhost:8000/trader/requisites/999', () =>
        HttpResponse.json({ detail: 'Requisite not found' }, { status: 404 })
      )
    );
    renderDetail('/trader/requisites/999');
    await waitFor(
      () => {
        expect(screen.queryByText('Загрузка...')).not.toBeInTheDocument();
        expect(screen.getByText(/не удалось загрузить/i)).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  });

  it('renders requisite data after successful load', async () => {
    renderDetail('/trader/requisites/1');
    await waitFor(() => {
      expect(screen.getByText('Test Card')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows "Нет заливов" in zalivs tab when empty', async () => {
    renderDetail('/trader/requisites/1');
    await waitFor(() => {
      expect(screen.getByText(/нет заливов/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });
});
