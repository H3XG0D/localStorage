// In production: relative /api prefix → nginx strips /api and proxies to backend.
// In development: set VITE_API_URL=http://localhost:8000 to hit backend directly.
const API_URL = import.meta.env.VITE_API_URL ?? '/api';

export type UserRole = 'owner' | 'trader' | 'dolivshchik' | 'admin';
export type StatsScope = 'admin' | 'owner';

export interface User {
  id: number;
  login: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  last_login: string | null;
  profit_percent: string | null;
  doliv_salary_usdt: string | null;
  created_at: string;
}

export interface DolivshchikStats {
  user_id: number;
  login: string;
  full_name: string;
  dolivs_count: number;
  total_doliv_amount: string;
  total_doliv_amount_usdt: string;
  avg_doliv_rate: string;
  total_processed: string;
  total_doliv_loss: string;
  salary_per_doliv_usdt: string;
  dolivs_today: number;
  earnings_today: string;
}

export interface OwnerDashboard {
  stats: DashboardStats & Record<string, unknown>;
  admin_summary: {
    total: number;
    active: number;
    inactive: number;
    admins: User[];
  };
}

export interface Notification {
  id: number;
  title: string;
  message: string;
  kind: string;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

export interface Requisite {
  id: number;
  trader_id: number;
  name: string;
  total_amount: string;
  target_rate: string;
  comment: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Zaliv {
  id: number;
  amount: string;
  rate: string;
  profit_percent: string;
  receipt_path: string;
  created_at: string;
}

export interface FakeCheck {
  id: number;
  requisite_id: number;
  amount_rub: string;
  rate: string;
  amount_usdt: string;
  comment: string | null;
  file_path: string | null;
  operation_date: string;
  created_by_id: number;
  created_by_name: string | null;
  created_at: string;
}

export interface RequisiteDetail extends Requisite {
  zalivs: Zaliv[];
  zaliv_total: string;
  remaining: string;
  avg_rate: string | null;
  current_profit: string;
  trader_name?: string;
  fake_checks?: FakeCheck[];
  gross_profit?: string;
  fake_check_loss?: string;
  doliv_loss?: string;
  net_profit?: string;
}

export interface DolivRequest {
  id: number;
  requisite_id: number;
  required_amount: string;
  status: string;
  sent_at: string;
  assigned_dolivshchik_id: number | null;
  assigned_dolivshchik_name?: string | null;
  requisite_name?: string;
  target_rate?: string;
  trader_name?: string;
  zaliv_total?: string;
}

export interface AdminDoliv {
  id: number;
  request_id: number;
  requisite_id: number;
  requisite_name: string;
  trader_name: string;
  dolivshchik_name: string;
  amount: string;
  rate: string;
  receipt_path: string;
  status: string;
  completed_at: string;
}

export interface Receipt {
  id: number;
  type: 'zaliv' | 'doliv';
  requisite_id: number;
  requisite_name: string;
  uploader_name: string;
  amount: string;
  rate: string;
  receipt_path: string;
  created_at: string;
}

export interface DealResult {
  total_turnover: string;
  avg_rate: string;
  doliv_amount: string;
  doliv_rate: string;
  zaliv_profit: string;
  doliv_profit_loss: string;
  final_profit: string;
  merged_receipt_path: string | null;
  calculated_at: string;
}

export interface DashboardStats {
  total_turnover: string;
  total_turnover_usdt: string;
  total_profit: string;
  doliv_loss: string;
  fake_check_count?: number;
  fake_check_loss_usdt?: string;
  active_requisites: number;
  awaiting_doliv: number;
  closed_requisites: number;
  dolivs_count: number;
  profit_by_day: { day: string; profit: number; doliv_loss?: number; fake_check_loss?: number; net_profit?: number }[];
  profit_distribution: { name: string; value: number; amount: string }[];
  operations_today: {
    new_requisites: number;
    zalivs: number;
    dolivs: number;
    closed_requisites: number;
  };
}

export interface FakeCheckAuditLog {
  id: number;
  action: string;
  requisite_id: number;
  fake_check_id: number | null;
  amount_rub: string | null;
  rate: string | null;
  amount_usdt: string | null;
  comment: string | null;
  file_path: string | null;
  user_id: number;
  user_name: string | null;
  created_at: string;
}

export interface AnalyticsChartPoint {
  label: string;
  profit: number;
  doliv_loss: number;
  fake_check_loss: number;
  net_profit: number;
}

export interface AnalyticsStats {
  total_profit: string | number;
  doliv_loss: string | number;
  fake_check_count: number;
  fake_check_loss_usdt: string | number;
  chart: AnalyticsChartPoint[];
  traders: { id: number; name: string }[];
  requisites: { id: number; name: string }[];
}

export interface FakeCheckTopEntry {
  requisite_id?: number;
  trader_id?: number;
  name: string;
  loss_usdt: string | number;
  count: number;
}

export interface ActivityEvent {
  id: string;
  type: 'requisite' | 'zaliv' | 'doliv';
  text: string;
  created_at: string;
  requisite_id: number;
}

export interface EmployeeStats {
  id: number;
  full_name: string;
  login: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  turnover: string;
  turnover_usdt: string;
  profit: string;
  transactions: number;
  efficiency: string;
}

export interface SalaryRow {
  user_id: number;
  login: string;
  full_name: string;
  role: UserRole;
  method: string;
  turnover: string;
  turnover_usdt: string;
  profit: string;
  salary: string;
}

export interface StatementRow {
  item: string;
  amount: string;
  kind: 'income' | 'expense' | 'total';
}

export interface StatementsResponse {
  cards: { label: string; value: string }[];
  items: StatementRow[];
}

export interface RolePermissions {
  role: UserRole;
  permissions: Record<string, string[]>;
}

export interface AppSettings {
  currency: string;
  timezone: string;
  default_profit_percent: string;
  trader_salary_percent: string;
  doliv_salary_percent: string;
  date_format: string;
  receipt_formats: string[];
  max_upload_mb: number;
}

async function downloadBlob(path: string, allowRefresh = true): Promise<Blob> {
  const res = await fetch(`${API_URL}${path}`, { credentials: 'include' });
  if (res.status === 401 && allowRefresh) {
    try {
      await request<{ access_token: string }>('/auth/refresh', { method: 'POST' }, false);
      return downloadBlob(path, false);
    } catch {
      onUnauthorized?.();
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err?.detail;
    const message = typeof detail === 'string' ? detail : `Download failed: ${res.status}`;
    throw new ApiError(message, res.status);
  }
  return res.blob();
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function request<T>(path: string, options: RequestInit = {}, allowRefresh = true): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: 'include' });
  } catch {
    throw new NetworkError('Сервер недоступен. Проверьте подключение к интернету или обратитесь к администратору.');
  }
  if (res.status === 401 && allowRefresh && path !== '/auth/login' && path !== '/auth/refresh') {
    try {
      await request<{ access_token: string }>('/auth/refresh', { method: 'POST' }, false);
      return request<T>(path, options, false);
    } catch {
      onUnauthorized?.();
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({
      detail: res.status === 405 ? 'Ошибка API. Обновите страницу (Ctrl+Shift+R) и попробуйте снова.' : res.statusText,
    }));
    const detail = err?.detail;
    let message: string;
    if (typeof detail === 'string') {
      message = detail;
    } else if (Array.isArray(detail)) {
      message = detail.map((d) => (typeof d === 'object' && d !== null ? (d as { msg?: string }).msg ?? JSON.stringify(d) : String(d))).join('; ');
    } else if (detail) {
      message = JSON.stringify(detail);
    } else {
      message = 'Request failed';
    }
    if (res.status === 401 && path !== '/auth/login') {
      onUnauthorized?.();
    }
    throw new ApiError(message, res.status);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type');
  if (ct?.includes('application/json')) return res.json();
  return res as unknown as T;
}

export const api = {
  login: (login: string, password: string) =>
    request<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login, password }),
    }),

  me: () => request<User>('/auth/me'),

  refresh: () => request<{ access_token: string }>('/auth/refresh', { method: 'POST' }),

  logout: () => request<{ message: string }>('/auth/logout', { method: 'POST' }),

  // Notifications
  notifications: (params?: { unread_only?: boolean; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.unread_only) q.set('unread_only', 'true');
    if (params?.limit) q.set('limit', String(params.limit));
    return request<Notification[]>(`/notifications${q.size ? `?${q}` : ''}`);
  },
  unreadNotificationsCount: () => request<{ count: number }>('/notifications/unread-count'),
  markNotificationRead: (id: number) =>
    request<Notification>(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () =>
    request<{ updated: number }>('/notifications/read-all', { method: 'POST' }),

  // Trader
  listRequisites: (status?: string) => {
    const q = status ? `?status=${status}` : '';
    return request<Requisite[]>(`/trader/requisites${q}`);
  },
  archiveRequisite: (id: number) =>
    request<{ message: string }>(`/trader/requisites/${id}/archive`, { method: 'POST' }),
  deactivateRequisite: (id: number) =>
    request<{ message: string }>(`/trader/requisites/${id}/deactivate`, { method: 'POST' }),
  createRequisite: (data: { name: string; total_amount: number; target_rate: number; comment?: string }) =>
    request<Requisite>('/trader/requisites', { method: 'POST', body: JSON.stringify(data) }),
  getRequisite: (id: number) => request<RequisiteDetail>(`/trader/requisites/${id}`),
  addZaliv: (id: number, form: FormData) =>
    request<Zaliv>(`/trader/requisites/${id}/zalivs`, { method: 'POST', body: form }),
  sendToDoliv: (id: number) =>
    request<{ message: string; request_id: number; required_amount: string }>(`/trader/requisites/${id}/send-to-doliv`, { method: 'POST' }),
  traderDolivRequests: () => request<DolivRequest[]>('/trader/doliv-requests'),
  traderReceipts: () => request<Receipt[]>('/trader/receipts'),
  traderDealResult: (id: number) => request<DealResult | null>(`/trader/requisites/${id}/deal-result`),
  traderStats: () => request<Record<string, unknown>>('/trader/stats'),
  traderSettings: () => request<{ profit_percent: string; currency: string }>('/trader/settings'),
  downloadTraderReceipt: (type: 'zaliv' | 'doliv', id: number) =>
    downloadBlob(`/trader/receipts/${type}/${id}/download`),
  downloadTraderPdf: (requisiteId: number) =>
    downloadBlob(`/trader/requisites/${requisiteId}/receipts.pdf`),

  // Doliv
  listDolivRequests: (status?: string) =>
    request<DolivRequest[]>(`/doliv/requests${status ? `?status=${status}` : ''}`),
  takeRequest: (id: number) =>
    request<{ message: string }>(`/doliv/requests/${id}/take`, { method: 'POST' }),
  completeDoliv: (id: number, form: FormData) =>
    request<unknown>(`/doliv/requests/${id}/complete`, { method: 'POST', body: form }),
  dolivStats: () => request<DolivshchikStats>('/doliv/stats'),
  dolivSettings: () => request<{ salary_per_doliv_usdt: string; currency: string }>('/doliv/settings'),
  dolivHistory: () => request<unknown[]>('/doliv/history'),
  dolivReceipts: () => request<Receipt[]>('/doliv/receipts'),
  downloadDolivReceipt: (id: number) =>
    downloadBlob(`/doliv/receipts/${id}/download`),

  // Admin
  adminRequisites: (params?: { status?: string; trader_id?: number; search?: string; date_from?: string; date_to?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set('status', params.status);
    if (params?.trader_id) q.set('trader_id', String(params.trader_id));
    if (params?.search) q.set('search', params.search);
    if (params?.date_from) q.set('date_from', params.date_from);
    if (params?.date_to) q.set('date_to', params.date_to);
    return request<Requisite[]>(`/admin/requisites?${q}`);
  },
  adminRequisite: (id: number) => request<RequisiteDetail>(`/admin/requisites/${id}`),
  adminDeactivateRequisite: (id: number) =>
    request<{ message: string }>(`/admin/requisites/${id}/deactivate`, { method: 'POST' }),
  adminUsers: () => request<User[]>('/admin/users'),
  createUser: (data: { login: string; password: string; full_name: string; role: UserRole; profit_percent?: string; doliv_salary_usdt?: string }) =>
    request<User>('/admin/users', { method: 'POST', body: JSON.stringify(data) }),
  updateUser: (id: number, data: Partial<{ full_name: string; password: string; role: UserRole; is_active: boolean; profit_percent: string; doliv_salary_usdt: string }>) =>
    request<User>(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  adminDolivRequests: (status?: string) =>
    request<DolivRequest[]>(`/admin/doliv-requests${status ? `?status=${status}` : ''}`),
  assignAdminDolivRequest: (id: number, dolivshchikId: number) =>
    request<DolivRequest>(`/admin/doliv-requests/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ dolivshchik_id: dolivshchikId }),
    }),
  cancelAdminDolivRequest: (id: number) =>
    request<DolivRequest>(`/admin/doliv-requests/${id}/cancel`, { method: 'POST' }),
  statsOverview: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<Record<string, unknown>>(`/admin/stats/overview${q.size ? `?${q}` : ''}`);
  },
  statsDashboard: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<DashboardStats>(`/admin/stats/dashboard${q.size ? `?${q}` : ''}`);
  },
  statsAnalytics: (params?: {
    start?: string;
    end?: string;
    trader_id?: number;
    requisite_id?: number;
    period?: 'day' | 'week' | 'month';
  }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    if (params?.trader_id) q.set('trader_id', String(params.trader_id));
    if (params?.requisite_id) q.set('requisite_id', String(params.requisite_id));
    if (params?.period) q.set('period', params.period);
    return request<AnalyticsStats>(`/admin/stats/analytics${q.size ? `?${q}` : ''}`);
  },
  activity: () => request<ActivityEvent[]>('/admin/activity'),
  adminDealResult: (id: number) => request<DealResult | null>(`/admin/requisites/${id}/deal-result`),
  statsTraders: () => request<unknown[]>('/admin/stats/traders'),
  statsDolivshchiks: () => request<unknown[]>('/admin/stats/dolivshchiks'),
  adminDolivs: () => request<AdminDoliv[]>('/admin/dolivs'),
  adminReceipts: () => request<Receipt[]>('/admin/receipts'),
  adminEmployees: () => request<EmployeeStats[]>('/admin/employees'),
  adminSalaries: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<SalaryRow[]>(`/admin/salaries${q.size ? `?${q}` : ''}`);
  },
  adminStatements: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<StatementsResponse>(`/admin/statements${q.size ? `?${q}` : ''}`);
  },
  adminRoles: () => request<RolePermissions[]>('/admin/roles'),
  updateAdminRolePermissions: (role: UserRole, permissions: Record<string, string[]>) =>
    request<{ message: string }>(`/admin/roles/${role}`, {
      method: 'PATCH',
      body: JSON.stringify({ permissions }),
    }),
  adminSettings: () => request<AppSettings>('/admin/settings'),
  updateAdminSettings: (data: Partial<AppSettings>) =>
    request<AppSettings>('/admin/settings', { method: 'PATCH', body: JSON.stringify(data) }),
  exportExcel: (scope: StatsScope = 'admin') =>
    downloadBlob(`/${scope}/export/stats.xlsx`).catch((e) => {
      if (e instanceof Error && e.message.startsWith('Download failed')) {
        throw new Error(`Export failed: ${e.message.split(': ')[1]}`);
      }
      throw e;
    }),

  // Owner
  ownerDashboard: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<OwnerDashboard>(`/owner/dashboard${q.size ? `?${q}` : ''}`);
  },
  ownerAdmins: () => request<User[]>('/owner/admins'),
  createAdmin: (data: { login: string; password: string; full_name: string }) =>
    request<User>('/owner/admins', { method: 'POST', body: JSON.stringify(data) }),
  updateAdmin: (id: number, data: Partial<{ full_name: string; password: string; is_active: boolean }>) =>
    request<User>(`/owner/admins/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  ownerStatsOverview: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<Record<string, unknown>>(`/owner/stats/overview${q.size ? `?${q}` : ''}`);
  },
  ownerStatsDashboard: (params?: { start?: string; end?: string }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    return request<DashboardStats>(`/owner/stats/dashboard${q.size ? `?${q}` : ''}`);
  },
  ownerStatsAnalytics: (params?: {
    start?: string;
    end?: string;
    trader_id?: number;
    requisite_id?: number;
    period?: 'day' | 'week' | 'month';
  }) => {
    const q = new URLSearchParams();
    if (params?.start) q.set('start', params.start);
    if (params?.end) q.set('end', params.end);
    if (params?.trader_id) q.set('trader_id', String(params.trader_id));
    if (params?.requisite_id) q.set('requisite_id', String(params.requisite_id));
    if (params?.period) q.set('period', params.period);
    return request<AnalyticsStats>(`/owner/stats/analytics${q.size ? `?${q}` : ''}`);
  },
  ownerStatsTraders: () => request<unknown[]>('/owner/stats/traders'),
  ownerStatsDolivshchiks: () => request<unknown[]>('/owner/stats/dolivshchiks'),
  ownerEmployees: () => request<EmployeeStats[]>('/owner/employees'),
  downloadPdf: (requisiteId: number) =>
    downloadBlob(`/admin/requisites/${requisiteId}/receipts.pdf`),
  downloadReceipt: (type: 'zaliv' | 'doliv', id: number) =>
    downloadBlob(`/admin/receipts/${type}/${id}/download`),

  addFakeCheck: (requisiteId: number, form: FormData) =>
    request<FakeCheck>(`/admin/requisites/${requisiteId}/fake-checks`, { method: 'POST', body: form }),
  updateFakeCheck: (id: number, form: FormData) =>
    request<FakeCheck>(`/admin/fake-checks/${id}`, { method: 'PUT', body: form }),
  deleteFakeCheck: (id: number) =>
    request<void>(`/admin/fake-checks/${id}`, { method: 'DELETE' }),
  fakeCheckHistory: (requisiteId: number) =>
    request<FakeCheckAuditLog[]>(`/admin/requisites/${requisiteId}/fake-check-history`),
  downloadFakeCheckFile: (id: number) =>
    downloadBlob(`/admin/fake-checks/${id}/file`),
};

export function getStatsApi(scope: StatsScope) {
  if (scope === 'owner') {
    return {
      statsOverview: api.ownerStatsOverview,
      statsDashboard: api.ownerStatsDashboard,
      statsAnalytics: api.ownerStatsAnalytics,
      statsTraders: api.ownerStatsTraders,
      statsDolivshchiks: api.ownerStatsDolivshchiks,
      employees: api.ownerEmployees,
      exportExcel: () => api.exportExcel('owner'),
    };
  }
  return {
    statsOverview: api.statsOverview,
    statsDashboard: api.statsDashboard,
    statsAnalytics: api.statsAnalytics,
    statsTraders: api.statsTraders,
    statsDolivshchiks: api.statsDolivshchiks,
    employees: api.adminEmployees,
    exportExcel: () => api.exportExcel('admin'),
  };
}

export async function meWithRetry(): Promise<User> {
  try {
    return await api.me();
  } catch (err) {
    if (err instanceof NetworkError) {
      await new Promise((r) => setTimeout(r, 2000));
      return api.me();
    }
    throw err;
  }
}

export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    active: 'Активен',
    in_work: 'В работе',
    awaiting_doliv: 'Ожидает долив',
    doliv_in_progress: 'Доливается',
    closed: 'Закрыт',
    archive: 'Архив',
    pending: 'Ожидает',
    in_progress: 'В работе',
    completed: 'Завершён',
    cancelled: 'Отменён',
  };
  return labels[status] || status;
}

export function formatMoney(val: string | number): string {
  const n = typeof val === 'string' ? parseFloat(val) : val;
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(n);
}

export function formatUsdt(val: string | number): string {
  const n = typeof val === 'string' ? parseFloat(val) : val;
  const formatted = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number.isFinite(n) ? n : 0);
  return `${formatted} USDT`;
}
