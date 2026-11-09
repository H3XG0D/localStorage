import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, formatUsdt } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { Modal } from '../../components/ui/Modal';
import type { WorkToken } from '../../api/client';

export default function AdminTokensPage() {
  const qc = useQueryClient();
  const { data: tokens } = useQuery({ queryKey: ['work-tokens'], queryFn: api.listWorkTokens });
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: api.adminUsers });

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [memberId, setMemberId] = useState('');
  const [exempt, setExempt] = useState(false);
  const [depositOpen, setDepositOpen] = useState<WorkToken | null>(null);
  const [amount, setAmount] = useState('');
  const [apiKeyMsg, setApiKeyMsg] = useState('');
  const [err, setErr] = useState('');

  const create = useMutation({
    mutationFn: () =>
      api.createWorkToken({
        name,
        deposit_exempt: exempt,
        member_user_ids: memberId ? [Number(memberId)] : [],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['work-tokens'] });
      setCreateOpen(false);
      setName('');
      setMemberId('');
      setExempt(false);
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const deposit = useMutation({
    mutationFn: () => api.depositWorkToken(depositOpen!.id, parseFloat(amount)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['work-tokens'] });
      setDepositOpen(null);
      setAmount('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const makeKey = useMutation({
    mutationFn: (tokenId: number) => api.createApiKey(tokenId, 'lab-key'),
    onSuccess: (r) => setApiKeyMsg(r.raw_key ? `API key (скопируй сейчас): ${r.raw_key}` : 'created'),
  });

  const cols: Column<WorkToken>[] = [
    { key: 'id', header: 'ID', render: (t) => `#${t.id}` },
    { key: 'name', header: 'Токен', render: (t) => t.name },
    { key: 'bal', header: 'Баланс', render: (t) => formatUsdt(t.balance ?? 0) },
    { key: 'held', header: 'Холд', render: (t) => formatUsdt(t.held ?? 0) },
    { key: 'avail', header: 'Доступно', render: (t) => formatUsdt(t.available ?? 0) },
    { key: 'ex', header: 'Exempt', render: (t) => (t.deposit_exempt ? 'да' : 'нет') },
    {
      key: 'act',
      header: '',
      render: (t) => (
        <div className="flex gap-2">
          <button className="text-sm text-accent" onClick={() => { setDepositOpen(t); setErr(''); }}>Депозит</button>
          <button className="text-sm text-muted" onClick={() => makeKey.mutate(t.id)}>API key</button>
        </div>
      ),
    },
  ];

  const traders = (users ?? []).filter((u) => u.role === 'trader' || u.role === 'teamlead');

  return (
    <AppShell title="Токены">
      <PageHeader
        title="Work tokens"
        subtitle="Рабочие депозиты"
        action={
          <button className="btn-primary" onClick={() => setCreateOpen(true)}>Создать</button>
        }
      />
      {apiKeyMsg && <p className="mb-4 text-sm break-all bg-elevated p-3 rounded-lg">{apiKeyMsg}</p>}
      <DataTable columns={cols} data={tokens ?? []} keyField="id" />

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Новый токен">
        <div className="space-y-3">
          <input className="input w-full" placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} />
          <select className="input w-full" value={memberId} onChange={(e) => setMemberId(e.target.value)}>
            <option value="">Участник (опц.)</option>
            {traders.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name} ({u.login})</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={exempt} onChange={(e) => setExempt(e.target.checked)} />
            Без депозита (merchant exempt)
          </label>
          {err && <p className="text-danger text-sm">{err}</p>}
          <button className="btn-primary w-full" disabled={!name || create.isPending} onClick={() => create.mutate()}>
            Создать
          </button>
        </div>
      </Modal>

      <Modal open={!!depositOpen} onClose={() => setDepositOpen(null)} title={`Депозит: ${depositOpen?.name ?? ''}`}>
        <div className="space-y-3">
          <input className="input w-full" placeholder="USDT" value={amount} onChange={(e) => setAmount(e.target.value)} />
          {err && <p className="text-danger text-sm">{err}</p>}
          <button className="btn-primary w-full" disabled={!amount || deposit.isPending} onClick={() => deposit.mutate()}>
            Зачислить
          </button>
        </div>
      </Modal>
    </AppShell>
  );
}
