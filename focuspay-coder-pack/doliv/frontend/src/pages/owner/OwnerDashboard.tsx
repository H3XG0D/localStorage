import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  TrendingUp, TrendingDown, CreditCard, Clock, CheckCircle, Wallet, AlertTriangle, Shield, Users,
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { api, formatUsdt } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { StatCard } from '../../components/ui/StatCard';
import { ChartCard } from '../../components/ui/StatCard';

const PIE_COLORS = ['#6366f1', '#22d3ee', '#f87171'];

interface TraderStatRow {
  user_id: number;
  login: string;
  full_name: string;
  total_profit: string;
  requisites_count: number;
}

interface DolivStatRow {
  user_id: number;
  login: string;
  full_name: string;
  dolivs_count: number;
  total_doliv_loss: string;
}

export default function OwnerDashboard() {
  const { data: dashboard, isError: dashError, refetch: refetchDash } = useQuery({
    queryKey: ['owner-dashboard'],
    queryFn: () => api.ownerDashboard(),
    refetchInterval: 30000,
  });

  const { data: traders, isError: tradersError, refetch: refetchTraders } = useQuery({
    queryKey: ['owner-traders'],
    queryFn: api.ownerStatsTraders,
  }) as { data: TraderStatRow[] | undefined; isError: boolean; refetch: () => void };

  const { data: dolivshchiks, isError: dolivError, refetch: refetchDoliv } = useQuery({
    queryKey: ['owner-dolivshchiks'],
    queryFn: api.ownerStatsDolivshchiks,
  }) as { data: DolivStatRow[] | undefined; isError: boolean; refetch: () => void };

  const stats = dashboard?.stats;
  const adminSummary = dashboard?.admin_summary;

  const chartData = (stats?.profit_by_day ?? []).slice().reverse().map((d) => ({
    day: d.day.slice(5),
    profit: d.profit,
  }));
  const pieData = stats?.profit_distribution ?? [];

  return (
    <AppShell title="Кабинет владельца">
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold">Обзор системы</h1>
            <p className="text-sm text-muted mt-0.5">Статистика и управление администраторами</p>
          </div>
          <Link to="/owner/admins" className="btn-primary flex items-center gap-2 text-sm">
            <Shield size={15} /> Администраторы
          </Link>
        </div>

        {(dashError || tradersError || dolivError) && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex flex-wrap items-center justify-between gap-3">
            <span>Не удалось загрузить часть данных</span>
            <button
              type="button"
              className="text-accent hover:text-accent-hover shrink-0"
              onClick={() => { void refetchDash(); void refetchTraders(); void refetchDoliv(); }}
            >
              Повторить
            </button>
          </div>
        )}

        <div className="card border border-violet-500/20">
          <div className="flex items-center gap-2 mb-4">
            <Users size={16} className="text-violet-400" />
            <h3 className="font-semibold text-sm">Администраторы</h3>
          </div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <p className="text-xs text-muted">Всего</p>
              <p className="text-2xl font-bold">{adminSummary?.total ?? 0}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Активных</p>
              <p className="text-2xl font-bold text-emerald-400">{adminSummary?.active ?? 0}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Отключённых</p>
              <p className="text-2xl font-bold text-zinc-500">{adminSummary?.inactive ?? 0}</p>
            </div>
          </div>
          <div className="space-y-2">
            {(adminSummary?.admins ?? []).slice(0, 5).map((a) => (
              <div key={a.id} className="flex items-center justify-between text-sm rounded-lg bg-elevated/40 px-3 py-2">
                <div>
                  <span className="font-medium">@{a.login}</span>
                  <span className="text-muted ml-2">{a.full_name}</span>
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className={a.is_active ? 'text-emerald-400' : 'text-zinc-500'}>
                    {a.is_active ? 'активен' : 'отключён'}
                  </span>
                  <span className="text-muted">
                    {a.last_login
                      ? new Date(a.last_login).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'short' })
                      : 'не входил'}
                  </span>
                </div>
              </div>
            ))}
            {(adminSummary?.admins ?? []).length === 0 && (
              <p className="text-sm text-muted">Нет администраторов. Создайте первого в разделе «Администраторы».</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          <StatCard label="Общий оборот" value={formatUsdt(String(stats?.total_turnover_usdt ?? 0))} icon={Wallet} accent="#6366f1" />
          <StatCard label="Общая прибыль" value={formatUsdt(String(stats?.total_profit ?? 0))} icon={TrendingUp} accent="#22c55e" />
          <StatCard label="Потери на доливах" value={formatUsdt(String(stats?.doliv_loss ?? 0))} icon={TrendingDown} trendUp={false} accent="#f87171" />
          <div className="card flex flex-col gap-1">
            <p className="text-xs text-muted flex items-center gap-1"><AlertTriangle size={11} className="text-orange-400" /> Фейк-чеки</p>
            <p className="text-xl font-bold">{stats?.fake_check_count ?? 0} <span className="text-xs font-normal text-muted">шт.</span></p>
            <p className="text-sm font-semibold text-orange-400">-{formatUsdt(String(stats?.fake_check_loss_usdt ?? 0))}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          <StatCard label="Активные реквизиты" value={stats?.active_requisites ?? 0} icon={CreditCard} accent="#22d3ee" />
          <StatCard label="Ожидают долив" value={stats?.awaiting_doliv ?? 0} icon={Clock} accent="#f59e0b" />
          <StatCard label="Закрытые" value={stats?.closed_requisites ?? 0} icon={CheckCircle} accent="#a78bfa" />
        </div>

        <div className="grid lg:grid-cols-2 gap-4">
          <ChartCard title="График прибыли">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={chartData.length ? chartData : [{ day: '—', profit: 0 }]}>
                <XAxis dataKey="day" />
                <YAxis />
                <Tooltip contentStyle={{ background: '#141416', border: '1px solid #27272a', borderRadius: 8 }} />
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
                  <tr><th>#</th><th>Имя</th><th>Реквизитов</th><th>Прибыль</th></tr>
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
                  <tr><th>#</th><th>Имя</th><th>Доливов</th><th>Потери</th></tr>
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
    </AppShell>
  );
}
