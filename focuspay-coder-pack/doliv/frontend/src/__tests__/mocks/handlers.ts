import { http, HttpResponse } from 'msw';

const API = 'http://localhost:8000';

export const mockUser = {
  id: 1,
  login: 'trader1',
  full_name: 'Test Trader',
  role: 'trader' as const,
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

export const mockAdminUser = {
  id: 2,
  login: 'admin1',
  full_name: 'Test Admin',
  role: 'admin' as const,
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

export const mockRequisite = {
  id: 1,
  trader_id: 1,
  name: 'Test Card',
  total_amount: '50000',
  target_rate: '90.5000',
  comment: null,
  status: 'active',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  zalivs: [],
  zaliv_total: '0',
  remaining: '50000',
  avg_rate: null,
  current_profit: '0',
};

export const mockDolivRequest = {
  id: 10,
  requisite_id: 1,
  required_amount: '25000',
  status: 'pending',
  sent_at: '2024-01-02T00:00:00Z',
  assigned_dolivshchik_id: null,
  assigned_dolivshchik_name: null,
  requisite_name: 'Test Card',
  target_rate: '90.5000',
  trader_name: 'Test Trader',
  zaliv_total: '25000',
};

export const handlers = [
  http.post(`${API}/auth/login`, () =>
    HttpResponse.json({ access_token: 'mock-token', token_type: 'bearer' })
  ),

  http.get(`${API}/auth/me`, () => HttpResponse.json(mockUser)),

  http.get(`${API}/trader/requisites`, () => HttpResponse.json([mockRequisite])),

  http.get(`${API}/trader/requisites/:id`, ({ params }) => {
    const id = Number(params.id);
    if (Number.isNaN(id) || id === 999) {
      return HttpResponse.json({ detail: 'Requisite not found' }, { status: 404 });
    }
    return HttpResponse.json({ ...mockRequisite, id });
  }),

  http.get(`${API}/trader/doliv-requests`, () => HttpResponse.json([mockDolivRequest])),

  http.get(`${API}/doliv/stats`, () =>
    HttpResponse.json({
      user_id: 1,
      login: 'doliv1',
      full_name: 'Test Doliv',
      dolivs_count: 12,
      total_doliv_amount: '120000',
      total_doliv_amount_usdt: '1300',
      avg_doliv_rate: '91.5',
      total_processed: '120000',
      total_doliv_loss: '0',
      salary_per_doliv_usdt: '1',
      dolivs_today: 2,
      earnings_today: '2',
    })
  ),

  http.get(`${API}/doliv/settings`, () =>
    HttpResponse.json({ salary_per_doliv_usdt: '1', currency: 'RUB' })
  ),

  http.get(`${API}/trader/stats`, () =>
    HttpResponse.json({
      user_id: 1,
      full_name: 'Test Trader',
      requisites_count: 3,
      total_turnover: '150000',
      total_turnover_usdt: '1621.62',
      total_profit: '18000',
      avg_profit_per_requisite: '6000',
      profit_day: '1200',
      profit_week: '8400',
      profit_month: '18000',
    })
  ),

  http.get(`${API}/trader/settings`, () =>
    HttpResponse.json({ profit_percent: '12', currency: 'RUB' })
  ),

  http.get(`${API}/notifications`, () => HttpResponse.json([])),
  http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ count: 0 })),
];
