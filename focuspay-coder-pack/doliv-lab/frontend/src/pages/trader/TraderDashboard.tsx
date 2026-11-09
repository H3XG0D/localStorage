import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  CheckCircle,
  Clock,
  CreditCard,
  Download,
  FileText,
  Plus,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import {
  Line,
  LineChart,
  Pie,
  PieChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api, formatMoney, formatUsdt, statusLabel } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { StatCard } from '../../components/ui/StatCard';
import { StatusBadge } from '../../components/ui/StatusBadge';
import type { Receipt, Requisite } from '../../api/client';

interface TraderStats {
  profit_month?: string | number;
  profit_day?: string | number;
  profit_week?: string | number;
  total_turnover?: string | number;
  total_turnover_usdt?: string | number;
  total_profit?: string | number;
  requisites_count?: number;
  avg_profit_per_requisite?: string | number;
  active_profit?: string | number;
}

function amountToUsdt(amount: string | number | undefined, rate: string | number | undefined): number {
  const value = numeric(amount);
  const exchangeRate = numeric(rate);
  return exchangeRate > 0 ? value / exchangeRate : 0;
}

function numeric(value: string | number | undefined): number {
  if (value === undefined) return 0;
  return typeof value === 'string' ? Number.parseFloat(value) || 0 : value;
}

function CompactRequisiteRow({ requisite }: { requisite: Requisite }) {
  return (
    <Link
      to={`/trader/requisites/${requisite.id}`}
      className="grid grid-cols-[1fr_auto] sm:grid-cols-[1.4fr_0.9fr_0.7fr_0.8fr] items-center gap-3 rounded-xl border border-border/70 bg-elevated/35 px-3 py-2.5 text-sm transition-colors hover:border-accent/40"
    >
      <div>
        <p className="font-medium">{requisite.name}</p>
        <p className="mt-0.5 text-[11px] text-muted">#{requisite.id} · {statusLabel(requisite.status)}</p>
        <p className="mt-1 text-xs text-muted sm:hidden">
          {formatMoney(requisite.total_amount)} · курс {requisite.target_rate}
        </p>
      </div>
      <span className="hidden sm:block">{formatMoney(requisite.total_amount)}</span>
      <span className="hidden sm:block text-muted">{requisite.target_rate}</span>
      <div className="text-right">
        <StatusBadge status={requisite.status} />
      </div>
    </Link>
  );
}

