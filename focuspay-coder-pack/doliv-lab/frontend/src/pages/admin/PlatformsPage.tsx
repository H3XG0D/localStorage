import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type MerchantPartner } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { Modal } from '../../components/ui/Modal';

export default function AdminPlatformsPage() {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [callback, setCallback] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [err, setErr] = useState('');
  const [created, setCreated] = useState<{ api_key: string; secret: string } | null>(null);

  const { data: partners } = useQuery({
    queryKey: ['admin-merchant-partners'],
    queryFn: api.adminMerchantPartners,
  });

  const create = useMutation({
    mutationFn: () =>
      api.createMerchantPartner({
        name: name.trim(),
        callback_url_default: callback.trim() || undefined,
      }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['admin-merchant-partners'] });
      setCreated({ api_key: p.api_key, secret: p.secret || '' });
      setName('');
      setCallback('');
      setCreateOpen(false);
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const patch = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { is_active?: boolean; name?: string } }) =>
      api.updateMerchantPartner(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-merchant-partners'] });
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const cols: Column<MerchantPartner>[] = [
    { key: 'id', header: 'ID', render: (p) => `#${p.id}` },
    { key: 'name', header: 'Площадка', render: (p) => p.name },
    {
      key: 'key',
      header: 'API key',
      render: (p) => <span className="font-mono text-xs break-all">{p.api_key}</span>,
    },
    { key: 'hint', header: 'Secret', render: (p) => p.secret_hint || '—' },
    {
      key: 'cb',
      header: 'Callback',
      render: (p) => <span className="text-xs break-all">{p.callback_url_default || '—'}</span>,
    },
    {
      key: 'on',
      header: 'Статус',
      render: (p) => (p.is_active ? 'вкл' : 'выкл'),
    },
    {
      key: 'act',
      header: '',
      render: (p) => (
        <button
          type="button"
          className="btn-ghost text-xs"
          disabled={patch.isPending}
          onClick={() => patch.mutate({ id: p.id, data: { is_active: !p.is_active } })}
        >
          {p.is_active ? 'Выключить' : 'Включить'}
        </button>
      ),
    },
  ];

  return (
    <AppShell title="Площадки">
      <PageHeader
        title="Площадки"
        subtitle="Merchant API · HMAC как Payfast · общий пул карт"
        action={
          <button className="btn-primary" onClick={() => { setCreateOpen(true); setErr(''); }}>
            Подключить площадку
          </button>
        }
      />
      {err && <p className="text-danger text-sm mb-4">{err}</p>}
      {created && (
        <div className="card p-4 mb-4">
          <p className="font-semibold mb-1">Ключи показаны один раз</p>
          <pre className="text-xs whitespace-pre-wrap break-all">
            {`api_key=${created.api_key}\nsecret=${created.secret}`}
          </pre>
        </div>
      )}
      <DataTable columns={cols} data={partners ?? []} keyField="id" />

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Новая площадка">
        <div className="space-y-3">
          <input
            className="input w-full"
            placeholder="Название (FocusPay, …)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="input w-full"
            placeholder="Callback URL (необязательно)"
            value={callback}
            onChange={(e) => setCallback(e.target.value)}
          />
          {err && <p className="text-danger text-sm">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Создать ключи
          </button>
        </div>
      </Modal>
    </AppShell>
  );
}
