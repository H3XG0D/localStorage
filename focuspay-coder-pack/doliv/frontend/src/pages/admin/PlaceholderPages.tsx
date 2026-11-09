import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ChartCard } from '../../components/ui/StatCard';
import { api, formatMoney, formatUsdt, getStatsApi, StatsScope } from '../../api/client';
import type {
  AdminDoliv,
  AppSettings,
  DolivRequest,
  EmployeeStats,
  Receipt,
  RolePermissions,
  SalaryRow,
  StatementRow,
  User,
} from '../../api/client';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend } from 'recharts';

export function AdminDolivRequests() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState('');
  const [actionError, setActionError] = useState('');
  const { data: requests, isLoading, isError, refetch } = useQuery({
    queryKey: ['admin-doliv-requests', statusFilter],
    queryFn: () => api.adminDolivRequests(statusFilter || undefined),
    refetchInterval: 30000,
  });
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: api.adminUsers });
  const dolivshchiks = (users ?? []).filter((user: User) => user.role === 'dolivshchik' && user.is_active);

  const assign = useMutation({
    mutationFn: ({ requestId, dolivshchikId }: { requestId: number; dolivshchikId: number }) =>
      api.assignAdminDolivRequest(requestId, dolivshchikId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-doliv-requests'] });
      qc.invalidateQueries({ queryKey: ['admin-requisites'] });
      setActionError('');
    },
    onError: (err: Error) => setActionError(err.message),
  });

  const cancel = useMutation({
    mutationFn: (requestId: number) => api.cancelAdminDolivRequest(requestId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-doliv-requests'] });
      qc.invalidateQueries({ queryKey: ['admin-requisites'] });
      setActionError('');
    },
    onError: (err: Error) => setActionError(err.message),
  });

  const columns: Column<DolivRequest>[] = [
    { key: 'id', header: 'ID', render: (r) => <span className="text-muted">#{r.id}</span> },
    { key: 'requisite', header: 'Реквизит', render: (r) => r.requisite_name ?? `#${r.requisite_id}` },
    { key: 'trader', header: 'Трейдер', render: (r) => r.trader_name ? `@${r.trader_name}` : '—' },
    { key: 'amount', header: 'Сумма', render: (r) => formatMoney(r.required_amount) },
    { key: 'rate', header: 'Курс', render: (r) => r.target_rate ?? '—' },
    { key: 'dolivshchik', header: 'Доливщик', render: (r) => r.assigned_dolivshchik_name ? `@${r.assigned_dolivshchik_name}` : 'Не назначен' },
    { key: 'status', header: 'Статус', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'date', header: 'Дата', render: (r) => new Date(r.sent_at).toLocaleString('ru') },
    {
      key: 'actions',
      header: 'Действия',
      render: (r) => (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center" onClick={(e) => e.stopPropagation()}>
          <select
            className="input py-1.5 text-xs"
            value={r.assigned_dolivshchik_id ?? ''}
            disabled={['completed', 'cancelled'].includes(r.status) || assign.isPending}
            onChange={(e) => {
              const value = Number(e.target.value);
              if (value) assign.mutate({ requestId: r.id, dolivshchikId: value });
            }}
          >
            <option value="">Назначить</option>
            {dolivshchiks.map((user) => (
              <option key={user.id} value={user.id}>{user.full_name}</option>
            ))}
          </select>
          {!['completed', 'cancelled'].includes(r.status) && (
            <button
              className="btn-danger px-3 py-1.5 text-xs"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate(r.id)}
            >
              Отменить
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <AppShell title="Заявки на долив">
      <PageHeader
        title="Заявки на долив"
        subtitle={isLoading ? 'Загрузка...' : `Всего: ${requests?.length ?? 0}`}
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {[
          ['', 'Все'],
          ['pending', 'Ожидают'],
          ['in_progress', 'В работе'],
          ['completed', 'Завершены'],
          ['cancelled', 'Отменены'],
        ].map(([value, label]) => (
          <button
            key={value || 'all'}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              statusFilter === value ? 'bg-accent/15 text-accent' : 'bg-elevated text-muted hover:text-white'
            }`}
            onClick={() => setStatusFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {actionError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {actionError}
        </div>
      )}
      {isError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center justify-between gap-3">
          <span>Не удалось загрузить заявки</span>
          <button type="button" className="text-accent hover:text-accent-hover shrink-0" onClick={() => void refetch()}>
            Повторить
          </button>
        </div>
      )}
      <div className="md:hidden space-y-3 mb-4">
        {(requests ?? []).map((r) => (
          <div
            key={r.id}
            className="rounded-2xl border border-border bg-elevated/40 p-4 text-sm cursor-pointer"
            onClick={() => navigate(`/admin/requisites/${r.requisite_id}`)}
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-semibold">{r.requisite_name ?? `#${r.requisite_id}`}</p>
                <p className="text-xs text-muted mt-0.5">#{r.id} · {r.trader_name ? `@${r.trader_name}` : '—'}</p>
              </div>
              <StatusBadge status={r.status} />
            </div>
            <p className="mt-2">{formatMoney(r.required_amount)} · курс {r.target_rate ?? '—'}</p>
            <p className="text-xs text-muted mt-1">
              {r.assigned_dolivshchik_name ? `@${r.assigned_dolivshchik_name}` : 'Доливщик не назначен'}
            </p>
            <div className="mt-3 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
              <select
                className="input py-2"
                value={r.assigned_dolivshchik_id ?? ''}
                disabled={['completed', 'cancelled'].includes(r.status) || assign.isPending}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  if (value) assign.mutate({ requestId: r.id, dolivshchikId: value });
                }}
              >
                <option value="">Назначить доливщика</option>
                {dolivshchiks.map((user) => (
                  <option key={user.id} value={user.id}>{user.full_name}</option>
                ))}
              </select>
              {!['completed', 'cancelled'].includes(r.status) && (
                <button
                  type="button"
                  className="btn-danger w-full py-2 text-xs"
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate(r.id)}
                >
                  Отменить
                </button>
              )}
            </div>
          </div>
        ))}
        {!isLoading && !requests?.length && (
          <p className="py-8 text-center text-sm text-muted">Нет заявок</p>
        )}
      </div>
      <div className="hidden md:block">
        <DataTable
          columns={columns}
          data={requests ?? []}
          keyField="id"
          onRowClick={(r) => navigate(`/admin/requisites/${r.requisite_id}`)}
          emptyMessage="Нет заявок"
        />
      </div>
    </AppShell>
  );
}

