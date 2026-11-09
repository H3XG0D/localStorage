import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, formatMoney, formatUsdt } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';

export default function AdminBridgeOpsPage() {
  const qc = useQueryClient();
  const [amount, setAmount] = useState('10000');
  const [phone, setPhone] = useState('+79001112233');
  const [error, setError] = useState('');
  const [partnerName, setPartnerName] = useState('partner-lab');
  const [createdPartner, setCreatedPartner] = useState<{ api_key: string; secret: string } | null>(null);
  const [bridgeKey, setBridgeKey] = useState<string | null>(null);

  const { data: pending } = useQuery({
    queryKey: ['admin-wallet-requests'],
    queryFn: () => api.adminWalletRequests(true),
  });
  const { data: balances } = useQuery({
    queryKey: ['admin-card-balances'],
    queryFn: api.adminCardBalances,
  });

  const resolve = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      api.resolveWalletRequest(id, { approve }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-wallet-requests'] });
      setError('');
    },
    onError: (e: Error) => setError(e.message),
  });

  const createJob = useMutation({
    mutationFn: () =>
      api.adminCreatePayoutJob({
        amount_rub: parseFloat(amount),
        pay_method: 'sbp',
        requisites: { phone, method: 'sbp' },
        source: 'manual',
      }),
    onSuccess: () => setError(''),
    onError: (e: Error) => setError(e.message),
  });

  const createPartner = useMutation({
    mutationFn: () => api.createMerchantPartner({ name: partnerName }),
    onSuccess: (p) => {
      setCreatedPartner({ api_key: p.api_key, secret: p.secret || '' });
    },
    onError: (e: Error) => setError(e.message),
  });

  const createBridge = useMutation({
    mutationFn: () => api.createBridgeKey('focuspay'),
    onSuccess: (r) => setBridgeKey(r.raw_key),
    onError: (e: Error) => setError(e.message),
  });

  const cols: Column<NonNullable<typeof pending>[number]>[] = [
    { key: 'id', header: 'ID', render: (r) => `#${r.id}` },
    { key: 'user', header: 'User', render: (r) => String(r.user_id) },
    { key: 'kind', header: 'Тип', render: (r) => r.kind },
    { key: 'amt', header: 'USDT', render: (r) => formatUsdt(r.amount_usdt) },
    { key: 'fee', header: 'Fee', render: (r) => formatUsdt(r.fee_usdt) },
    { key: 'net', header: 'Сеть', render: (r) => r.network },
    { key: 'addr', header: 'Адрес', render: (r) => r.address || '—' },
    {
      key: 'act',
      header: '',
      render: (r) => (
        <div className="flex gap-1">
          <button className="btn-primary text-xs" onClick={() => resolve.mutate({ id: r.id, approve: true })}>
            OK
          </button>
          <button className="btn-ghost text-xs" onClick={() => resolve.mutate({ id: r.id, approve: false })}>
            Нет
          </button>
        </div>
      ),
    },
  ];

  return (
    <AppShell title="Мост / апрувы">
      <PageHeader title="Апрувы и мост" subtitle="Wallet requests · payout jobs · merchant / bridge keys" />
      {error && <p className="text-danger text-sm mb-4">{error}</p>}

      <div className="card p-4 mb-6">
        <h3 className="font-semibold mb-2">Float на картах</h3>
        <p className="text-sm">Всего: {formatMoney(balances?.total_float_rub ?? 0)}</p>
        <p className="text-xs text-muted">Трейдеров с float: {balances?.traders_with_float ?? 0}</p>
      </div>

      <h3 className="font-semibold mb-2">Заявки депозит/вывод</h3>
      <DataTable columns={cols} data={pending ?? []} keyField="id" />

      {(import.meta.env.DEV || import.meta.env.VITE_ROLE_SWITCHER === 'true') && (
        <>
      <div className="card p-4 mt-6 mb-6">
        <h3 className="font-semibold mb-2">Создать payout job (смок)</h3>
        <div className="flex flex-wrap gap-2 items-end">
          <label className="text-sm">
            ₽
            <input className="input mt-1" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="text-sm">
            СБП телефон
            <input className="input mt-1" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <button className="btn-primary" disabled={createJob.isPending} onClick={() => createJob.mutate()}>
            Создать
          </button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="card p-4">
          <h3 className="font-semibold mb-2">Merchant partner</h3>
          <input className="input mb-2" value={partnerName} onChange={(e) => setPartnerName(e.target.value)} />
          <button className="btn-primary" onClick={() => createPartner.mutate()}>
            Создать ключи
          </button>
          {createdPartner && (
            <pre className="text-xs mt-3 whitespace-pre-wrap break-all">
              api_key={createdPartner.api_key}
              {'\n'}
              secret={createdPartner.secret}
            </pre>
          )}
        </div>
        <div className="card p-4">
          <h3 className="font-semibold mb-2">Bridge key (FocusPay)</h3>
          <button className="btn-primary" onClick={() => createBridge.mutate()}>
            Выпустить X-Bridge-Key
          </button>
          {bridgeKey && <pre className="text-xs mt-3 break-all">{bridgeKey}</pre>}
        </div>
      </div>
        </>
      )}
    </AppShell>
  );
}
