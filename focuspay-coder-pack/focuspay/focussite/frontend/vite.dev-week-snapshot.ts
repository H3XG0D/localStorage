// @ts-nocheck — Vite Node plugin; @types/node is not a frontend dependency.
import fs from "node:fs";
import path from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const SNAPSHOT_FILE = ".dev-week-snapshot.json";

function isLoopback(req: IncomingMessage): boolean {
  const ip = req.socket.remoteAddress || "";
  return ip === "127.0.0.1" || ip === "::1" || ip === "::ffff:127.0.0.1";
}

let cachedSnap: { mtimeMs: number; data: Record<string, unknown> } | null = null;

function loadSnapshot(): Record<string, unknown> | null {
  const file = path.join(process.cwd(), SNAPSHOT_FILE);
  try {
    const st = fs.statSync(file);
    if (cachedSnap && cachedSnap.mtimeMs === st.mtimeMs) return cachedSnap.data;
    const data = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
    cachedSnap = { mtimeMs: st.mtimeMs, data };
    return data;
  } catch {
    return null;
  }
}

function parseUrl(raw: string): { pathname: string; query: URLSearchParams } {
  const u = new URL(raw, "http://127.0.0.1");
  const pathname = (u.pathname.replace(/\/$/, "") || "/") as string;
  return { pathname, query: u.searchParams };
}

function adminBlob(snap: Record<string, unknown>): Record<string, unknown> {
  return (snap.admin as Record<string, unknown> | undefined) || {};
}

function num(v: string | null, fallback: number): number {
  if (v == null || v === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function hay(parts: unknown[]): string {
  return parts
    .map((p) => String(p ?? "").toLowerCase())
    .join(" ");
}

function filterOrders(admin: Record<string, unknown>, query: URLSearchParams) {
  const pack = (admin.orders as { orders?: Record<string, unknown>[]; partner_options?: unknown[] }) || {};
  let rows = Array.isArray(pack.orders) ? pack.orders.slice() : [];
  const status = (query.get("status") || "").trim().toUpperCase();
  const direction = (query.get("direction") || "").trim().toLowerCase();
  const crypto = (query.get("crypto") || "").trim().toLowerCase();
  const origin = (query.get("origin") || "").trim().toLowerCase();
  const search = (query.get("search") || "").trim().toLowerCase();
  const searchField = (query.get("search_field") || "").trim().toLowerCase();
  const partnerId = query.get("partner_id");
  const dateFrom = query.get("date_from") || "";
  const dateTo = query.get("date_to") || "";
  const userId = query.get("user_id");

  if (status && status !== "ALL") rows = rows.filter((r) => String(r.status || "").toUpperCase() === status);
  if (direction && direction !== "all") rows = rows.filter((r) => String(r.direction || "").toLowerCase() === direction);
  if (crypto && crypto !== "all") rows = rows.filter((r) => String(r.crypto || "").toLowerCase().includes(crypto));
  if (origin === "manual" || origin === "auto") rows = rows.filter((r) => String(r.origin || "") === origin);
  if (partnerId && Number(partnerId) > 0) {
    const pid = Number(partnerId);
    rows = rows.filter((r) => Array.isArray(r.partner_campaign_ids) && r.partner_campaign_ids.includes(pid));
  }
  if (userId) rows = rows.filter((r) => String(r.user_id) === String(userId));
  if (dateFrom && dateTo) {
    rows = rows.filter((r) => {
      const day = String(r.created_at || "").slice(0, 10);
      return day >= dateFrom && day <= dateTo;
    });
  }
  if (search) {
    rows = rows.filter((r) => {
      if (searchField === "referrer") {
        return hay([r.referrer_user_id, r.referrer_username, r.referrer_first_name]).includes(search);
      }
      return hay([
        r.order_id,
        r.merchant_order_id,
        r.requisites,
        r.user_id,
        r.buyer_username,
        r.buyer_first_name,
      ]).includes(search);
    });
  }

  const limit = Math.min(200, Math.max(1, num(query.get("limit"), 50)));
  const offset = Math.max(0, num(query.get("offset"), 0));
  return {
    orders: rows.slice(offset, offset + limit),
    total: rows.length,
    limit,
    offset,
    partner_options: pack.partner_options || [],
  };
}

function orderHistoryCounts(admin: Record<string, unknown>, query: URLSearchParams) {
  const statuses = ["AWAITING_CHECK", "PENDING", "CREATED", "DISPUTE", "PAID", "CANCELED", "EXPIRED"];
  const base = new URLSearchParams(query);
  base.delete("status");
  base.set("limit", "1");
  base.set("offset", "0");
  const out: Record<string, number> = { all: filterOrders(admin, base).total };
  for (const status of statuses) {
    const q = new URLSearchParams(base);
    q.set("status", status);
    out[status] = filterOrders(admin, q).total;
  }
  return out;
}

function filterUsers(admin: Record<string, unknown>, query: URLSearchParams) {
  let rows = Array.isArray(admin.users) ? (admin.users as Record<string, unknown>[]).slice() : [];
  const search = (query.get("search") || "").trim().toLowerCase();
  const channel = (query.get("channel") || "").trim();
  if (search) {
    rows = rows.filter((r) => hay([r.user_id, r.username, r.first_name]).includes(search));
  }
  if (channel && channel !== "all") {
    rows = rows.filter((r) => String(r.channel || "") === channel);
  }
  const sortBy = query.get("sort_by") || "last_order_at";
  const sortDir = (query.get("sort_dir") || "desc").toLowerCase() === "asc" ? 1 : -1;
  rows.sort((a, b) => {
    const av = a[sortBy];
    const bv = b[sortBy];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir;
    return String(av).localeCompare(String(bv), "ru") * sortDir;
  });
  const limit = Math.min(200, Math.max(1, num(query.get("limit"), 50)));
  const offset = Math.max(0, num(query.get("offset"), 0));
  return {
    users: rows.slice(offset, offset + limit),
    total: rows.length,
    limit,
    offset,
  };
}

function ymd(v: unknown): string {
  return String(v ?? "").slice(0, 10);
}

function inRange(day: string, from: string, to: string): boolean {
  if (!from || !to) return true;
  return day >= from && day <= to;
}

function eachDay(from: string, to: string): string[] {
  const out: string[] = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to) || from > to) return out;
  let cur = from;
  while (cur <= to) {
    out.push(cur);
    const [y, m, d] = cur.split("-").map(Number);
    cur = new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
  }
  return out;
}

