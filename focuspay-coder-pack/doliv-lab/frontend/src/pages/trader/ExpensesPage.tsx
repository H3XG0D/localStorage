import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  api,
  formatDual,
  type TraderExpense,
} from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { Modal } from '../../components/ui/Modal';

const CAT_LABELS: Record<string, string> = {
  card_purchase: 'Закупка карты',
  warm: 'Прогрев',
  block_loss: 'Блок / потеря',
  other: 'Прочее',
};

export default function TraderExpensesPage() {
  const qc = useQueryClient();
  const [expOpen, setExpOpen] = useState(false);
  const [err, setErr] = useState('');
  const [cat, setCat] = useState('warm');
  const [amountRub, setAmountRub] = useState('');
  const [cardId, setCardId] = useState('');
  const [comment, setComment] = useState('');

  const { data: expenses } = useQuery({ queryKey: ['trader-expenses'], queryFn: api.traderExpenses });
  const { data: cardsList } = useQuery({ queryKey: ['trader-cards', 'all'], queryFn: () => api.traderCards({ limit: 500 }) });
  const { data: net } = useQuery({ queryKey: ['trader-net'], queryFn: api.traderNet });
  const { data: cats } = useQuery({ queryKey: ['expense-categories'], queryFn: api.expenseCategories });
  const cards = cardsList?.items ?? [];
  const primary = (net?.display_currency === 'USDT' ? 'USDT' : 'RUB') as 'RUB' | 'USDT';

  const createExp = useMutation({
    mutationFn: () =>
      api.createTraderExpense({
        category: cat,
        amount_rub: parseFloat(amountRub),
        card_id: cardId ? Number(cardId) : null,
        comment: comment || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trader-expenses'] });
      qc.invalidateQueries({ queryKey: ['trader-net'] });
      qc.invalidateQueries({ queryKey: ['trader-cards'] });
      setExpOpen(false);
      setAmountRub('');
      setCardId('');
      setComment('');
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const expCols: Column<TraderExpense>[] = useMemo(
    () => [
      { key: 'id', header: 'ID', render: (e) => `#${e.id}` },
      { key: 'cat', header: 'Категория', render: (e) => CAT_LABELS[e.category] || e.category },
      { key: 'amt', header: 'Сумма ₽ / USDT', render: (e) => formatDual(e.amount_rub, e.amount_usdt, primary) },
      { key: 'rate', header: 'Курс', render: (e) => e.rate },
      { key: 'card', header: 'Карта', render: (e) => (e.card_id ? `#${e.card_id}` : '—') },
      { key: 'deb', header: 'Debit', render: (e) => (e.debited ? 'да' : 'учёт') },
      { key: 'cmt', header: 'Коммент', render: (e) => e.comment || '—' },
      { key: 'at', header: 'Когда', render: (e) => new Date(e.created_at).toLocaleString('ru-RU') },
    ],
    [primary],
  );

  return (
    <AppShell title="Затраты">
      <PageHeader
        title="Затраты"
        subtitle="Учёт закупки, прогрева и потерь"
        action={
          <div className="flex gap-2">
            <Link to="/trader/assets" className="btn-ghost text-sm">К картам</Link>
            <button className="btn-primary" onClick={() => { setExpOpen(true); setErr(''); }}>Добавить затрату</button>
          </div>
        }
      />
      <DataTable columns={expCols} data={expenses ?? []} keyField="id" emptyMessage="Нет затрат" />
      <Modal open={expOpen} onClose={() => setExpOpen(false)} title="Новая затрата">
        <div className="space-y-4">
          <div>
            <label className="field-label">Категория</label>
            <select className="input w-full" value={cat} onChange={(e) => setCat(e.target.value)}>
              {(cats ?? Object.keys(CAT_LABELS).map((id) => ({ id, label: CAT_LABELS[id] }))).map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Сумма ₽</label>
            <input className="input w-full" value={amountRub} onChange={(e) => setAmountRub(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Карта (опц.)</label>
            <select className="input w-full" value={cardId} onChange={(e) => setCardId(e.target.value)}>
              <option value="">—</option>
              {cards.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Комментарий</label>
            <input className="input w-full" value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
          {err && <p className="text-red-400 text-sm">{err}</p>}
          <button className="btn-primary w-full" disabled={!amountRub || createExp.isPending} onClick={() => createExp.mutate()}>
            Сохранить
          </button>
        </div>
      </Modal>
    </AppShell>
  );
}
