import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  TrendingUp, TrendingDown, CreditCard, Clock, CheckCircle, Wallet, AlertTriangle,
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { api, formatMoney, formatUsdt } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { AppShell } from '../../components/layout/AppShell';
import { DashboardLayout } from '../../components/layout/RightPanel';
import { StatCard } from '../../components/ui/StatCard';
import { ChartCard } from '../../components/ui/StatCard';
import { DataTable, Column } from '../../components/ui/DataTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import type { DashboardStats, Requisite } from '../../api/client';

interface StatsRecord {
  total_turnover?: string | number;
  total_turnover_usdt?: string | number;
  total_profit?: string | number;
  requisites_count?: number;
  dolivs_count?: number;
  profit_by_day?: { day: string; profit: number }[];
}

interface TraderStatRow {
  user_id: number;
  login: string;
  full_name: string;
  total_profit: string;
  total_turnover: string;
  requisites_count: number;
}

interface DolivStatRow {
  user_id: number;
  login: string;
  full_name: string;
  total_doliv_amount: string;
  dolivs_count: number;
  avg_doliv_rate: string;
  total_doliv_loss: string;
}

const PIE_COLORS = ['#6366f1', '#22d3ee', '#f87171'];

function QueryErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="card border border-red-500/30 bg-red-500/10 mb-4 flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-red-300">{message}</p>
      <button type="button" onClick={onRetry} className="btn-secondary text-xs py-1.5 px-3">
        Повторить
      </button>
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="card animate-pulse">
      <div className="h-3 w-24 bg-elevated rounded mb-2" />
      <div className="h-7 w-32 bg-elevated rounded" />
    </div>
  );
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const queryEnabled = !!user;

  const overviewQuery = useQuery({
    queryKey: ['admin-overview'],
    queryFn: () => api.statsOverview(),
    refetchInterval: 30000,
    enabled: queryEnabled,
  });
  const overview = overviewQuery.data as StatsRecord | undefined;

  const dashboardQuery = useQuery({
    queryKey: ['admin-dashboard-stats'],
    queryFn: () => api.statsDashboard(),
    refetchInterval: 30000,
    enabled: queryEnabled,
  });
  const dashboard = dashboardQuery.data as DashboardStats | undefined;

  const requisitesQuery = useQuery({
    queryKey: ['admin-requisites'],
    queryFn: () => api.adminRequisites(),
    refetchInterval: 30000,
    enabled: queryEnabled,
  });
  const requisites = requisitesQuery.data;

  const tradersQuery = useQuery({
    queryKey: ['admin-traders'],
    queryFn: api.statsTraders,
    enabled: queryEnabled,
  });
  const traders = tradersQuery.data as TraderStatRow[] | undefined;

  const dolivshchiksQuery = useQuery({
    queryKey: ['admin-dolivshchiks'],
    queryFn: api.statsDolivshchiks,
    enabled: queryEnabled,
  });
  const dolivshchiks = dolivshchiksQuery.data as DolivStatRow[] | undefined;

  const statsLoading = dashboardQuery.isLoading || overviewQuery.isLoading;
  const statsError = dashboardQuery.isError || overviewQuery.isError;
  const statsErrorMessage =
    (dashboardQuery.error as Error | undefined)?.message
    ?? (overviewQuery.error as Error | undefined)?.message
    ?? 'Не удалось загрузить статистику';

  const retryStats = () => {
    void dashboardQuery.refetch();
    void overviewQuery.refetch();
  };

  const active = requisites?.filter((r) => ['active', 'in_work'].includes(r.status)).length ?? 0;
  const awaiting = requisites?.filter((r) => r.status === 'awaiting_doliv').length ?? 0;
  const closed = requisites?.filter((r) => r.status === 'closed').length ?? 0;

  const chartData = (dashboard?.profit_by_day ?? overview?.profit_by_day ?? []).slice().reverse().map((d) => ({
    day: d.day.slice(5),
    profit: d.profit,
  }));
  const pieData = dashboard?.profit_distribution ?? [];

  const reqColumns: Column<Requisite>[] = [
    { key: 'id', header: 'ID', render: (r) => <span className="text-muted">#{r.id}</span> },
    { key: 'name', header: 'Реквизит', render: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'amount', header: 'Сумма', render: (r) => formatMoney(r.total_amount) },
    { key: 'rate', header: 'Курс', render: (r) => r.target_rate },
    { key: 'status', header: 'Статус', render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <AppShell title="Главная панель">
      <DashboardLayout rightPanel>
        <div className="space-y-5">
          {statsError && (
            <QueryErrorBanner message={statsErrorMessage} onRetry={retryStats} />
          )}

          {statsLoading && !dashboard && !overview ? (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 mb-3">
                {Array.from({ length: 4 }).map((_, i) => <StatSkeleton key={i} />)}
              </div>
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                {Array.from({ length: 3 }).map((_, i) => <StatSkeleton key={i} />)}
              </div>
            </>
          ) : (
            <>
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 mb-3">
            <StatCard label="Общий оборот" value={formatUsdt(String(dashboard?.total_turnover_usdt ?? overview?.total_turnover_usdt ?? 0))} icon={Wallet} accent="#6366f1" />
            <StatCard label="Общая прибыль" value={formatUsdt(String(dashboard?.total_profit ?? overview?.total_profit ?? 0))} icon={TrendingUp} accent="#22c55e" />
            <StatCard label="Потери на доливах" value={formatUsdt(String(dashboard?.doliv_loss ?? 0))} icon={TrendingDown} trendUp={false} accent="#f87171" />
            <div className="card flex flex-col gap-1">
              <p className="text-xs text-muted flex items-center gap-1"><AlertTriangle size={11} className="text-orange-400" /> Фейк-чеки</p>
              <p className="text-xl font-bold">{dashboard?.fake_check_count ?? 0} <span className="text-xs font-normal text-muted">шт.</span></p>
              <p className="text-sm font-semibold text-orange-400">-{formatUsdt(String(dashboard?.fake_check_loss_usdt ?? 0))}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <StatCard label="Активные реквизиты" value={dashboard?.active_requisites ?? active} icon={CreditCard} accent="#22d3ee" />
            <StatCard label="Ожидают долив" value={dashboard?.awaiting_doliv ?? awaiting} icon={Clock} accent="#f59e0b" />
            <StatCard label="Закрытые" value={dashboard?.closed_requisites ?? (closed || overview?.requisites_count || 0)} icon={CheckCircle} accent="#a78bfa" />
          </div>
            </>
          )}

          <div className="card">
            <h3 className="font-semibold text-sm mb-4">Последние реквизиты</h3>
            {requisitesQuery.isError ? (
              <div className="flex flex-wrap items-center justify-between gap-2 py-4">
                <p className="text-sm text-red-300">
                  {(requisitesQuery.error as Error).message || 'Не удалось загрузить реквизиты'}
                </p>
                <button type="button" onClick={() => requisitesQuery.refetch()} className="btn-secondary text-xs py-1.5 px-3">
                  Повторить
                </button>
              </div>
            ) : requisitesQuery.isLoading && !requisites ? (
              <p className="text-sm text-muted py-4">Загрузка реквизитов…</p>
            ) : (
            <DataTable
              columns={reqColumns}
              data={requisites?.slice(0, 8) ?? []}
              keyField="id"
              onRowClick={(r) => navigate(`/admin/requisites/${r.id}`)}
            />
            )}
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <ChartCard title="График прибыли">
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={chartData.length ? chartData : [{ day: '—', profit: 0 }]}>
                  <XAxis dataKey="day" />
                  <YAxis />
                  <Tooltip
                    contentStyle={{ background: '#141416', border: '1px solid #27272a', borderRadius: 8 }}
                    labelStyle={{ color: '#fafafa' }}
                  />
                  <Line type="monotone" dataKey="profit" stroke="#6366f1" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Распределение прибыли">
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={pieData.length ? pieData : [{ name: 'Нет данных', value: 1 }]} cx="50%" cy="50%" innerRadius={50} outerRadius={75} dataKey="value" paddingAngle={3}>
                    {(pieData.length ? pieData : [{ name: 'Нет данных', value: 1 }]).map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Legend formatter={(v) => <span style={{ color: '#71717a', fontSize: 11 }}>{v}</span>} />
                  <Tooltip contentStyle={{ background: '#141416', border: '1px solid #27272a', borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Топ трейдеров</h3>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th><th>Имя</th><th>Реквизитов</th><th>Прибыль</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(traders ?? []).slice(0, 5).map((t, i) => (
                      <tr key={t.user_id}>
                        <td className="text-muted">{i + 1}</td>
                        <td className="font-medium">@{t.login || t.full_name}</td>
                        <td>{t.requisites_count}</td>
                        <td className="text-emerald-400">{formatUsdt(t.total_profit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Топ доливщиков</h3>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th><th>Имя</th><th>Доливов</th><th>Потери</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...(dolivshchiks ?? [])]
                      .sort((a, b) => parseFloat(b.total_doliv_loss ?? '0') - parseFloat(a.total_doliv_loss ?? '0'))
                      .slice(0, 5)
                      .map((d, i) => (
                      <tr key={d.user_id}>
                        <td className="text-muted">{i + 1}</td>
                        <td className="font-medium">@{d.login || d.full_name}</td>
                        <td>{d.dolivs_count}</td>
                        <td className="text-red-400">{formatUsdt(d.total_doliv_loss ?? '0')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </DashboardLayout>
    </AppShell>
  );
}