function addDays(day: string, delta: number): string {
  const [y, m, d] = day.split("-").map(Number);
  if (!y || !m || !d) return day;
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10);
}

function ordersOf(admin: Record<string, unknown>): Record<string, unknown>[] {
  const pack = (admin.orders as { orders?: Record<string, unknown>[] }) || {};
  return Array.isArray(pack.orders) ? pack.orders : [];
}

function rangeFromQuery(query: URLSearchParams, fallbackFrom: string, fallbackTo: string): { from: string; to: string } {
  const from = query.get("date_from") || fallbackFrom;
  const to = query.get("date_to") || fallbackTo;
  if (/^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && from <= to) return { from, to };
  return { from: fallbackFrom, to: fallbackTo };
}

function snapshotRange(snap: Record<string, unknown>, admin: Record<string, unknown>): { from: string; to: string } {
  const orders = ordersOf(admin);
  const days = orders.map((o) => ymd(o.created_at)).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
  const fromDump = String(snap.dump_week_from || "").slice(0, 10);
  const toDump = String(snap.dump_week_to || "").slice(0, 10);
  return {
    from: /^\d{4}-\d{2}-\d{2}$/.test(fromDump) ? fromDump : days[0] || "2026-08-03",
    to: /^\d{4}-\d{2}-\d{2}$/.test(toDump) ? toDump : days[days.length - 1] || "2026-08-10",
  };
}

function n(v: unknown): number {
  const x = Number(v ?? 0);
  return Number.isFinite(x) ? x : 0;
}

function paidStatus(status: unknown): boolean {
  const s = String(status || "").toUpperCase();
  return s === "PAID" || s === "COMPLETED";
}

function buildStats(admin: Record<string, unknown>, from: string, to: string) {
  const inPeriod = ordersOf(admin).filter((o) => inRange(ymd(o.created_at), from, to));
  const paid = inPeriod.filter((o) => paidStatus(o.status));
  const byBuy: Record<string, { crypto: string; count: number; crypto_volume: number; fiat_volume: number; rateSum: number }> = {};
  const bySell: typeof byBuy = {};
  const dayMap: Record<string, { date: string; buy_fiat: number; sell_fiat: number; count: number; profit: number }> = {};
  for (const day of eachDay(from, to)) dayMap[day] = { date: day, buy_fiat: 0, sell_fiat: 0, count: 0, profit: 0 };
  let buyFiat = 0;
  let sellFiat = 0;
  let profit = 0;
  for (const o of paid) {
    const crypto = String(o.crypto || "usdt").toLowerCase();
    const dir = String(o.direction || "").toLowerCase();
    const fiat = n(o.fiat_amount);
    const cvol = n(o.crypto_amount);
    const bag = dir === "sell" ? bySell : byBuy;
    if (!bag[crypto]) bag[crypto] = { crypto, count: 0, crypto_volume: 0, fiat_volume: 0, rateSum: 0 };
    bag[crypto].count += 1;
    bag[crypto].crypto_volume += cvol;
    bag[crypto].fiat_volume += fiat;
    bag[crypto].rateSum += n(o.rate);
    if (dir === "sell") sellFiat += fiat;
    else buyFiat += fiat;
    profit += n(o.service_profit_rub);
    const day = ymd(o.created_at);
    if (!dayMap[day]) dayMap[day] = { date: day, buy_fiat: 0, sell_fiat: 0, count: 0, profit: 0 };
    dayMap[day].count += 1;
    dayMap[day].profit += n(o.service_profit_rub);
    if (dir === "sell") dayMap[day].sell_fiat += fiat;
    else dayMap[day].buy_fiat += fiat;
  }
  const finalise = (bag: typeof byBuy) =>
    Object.values(bag).map((r) => ({
      crypto: r.crypto,
      count: r.count,
      crypto_volume: Math.round(r.crypto_volume * 100) / 100,
      fiat_volume: Math.round(r.fiat_volume * 100) / 100,
      avg_rate: r.count ? Math.round((r.rateSum / r.count) * 100) / 100 : 0,
    }));
  const chart = Object.values(dayMap)
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((d) => ({
      ...d,
      buy_fiat: Math.round(d.buy_fiat * 100) / 100,
      sell_fiat: Math.round(d.sell_fiat * 100) / 100,
      profit: Math.round(d.profit * 100) / 100,
      profit_net: Math.round(d.profit * 100) / 100,
      profit_net_total: Math.round(d.profit * 100) / 100,
      cost_overhead: 0,
      cost_total: 0,
    }));
  return {
    period: { from, to },
    can_view_finance: true,
    source: "snapshot_approx",
    summary: {
      total_orders_paid: paid.length,
      total_orders_period: inPeriod.length,
      active_orders: inPeriod.filter((o) => ["CREATED", "AWAITING_CHECK", "PENDING"].includes(String(o.status || "").toUpperCase())).length,
      total_fiat_buy: Math.round(buyFiat * 100) / 100,
      total_fiat_sell: Math.round(sellFiat * 100) / 100,
      estimated_profit: Math.round(profit * 100) / 100,
    },
    by_crypto_buy: finalise(byBuy),
    by_crypto_sell: finalise(bySell),
    chart,
  };
}

