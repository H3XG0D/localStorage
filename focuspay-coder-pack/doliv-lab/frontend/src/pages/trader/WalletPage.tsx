import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Wallet } from 'lucide-react';
import { api, formatMoney, formatUsdt } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { StatCard } from '../../components/ui/StatCard';
import { DataTable, Column } from '../../components/ui/DataTable';

const NETWORKS = [
  { value: 'usdt_trc20', label: 'USDT TRC20 (fee $3)' },
  { value: 'btc', label: 'BTC (fee $2)' },
  { value: 'ltc', label: 'LTC (fee $2)' },
  { value: 'other', label: 'Other (fee $3)' },
];

export default function TraderWalletPage({ role = 'trader' }: { role?: 'trader' | 'teamlead' }) {
  const isTeamlead = role === 'teamlead';
  const qc = useQueryClient();
  const [kind, setKind] = useState<'deposit' | 'withdraw'>('deposit');
  const [amount, setAmount] = useState('');
  const [network, setNetwork] = useState('usdt_trc20');
  const [address, setAddress] = useState('');
  const [payoutAmount, setPayoutAmount] = useState('');
  const [error, setError] = useState('');

  const { data: wallet } = useQuery({
    queryKey: [isTeamlead ? 'teamlead-wallet' : 'trader-wallet'],
    queryFn: isTeamlead ? api.teamleadWallet : api.traderWallet,
  });
  const { data: ledger } = useQuery({
    queryKey: [isTeamlead ? 'teamlead-wallet-ledger' : 'trader-wallet-ledger'],
    queryFn: isTeamlead ? api.teamleadWalletLedger : api.traderWalletLedger,
  });
  const { data: floatData } = useQuery({
    queryKey: ['trader-float'],
    queryFn: api.traderFloat,
    enabled: !isTeamlead,
  });
  const { data: requests } = useQuery({
    queryKey: [isTeamlead ? 'teamlead-wallet-requests' : 'trader-wallet-requests'],
    queryFn: isTeamlead ? api.teamleadWalletRequests : api.traderWalletRequests,
  });

  const invalidateWallet = () => {
    qc.invalidateQueries({ queryKey: [isTeamlead ? 'teamlead-wallet' : 'trader-wallet'] });
    qc.invalidateQueries({ queryKey: [isTeamlead ? 'teamlead-wallet-ledger' : 'trader-wallet-ledger'] });
    qc.invalidateQueries({ queryKey: [isTeamlead ? 'teamlead-wallet-requests' : 'trader-wallet-requests'] });
    if (!isTeamlead) qc.invalidateQueries({ queryKey: ['trader-float'] });
  };

  const createReq = useMutation({
    mutationFn: () =>
      (isTeamlead ? api.createTeamleadWalletRequest : api.createWalletRequest)({
        kind,
        amount_usdt: parseFloat(amount),
        network,
        address: kind === 'withdraw' ? address : undefined,
      }),
    onSuccess: () => {
      invalidateWallet();
      setAmount('');
      setAddress('');
      setError('');
    },
    onError: (e: Error) => setError(e.message),
  });

  const payout = useMutation({
    mutationFn: () => api.traderPayout({ amount_usdt: parseFloat(payoutAmount) }),
    onSuccess: () => {
      invalidateWallet();
      setPayoutAmount('');
      setError('');
    },
    onError: (e: Error) => setError(e.message),
  });

  const reqCols: Column<NonNullable<typeof requests>[number]>[] = [
    { key: 'id', header: 'ID', render: (r) => `#${r.id}` },
    { key: 'kind', header: 'Тип', render: (r) => r.kind },
    { key: 'amount', header: 'USDT', render: (r) => formatUsdt(r.amount_usdt) },
    { key: 'fee', header: 'Fee', render: (r) => formatUsdt(r.fee_usdt) },
    { key: 'net', header: 'Сеть', render: (r) => r.network },
    { key: 'addr', header: 'Адрес', render: (r) => r.address || '—' },
    { key: 'status', header: 'Статус', render: (r) => r.status },
  ];

  const ledgerCols: Column<NonNullable<typeof ledger>[number]>[] = [
    { key: 'id', header: 'ID', render: (r) => `#${r.id}` },
    { key: 'type', header: 'Тип', render: (r) => r.entry_type },
    { key: 'amount', header: 'USDT', render: (r) => formatUsdt(r.amount) },
    { key: 'comment', header: 'Комментарий', render: (r) => r.comment || '—' },
    { key: 'at', header: 'Когда', render: (r) => new Date(r.created_at).toLocaleString('ru-RU') },
  ];

  const floatCols: Column<NonNullable<typeof floatData>['items'][number]>[] = [
    { key: 'id', header: 'Рек', render: (r) => `#${r.requisite_id} ${r.name}` },
    { key: 'status', header: 'Статус', render: (r) => r.status },
    { key: 'float', header: 'На карте', render: (r) => formatMoney(r.float_rub) },
  ];

  return (
    <AppShell title="Депозит">
      <PageHeader
        title={isTeamlead ? 'Депозит тимлида' : 'Рабочий депозит'}
        subtitle="Пополнение и вывод только после апрува админа. Это не страница команды."
      />
      <div className="grid gap-4 sm:grid-cols-3 mb-6">
        <StatCard label="Баланс" value={formatUsdt(wallet?.balance ?? 0)} icon={Wallet} accent="#22c55e" />
        <StatCard label="В холде" value={formatUsdt(wallet?.held ?? 0)} icon={Wallet} accent="#f59e0b" />
        <StatCard label="Доступно" value={formatUsdt(wallet?.available ?? 0)} icon={Wallet} accent="#6366f1" />
      </div>

      <div className="card p-4 mb-6">
        <h3 className="font-semibold mb-2 text-[#fafafa]">Заявка на депозит / вывод</h3>
        <div className="flex flex-wrap gap-2 mb-3">
          <button
            type="button"
            className={kind === 'deposit' ? 'btn-primary' : 'btn-ghost'}
            onClick={() => setKind('deposit')}
          >
            Пополнить
          </button>
          <button
            type="button"
            className={kind === 'withdraw' ? 'btn-primary' : 'btn-ghost'}
            onClick={() => setKind('withdraw')}
          >
            Вывести
          </button>
        </div>
        <div className="flex flex-wrap gap-2 items-end">
          <label className="text-sm text-[#fafafa]">
            USDT
            <input
              className="input mt-1"
              type="number"
              min="0"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          {kind === 'withdraw' && (
            <>
              <label className="text-sm text-[#fafafa]">
                Сеть
                <select className="input mt-1" value={network} onChange={(e) => setNetwork(e.target.value)}>
                  {NETWORKS.map((n) => (
                    <option key={n.value} value={n.value}>
                      {n.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm text-[#fafafa] min-w-[200px] flex-1">
                Кошелёк
                <input
                  className="input mt-1 w-full"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="адрес"
                />
              </label>
            </>
          )}
          <button
            className="btn-primary"
            disabled={
              !amount ||
              parseFloat(amount) <= 0 ||
              createReq.isPending ||
              (kind === 'withdraw' && !address.trim())
            }
            onClick={() => createReq.mutate()}
          >
            Отправить на апрув
          </button>
        </div>
        {error && <p className="text-danger text-sm mt-2">{error}</p>}
      </div>

      <h3 className="font-semibold mb-2 text-[#fafafa]">Мои заявки</h3>
      <DataTable columns={reqCols} data={requests ?? []} keyField="id" />

      {!isTeamlead && (
        <>
          <div className="card mb-6 mt-6 p-4">
            <h3 className="font-semibold mb-2 text-[#fafafa]">Возврат USDT с карт (+1%)</h3>
            <p className="text-xs text-muted mb-3">Не очередь выплат мерчанту. Начисляет возврат с float и бонус 1%.</p>
            <div className="flex flex-wrap gap-2 items-end">
              <label className="text-sm text-[#fafafa]">
                USDT
                <input className="input mt-1" value={payoutAmount} onChange={(e) => setPayoutAmount(e.target.value)} />
              </label>
              <button
                className="btn-primary"
                disabled={!payoutAmount || payout.isPending}
                onClick={() => payout.mutate()}
              >
                Начислить возврат + бонус
              </button>
            </div>
          </div>

          <h3 className="font-semibold mb-2 text-[#fafafa]">На картах (float)</h3>
          <p className="text-sm text-muted mb-3">Всего: {formatMoney(floatData?.total_float_rub ?? 0)}</p>
          <DataTable columns={floatCols} data={floatData?.items ?? []} keyField="requisite_id" />
        </>
      )}

      <h3 className="font-semibold mt-8 mb-2 text-[#fafafa]">История токена</h3>
      <DataTable columns={ledgerCols} data={ledger ?? []} keyField="id" />
    </AppShell>
  );
}