export default function TraderDashboard() {
  const { data: stats, isError: statsError, refetch: refetchStats } = useQuery({
    queryKey: ['trader-stats'],
    queryFn: api.traderStats,
  }) as { data: TraderStats | undefined; isError: boolean; refetch: () => void };
  const { data: requisites, isError: reqError, refetch: refetchReq } = useQuery({
    queryKey: ['requisites'],
    queryFn: () => api.listRequisites(),
    refetchInterval: 30000,
  });
  const { data: dolivRequests } = useQuery({ queryKey: ['trader-doliv-requests'], queryFn: api.traderDolivRequests, refetchInterval: 30000 });
  const { data: receipts } = useQuery({ queryKey: ['trader-receipts'], queryFn: api.traderReceipts, refetchInterval: 30000 });

  const active = requisites?.filter((r) => !['closed', 'archive'].includes(r.status)) ?? [];
  const awaiting = dolivRequests?.filter((r) => ['pending', 'in_progress'].includes(r.status)) ?? [];
  const completed = requisites?.filter((r) => r.status === 'closed') ?? [];
  const totalRequisites = requisites?.length ?? 0;
  const turnoverUsdt = numeric(stats?.total_turnover_usdt)
    || active.reduce((sum, r) => sum + amountToUsdt(r.total_amount, r.target_rate), 0);
  const closedProfit = numeric(stats?.profit_month || stats?.total_profit);
  const activeProfit = numeric(stats?.active_profit);
  const profit = closedProfit;
  const recentReceipts = (receipts ?? []).slice(0, 4);
  const fillPercent = turnoverUsdt > 0 ? Math.min(Math.round((closedProfit / turnoverUsdt) * 1000) / 10, 99) : 0;

  // Build chart data from real stats when available
  const profitTrend = numeric(stats?.profit_day) > 0 && numeric(stats?.profit_week) > 0
    ? [
        { day: 'Нед', profit: numeric(stats?.profit_week) },
        { day: 'Мес', profit: numeric(stats?.profit_month ?? stats?.total_profit) },
      ]
    : null;

  // Pie: proportion of turnover from closed deals vs active
  const closedTurnoverUsdt = numeric(stats?.total_turnover_usdt);
  const activeTurnoverUsdt = active.reduce((s, r) => s + amountToUsdt(r.total_amount, r.target_rate), 0);
  const totalForPie = closedTurnoverUsdt + activeTurnoverUsdt || 1;
  const pieData = [
    { name: 'Закрыто', value: Math.round((closedTurnoverUsdt / totalForPie) * 100), color: '#6366f1' },
    { name: 'Активно', value: Math.round((activeTurnoverUsdt / totalForPie) * 100), color: '#f59e0b' },
  ].filter((e) => e.value > 0);

  const downloadReceipt = async (receipt: Receipt) => {
    try {
      const blob = await api.downloadTraderReceipt(receipt.type, receipt.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${receipt.type}_${receipt.id}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silent on dashboard list — user can retry from detail page
    }
  };

  return (
    <AppShell title="Главная">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Трейдер</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight">Рабочий стол</h2>
          <p className="mt-1 text-sm text-muted">Карты с лимитом, заливы, доливы и депозит.</p>
        </div>
        <Link to="/trader/assets" className="btn-primary inline-flex items-center gap-2">
          <Plus size={16} />
          Новая карта / лимит
        </Link>
      </div>

      {(statsError || reqError) && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex flex-wrap items-center justify-between gap-3">
          <span>Не удалось загрузить данные дашборда</span>
          <button
            type="button"
            className="text-accent hover:text-accent-hover shrink-0"
            onClick={() => { void refetchStats(); void refetchReq(); }}
          >
            Повторить
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Реквизитов" value={totalRequisites} icon={CreditCard} accent="#6366f1" />
        <StatCard label="Оборот" value={formatUsdt(turnoverUsdt)} icon={Wallet} accent="#22d3ee" />
        <StatCard label="Прибыль (сделки)" value={formatUsdt(profit)} icon={TrendingUp} accent="#22c55e" />
        <StatCard label="Прибыль в работе" value={activeProfit > 0 ? `+${formatUsdt(activeProfit)}` : formatUsdt(0)} icon={TrendingUp} accent="#f59e0b" />
        <StatCard label="Ожидают долив" value={awaiting.length} icon={Clock} accent="#a78bfa" />
        <StatCard label="Закрыто" value={completed.length} icon={CheckCircle} accent="#f472b6" />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[1.25fr_0.9fr]">
        <section className="card">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold">Мои сессии</h3>
              <p className="text-xs text-muted">Лимиты на картах (история)</p>
            </div>
            <Link to="/trader/assets" className="text-xs font-medium text-accent hover:text-accent-hover">
              К картам
            </Link>
          </div>
          <div className="mb-2 hidden sm:grid grid-cols-[1.4fr_0.9fr_0.7fr_0.8fr] gap-3 px-3 text-[11px] font-medium uppercase tracking-wide text-muted">
            <span>Реквизит</span>
            <span>Сумма</span>
            <span>Курс</span>
            <span className="text-right">Статус</span>
          </div>
          <div className="space-y-2">
            {active.slice(0, 6).map((r) => (
              <CompactRequisiteRow key={r.id} requisite={r} />
            ))}
            {!active.length && <p className="py-8 text-center text-sm text-muted">Нет активных реквизитов</p>}
          </div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold">Карточка реквизита</h3>
              <p className="text-xs text-muted">Быстрый статус последней карты</p>
            </div>
            <CreditCard size={18} className="text-accent" />
          </div>
          {active[0] ? (
            <div className="space-y-4">
              <div className="rounded-2xl border border-accent/25 bg-gradient-to-br from-accent/25 to-cyan-500/10 p-4">
                <p className="text-xs text-muted">Название</p>
                <p className="mt-1 text-lg font-semibold">{active[0].name}</p>
                <div className="mt-5 grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <p className="text-[11px] text-muted">Сумма</p>
                    <p className="font-semibold">{formatMoney(active[0].total_amount)}</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-muted">Курс</p>
                    <p className="font-semibold">{active[0].target_rate}</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-muted">Маржа</p>
                    <p className="font-semibold text-emerald-400">{fillPercent}%</p>
                  </div>
                </div>
              </div>
              <div>
                <div className="mb-1 flex justify-between text-xs text-muted">
                  <span>Маржа закрытых</span>
                  <span>{fillPercent}%</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${fillPercent}%` }} />
                </div>
              </div>
              <Link to={`/trader/requisites/${active[0].id}`} className="btn-primary block w-full text-center text-sm">
                Открыть карточку
              </Link>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-muted">Нет данных для карточки</p>
          )}
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.1fr_0.85fr]">
        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold">Заявки на долив</h3>
              <p className="text-xs text-muted">Реквизиты, ожидающие исполнения</p>
            </div>
            <Link to="/trader/doliv-requests" className="text-xs font-medium text-accent hover:text-accent-hover">
              Все заявки
            </Link>
          </div>
          <div className="space-y-2">
            {awaiting.slice(0, 5).map((r) => (
              <Link key={r.id} to={`/trader/requisites/${r.requisite_id}`} className="flex items-center justify-between rounded-xl bg-elevated/35 px-3 py-3 text-sm hover:bg-elevated/60">
                <div>
                  <p className="font-medium">#{r.id} · {r.requisite_name ?? 'Реквизит'}</p>
                  <p className="text-xs text-muted">
                    {formatMoney(r.required_amount)} · курс {r.target_rate ?? '—'}
                    {r.assigned_dolivshchik_name ? ` · ${r.assigned_dolivshchik_name}` : ''}
                  </p>
                </div>
                <StatusBadge status={r.status} />
              </Link>
            ))}
            {!awaiting.length && <p className="py-8 text-center text-sm text-muted">Нет заявок на долив</p>}
          </div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold">Чеки</h3>
              <p className="text-xs text-muted">Последние документы по реквизитам</p>
            </div>
            <Download size={17} className="text-muted" />
          </div>
          <div className="space-y-2">
            {recentReceipts.map((r) => (
              <Link key={`${r.type}-${r.id}`} to={`/trader/requisites/${r.requisite_id}`} className="flex items-center gap-3 rounded-xl bg-elevated/35 p-3 text-sm hover:bg-elevated/60">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/15 text-accent">
                  <FileText size={17} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{r.requisite_name}</p>
                  <p className="text-xs text-muted">{formatMoney(r.amount)} · {new Date(r.created_at).toLocaleDateString('ru')}</p>
                </div>
                <button
                  className="text-muted hover:text-accent"
                  onClick={(e) => {
                    e.preventDefault();
                    void downloadReceipt(r);
                  }}
                  title="Скачать чек"
                >
                  <Download size={15} />
                </button>
              </Link>
            ))}
            {!recentReceipts.length && <p className="py-8 text-center text-sm text-muted">Нет чеков</p>}
          </div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold">Моя статистика</h3>
              <p className="text-xs text-muted">Период: за месяц</p>
            </div>
            <span className="rounded-lg bg-elevated px-2 py-1 text-[11px] text-muted">{
            (() => {
              const now = new Date();
              const start = new Date(now.getFullYear(), now.getMonth(), 1).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' });
              const end = new Date(now.getFullYear(), now.getMonth() + 1, 0).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' });
              return `${start} – ${end}`;
            })()
          }</span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-xl bg-elevated/35 p-3">
              <p className="text-[11px] text-muted">Оборот</p>
              <p className="mt-1 font-semibold">{formatUsdt(turnoverUsdt)}</p>
            </div>
            <div className="rounded-xl bg-elevated/35 p-3">
              <p className="text-[11px] text-muted">Прибыль</p>
              <p className="mt-1 font-semibold text-emerald-400">
                {activeProfit > 0 ? `+${formatUsdt(activeProfit)}` : formatUsdt(closedProfit)}
              </p>
            </div>
            <div className="rounded-xl bg-elevated/35 p-3">
              <p className="text-[11px] text-muted">Сделки</p>
              <p className="mt-1 font-semibold">{completed.length}</p>
            </div>
          </div>
          <div className="mt-4 h-40">
            {profitTrend ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={profitTrend}>
                  <XAxis dataKey="day" />
                  <YAxis hide />
                  <Tooltip contentStyle={{ background: '#141416', border: '1px solid #27272a', borderRadius: 8 }} />
                  <Line type="monotone" dataKey="profit" stroke="#6366f1" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="flex h-full items-center justify-center text-xs text-muted">Нет данных для графика</p>
            )}
          </div>
          <div className="mt-3 grid grid-cols-[100px_1fr] items-center gap-3">
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} dataKey="value" innerRadius={28} outerRadius={44} paddingAngle={3}>
                    {pieData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-2">
              {pieData.map((entry) => (
                <div key={entry.name} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-muted">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
                    {entry.name}
                  </span>
                  <span>{entry.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
