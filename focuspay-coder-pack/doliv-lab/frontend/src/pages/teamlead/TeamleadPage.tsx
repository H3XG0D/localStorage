import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, formatMoney, formatUsdt } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { StatCard } from '../../components/ui/StatCard';
import { Modal } from '../../components/ui/Modal';
import { Wallet, Users, Plus, Percent } from 'lucide-react';

type TeamRow = Awaited<ReturnType<typeof api.teamleadTraders>>[number];

const MODE_LABELS: Record<string, string> = {
  manual: 'ручной',
  rapira_snap: 'снимок Rapira',
  fixed: 'фиксированный',
};

export default function TeamleadPage() {
  const qc = useQueryClient();
  const { data: traders } = useQuery({ queryKey: ['teamlead-traders'], queryFn: api.teamleadTraders });
  const { data: summary } = useQuery({ queryKey: ['teamlead-summary'], queryFn: api.teamleadSummary });
  const { data: me } = useQuery({ queryKey: ['teamlead-me'], queryFn: api.teamleadMe });
  const { data: working } = useQuery({ queryKey: ['working-rate'], queryFn: api.workingRate });
  const { data: rapira } = useQuery({
    queryKey: ['rapira-rate'],
    queryFn: api.rapiraRate,
    refetchInterval: 60_000,
  });

  const pool = parseFloat(String(me?.pool_percent ?? summary?.pool_percent ?? me?.teamlead_percent ?? summary?.teamlead_percent ?? '12'));

  const [createOpen, setCreateOpen] = useState(false);
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [profitPct, setProfitPct] = useState('11');
  const [err, setErr] = useState('');

  const [editRow, setEditRow] = useState<TeamRow | null>(null);
  const [editPct, setEditPct] = useState('');
  const [editName, setEditName] = useState('');

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['teamlead-traders'] });
    qc.invalidateQueries({ queryKey: ['teamlead-summary'] });
  };

  const keepPreview = (pctStr: string) => {
    const p = parseFloat(pctStr);
    if (Number.isNaN(p)) return '—';
    return Math.max(0, pool - p).toFixed(2);
  };

  const pause = useMutation({
    mutationFn: (id: number) => api.teamleadPause(id),
    onSuccess: invalidate,
  });
  const resume = useMutation({
    mutationFn: (id: number) => api.teamleadResume(id),
    onSuccess: invalidate,
  });

  const create = useMutation({
    mutationFn: () =>
      api.teamleadCreateTrader({
        login: login.trim(),
        password: password.trim(),
        full_name: fullName.trim(),
        profit_percent: parseFloat(profitPct),
      }),
    onSuccess: () => {
      invalidate();
      setCreateOpen(false);
      setLogin('');
      setPassword('');
      setFullName('');
      setProfitPct(String(Math.min(11, pool)));
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const update = useMutation({
    mutationFn: () =>
      api.teamleadUpdateTrader(editRow!.id, {
        full_name: editName.trim(),
        profit_percent: parseFloat(editPct),
      }),
    onSuccess: () => {
      invalidate();
      setEditRow(null);
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const cols: Column<TeamRow>[] = useMemo(
    () => [
      {
        key: 'name',
        header: 'Трейдер',
        render: (r) => (
          <div>
            <div className="font-medium">{r.full_name}</div>
            <div className="text-xs text-muted">{r.login}</div>
          </div>
        ),
      },
      {
        key: 'pct',
        header: '% трейдера',
        render: (r) => (
          <button
            type="button"
            className="text-accent text-sm"
            onClick={() => {
              setEditRow(r);
              setEditPct(r.profit_percent ?? '11');
              setEditName(r.full_name);
              setErr('');
            }}
          >
            {r.profit_percent ?? '—'}%
          </button>
        ),
      },
      {
        key: 'keep',
        header: 'Остаток TL',
        render: (r) => (
          <span className="text-sm text-muted">
            {r.teamlead_keep_percent != null ? `${r.teamlead_keep_percent}%` : '—'}
          </span>
        ),
      },
      { key: 'float', header: 'Float', render: (r) => formatMoney(r.total_float_rub) },
      {
        key: 'comm',
        header: 'Credits',
        render: (r) => (r.commissions_usdt != null ? formatUsdt(r.commissions_usdt) : '—'),
      },
      { key: 'avail', header: 'Доступно', render: (r) => (r.token_available != null ? formatUsdt(r.token_available) : '—') },
      { key: 'held', header: 'Холд', render: (r) => (r.token_held != null ? formatUsdt(r.token_held) : '—') },
      {
        key: 'act',
        header: '',
        render: (r) =>
          r.is_active ? (
            <button className="text-sm text-danger" onClick={() => pause.mutate(r.id)}>Пауза</button>
          ) : (
            <button className="text-sm text-accent" onClick={() => resume.mutate(r.id)}>Вкл</button>
          ),
      },
    ],
    [pause, resume],
  );

  return (
    <AppShell title="Команда">
      <div className="mb-4 rounded-xl border border-border bg-elevated px-4 py-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs text-muted">Рабочий курс офиса</p>
          <p className="text-lg font-semibold text-[#fafafa]">
            1 USDT = <span className="text-accent">{working?.rate ?? '—'}</span> ₽
          </p>
        </div>
        <p className="text-sm text-muted">
          {working ? MODE_LABELS[working.mode] || working.mode : '—'}
          {working?.valid_until
            ? ` · до ${new Date(working.valid_until).toLocaleString('ru-RU')}`
            : ''}
          {rapira
            ? ` · Rapira ${rapira.rate}${rapira.source === 'fallback' ? ' fallback' : ''}`
            : ''}
        </p>
      </div>

      <PageHeader
        title="Тимлид"
        subtitle={`Пул маржи ${pool}% — раздаёте трейдерам; остаток ваш на закрытии`}
        action={
          <div className="flex flex-wrap gap-2">
            <Link className="btn-secondary text-sm px-3 py-2" to="/teamlead/requisites">
              Сессии команды
            </Link>
            <button className="btn-primary flex items-center gap-2" onClick={() => { setCreateOpen(true); setErr(''); }}>
              <Plus size={16} /> Трейдер
            </button>
          </div>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <StatCard label="Трейдеров" value={String(summary?.traders_count ?? traders?.length ?? 0)} icon={Users} accent="#6366f1" />
        <StatCard label="Пул %" value={`${pool}%`} icon={Percent} accent="#a855f7" />
        <StatCard label="Мой плюс (credits)" value={formatUsdt(summary?.credits_usdt ?? 0)} icon={Wallet} accent="#22c55e" />
        <StatCard label="Доступно" value={formatUsdt(summary?.token_available ?? 0)} icon={Wallet} accent="#f59e0b" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 mb-6">
        <StatCard label="Баланс токена" value={formatUsdt(summary?.token_balance ?? 0)} icon={Wallet} accent="#22c55e" />
        <StatCard label="Float команды ₽" value={formatMoney(summary?.team_float_rub ?? 0)} icon={Wallet} accent="#38bdf8" />
      </div>
      <DataTable columns={cols} data={traders ?? []} keyField="id" />

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Новый трейдер">
        <div className="space-y-3">
          <div>
            <label className="field-label">Логин</label>
            <input className="input w-full" value={login} onChange={(e) => setLogin(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Пароль (от 12 символов)</label>
            <input className="input w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div>
            <label className="field-label">ФИО</label>
            <input className="input w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
          <div>
            <label className="field-label">% трейдера (из пула {pool}%)</label>
            <input
              className="input w-full"
              type="number"
              step="0.01"
              min="0"
              max={pool}
              value={profitPct}
              onChange={(e) => setProfitPct(e.target.value)}
            />
            <p className="text-xs text-muted mt-1">Вам останется {keepPreview(profitPct)}%</p>
          </div>
          {err && <p className="text-sm text-red-400">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={!login || !password || !fullName || create.isPending || parseFloat(profitPct) > pool}
            onClick={() => create.mutate()}
          >
            Создать
          </button>
        </div>
      </Modal>

      <Modal open={!!editRow} onClose={() => setEditRow(null)} title={`Правка: ${editRow?.login ?? ''}`}>
        <div className="space-y-3">
          <div>
            <label className="field-label">ФИО</label>
            <input className="input w-full" value={editName} onChange={(e) => setEditName(e.target.value)} />
          </div>
          <div>
            <label className="field-label">% трейдера (макс {pool}%)</label>
            <input
              className="input w-full"
              type="number"
              step="0.01"
              min="0"
              max={pool}
              value={editPct}
              onChange={(e) => setEditPct(e.target.value)}
            />
            <p className="text-xs text-muted mt-1">Вам останется {keepPreview(editPct)}%</p>
          </div>
          {err && <p className="text-sm text-red-400">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={update.isPending || parseFloat(editPct) > pool}
            onClick={() => update.mutate()}
          >
            Сохранить
          </button>
        </div>
      </Modal>
    </AppShell>
  );
}
