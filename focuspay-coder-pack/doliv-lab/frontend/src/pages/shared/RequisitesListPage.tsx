import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, Link } from 'react-router-dom';
import { Eye } from 'lucide-react';
import { api, formatMoney, Requisite, statusLabel } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { StatusBadge } from '../../components/ui/StatusBadge';

interface RequisitesListPageProps {
  role: 'admin' | 'trader' | 'teamlead';
}

export function RequisitesListPage({ role }: RequisitesListPageProps) {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const basePath =
    role === 'admin' ? '/admin/requisites' : role === 'teamlead' ? '/teamlead/requisites' : '/trader/requisites';
  const useAdminApi = role === 'admin' || role === 'teamlead';

  const adminParams = useAdminApi ? {
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(search ? { search } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  } : undefined;

  const { data: requisites, isLoading, isError, refetch } = useQuery({
    queryKey: ['requisites', role, statusFilter, search, dateFrom, dateTo],
    queryFn: () =>
      useAdminApi
        ? api.adminRequisites(adminParams)
        : api.listRequisites(statusFilter || undefined),
  });

  const filtered = useAdminApi
    ? (requisites ?? [])
    : (requisites ?? []).filter(
        (r) => !search || r.name.toLowerCase().includes(search.toLowerCase()),
      );

  const columns: Column<Requisite>[] = [
    { key: 'id', header: 'ID', render: (r) => `#${r.id}` },
    { key: 'name', header: 'Название', render: (r) => <span className="font-medium text-[#fafafa]">{r.name}</span> },
    ...(role === 'teamlead'
      ? [{ key: 'trader', header: 'Трейдер', render: (r: Requisite) => r.trader_name || `#${r.trader_id}` }]
      : []),
    { key: 'total', header: 'Сумма', render: (r) => formatMoney(r.total_amount) },
    { key: 'rate', header: 'Курс', render: (r) => r.target_rate },
    {
      key: 'status',
      header: 'Статус',
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: 'float',
      header: 'Float',
      render: (r) => (r.float_rub != null ? formatMoney(r.float_rub) : '—'),
    },
    {
      key: '',
      header: '',
      render: (r) => (
        <button
          onClick={(e) => { e.stopPropagation(); navigate(`${basePath}/${r.id}`); }}
          className="text-muted hover:text-accent p-1"
        >
          <Eye size={16} />
        </button>
      ),
    },
  ];

  return (
    <AppShell
      title={role === 'trader' ? 'Сессии' : 'Реквизиты'}
      search={search}
      onSearchChange={setSearch}
      searchPlaceholder={role === 'trader' ? 'Поиск по сессиям...' : 'Поиск по реквизитам...'}
    >
      <PageHeader
        title={role === 'trader' ? 'История сессий' : 'Реквизиты'}
        subtitle={
          role === 'trader'
            ? `Только просмотр. Новая работа — на странице «Карты». Всего: ${filtered.length}`
            : `Всего: ${filtered.length}`
        }
        action={
          role === 'trader' ? (
            <Link to="/trader/assets" className="btn-primary text-sm">К картам</Link>
          ) : undefined
        }
      />

      {isError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center justify-between gap-3">
          <span>Не удалось загрузить данные</span>
          <button type="button" className="text-accent hover:text-accent-hover shrink-0" onClick={() => void refetch()}>
            Повторить
          </button>
        </div>
      )}

      {useAdminApi && (
        <div className="card mb-4 flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted">Дата создания:</span>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted">с</label>
            <input type="date" className="input py-1.5" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted">по</label>
            <input type="date" className="input py-1.5" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          {(dateFrom || dateTo) && (
            <button onClick={() => { setDateFrom(''); setDateTo(''); }} className="text-xs text-muted hover:text-accent">
              Сбросить
            </button>
          )}
        </div>
      )}

      <div className="flex gap-2 mb-4 flex-wrap">
        {['', 'active', 'in_work', 'awaiting_doliv', 'doliv_in_progress', 'closed', 'archive'].map((s) => (
          <button
            key={s || 'all'}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              statusFilter === s ? 'bg-accent/15 text-accent' : 'bg-elevated text-muted hover:text-white'
            }`}
          >
            {s ? statusLabel(s) : 'Все'}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-muted text-sm">Загрузка...</p>
      ) : (
        <DataTable
          columns={columns}
          data={filtered}
          keyField="id"
          onRowClick={(r) => navigate(`${basePath}/${r.id}`)}
        />
      )}
    </AppShell>
  );
}
