import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, formatMoney } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';

function formatRequisites(raw: Record<string, unknown> | null): string {
  if (!raw) return '';
  const labels: Record<string, string> = {
    phone: 'Телефон',
    reciver: 'Получатель',
    receiver: 'Получатель',
    card: 'Карта',
    card_number: 'Карта',
    bank: 'Банк',
    bankName: 'Банк',
    holderName: 'ФИО',
    method: 'Метод',
    name: 'Имя',
  };
  return Object.entries(raw)
    .filter(([, v]) => v != null && String(v) !== '')
    .map(([k, v]) => `${labels[k] || k}: ${String(v)}`)
    .join(' · ');
}

function deadlineLeft(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return '';
  if (ms <= 0) return 'время вышло';
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m} мин ${s} с`;
}

export default function TraderPayoutsPage() {
  const qc = useQueryClient();
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const [error, setError] = useState('');

  const { data: jobs } = useQuery({
    queryKey: ['trader-payout-jobs'],
    queryFn: api.traderPayoutJobs,
    refetchInterval: 15_000,
  });

  const claim = useMutation({
    mutationFn: ({ jobId, amount }: { jobId: number; amount: number }) =>
      api.claimPayoutJob(jobId, amount),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trader-payout-jobs'] });
      setError('');
    },
    onError: (e: Error) => setError(e.message),
  });

  const markPaid = useMutation({
    mutationFn: (claimId: number) => api.markPayoutClaimPaid(claimId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trader-payout-jobs'] }),
    onError: (e: Error) => setError(e.message),
  });

  return (
    <AppShell title="Выплаты">
      <PageHeader
        title="Очередь выплат"
        subtitle="Примите часть суммы за 15 минут · старайтесь закрывать крупнее (меньше чеков)"
      />
      {error && <p className="text-danger text-sm mb-4">{error}</p>}
      <div className="space-y-4">
        {(jobs ?? []).map((j) => {
          const suggested = j.remaining_rub;
          return (
            <div key={j.id} className="card p-4">
              <div className="flex flex-wrap justify-between gap-2 mb-2">
                <div>
                  <p className="font-semibold text-[#fafafa]">
                    #{j.id} · {formatMoney(j.amount_rub)} · осталось {formatMoney(j.remaining_rub)}
                  </p>
                  <p className="text-xs text-muted">
                    {j.pay_method.toUpperCase()} · {j.source} · до{' '}
                    {new Date(j.claim_deadline).toLocaleString('ru-RU')} · {deadlineLeft(j.claim_deadline)}
                  </p>
                  {j.requisites && (
                    <p className="text-sm text-[#e4e4e7] mt-2">{formatRequisites(j.requisites)}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 items-end">
                  <label className="text-sm text-[#fafafa]">
                    Сумма ₽
                    <input
                      className="input mt-1 w-32"
                      value={amounts[j.id] ?? suggested}
                      onChange={(e) => setAmounts((m) => ({ ...m, [j.id]: e.target.value }))}
                    />
                  </label>
                  <button
                    className="btn-primary"
                    disabled={claim.isPending}
                    onClick={() =>
                      claim.mutate({
                        jobId: j.id,
                        amount: parseFloat(amounts[j.id] ?? String(suggested)),
                      })
                    }
                  >
                    Принять
                  </button>
                </div>
              </div>
              {j.claims?.length > 0 && (
                <ul className="text-xs text-muted space-y-1 mt-2">
                  {j.claims.map((c) => (
                    <li key={c.id} className="flex gap-2 items-center">
                      claim #{c.id}: {formatMoney(c.amount_rub)} · {c.status}
                      {c.status === 'claimed' && (
                        <button className="btn-ghost text-xs" onClick={() => markPaid.mutate(c.id)}>
                          Выплатил
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
        {!jobs?.length && <p className="text-muted text-sm">Нет открытых заявок</p>}
      </div>
    </AppShell>
  );
}