function buildFinance(admin: Record<string, unknown>, from: string, to: string) {
  const stats = buildStats(admin, from, to);
  const paid = ordersOf(admin).filter((o) => inRange(ymd(o.created_at), from, to) && paidStatus(o.status));
  const byType: Record<string, { type: string; orders: number; fiat_volume: number; net_profit: number }> = {
    auto_buy: { type: "auto_buy", orders: 0, fiat_volume: 0, net_profit: 0 },
    manual_buy: { type: "manual_buy", orders: 0, fiat_volume: 0, net_profit: 0 },
    sell: { type: "sell", orders: 0, fiat_volume: 0, net_profit: 0 },
  };
  for (const o of paid) {
    const dir = String(o.direction || "").toLowerCase();
    const origin = String(o.origin || "").toLowerCase();
    const key = dir === "sell" ? "sell" : origin === "manual" ? "manual_buy" : "auto_buy";
    byType[key].orders += 1;
    byType[key].fiat_volume += n(o.fiat_amount);
    byType[key].net_profit += n(o.service_profit_rub);
  }
  const profit = n(stats.summary.estimated_profit);
  const volume = n(stats.summary.total_fiat_buy) + n(stats.summary.total_fiat_sell);
  const by_type = Object.values(byType).map((row) => ({
    ...row,
    fiat_volume: Math.round(row.fiat_volume * 100) / 100,
    net_profit: Math.round(row.net_profit * 100) / 100,
    spread_revenue: Math.round(row.net_profit * 100) / 100,
    card_fee_cost: 0,
    margin_pct: row.fiat_volume ? Math.round((row.net_profit / row.fiat_volume) * 1000) / 10 : 0,
  }));
  const waterfall = [
    { key: "fiat_volume", label: "Оборот", amount: volume, kind: "info" },
    { key: "service_profit", label: "Маржа сделок", amount: profit, kind: "income" },
    { key: "owner_residual", label: "Результат владельца", amount: profit, kind: "total" },
  ];
  const kpi = [
    { label: "Оборот", value: volume, sub: "снимок", deltaPct: null },
    { label: "Сделки", value: paid.length, sub: "оплаченные", deltaPct: null },
    { label: "Маржа", value: profit, sub: "service profit", deltaPct: null },
    { label: "Чистая", value: profit, sub: "без затрат в дампе", deltaPct: null },
    { label: "После начислений", value: profit, sub: "снимок", deltaPct: null },
    { label: "Владелец", value: profit, sub: "снимок", deltaPct: null },
  ];
  return {
    period: { from, to },
    previous_period: { from, to },
    source: "snapshot_approx",
    kpi,
    income: {},
    expenses: { by_category: { mandatory: [], work: [], unexpected: [] }, totals: {}, list_period: { from, to } },
    salaries: {},
    pnl: {
      period: { from, to },
      by_type,
      waterfall,
      manual_expenses: { total: 0 },
      costs: { cashback: 0, referral: 0, partner: 0, review_bonus: 0, wallet_payout: 0, swap_commission: 0, usdt_issued_rub: 0, total: 0 },
      payroll: { operators_total: 0, admin_salary: 0, owner_residual: profit, total: 0 },
      total: {
        fiat_volume: volume,
        fiat_volume_with_external: volume,
        spread_revenue: profit,
        card_fee_cost: 0,
        net_profit: profit,
        profit_after_costs: profit,
        net_margin_pct: volume ? Math.round((profit / volume) * 1000) / 10 : 0,
        margin_after_costs_pct: volume ? Math.round((profit / volume) * 1000) / 10 : 0,
        owner_margin_pct: volume ? Math.round((profit / volume) * 1000) / 10 : 0,
      },
      external: {},
    },
    chart: stats.chart,
  };
}

function buildPromo(admin: Record<string, unknown>) {
  const partners = ((admin.referral_partners as { partners?: Record<string, unknown>[] })?.partners) || [];
  const stored = Array.isArray(admin.promo_campaigns) ? (admin.promo_campaigns as Record<string, unknown>[]) : [];
  const campaigns = (stored.length ? stored : partners).map((p) => {
    const profit = n(p.service_profit_net_rub ?? p.estimated_profit);
    const ad = n(p.ad_spend_rub);
    const roi = ad > 0 ? Math.round((profit / ad) * 1000) / 10 : null;
    return {
      id: p.id,
      code: p.code,
      name: p.name,
      bonus_percent: n(p.bonus_percent),
      partner_commission_percent: n(p.partner_commission_percent ?? p.effective_percent),
      ad_spend_rub: ad,
      is_active: p.is_active ?? p.status === "active",
      attracted_users: n(p.attracted_users),
      paid_orders_count: n(p.paid_orders_count),
      paid_fiat_sum: n(p.paid_fiat_sum),
      estimated_profit: profit,
      roi_percent: p.roi_percent ?? roi,
    };
  });
  return { can_view_finance: true, campaigns, source: "snapshot_approx" };
}

function buildCohorts(admin: Record<string, unknown>, from: string, to: string) {
  const users = Array.isArray(admin.users) ? (admin.users as Record<string, unknown>[]) : [];
  const inPeriod = ordersOf(admin).filter((o) => inRange(ymd(o.created_at), from, to));
  const perUser = new Map<string, number>();
  for (const o of inPeriod) {
    const uid = String(o.user_id ?? "");
    if (!uid) continue;
    perUser.set(uid, (perUser.get(uid) || 0) + 1);
  }
  const lifetime = (threshold: number) => users.filter((u) => n(u.total_fiat) >= threshold).length;
  const buckets = [50000, 100000, 200000].map((threshold) => ({
    threshold,
    label: `${Math.round(threshold / 1000)}к+`,
    count: lifetime(threshold),
  }));
  const newClients = users.filter((u) => inRange(ymd(u.first_seen_at), from, to)).length;
  const repeaters = [...perUser.values()].filter((c) => c >= 2).length;
  const frequent = [...perUser.values()].filter((c) => c >= 5).length;
  const chart = eachDay(from, to).map((date) => {
    const dayOrders = inPeriod.filter((o) => ymd(o.created_at) === date);
    const ids = new Set(dayOrders.map((o) => String(o.user_id ?? "")));
    return { date, new_clients: 0, repeaters: 0, frequent: ids.size, new_50k: 0, new_100k: 0, new_200k: 0 };
  });
  return {
    mode: "lifetime",
    mode_label: "Снимок: накопительно по клиентам недели",
    period: { from, to },
    thresholds: [50000, 100000, 200000],
    buckets,
    week_volume: buckets,
    week_ge_50k: buckets[0]?.count ?? 0,
    chart_kind: "new_crossers",
    chart,
    retention: {
      new_clients: { period: newClients, today: 0, week: newClients },
      repeaters: { period: repeaters, today: 0, week: repeaters },
      frequent: { total: users.filter((u) => n(u.total_orders) >= 5).length, period: frequent, week: frequent, max_avg_gap_days: 3 },
      chart: chart.map((row) => ({ date: row.date, new_clients: row.new_clients, repeaters: row.repeaters, frequent: row.frequent })),
    },
    source: "snapshot_approx",
  };
}

function uniqueMissRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const hourMs = 60 * 60 * 1000;
  const last = new Map<number, number>();
  const kept: Record<string, unknown>[] = [];
  const ordered = [...rows].sort((a, b) => asUtcMs(a.created_at) - asUtcMs(b.created_at));
  for (const row of ordered) {
    const uid = Number(row.user_id || 0);
    const ts = asUtcMs(row.created_at);
    if (!uid || !Number.isFinite(ts)) continue;
    const prev = last.get(uid);
    if (prev != null && ts - prev < hourMs) continue;
    kept.push(row);
    last.set(uid, ts);
  }
  return kept;
}

function asUtcMs(iso: unknown): number {
  const s = String(iso || "");
  if (!s) return NaN;
  const withZ = /(?:Z|[+-]\d{2}:?\d{2})$/.test(s) ? s : `${s}Z`;
  return Date.parse(withZ);
}

function mskHour(iso: unknown): number {
  const ts = asUtcMs(iso);
  if (!Number.isFinite(ts)) return 0;
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Moscow", hour: "2-digit", hourCycle: "h23" }).formatToParts(new Date(ts));
  return Number(parts.find((p) => p.type === "hour")?.value || 0);
}

function buildMisses(admin: Record<string, unknown>, from: string, to: string) {
  const pack = (admin.misses as { data_status?: string; reason?: string; rows?: Record<string, unknown>[]; definitions?: unknown }) || {};
  const raw = Array.isArray(pack.rows) ? pack.rows : [];
  const lookback = addDays(from, -1);
  const windowRows = raw.filter((r) => inRange(ymd(r.created_at), lookback, to));
  const unique = uniqueMissRows(windowRows).filter((r) => inRange(ymd(r.created_at), from, to));
  const available = pack.data_status === "available" || unique.length > 0 || raw.length > 0;
  const emptyHour = () => Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0, fiat_sum: null as number | null }));
  if (!available && pack.data_status !== "empty") {
    return {
      period: { from, to },
      timezone: "Europe/Moscow",
      data_status: "unavailable",
      reason: pack.reason || "table_missing",
      total: 0,
      fiat_sum: null,
      unique_rule: "one_client_per_hour",
      by_direction: [],
      by_reason: [],
      by_hour: emptyHour(),
      chart: eachDay(from, to).map((date) => ({ date, count: 0, fiat_sum: null })),
      definitions: pack.definitions || { miss: "Пропуски из no_shift_requisites_blocks" },
    };
  }
  const byDay: Record<string, { count: number; fiat: number }> = {};
  for (const day of eachDay(from, to)) byDay[day] = { count: 0, fiat: 0 };
  const byDir: Record<string, { count: number; fiat: number }> = {};
  const byReason: Record<string, number> = {};
  const byHour = Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0, fiat: 0 }));
  let fiatSum = 0;
  let fiatKnown = false;
  for (const r of unique) {
    const day = ymd(r.created_at);
    if (!byDay[day]) byDay[day] = { count: 0, fiat: 0 };
    byDay[day].count += 1;
    const dir = String(r.direction || "buy");
    if (!byDir[dir]) byDir[dir] = { count: 0, fiat: 0 };
    byDir[dir].count += 1;
    const reason = String(r.reason || "no_shift");
    byReason[reason] = (byReason[reason] || 0) + 1;
    const hour = Math.min(23, Math.max(0, mskHour(r.created_at)));
    byHour[hour].count += 1;
    if (r.fiat_amount != null) {
      fiatKnown = true;
      const f = n(r.fiat_amount);
      fiatSum += f;
      byDay[day].fiat += f;
      byDir[dir].fiat += f;
      byHour[hour].fiat += f;
    }
  }
  return {
    period: { from, to },
    timezone: "Europe/Moscow",
    data_status: unique.length ? "available" : "empty",
    reason: unique.length ? null : "no_rows",
    total: unique.length,
    fiat_sum: fiatKnown ? Math.round(fiatSum * 100) / 100 : null,
    unique_rule: "one_client_per_hour",
    by_direction: Object.entries(byDir).map(([direction, v]) => ({
      direction,
      count: v.count,
      fiat_sum: fiatKnown ? Math.round(v.fiat * 100) / 100 : null,
    })),
    by_reason: Object.entries(byReason).map(([reason, count]) => ({ reason, count })),
    by_hour: byHour.map((slot) => ({
      hour: slot.hour,
      count: slot.count,
      fiat_sum: fiatKnown ? Math.round(slot.fiat * 100) / 100 : null,
    })),
    chart: Object.keys(byDay)
      .sort()
      .map((date) => ({
        date,
        count: byDay[date].count,
        fiat_sum: fiatKnown ? Math.round(byDay[date].fiat * 100) / 100 : null,
      })),
    definitions: pack.definitions || {
      miss: "Пропуски из no_shift_requisites_blocks",
      unique: "Один клиент за скользящий час. Сумма — первая попытка.",
    },
  };
}

function paidOrders(admin: Record<string, unknown>): Record<string, unknown>[] {
  return ordersOf(admin).filter((r) => {
    const st = String(r.status || "").toUpperCase();
    return st === "PAID" || st === "COMPLETED";
  });
}

function buildOperators(snap: Record<string, unknown>, admin: Record<string, unknown>) {
  const { to } = snapshotRange(snap, admin);
  const map = new Map<number, Record<string, unknown>>();
  for (const o of ordersOf(admin)) {
    const id = Number(o.operator_id);
    if (!Number.isFinite(id) || id <= 0) continue;
    const rec = map.get(id) || {
      id,
      username: String(o.operator_name || `op${id}`),
      display_name: String(o.operator_name || `Оператор ${id}`),
      is_active: true,
      operator_roles: ["client"],
      operator_role: "client",
      on_shift: false,
      active_shifts: 0,
      orders_today: 0,
    };
    if (ymd(o.created_at) === to) rec.orders_today = Number(rec.orders_today || 0) + 1;
    map.set(id, rec);
  }
  const me = snap.operator_me as { team_on_shift?: Record<string, unknown>[]; operator?: Record<string, unknown> } | undefined;
  for (const t of me?.team_on_shift || []) {
    const id = Number(t.id ?? t.operator_id);
    if (!Number.isFinite(id) || id <= 0) continue;
    const rec = map.get(id) || {
      id,
      username: String(t.username || `op${id}`),
      display_name: String(t.display_name || t.username || `Оператор ${id}`),
      is_active: true,
      operator_roles: ["client"],
    };
    rec.on_shift = true;
    rec.active_shifts = 1;
    map.set(id, rec);
  }
  return { operators: [...map.values()], can_view_finance: true, shift_gate: { allow: true, missing_roles: [] }, source: "snapshot_approx" };
}

