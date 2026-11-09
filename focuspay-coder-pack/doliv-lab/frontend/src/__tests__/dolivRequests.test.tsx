/**
 * Tests for TraderDolivRequests page:
 * - Uses api.traderDolivRequests() (correct endpoint)
 * - Displays request fields: ID, amount, status
 * - Shows error state on API failure
 */
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import TraderDolivRequests from '../pages/trader/DolivRequests';
import { AuthProvider } from '../context/AuthContext';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <TraderDolivRequests />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('TraderDolivRequests', () => {
  it('renders requisite name from doliv request data', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Test Card')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows required_amount in the table', async () => {
    renderPage();
    await waitFor(() => {
      // formatMoney(25000) should render ₽
      const cells = screen.getAllByText(/25/);
      expect(cells.length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('shows error message when API fails', async () => {
    server.use(
      http.get('http://localhost:8000/trader/doliv-requests', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/не удалось загрузить заявки/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows "Нет заявок на долив" when list is empty', async () => {
    server.use(
      http.get('http://localhost:8000/trader/doliv-requests', () =>
        HttpResponse.json([])
      )
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/нет заявок на долив/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });
});
