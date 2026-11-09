/**
 * Tests for DolivDashboard page:
 * - Renders request queue
 * - Shows "Взять" button for pending requests
 * - Shows "Выполнить" for in_progress requests
 * - Shows stats cards with data
 * - Empty state when no requests
 * - Loading state
 * - Error state on API failure
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import DolivDashboard from '../pages/doliv/DolivPages';
import { AuthProvider } from '../context/AuthContext';

// ──────────────────────────────────────────────────────────────────────────────
// Mock data
// ──────────────────────────────────────────────────────────────────────────────

const mockDolivUser = {
  id: 5,
  login: 'doliv1',
  full_name: 'Василий Доливщик',
  role: 'dolivshchik' as const,
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

const mockPendingRequest = {
  id: 10,
  requisite_id: 1,
  required_amount: '15000',
  status: 'pending',
  sent_at: '2024-06-01T10:00:00Z',
  assigned_dolivshchik_id: null,
  assigned_dolivshchik_name: null,
  requisite_name: 'SberCard 4444',
  target_rate: '92.5000',
  trader_name: 'Иван Трейдер',
};

const mockInProgressRequest = {
  ...mockPendingRequest,
  id: 11,
  status: 'in_progress',
  assigned_dolivshchik_id: 5,
  assigned_dolivshchik_name: 'Василий Доливщик',
  requisite_name: 'TinkoffCard 5555',
};

const mockDolivStats = {
  dolivs_count: 12,
  total_doliv_amount: '480000',
  avg_doliv_rate: '91.5',
};

const mockDolivHistory = [
  {
    id: 1,
    amount: '20000',
    rate: '92.0',
    receipt_path: 'receipt1.jpg',
    completed_at: '2024-06-15T14:30:00Z',
    dolivshchik_name: 'Василий Доливщик',
  },
];

const mockDolivReceipts = [
  {
    id: 1,
    kind: 'doliv',
    receipt_path: 'receipt1.jpg',
    created_at: '2024-06-15T14:30:00Z',
  },
];

function setupDolivMocks(requests = [mockPendingRequest]) {
  server.use(
    http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
    http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json(requests)),
    http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
    http.get('http://localhost:8000/doliv/history', () => HttpResponse.json(mockDolivHistory)),
    http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
    http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 2 })),
  );
}

function renderDolivDashboard() {
  setupDolivMocks();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <DolivDashboard />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

describe('DolivDashboard', () => {
  beforeEach(() => {
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('renders pending request in queue', async () => {
    renderDolivDashboard();
    await waitFor(() => {
      // Request name may appear multiple times (queue row + active request panel)
      expect(screen.getAllByText('SberCard 4444').length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });
  });

  it('shows trader name in request row', async () => {
    renderDolivDashboard();
    await waitFor(() => {
      expect(screen.getAllByText(/иван трейдер/i).length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });
  });

  it('shows "Взять" button for pending requests', async () => {
    renderDolivDashboard();
    await waitFor(() => {
      expect(screen.getByText('Взять')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows "Выполнить" button for in_progress requests', async () => {
    server.use(
      http.get('http://localhost:8000/doliv/requests', () =>
        HttpResponse.json([mockInProgressRequest])
      )
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Выполнить')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows empty state when no requests', async () => {
    server.use(
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json([]))
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => {
      expect(screen.getByText(/нет новых заявок/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows stats: dolivs today and earnings', async () => {
    renderDolivDashboard();
    await waitFor(() => {
      expect(screen.getByText('Доливов сегодня')).toBeInTheDocument();
      expect(screen.getByText('2')).toBeInTheDocument();
      expect(screen.getByText('Заработок сегодня')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('calls take API when "Взять" is clicked', async () => {
    let takeCalled = false;
    server.use(
      http.post('http://localhost:8000/doliv/requests/10/take', () => {
        takeCalled = true;
        return HttpResponse.json({ message: 'Request taken' });
      })
    );

    renderDolivDashboard();

    await waitFor(() => {
      expect(screen.getByText('Взять')).toBeInTheDocument();
    }, { timeout: 3000 });

    fireEvent.click(screen.getByText('Взять'));

    await waitFor(() => {
      expect(takeCalled).toBe(true);
    }, { timeout: 3000 });
  });

  it('shows page title "Рабочая очередь"', async () => {
    renderDolivDashboard();
    await waitFor(() => {
      expect(screen.getByText('Рабочая очередь')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('displays required_amount formatted as money', async () => {
    renderDolivDashboard();
    await waitFor(() => {
      // 15000 should appear (possibly formatted as ₽15 000 or 15 000 ₽)
      const els = screen.getAllByText(/15/);
      expect(els.length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('shows all in_progress requests in "Мои доливы" without a limit of 3', async () => {
    const inProgressRequests = Array.from({ length: 5 }, (_, i) => ({
      ...mockInProgressRequest,
      id: 20 + i,
      requisite_name: `Rek ${i + 1}`,
    }));

    server.use(
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json(inProgressRequests)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Мои доливы')).toBeInTheDocument();
      expect(screen.getAllByText('Выполнить')).toHaveLength(5);
      for (let i = 1; i <= 5; i++) {
        expect(screen.getAllByText(`Rek ${i}`).length).toBeGreaterThanOrEqual(1);
      }
    }, { timeout: 3000 });
  });

  it('does not show completed history in "Мои доливы" panel', async () => {
    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json([mockInProgressRequest])),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json(mockDolivHistory)),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Мои доливы')).toBeInTheDocument();
      expect(screen.getAllByText('TinkoffCard 5555').length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });

    expect(screen.queryByText('Долив #1')).not.toBeInTheDocument();
  });

  it('filters in_progress requests in "Мои доливы" by search query', async () => {
    const inProgressRequests = [
      { ...mockInProgressRequest, id: 21, requisite_name: 'Alpha Card' },
      { ...mockInProgressRequest, id: 22, requisite_name: 'Beta Card' },
    ];

    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json(inProgressRequests)),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('Alpha Card').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Beta Card').length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });

    fireEvent.change(screen.getByPlaceholderText(/поиск по реквизиту/i), { target: { value: 'alpha' } });

    await waitFor(() => {
      expect(screen.getAllByText('Alpha Card').length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText('Beta Card')).not.toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('prefills form when "Выполнить" is clicked in "Мои доливы"', async () => {
    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json([mockInProgressRequest])),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Выполнить')).toBeInTheDocument();
    }, { timeout: 3000 });

    fireEvent.click(screen.getByText('Выполнить'));

    await waitFor(() => {
      const amountInput = screen.getByPlaceholderText('Сумма') as HTMLInputElement;
      expect(amountInput.value).toBe('15000');
      expect(screen.getByText(/сумма должна точно совпадать/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows form error when submitting without receipt file', async () => {
    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json([mockInProgressRequest])),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Подтвердить выполнение')).toBeInTheDocument();
    }, { timeout: 3000 });

    fireEvent.click(screen.getByText('Подтвердить выполнение'));

    await waitFor(() => {
      expect(screen.getByText(/прикрепите файл чека/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows API error when take fails', async () => {
    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json([mockPendingRequest])),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
      http.post('http://localhost:8000/doliv/requests/10/take', () =>
        HttpResponse.json({ detail: 'Request not available' }, { status: 400 })
      ),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Взять')).toBeInTheDocument();
    }, { timeout: 3000 });

    fireEvent.click(screen.getByText('Взять'));

    await waitFor(() => {
      expect(screen.getByText(/заявка уже недоступна/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('completes doliv when receipt file is attached', async () => {
    let completeCalled = false;
    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json([mockInProgressRequest])),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
      http.post('http://localhost:8000/doliv/requests/11/complete', async () => {
        completeCalled = true;
        return HttpResponse.json({ message: 'ok' });
      }),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Подтвердить выполнение')).toBeInTheDocument();
    }, { timeout: 3000 });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const receipt = new File(['fake'], 'receipt.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [receipt] } });

    fireEvent.click(screen.getByText('Подтвердить выполнение'));

    await waitFor(() => {
      expect(completeCalled).toBe(true);
      expect(screen.getByText(/долив успешно завершён/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('disables only the clicked "Взять" button while taking', async () => {
    const pendingRequests = [
      mockPendingRequest,
      { ...mockPendingRequest, id: 12, requisite_name: 'Second Card' },
    ];

    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json(pendingRequests)),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
      http.post('http://localhost:8000/doliv/requests/10/take', async () => {
        await new Promise((r) => setTimeout(r, 200));
        return HttpResponse.json({ message: 'Request taken' });
      }),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('Взять')).toHaveLength(2);
    }, { timeout: 3000 });

    const takeButtons = screen.getAllByText('Взять');
    fireEvent.click(takeButtons[0]);

    await waitFor(() => {
      expect(takeButtons[0]).toBeDisabled();
      expect(takeButtons[1]).not.toBeDisabled();
    }, { timeout: 3000 });
  });

  it('shows error banner when requests API fails', async () => {
    server.use(
      http.get('http://localhost:8000/auth/me', () => HttpResponse.json(mockDolivUser)),
      http.get('http://localhost:8000/doliv/requests', () => HttpResponse.json({ detail: 'fail' }, { status: 500 })),
      http.get('http://localhost:8000/doliv/stats', () => HttpResponse.json(mockDolivStats)),
      http.get('http://localhost:8000/doliv/history', () => HttpResponse.json([])),
      http.get('http://localhost:8000/doliv/receipts', () => HttpResponse.json(mockDolivReceipts)),
      http.get('http://localhost:8000/notifications/unread-count', () => HttpResponse.json({ count: 0 })),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <DolivDashboard />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/не удалось загрузить заявки/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });
});
