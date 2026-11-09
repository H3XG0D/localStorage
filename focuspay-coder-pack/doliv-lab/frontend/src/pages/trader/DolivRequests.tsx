import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api, formatMoney } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import type { DolivRequest } from '../../api/client';

export default function TraderDolivRequests() {
  const navigate = useNavigate();
  const { data: requests, isLoading, isError } = useQuery({
    queryKey: ['trader-doliv-requests'],
    queryFn: api.traderDolivRequests,
    refetchInterval: 30000,
  });

  const columns: Column<DolivRequest>[] = [
    { key: 'id', header: 'ID', render: (r) => <span className="text-muted">#{r.id}</span> },
    { key: 'name', header: 'Реквизит', render: (r) => r.requisite_name ?? `#${r.requisite_id}` },
    { key: 'required_amount', header: 'Сумма долива', render: (r) => formatMoney(r.required_amount) },
    { key: 'rate', header: 'Целевой курс', render: (r) => r.target_rate ?? '—' },
    {
      key: 'dolivshchik',
      header: 'Доливщик',
      render: (r) => r.assigned_dolivshchik_name ?? <span className="text-muted">Не назначен</span>,
    },
    { key: 'sent_at', header: 'Отправлено', render: (r) => new Date(r.sent_at).toLocaleString('ru') },
    { key: 'status', header: 'Статус', render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <AppShell title="Заявки на долив">
      <PageHeader title="Заявки на долив" subtitle="Реквизиты, отправленные на долив" />
      {isError && (
        <p className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
          Не удалось загрузить заявки. Попробуйте обновить страницу.
        </p>
      )}
      <DataTable
        columns={columns}
        data={requests ?? []}
        keyField="id"
        onRowClick={(r) => navigate(`/trader/requisites/${r.requisite_id}`)}
        emptyMessage={isLoading ? 'Загрузка...' : 'Нет заявок на долив'}
      />
    </AppShell>
  );
}