function buildOperatorStats(
  snap: Record<string, unknown>,
  admin: Record<string, unknown>,
  operatorId: number,
  query: URLSearchParams,
) {
  const fallback = snapshotRange(snap, admin);
  const { from, to } = rangeFromQuery(query, fallback.from, fallback.to);
  const days = eachDay(from, to);
  const rows = paidOrders(admin).filter((o) => Number(o.operator_id) === operatorId && inRange(ymd(o.created_at), from, to));
  const list = buildOperators(snap, admin).operators as Record<string, unknown>[];
  const op = list.find((r) => Number(r.id) === operatorId);
  if (!op && rows.length === 0) return null;
  const byDay = new Map<string, { orders: number; fiat: number }>();
  for (const o of rows) {
    const day = ymd(o.created_at);
    const rec = byDay.get(day) || { orders: 0, fiat: 0 };
    rec.orders += 1;
    rec.fiat += Number(o.fiat_amount || 0);
    byDay.set(day, rec);
  }
  const daily = days
    .filter((d) => byDay.has(d))
    .map((date) => {
      const rec = byDay.get(date)!;
      return { date, shifts_count: 0, hours: 0, shift_times: [], orders: rec.orders, fiat: Math.round(rec.fiat * 100) / 100 };
    });
  const daysWorked = daily.length;
  const fiat = daily.reduce((s, d) => s + d.fiat, 0);
  const orders = daily.reduce((s, d) => s + d.orders, 0);
  return {
    operator: op || { id: operatorId, username: `op${operatorId}`, display_name: `Оператор ${operatorId}`, is_active: true },
    date_from: from,
    date_to: to,
    can_view_finance: true,
    summary: {
      days_in_period: days.length || 1,
      days_worked: daysWorked,
      work_frequency_pct: Math.round((daysWorked / Math.max(1, days.length)) * 100),
      total_hours: 0,
      avg_hours_per_work_day: 0,
      shifts_count: 0,
      orders,
      fiat: Math.round(fiat * 100) / 100,
    },
    daily,
    daily_balances: [],
    shifts: [],
    totals: { orders, fiat: Math.round(fiat * 100) / 100 },
    source: "snapshot_approx",
  };
}

function buildPromos(admin: Record<string, unknown>) {
  const map = (admin.promos_by_id as Record<string, { promo?: Record<string, unknown> }> | undefined) || {};
  const promos = Object.values(map)
    .map((v) => v?.promo)
    .filter((p): p is Record<string, unknown> => !!p);
  return { promos };
}

