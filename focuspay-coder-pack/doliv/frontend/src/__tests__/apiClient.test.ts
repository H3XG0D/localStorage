/**
 * Tests for api/client.ts: error parsing, blob download guards, formatMoney.
 */
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import { api, formatMoney, statusLabel } from '../api/client';

// ──────────────────────────────────────────────────────────────────────────────
// formatMoney
// ──────────────────────────────────────────────────────────────────────────────

describe('formatMoney', () => {
  it('formats a numeric string', () => {
    const result = formatMoney('5000');
    expect(result).toContain('5');
    expect(result).toContain('000');
  });

  it('formats a number directly', () => {
    const result = formatMoney(1234.56);
    expect(result).toContain('1');
  });

  it('handles zero', () => {
    const result = formatMoney('0');
    expect(result).toBeTruthy();
  });
});

describe('statusLabel', () => {
  it('localizes cancelled status', () => {
    expect(statusLabel('cancelled')).toBe('Отменён');
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Error parsing
// ──────────────────────────────────────────────────────────────────────────────

describe('request() error parsing', () => {
  it('throws string detail as-is', async () => {
    server.use(
      http.get('http://localhost:8000/trader/requisites', () =>
        HttpResponse.json({ detail: 'Requisite not found' }, { status: 404 })
      )
    );
    await expect(api.listRequisites()).rejects.toThrow('Requisite not found');
  });

  it('converts array detail to readable message', async () => {
    server.use(
      http.get('http://localhost:8000/trader/requisites', () =>
        HttpResponse.json(
          { detail: [{ msg: 'field required', loc: ['body', 'name'] }] },
          { status: 422 }
        )
      )
    );
    await expect(api.listRequisites()).rejects.toThrow('field required');
  });

  it('falls back to "Request failed" for empty detail', async () => {
    server.use(
      http.get('http://localhost:8000/trader/requisites', () =>
        HttpResponse.json({}, { status: 500 })
      )
    );
    await expect(api.listRequisites()).rejects.toThrow('Request failed');
  });

  it('handles object detail without crashing', async () => {
    server.use(
      http.get('http://localhost:8000/trader/requisites', () =>
        HttpResponse.json({ detail: { code: 'ERR', message: 'bad' } }, { status: 400 })
      )
    );
    await expect(api.listRequisites()).rejects.toThrow();
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Blob download – r.ok guard
// ──────────────────────────────────────────────────────────────────────────────

describe('blob download r.ok guard', () => {
  it('throws on 404 instead of returning a corrupt blob', async () => {
    server.use(
      http.get('http://localhost:8000/trader/receipts/zaliv/999/download', () =>
        HttpResponse.json({ detail: 'Not found' }, { status: 404 })
      )
    );
    await expect(api.downloadTraderReceipt('zaliv', 999)).rejects.toThrow('Not found');
  });

  it('throws on 401 instead of returning auth error as blob', async () => {
    server.use(
      http.get('http://localhost:8000/doliv/receipts/999/download', () =>
        HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      ),
      http.post('http://localhost:8000/auth/refresh', () =>
        HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      ),
    );
    await expect(api.downloadDolivReceipt(999)).rejects.toThrow('Unauthorized');
  });

  it('throws on admin export 401', async () => {
    server.use(
      http.get('http://localhost:8000/admin/export/stats.xlsx', () =>
        HttpResponse.json({ detail: 'Not authenticated' }, { status: 403 })
      )
    );
    await expect(api.exportExcel()).rejects.toThrow();
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Successful API calls
// ──────────────────────────────────────────────────────────────────────────────

describe('api happy paths', () => {
  it('login returns access_token', async () => {
    const result = await api.login('trader1', 'pass');
    expect(result.access_token).toBe('mock-token');
  });

  it('me returns user', async () => {
    const user = await api.me();
    expect(user.login).toBe('trader1');
    expect(user.role).toBe('trader');
  });

  it('listRequisites returns array', async () => {
    const list = await api.listRequisites();
    expect(Array.isArray(list)).toBe(true);
    expect(list[0].name).toBe('Test Card');
  });

  it('traderDolivRequests returns array', async () => {
    const list = await api.traderDolivRequests();
    expect(Array.isArray(list)).toBe(true);
    expect(list[0].required_amount).toBe('25000');
  });
});