export function AdminDolivs() {
  const navigate = useNavigate();
  const { data: dolivs, isLoading } = useQuery({
    queryKey: ['admin-dolivs'],
    queryFn: api.adminDolivs,
    refetchInterval: 30000,
  });

  const columns: Column<AdminDoliv>[] = [
    { key: 'id', header: 'ID', render: (r) => <span className="text-muted">#{r.id}</span> },
    { key: 'requisite', header: 'Реквизит', render: (r) => r.requisite_name },
    { key: 'trader', header: 'Трейдер', render: (r) => `@${r.trader_name}` },
    { key: 'dolivshchik', header: 'Доливщик', render: (r) => `@${r.dolivshchik_name}` },
    { key: 'amount', header: 'Сумма', render: (r) => formatMoney(r.amount) },
    { key: 'rate', header: 'Курс', render: (r) => r.rate },
    { key: 'status', header: 'Статус', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'date', header: 'Дата', render: (r) => new Date(r.completed_at).toLocaleString('ru') },
  ];

  return (
    <AppShell title="Доливы">
      <PageHeader
        title="Доливы"
        subtitle={isLoading ? 'Загрузка...' : `Всего: ${dolivs?.length ?? 0}`}
      />
      <DataTable
        columns={columns}
        data={dolivs ?? []}
        keyField="id"
        onRowClick={(r) => navigate(`/admin/requisites/${r.requisite_id}`)}
        emptyMessage="Пока нет выполненных доливов"
      />
    </AppShell>
  );
}

export function AdminReceipts() {
  const navigate = useNavigate();
  const { data: receipts, isLoading } = useQuery({
    queryKey: ['admin-receipts'],
    queryFn: api.adminReceipts,
    refetchInterval: 30000,
  });

  const downloadReceipt = async (receipt: Receipt) => {
    const blob = await api.downloadReceipt(receipt.type, receipt.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = receipt.receipt_path.split('/').pop() || `${receipt.type}_${receipt.id}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: Column<Receipt>[] = [
    { key: 'id', header: 'ID', render: (r) => <span className="text-muted">#{r.id}</span> },
    { key: 'type', header: 'Тип', render: (r) => (r.type === 'zaliv' ? 'Залив' : 'Долив') },
    { key: 'requisite', header: 'Реквизит', render: (r) => r.requisite_name },
    { key: 'uploader', header: 'Загрузил', render: (r) => `@${r.uploader_name}` },
    { key: 'amount', header: 'Сумма', render: (r) => formatMoney(r.amount) },
    { key: 'rate', header: 'Курс', render: (r) => r.rate },
    { key: 'date', header: 'Дата', render: (r) => new Date(r.created_at).toLocaleString('ru') },
    {
      key: 'download',
      header: '',
      render: (r) => (
        <button
          className="text-accent hover:underline"
          onClick={(e) => {
            e.stopPropagation();
            downloadReceipt(r);
          }}
        >
          Скачать
        </button>
      ),
    },
  ];

  return (
    <AppShell title="Чеки">
      <PageHeader
        title="Чеки"
        subtitle={isLoading ? 'Загрузка...' : `Всего файлов: ${receipts?.length ?? 0}`}
      />
      <DataTable
        columns={columns}
        data={receipts ?? []}
        keyField={(r) => `${r.type}-${r.id}`}
        onRowClick={(r) => navigate(`/admin/requisites/${r.requisite_id}`)}
        emptyMessage="Пока нет загруженных чеков"
      />
    </AppShell>
  );
}

export function AdminAnalytics({ scope = 'admin' }: { scope?: StatsScope }) {
  const statsApi = getStatsApi(scope);
  const queryPrefix = scope === 'owner' ? 'owner' : 'admin';
  const [dateStart, setDateStart] = useState('');
  const [dateEnd, setDateEnd] = useState('');
  const [traderId, setTraderId] = useState('');
  const [requisiteId, setRequisiteId] = useState('');
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('day');

  const params = {
    ...(dateStart ? { start: dateStart } : {}),
    ...(dateEnd ? { end: dateEnd } : {}),
    ...(traderId ? { trader_id: parseInt(traderId, 10) } : {}),
    ...(requisiteId ? { requisite_id: parseInt(requisiteId, 10) } : {}),
    period,
  };

  const { data: analytics } = useQuery({
    queryKey: [`${queryPrefix}-analytics`, dateStart, dateEnd, traderId, requisiteId, period],
    queryFn: () => statsApi.statsAnalytics(params),
  });

  const chartData = (analytics?.chart ?? []).map((d) => ({
    label: period === 'day' ? d.label.slice(5) : d.label,
    profit: d.profit,
    doliv_loss: d.doliv_loss,
    fake_check_loss: d.fake_check_loss,
    net_profit: d.net_profit,
  }));

  const netProfit = parseFloat(String(analytics?.total_profit ?? 0));
  const fcLoss = parseFloat(String(analytics?.fake_check_loss_usdt ?? 0));
  const net = netProfit - fcLoss;

  return (
    <AppShell title="Аналитика">
      <PageHeader title="Аналитика" subtitle="Прибыль, потери на доливах и фейк-чеки" />

      <div className="card mb-5 flex flex-wrap items-center gap-3">
        <span className="text-xs text-muted">Период:</span>
        <input type="date" className="input text-sm py-1.5" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
        <span className="text-xs text-muted">—</span>
        <input type="date" className="input text-sm py-1.5" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
        <select className="input text-sm py-1.5" value={traderId} onChange={(e) => setTraderId(e.target.value)}>
          <option value="">Все трейдеры</option>
          {(analytics?.traders ?? []).map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <select className="input text-sm py-1.5" value={requisiteId} onChange={(e) => setRequisiteId(e.target.value)}>
          <option value="">Все реквизиты</option>
          {(analytics?.requisites ?? []).map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {(['day', 'week', 'month'] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                period === p ? 'bg-accent/15 text-accent' : 'bg-elevated text-muted hover:text-white'
              }`}
            >
              {p === 'day' ? 'Дни' : p === 'week' ? 'Недели' : 'Месяцы'}
            </button>
          ))}
        </div>
        {(dateStart || dateEnd || traderId || requisiteId) && (
          <button
            onClick={() => { setDateStart(''); setDateEnd(''); setTraderId(''); setRequisiteId(''); }}
            className="text-xs text-muted hover:text-accent"
          >
            Сбросить
          </button>
        )}
      </div>

      <div className="grid sm:grid-cols-4 gap-4 mb-6">
        <div className="card">
          <p className="text-xs text-muted">Прибыль по сделкам</p>
          <p className="text-xl font-bold mt-1">{formatUsdt(String(analytics?.total_profit ?? 0))}</p>
        </div>
        <div className="card">
          <p className="text-xs text-muted">Потери на доливах</p>
          <p className="text-xl font-bold mt-1 text-red-400">-{formatUsdt(String(analytics?.doliv_loss ?? 0))}</p>
        </div>
        <div className="card border border-orange-500/20">
          <p className="text-xs text-muted">Потери по фейк-чекам</p>
          <p className="text-xl font-bold mt-1 text-orange-400">-{formatUsdt(String(analytics?.fake_check_loss_usdt ?? 0))}</p>
          <p className="text-xs text-muted">{analytics?.fake_check_count ?? 0} шт.</p>
        </div>
        <div className="card border border-border/80">
          <p className="text-xs text-muted font-medium">Чистая прибыль</p>
          <p className={`text-xl font-bold mt-1 ${net >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {formatUsdt(String(net.toFixed(2)))}
          </p>
        </div>
      </div>
      <ChartCard title={`Динамика ${period === 'day' ? 'по дням' : period === 'week' ? 'по неделям' : 'по месяцам'}`}>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData.length ? chartData : [{ label: '—', profit: 0, doliv_loss: 0, fake_check_loss: 0, net_profit: 0 }]}>
            <XAxis dataKey="label" />
            <YAxis />
            <Tooltip
              contentStyle={{ background: '#141416', border: '1px solid #27272a', borderRadius: 8 }}
              formatter={(v: unknown) => [`${Number(v ?? 0).toFixed(2)} USDT`]}
            />
            <Legend />
            <Line type="monotone" dataKey="profit" stroke="#6366f1" strokeWidth={2} name="Прибыль" dot={false} />
            <Line type="monotone" dataKey="doliv_loss" stroke="#ef4444" strokeWidth={2} name="Потери на доливах" dot={false} />
            <Line type="monotone" dataKey="fake_check_loss" stroke="#f97316" strokeWidth={2} name="Потери по фейк-чекам" dot={false} />
            <Line type="monotone" dataKey="net_profit" stroke="#22c55e" strokeWidth={2} name="Чистая прибыль" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
    </AppShell>
  );
}

const EMP_ROLE_STYLE: Record<string, { badge: string; avatar: string }> = {
  admin:       { badge: 'bg-violet-500/20 text-violet-300 border-violet-500/30', avatar: 'bg-violet-500/30 text-violet-200' },
  trader:      { badge: 'bg-blue-500/20 text-blue-300 border-blue-500/30',       avatar: 'bg-blue-500/30 text-blue-200' },
  dolivshchik: { badge: 'bg-amber-500/20 text-amber-300 border-amber-500/30',    avatar: 'bg-amber-500/30 text-amber-200' },
};
const EMP_ROLE_LABELS: Record<string, string> = { admin: 'Админ', trader: 'Трейдер', dolivshchik: 'Доливщик' };

function relativeTime(isoDate: string | null): string {
  if (!isoDate) return 'никогда';
  const diff = Date.now() - new Date(isoDate).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'сегодня';
  if (days === 1) return 'вчера';
  if (days < 7) return `${days} дн. назад`;
  if (days < 30) return `${Math.floor(days / 7)} нед. назад`;
  return `${Math.floor(days / 30)} мес. назад`;
}

export function AdminEmployees({ scope = 'admin' }: { scope?: StatsScope }) {
  const statsApi = getStatsApi(scope);
  const queryPrefix = scope === 'owner' ? 'owner' : 'admin';
  const { data: employees = [] } = useQuery<EmployeeStats[]>({
    queryKey: [`${queryPrefix}-employees`],
    queryFn: statsApi.employees,
  });

  return (
    <AppShell title="Сотрудники">
      <PageHeader title="Сотрудники" subtitle={`Всего: ${employees.length}`} />
      <div className="overflow-x-auto rounded-xl border border-border/50">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 bg-elevated/60 text-xs text-muted font-medium">
              <th className="px-4 py-3 text-left">Сотрудник</th>
              <th className="px-4 py-3 text-left">Роль</th>
              <th className="px-4 py-3 text-right">Оборот</th>
              <th className="px-4 py-3 text-right">Прибыль</th>
              <th className="px-4 py-3 text-right">Операций</th>
              <th className="px-4 py-3 text-left w-40">Эффективность</th>
              <th className="px-4 py-3 text-left">Последний вход</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((u, idx) => {
              const style = EMP_ROLE_STYLE[u.role] ?? EMP_ROLE_STYLE.trader;
              const eff = Math.min(100, Math.max(0, parseFloat(u.efficiency)));
              const effColor = eff >= 75 ? 'bg-emerald-500' : eff >= 50 ? 'bg-amber-500' : 'bg-red-500';
              return (
                <tr key={u.id} className={`border-b border-border/30 hover:bg-elevated/40 transition-colors ${idx % 2 !== 0 ? 'bg-elevated/20' : ''}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0 ${style.avatar}`}>
                        {u.login.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <p className="font-semibold">@{u.login}</p>
                        <p className="text-xs text-muted">{u.full_name || '—'}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-1">
                      <span className={`inline-flex w-fit px-2 py-0.5 rounded-md text-[11px] font-medium border ${style.badge}`}>
                        {EMP_ROLE_LABELS[u.role] ?? u.role}
                      </span>
                      <span className={`text-[11px] ${u.is_active ? 'text-emerald-400' : 'text-zinc-500'}`}>
                        {u.is_active ? '● активен' : '○ неактивен'}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-medium">{formatUsdt(u.turnover_usdt)}</td>
                  <td className="px-4 py-3 text-right text-emerald-400 font-medium">{formatUsdt(u.profit)}</td>
                  <td className="px-4 py-3 text-right text-muted">{u.transactions}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-border/50">
                        <div className={`h-full rounded-full transition-all ${effColor}`} style={{ width: `${eff}%` }} />
                      </div>
                      <span className="text-xs text-muted w-10 text-right">{eff.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{relativeTime(u.last_login)}</td>
                </tr>
              );
            })}
            {employees.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-muted">Нет данных</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}

export function AdminSalaries() {
  const [period, setPeriod] = useState({ start: '', end: '' });
  const { data: salaries } = useQuery({
    queryKey: ['admin-salaries', period],
    queryFn: () => api.adminSalaries(period),
  });

  const columns: Column<SalaryRow>[] = [
    { key: 'name', header: 'Сотрудник', render: (r) => (
      <div>
        <p className="font-medium">@{r.login || r.full_name}</p>
        {r.login && r.full_name && <p className="text-xs text-muted">{r.full_name}</p>}
      </div>
    )},
    { key: 'role', header: 'Роль', render: (r) => r.role },
    { key: 'method', header: 'Метод', render: (r) => r.method },
    { key: 'turnover', header: 'Оборот', render: (r) => formatUsdt(r.turnover_usdt) },
    { key: 'profit', header: 'Прибыль', render: (r) => <span className="text-emerald-400">{formatUsdt(r.profit)}</span> },
    { key: 'salary', header: 'Зарплата', render: (r) => formatUsdt(r.salary) },
  ];

  return (
    <AppShell title="Зарплаты">
      <PageHeader title="Зарплаты" subtitle="Расчёт по периоду и индивидуальным ставкам" />
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="text-xs text-muted">
          Начало
          <input className="input mt-1" type="date" value={period.start} onChange={(e) => setPeriod((prev) => ({ ...prev, start: e.target.value }))} />
        </label>
        <label className="text-xs text-muted">
          Конец
          <input className="input mt-1" type="date" value={period.end} onChange={(e) => setPeriod((prev) => ({ ...prev, end: e.target.value }))} />
        </label>
      </div>
      <DataTable columns={columns} data={salaries ?? []} keyField="user_id" />
    </AppShell>
  );
}

export function AdminStatements() {
  const [period, setPeriod] = useState({ start: '', end: '' });
  const { data: statements } = useQuery({
    queryKey: ['admin-statements', period],
    queryFn: () => api.adminStatements(period),
  });

  return (
    <AppShell title="Ведомости">
      <PageHeader title="Ведомости" subtitle="Финансовая сводка из закрытых сделок и расчёта зарплат" />
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="text-xs text-muted">
          Начало
          <input className="input mt-1" type="date" value={period.start} onChange={(e) => setPeriod((prev) => ({ ...prev, start: e.target.value }))} />
        </label>
        <label className="text-xs text-muted">
          Конец
          <input className="input mt-1" type="date" value={period.end} onChange={(e) => setPeriod((prev) => ({ ...prev, end: e.target.value }))} />
        </label>
      </div>
      <div className="grid sm:grid-cols-2 gap-4 mb-6">
        {(statements?.cards ?? []).map((c) => (
          <div key={c.label} className="card"><p className="text-xs text-muted">{c.label}</p><p className="text-xl font-bold mt-1">{formatUsdt(c.value)}</p></div>
        ))}
      </div>
      <ul className="space-y-2">
        {(statements?.items ?? []).map((s: StatementRow) => (
          <li key={s.item} className="flex justify-between py-2 border-b border-border/50 text-sm">
            <span>{s.item}</span>
            <span className={`font-medium ${s.kind === 'expense' ? 'text-red-400' : s.kind === 'income' ? 'text-emerald-400' : ''}`}>{formatUsdt(s.amount)}</span>
          </li>
        ))}
      </ul>
    </AppShell>
  );
}

const SECTION_LABELS: Record<string, { label: string; icon: string }> = {
  dolivs:      { label: 'Доливы',      icon: '💧' },
  requests:    { label: 'Заявки',      icon: '📋' },
  settings:    { label: 'Настройки',   icon: '⚙️' },
  users:       { label: 'Пользователи',icon: '👥' },
  requisites:  { label: 'Реквизиты',   icon: '🏦' },
  stats:       { label: 'Статистика',  icon: '📊' },
  receipts:    { label: 'Чеки',        icon: '🧾' },
};

const ACTION_META: Record<string, { label: string; color: string; title: string }> = {
  view:   { label: 'Просмотр',  color: 'bg-sky-500/20 text-sky-300 border-sky-500/30',     title: 'Может видеть данные раздела' },
  create: { label: 'Создание',  color: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30', title: 'Может создавать новые записи' },
  edit:   { label: 'Изменение', color: 'bg-amber-500/20 text-amber-300 border-amber-500/30',   title: 'Может редактировать записи' },
  delete: { label: 'Удаление',  color: 'bg-red-500/20 text-red-300 border-red-500/30',      title: 'Может удалять записи' },
  export: { label: 'Экспорт',   color: 'bg-violet-500/20 text-violet-300 border-violet-500/30', title: 'Может выгружать данные' },
};

const ROLE_META: Record<string, { label: string; color: string; desc: string }> = {
  trader:      { label: 'Трейдер',    color: 'text-blue-400',   desc: 'Работает с реквизитами и заявками' },
  dolivshchik: { label: 'Доливщик',   color: 'text-amber-400',  desc: 'Исполняет заявки на долив' },
  admin:       { label: 'Администратор', color: 'text-accent',  desc: 'Полный доступ к системе' },
};

const ALL_ACTIONS = ['view', 'create', 'edit', 'delete', 'export'];

export function AdminRoles() {
  const { data: roles, isLoading } = useQuery({ queryKey: ['admin-roles'], queryFn: api.adminRoles });

  const sections = Array.from(
    new Set((roles ?? []).flatMap((r: RolePermissions) => Object.keys(r.permissions)))
  );

  if (isLoading) {
    return (
      <AppShell title="Роли и права">
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Роли и права">
      <PageHeader
        title="Роли и права"
        subtitle="Справочная матрица прав (только просмотр; изменения через API недоступны)"
      />

      <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
        Матрица прав носит информационный характер и не применяется на уровне API.
      </div>

      {/* Role summary cards */}
      <div className="mb-6 grid sm:grid-cols-3 gap-3">
        {(roles ?? []).map((r: RolePermissions) => {
          const meta = ROLE_META[r.role] ?? { label: r.role, color: 'text-white', desc: '' };
          const total = sections.reduce((s, sec) => s + (r.permissions[sec]?.length ?? 0), 0);
          const max = sections.length * ALL_ACTIONS.length;
          return (
            <div key={r.role} className="card flex items-start gap-3">
              <div className="flex-1">
                <p className={`font-semibold ${meta.color}`}>{meta.label}</p>
                <p className="text-xs text-muted mt-0.5">{meta.desc}</p>
                <div className="mt-2 h-1.5 rounded-full bg-border/50">
                  <div
                    className="h-full rounded-full bg-accent/70 transition-all"
                    style={{ width: `${max ? (total / max) * 100 : 0}%` }}
                  />
                </div>
                <p className="text-xs text-muted mt-1">{total} из {max} прав</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Permission matrix */}
      <div className="overflow-x-auto rounded-xl border border-border/50">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 bg-elevated/60">
              <th className="px-4 py-3 text-left text-xs text-muted font-medium w-44">Раздел</th>
              {(roles ?? []).map((r: RolePermissions) => {
                const meta = ROLE_META[r.role] ?? { label: r.role, color: 'text-white', desc: '' };
                return (
                  <th key={r.role} className="px-4 py-3 text-left">
                    <div>
                      <p className={`font-semibold text-sm ${meta.color}`}>{meta.label}</p>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sections.map((section, idx) => {
              const secMeta = SECTION_LABELS[section] ?? { label: section, icon: '📁' };
              return (
                <tr key={section} className={`border-b border-border/30 ${idx % 2 === 0 ? '' : 'bg-elevated/20'} hover:bg-elevated/40 transition-colors`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span>{secMeta.icon}</span>
                      <span className="font-medium text-white">{secMeta.label}</span>
                    </div>
                  </td>
                  {(roles ?? []).map((role: RolePermissions) => {
                    const cur = role.permissions[section] ?? [];
                    return (
                      <td key={role.role} className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5 items-center">
                          {ALL_ACTIONS.map((action) => {
                            const am = ACTION_META[action];
                            const on = cur.includes(action);
                            return (
                              <span
                                key={action}
                                title={am.title}
                                className={`px-2 py-0.5 rounded-md text-[11px] font-medium border select-none ${
                                  on
                                    ? am.color
                                    : 'bg-transparent text-muted/40 border-border/30'
                                }`}
                              >
                                {on ? '✓ ' : ''}{am.label}
                              </span>
                            );
                          })}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-4 flex flex-wrap gap-3">
        <p className="text-xs text-muted self-center">Права доступа:</p>
        {ALL_ACTIONS.map((action) => {
          const am = ACTION_META[action];
          return (
            <span key={action} className={`px-2 py-0.5 rounded-md text-[11px] font-medium border ${am.color}`}>
              {am.label}
            </span>
          );
        })}
      </div>
    </AppShell>
  );
}

export function AdminSettings() {
  const qc = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ['admin-settings'], queryFn: api.adminSettings });
  const [form, setForm] = useState({
    currency: 'RUB',
    timezone: 'Europe/Moscow',
    default_profit_percent: '12',
    trader_salary_percent: '20',
    doliv_salary_percent: '1',
    date_format: 'DD.MM.YYYY',
    receipt_formats: 'JPG, PNG, PDF',
    max_upload_mb: '10',
  });

  useEffect(() => {
    if (!settings) return;
    setForm({
      currency: settings.currency,
      timezone: settings.timezone,
      default_profit_percent: settings.default_profit_percent,
      trader_salary_percent: settings.trader_salary_percent,
      doliv_salary_percent: settings.doliv_salary_percent,
      date_format: settings.date_format,
      receipt_formats: settings.receipt_formats.join(', '),
      max_upload_mb: String(settings.max_upload_mb),
    });
  }, [settings]);

  const update = useMutation({
    mutationFn: () => api.updateAdminSettings({
      currency: form.currency,
      timezone: form.timezone,
      default_profit_percent: form.default_profit_percent,
      trader_salary_percent: form.trader_salary_percent,
      doliv_salary_percent: form.doliv_salary_percent,
      date_format: form.date_format,
      receipt_formats: form.receipt_formats.split(',').map((item) => item.trim()).filter(Boolean),
      max_upload_mb: Number(form.max_upload_mb),
    } as Partial<AppSettings>),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-settings'] }),
  });

  const setField = (field: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <AppShell title="Настройки">
      <PageHeader
        title="Настройки"
        subtitle="Системные параметры сохраняются в базе"
        action={
          <button className="btn-primary" onClick={() => update.mutate()} disabled={update.isPending}>
            {update.isPending ? 'Сохранение...' : 'Сохранить'}
          </button>
        }
      />
      <form
        className="max-w-xl space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate();
        }}
      >
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-muted mb-1">Валюта</label>
            <input className="input" value={form.currency} onChange={(e) => setField('currency', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Часовой пояс</label>
            <input className="input" value={form.timezone} onChange={(e) => setField('timezone', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Процент прибыли по умолчанию</label>
            <input className="input" type="number" min="0" step="0.01" value={form.default_profit_percent} onChange={(e) => setField('default_profit_percent', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">% зарплаты трейдера</label>
            <input className="input" type="number" min="0" max="100" step="0.01" value={form.trader_salary_percent} onChange={(e) => setField('trader_salary_percent', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Ставка доливщика (USDT за долив, не %)</label>
            <input className="input" type="number" min="0" step="0.01" value={form.doliv_salary_percent} onChange={(e) => setField('doliv_salary_percent', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Формат даты</label>
            <input className="input" value={form.date_format} onChange={(e) => setField('date_format', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Форматы чеков</label>
            <input className="input" value={form.receipt_formats} onChange={(e) => setField('receipt_formats', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Максимальный размер файла, MB</label>
            <input className="input" type="number" min="1" max="100" value={form.max_upload_mb} onChange={(e) => setField('max_upload_mb', e.target.value)} required />
          </div>
        </div>
        {update.isSuccess && <p className="text-sm text-emerald-400">Настройки сохранены</p>}
        {update.isError && <p className="text-sm text-red-400">{update.error.message}</p>}
      </form>
    </AppShell>
  );
}