function isoAgo(minutes: number) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function isoAhead(minutes: number) {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

/** Local UI without .dev-week-snapshot.json — never used in production builds. */
function builtinLocalSnap(): Record<string, unknown> {
  const activeDeal = {
    id: 9001,
    status: "awaiting_receipt",
    crypto: "usdt",
    sub_token: "SBPRUB",
    amount_rub: 8500,
    client_pays_rub: 10000,
    principal_usdt: 103.03,
    markup_pct: 15,
    markup_mode: "on_turnover",
    formula_text: "10 000 − 15% = 8 500 ₽ на баланс. К оплате: 10 000 ₽",
    created_at: isoAgo(8),
    expires_at: isoAhead(12),
    can_confirm_paid: true,
    can_upload_receipt: false,
    can_cancel: true,
    payment: {
      fiat_amount: 10000,
      bill: { bank: "Сбербанк", reciver: "+79001234567", fio: "Иван Иванов" },
    },
  };
  const confirmedDeal = {
    id: 9002,
    status: "confirmed",
    crypto: "usdt",
    sub_token: "CARDRUB",
    amount_rub: 42500,
    client_pays_rub: 50000,
    principal_usdt: 515.15,
    markup_pct: 15,
    markup_mode: "on_turnover",
    created_at: isoAgo(26 * 60),
    at: isoAgo(25 * 60),
    kind: "deal",
  };
  const payout = {
    id: 301,
    status: "paid",
    kind: "payout",
    crypto: "usdt",
    gross_usd: 250,
    fee_usd: 3,
    net_usd: 247,
    crypto_amount: 247,
    created_at: isoAgo(3 * 24 * 60),
    at: isoAgo(3 * 24 * 60),
  };
  return {
    exchanger_auth: {
      exchanger: { id: 1, username: "dev_shop", name: "Dev Shop", role: "owner", is_owner: true },
    },
    exchanger_dashboard: {
      exchanger_id: 1,
      name: "Dev Shop",
      username: "dev_shop",
      role: "owner",
      is_owner: true,
      totp_enabled: false,
      markup_pct: 15,
      markup_mode: "on_turnover",
      markup_hint:
        "Вы указываете сумму, которую платит клиент. Процент вычитается — остаток поступит на ваш баланс.",
      balance_usd: 1280.5,
      available_usd: 1280.5,
      has_pending_payout: false,
      pending_payout_gross_usd: 0,
      deal_count: 12,
      payout_count: 3,
      turnover_base_rub: 980000,
      turnover_client_rub: 1127000,
      total_credited_usd: 11900,
      total_paid_out_usd: 10619.5,
      conversion_pct: 91,
      deals_confirmed: 11,
      deals_failed: 1,
      last_deal_at: activeDeal.created_at,
      last_payout_at: payout.created_at,
      payout_threshold_usd: 3.01,
      withdraw_fee_usd: 3,
      withdraw_fees: { usdt: 3, btc: 2, ltc: 2, trx: 2 },
      active_deal_id: activeDeal.id,
      active_deal_ids: [activeDeal.id],
      active_count: 1,
    },
    exchanger_deals_active: { active: true, deals: [activeDeal], deal: activeDeal },
    exchanger_deals: { items: [activeDeal, confirmedDeal], total: 2, active_count: 1 },
    exchanger_payouts: { items: [payout], total: 1 },
    exchanger_history: {
      items: [
        { ...activeDeal, kind: "deal", at: activeDeal.created_at },
        { ...confirmedDeal, kind: "deal" },
        payout,
      ],
      total: 3,
    },
    exchanger_chat: {
      thread: { id: 1 },
      messages: [
        {
          id: 1,
          sender_role: "operator",
          body: "Если чек не пройдёт — пришлите видео экрана оплаты.",
          created_at: isoAgo(40),
        },
        {
          id: 2,
          sender_role: "exchanger",
          body: "Ок, по сделке #9001 клиент уже переводит.",
          created_at: isoAgo(12),
        },
      ],
    },
    exchanger_rates: {
      rates: {
        usdt: { market: 82.4, currency: "RUB" },
        btc: { market: 8_250_000, currency: "RUB" },
        trx: { market: 22.1, currency: "RUB" },
        ltc: { market: 8420, currency: "RUB" },
      },
      source: "local_stub",
      frozen: false,
      updated_at: Math.floor(Date.now() / 1000),
    },
    exchanger_api_keys: {
      key: {
        id: 1,
        api_key: "fp_dev_local_key",
        secret_hint: "••••dev1",
        is_active: true,
        created_at: isoAgo(14 * 24 * 60),
      },
    },
    exchanger_accounts: {
      current_account_id: 1,
      items: [
        {
          id: 1,
          username: "dev_shop",
          role: "owner",
          is_owner: true,
          label: "Владелец",
          is_active: true,
          totp_enabled: false,
        },
        {
          id: 2,
          username: "kassa_night",
          role: "clerk",
          is_owner: false,
          label: "Ночная смена",
          is_active: true,
          totp_enabled: false,
        },
      ],
    },
  };
}

function effectiveSnap(): Record<string, unknown> {
  const loaded = loadSnapshot();
  const local = builtinLocalSnap();
  return loaded ? { ...local, ...loaded } : local;
}

function exchangerDealsList(snap: Record<string, unknown>): Record<string, unknown>[] {
  const list = (snap.exchanger_deals as { items?: Record<string, unknown>[] } | undefined)?.items;
  const active = (snap.exchanger_deals_active as { deals?: Record<string, unknown>[] } | undefined)?.deals;
  return [...(Array.isArray(list) ? list : []), ...(Array.isArray(active) ? active : [])];
}

function enrichExchangerDashboard(snap: Record<string, unknown>): Record<string, unknown> {
  const dash = { ...((snap.exchanger_dashboard as Record<string, unknown> | undefined) || {}) };
  const sample = exchangerDealsList(snap).find((d) => d.markup_pct != null) || {};
  const mode = String(dash.markup_mode ?? sample.markup_mode ?? "on_turnover");
  if (dash.markup_pct == null) dash.markup_pct = sample.markup_pct ?? 15;
  if (dash.markup_mode == null) dash.markup_mode = mode;
  if (dash.markup_hint == null) {
    dash.markup_hint =
      mode === "on_turnover"
        ? "Вы указываете сумму, которую платит клиент. Процент вычитается — остаток поступит на ваш баланс."
        : "Вы указываете сумму, которая поступит на баланс. К оплате клиентом добавляется процент сверху.";
  }
  if (dash.withdraw_fees == null) dash.withdraw_fees = { usdt: 3, btc: 2, ltc: 2, trx: 2 };
  if (dash.withdraw_fee_usd == null) dash.withdraw_fee_usd = 3;
  return dash;
}

function snapshotDealPreview(snap: Record<string, unknown>, amountRub: number): Record<string, unknown> {
  const dash = enrichExchangerDashboard(snap);
  const pct = Number(dash.markup_pct ?? 15);
  const mode = String(dash.markup_mode ?? "on_turnover");
  const withdrawFees = (dash.withdraw_fees as Record<string, number>) || { usdt: 3, btc: 2, ltc: 2, trx: 2 };
  if (!(amountRub > 0)) {
    return {
      markup_pct: pct,
      markup_mode: mode,
      input_label: mode === "on_turnover" ? "Сумма оплаты клиента, ₽" : "Сумма на баланс, ₽",
      withdraw_fees: withdrawFees,
      withdraw_fee_usd: 3,
    };
  }
  const sample = exchangerDealsList(snap).find((d) => Number(d.principal_usdt) > 0 && Number(d.amount_rub) > 0);
  const rate = sample ? Number(sample.amount_rub) / Number(sample.principal_usdt) : 0;
  const clientPays = mode === "on_turnover" ? amountRub : Math.round(amountRub * (1 + pct / 100) * 100) / 100;
  const base = mode === "on_turnover" ? Math.round(amountRub * (1 - pct / 100) * 100) / 100 : amountRub;
  const fmt = (n: number) => n.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
  return {
    amount_rub: base,
    input_rub: amountRub,
    markup_pct: pct,
    markup_mode: mode,
    markup_rub: Math.round(Math.abs(clientPays - base) * 100) / 100,
    client_pays_rub: clientPays,
    principal_usdt: rate > 0 ? Math.round((base / rate) * 100) / 100 : 0,
    formula_text:
      mode === "on_turnover"
        ? `${fmt(amountRub)} − ${pct}% = ${fmt(base)} ₽ на баланс. К оплате: ${fmt(clientPays)} ₽`
        : `${fmt(amountRub)} + ${pct}% = ${fmt(clientPays)} ₽ к оплате. На баланс: ${fmt(base)} ₽`,
    input_label: mode === "on_turnover" ? "Сумма оплаты клиента, ₽" : "Сумма на баланс, ₽",
    withdraw_fees: withdrawFees,
    withdraw_fee_usd: 3,
  };
}

function snapshotPayoutPreview(snap: Record<string, unknown>, grossUsd: number, coin: string): Record<string, unknown> {
  const dash = enrichExchangerDashboard(snap);
  const fees = (dash.withdraw_fees as Record<string, number> | undefined) || { usdt: 3, btc: 2, ltc: 2, trx: 2 };
  const key = (coin || "usdt").toLowerCase();
  const fee = Number(fees[key] ?? dash.withdraw_fee_usd ?? 3);
  if (!(grossUsd > 0)) return { fee_usd: fee, crypto: coin || "usdt", withdraw_fees: fees };
  const net = Math.max(0, Math.round((grossUsd - fee) * 100) / 100);
  return { gross_usd: grossUsd, fee_usd: fee, net_usd: net, crypto: coin || "usdt", crypto_amount: net, withdraw_fees: fees };
}

function snapshotExchangerHistory(snap: Record<string, unknown>): { items: Record<string, unknown>[]; total: number } {
  const raw = snap.exchanger_history;
  const deals = exchangerDealsList(snap);
  const payouts = ((snap.exchanger_payouts as { items?: Record<string, unknown>[] } | undefined)?.items) || [];
  let items: Record<string, unknown>[] = [];
  if (Array.isArray(raw)) items = raw;
  else if (raw && typeof raw === "object" && Array.isArray((raw as { items?: unknown[] }).items)) {
    items = (raw as { items: Record<string, unknown>[] }).items;
  } else {
    items = [
      ...deals.map((d) => ({ ...d, kind: "deal", at: d.at ?? d.created_at })),
      ...payouts.map((p) => ({ ...p, kind: "payout", at: p.at ?? p.created_at })),
    ].sort((a, b) => String(b.at ?? "").localeCompare(String(a.at ?? "")));
  }
  const normalized = items.map((item) => {
    const kind =
      item.kind === "payout" || item.kind === "deal"
        ? item.kind
        : item.gross_usd != null && item.client_pays_rub == null && item.amount_rub == null
          ? "payout"
          : "deal";
    return {
      ...item,
      kind,
      at: item.at ?? item.created_at ?? null,
      amount_rub: item.amount_rub ?? item.client_pays_rub ?? null,
      amount_usd: item.amount_usd ?? item.principal_usdt ?? null,
    };
  });
  const total =
    raw && typeof raw === "object" && !Array.isArray(raw) && (raw as { total?: unknown }).total != null
      ? Number((raw as { total: number }).total)
      : normalized.length;
  return { items: normalized, total };
}

function matchPayload(snap: Record<string, unknown>, p: string, query: URLSearchParams): unknown {
  const admin = adminBlob(snap);
  if (p === "/api/admin/orders") return filterOrders(admin, query);
  const oneOrder = p.match(/^\/api\/admin\/orders\/([^/]+)$/);
  if (oneOrder && oneOrder[1] !== "undefined") {
    const pack = (admin.orders as { orders?: Record<string, unknown>[] }) || {};
    const hit = (pack.orders || []).find((r) => String(r.order_id) === oneOrder[1]);
    return hit ?? null;
  }
  if (p === "/api/admin/referral-partners") return admin.referral_partners;
  if (p === "/api/admin/referral-partners/tier-settings") return admin.tier_settings;
  const wd = p.match(/^\/api\/admin\/referral-partners\/(\d+)\/withdrawals$/);
  if (wd) {
    const map = (admin.partner_withdrawals_by_id as Record<string, unknown> | undefined) || {};
    return map[wd[1]] || { withdrawals: [] };
  }
  if (p === "/api/admin/promos") return buildPromos(admin);
  const promo = p.match(/^\/api\/admin\/promos\/(\d+)$/);
  if (promo) {
    const map = (admin.promos_by_id as Record<string, unknown> | undefined) || {};
    return map[promo[1]] ?? null;
  }
  if (p === "/api/admin/operators") return buildOperators(snap, admin);
  if (p === "/api/admin/operators/shifts") {
    return { shifts: [], can_view_finance: true, source: "snapshot_approx" };
  }
  const opStats = p.match(/^\/api\/admin\/operators\/(\d+)\/stats$/);
  if (opStats) return buildOperatorStats(snap, admin, Number(opStats[1]), query);
  if (p === "/api/admin/users") return filterUsers(admin, query);
  const oneUser = p.match(/^\/api\/admin\/users\/(\d+)$/);
  if (oneUser) {
    const map = (admin.users_by_id as Record<string, unknown> | undefined) || {};
    return map[oneUser[1]] ?? null;
  }
  if (p === "/api/admin/dashboard/live") return admin.dashboard_live;
  if (p === "/api/admin/dashboard/liabilities") return admin.dashboard_liabilities;
  if (p === "/api/admin/dashboard/owner") {
    const period = (query.get("period") || "week").toLowerCase();
    const all = (admin.dashboard_owner as Record<string, unknown> | undefined) || {};
    return all[period] || all.week;
  }
  const fallback = snapshotRange(snap, admin);
  const { from, to } = rangeFromQuery(query, fallback.from, fallback.to);
  if (p === "/api/admin/stats") return buildStats(admin, from, to);
  if (p === "/api/admin/finance-overview") return buildFinance(admin, from, to);
  if (p === "/api/admin/stats/promo") return { ...buildPromo(admin), period: { from, to } };
  if (p === "/api/admin/dashboard/volume-cohorts") return buildCohorts(admin, from, to);
  if (p === "/api/admin/misses") return buildMisses(admin, from, to);
  if (p === "/api/admin/external/summary") {
    return (
      admin.external_summary || {
        active_count: 0,
        total_count: 0,
        total_balance_usd: 0,
        total_turnover_base_rub: 0,
        total_turnover_client_rub: 0,
        house_profit_usd: 0,
        total_deals: 0,
        total_payouts: 0,
        source: "snapshot_approx",
      }
    );
  }
  if (p === "/api/auth/operator/me") {
    const auth = { ...((snap.operator_auth as Record<string, unknown>) || {}) };
    const operator = { ...((auth.operator as Record<string, unknown>) || {}) };
    const perms = Array.isArray(operator.permissions)
      ? (operator.permissions as unknown[]).map(String)
      : [];
    if (!perms.includes("orders.history")) perms.push("orders.history");
    if (!perms.includes("payout.requisites")) perms.push("payout.requisites");
    if (!perms.includes("payout.requisites.confirm")) perms.push("payout.requisites.confirm");
    operator.permissions = perms;
    return { ...auth, operator };
  }
  if (p === "/api/operator/me") return snap.operator_me;
  if (p === "/api/operator/orders/history") {
    const listed = filterOrders(adminBlob(snap), query);
    return { ...listed, counts: orderHistoryCounts(adminBlob(snap), query) };
  }
  const histOne = p.match(/^\/api\/operator\/orders\/history\/([^/]+)$/);
  if (histOne) {
    const id = decodeURIComponent(histOne[1]).toUpperCase();
    const pack = (adminBlob(snap).orders as { orders?: Record<string, unknown>[] }) || {};
    const hit = (pack.orders || []).find((r) => String(r.order_id || "").toUpperCase() === id);
    return hit || null;
  }
  if (p === "/api/operator/orders") return snap.operator_orders;
  if (p === "/api/operator/queue") return snap.operator_queue;
  const opUser = p.match(/^\/api\/operator\/users\/(\d+)$/);
  if (opUser) {
    const byId = (adminBlob(snap).users_by_id as Record<string, unknown> | undefined) || {};
    return byId[opUser[1]] ?? null;
  }
  if (p === "/api/operator/reviews/pending-count") return { count: 0 };
  if (p === "/api/operator/doliv/card-balances") return { total_float_rub: "0", traders_with_float: 0 };
  if (p === "/api/operator/team") return { operators: (snap.operator_me as { team_on_shift?: unknown[] })?.team_on_shift || [] };
  if (p === "/api/auth/exchanger/me") return snap.exchanger_auth;
  if (p === "/api/exchanger/dashboard") return enrichExchangerDashboard(snap);
  if (p === "/api/exchanger/deals/preview") {
    let amount = Number(query.get("amount_rub") || 0);
    const cryptoAmt = Number(query.get("amount_crypto") || 0);
    if (cryptoAmt > 0) {
      const coin = String(query.get("crypto") || "usdt").toLowerCase();
      const fake: Record<string, number> = { usdt: 80, btc: 8_000_000, ltc: 8000, trx: 20 };
      amount = Math.round(cryptoAmt * (fake[coin] || 80) * 100) / 100;
    }
    return snapshotDealPreview(snap, amount);
  }
  if (p === "/api/exchanger/deals/active") return snap.exchanger_deals_active || { active: false, deals: [] };
  if (p === "/api/exchanger/deals") return snap.exchanger_deals || { items: [], total: 0, active_count: 0 };
  const oneDeal = p.match(/^\/api\/exchanger\/deals\/(\d+)$/);
  if (oneDeal) {
    const hit = exchangerDealsList(snap).find((d) => String(d.id) === oneDeal[1]);
    return hit ?? null;
  }
  if (p === "/api/exchanger/payouts/balance") {
    const d = enrichExchangerDashboard(snap);
    return {
      available_usd: d.available_usd ?? 0,
      balance_usd: d.balance_usd ?? 0,
      has_pending_payout: Boolean(d.has_pending_payout),
      pending_payout_gross_usd: d.pending_payout_gross_usd ?? 0,
      payout_threshold_usd: d.payout_threshold_usd ?? 3.01,
      withdraw_fee_usd: d.withdraw_fee_usd ?? 3,
      withdraw_fees: d.withdraw_fees ?? { usdt: 3, btc: 2, ltc: 2, trx: 2 },
    };
  }
  if (p === "/api/exchanger/payouts/preview") {
    return snapshotPayoutPreview(snap, Number(query.get("gross_usd") || 0), String(query.get("crypto") || "usdt"));
  }
  if (p === "/api/exchanger/payouts") return snap.exchanger_payouts || { items: [], total: 0 };
  if (p === "/api/exchanger/history") return snapshotExchangerHistory(snap);
  if (p === "/api/exchanger/chat") return snap.exchanger_chat || { thread: { id: 0 }, messages: [] };
  if (p === "/api/exchanger/rates") {
    return (
      snap.exchanger_rates || {
        rates: {
          usdt: { market: 82.4, currency: "RUB" },
          btc: { market: 8_250_000, currency: "RUB" },
          trx: { market: 22.1, currency: "RUB" },
          ltc: { market: 8420, currency: "RUB" },
        },
        source: "local_stub",
        frozen: false,
        updated_at: Math.floor(Date.now() / 1000),
      }
    );
  }
  if (p === "/api/exchanger/api-keys") return snap.exchanger_api_keys || { key: null };
  if (p === "/api/exchanger/accounts") return snap.exchanger_accounts || { items: [], current_account_id: 0 };
  if (p === "/api/auth/partner/me") return snap.partner_auth;
  if (p === "/api/partner/dashboard") return snap.partner_dashboard;
  if (p === "/api/partner/ledger") return { items: [], total: 0 };
  if (p === "/api/partner/withdrawals") return { items: [], total: 0 };
  if (p.startsWith("/api/operator/chat")) return { threads: [], messages: [], count: 0 };
  if (p === "/api/operator/reviews") return { reviews: [], total: 0 };
  return undefined;
}

function sendJson(res: ServerResponse, body: unknown, status = 200) {
  const json = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(json);
}

const WRITE_BLOCK = new Set(["POST", "PATCH", "PUT", "DELETE"]);

function isSnapshotWrite(p: string): boolean {
  return p.startsWith("/api/admin/referral-partners") || /^\/api\/admin\/promos\/\d+/.test(p);
}

export function devWeekSnapshotPlugin(): Plugin {
  return {
    name: "dev-week-snapshot",
    apply: "serve",
    configureServer(server) {
      const first = loadSnapshot();
      if (!first) {
        console.warn("[dev-week-snapshot] нет .dev-week-snapshot.json — /exchanger идёт на встроенный stub");
      } else {
        const admin = adminBlob(first);
        const incoming = (first.operator_orders as { incoming?: unknown[] } | undefined)?.incoming?.length ?? 0;
        const deals = (first.exchanger_deals as { items?: unknown[] } | undefined)?.items?.length ?? 0;
        const orders = ((admin.orders as { orders?: unknown[] })?.orders?.length) ?? 0;
        const partners = ((admin.referral_partners as { partners?: unknown[] })?.partners?.length) ?? 0;
        const users = Array.isArray(admin.users) ? admin.users.length : 0;
        console.log(
          `[dev-week-snapshot] дамп: очередь ${incoming}, внештат ${deals}, заявки ${orders}, партнёры ${partners}, юзеры ${users}`,
        );
      }
      server.middlewares.use((req, res, next) => {
        if (!isLoopback(req)) {
          next();
          return;
        }
        const { pathname: p, query } = parseUrl(String(req.url || ""));
        if (!p.startsWith("/api/")) {
          next();
          return;
        }
        const method = String(req.method || "GET").toUpperCase();
        if (WRITE_BLOCK.has(method) && isSnapshotWrite(p)) {
          sendJson(res, { detail: "Локальный снимок: запись на прод отключена" }, 400);
          return;
        }
        if (method !== "GET") {
          next();
          return;
        }
        const snap = effectiveSnap();
        const payload = matchPayload(snap, p, query);
        if (payload === undefined) {
          next();
          return;
        }
        if (payload === null) {
          sendJson(res, { detail: "Не найдено" }, 404);
          return;
        }
        sendJson(res, payload);
      });
    },
  };
}
