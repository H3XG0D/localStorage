import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Plus, Eye } from 'lucide-react';
import { api, formatMoney, Requisite, statusLabel } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Modal } from '../../components/ui/Modal';

interface RequisitesListPageProps {
  role: 'admin' | 'trader';
}

export function RequisitesListPage({ role }: RequisitesListPageProps) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [total, setTotal] = useState('');
  const [rate, setRate] = useState('');
  const [comment, setComment] = useState('');
  const [createError, setCreateError] = useState('');

  const basePath = role === 'admin' ? '/admin/requisites' : '/trader/requisites';

  const adminParams = role === 'admin' ? {
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(search ? { search } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  } : undefined;

  const { data: requisites, isLoading, isError, refetch } = useQuery({
    queryKey: ['requisites', role, statusFilter, search, dateFrom, dateTo],
    queryFn: () =>
      role === 'admin'
        ? api.adminRequisites(adminParams)
        : api.listRequisites(statusFilter || undefined),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createRequisite({
        name,
        total_amount: parseFloat(total),
        target_rate: parseFloat(rate),
        comment: comment || undefined,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['requisites'] });
      setModalOpen(false);
      setName(''); setTotal(''); setRate(''); setComment('');
      setCreateError('');
      navigate(`${basePath}/${r.id}`);
    },
    onError: (err: Error) => setCreateError(err.message),
  });

  const filtered = role === 'admin'
    ? (requisites ?? [])
    : (requisites ?? []).filter(
        (r) => !search || r.name.toLowerCase().includes(search.toLowerCase()),
      );

  const columns: Column<Requisite>[] = [
    { key: 'id', header: 'ID', render: (r) => <span className="text-muted">#{r.id}</span> },
    { key: 'name', header: 'Реквизит', render: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'amount', header: 'Сумма', render: (r) => formatMoney(r.total_amount) },
    { key: 'rate', header: 'Целевой курс', render: (r) => r.target_rate },
    { key: 'status', header: 'Статус', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions',
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
      title="Реквизиты"
      search={search}
      onSearchChange={setSearch}
      searchPlaceholder="Поиск по реквизитам..."
    >
      <PageHeader
        title="Реквизиты"
        subtitle={`Всего: ${filtered.length}`}
        action={
          role === 'trader' ? (
            <button className="btn-primary flex items-center gap-2" onClick={() => setModalOpen(true)}>
              <Plus size={16} /> Добавить реквизит
            </button>
          ) : undefined
        }
      />

      {isError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center justify-between gap-3">
          <span>Не удалось загрузить реквизиты</span>
          <button type="button" className="text-accent hover:text-accent-hover shrink-0" onClick={() => void refetch()}>
            Повторить
          </button>
        </div>
      )}

      {role === 'admin' && (
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

      {role === 'trader' && (
        <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Новый реквизит">
          <form
            className="space-y-4"
            onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          >
            {createError && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {createError}
              </div>
            )}
            <div>
              <label className="block text-xs text-muted mb-1">Название</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} required placeholder="Tinkoff **** 5678" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted mb-1">Сумма (₽)</label>
                <input className="input" type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} required />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Целевой курс</label>
                <input className="input" type="number" step="0.0001" value={rate} onChange={(e) => setRate(e.target.value)} required />
              </div>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Комментарий</label>
              <textarea className="input" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
            </div>
            <button type="submit" className="btn-primary w-full" disabled={create.isPending}>
              Создать
            </button>
          </form>
        </Modal>
      )}
    </AppShell>
  );
}
