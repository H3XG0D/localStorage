import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { CreditCard, Receipt } from 'lucide-react';
import {
  api,
  formatDual,
  formatMoney,
  trafficAudienceLabel,
  type TraderCard,
  type TraderExpense,
} from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { Modal } from '../../components/ui/Modal';
import { useAuth } from '../../context/AuthContext';

const CARD_STATUSES: Record<string, string> = {
  active: 'Активна',
  warming: 'Прогрев',
  blocked: 'Блок',
  archived: 'Архив',
};

const CAT_LABELS: Record<string, string> = {
  card_purchase: 'Закупка карты',
  warm: 'Прогрев',
  block_loss: 'Блок / потеря',
  other: 'Прочее',
};

type Tab = 'cards' | 'expenses';

export default function AdminCardsExpensesPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isTeamlead = user?.role === 'teamlead';

  const [tab, setTab] = useState<Tab>('cards');
  const [traderFilter, setTraderFilter] = useState('');
  const [cardOpen, setCardOpen] = useState(false);
  const [expOpen, setExpOpen] = useState(false);
  const [trafficCard, setTrafficCard] = useState<TraderCard | null>(null);
  const [minOrders, setMinOrders] = useState('');
  const [maxOrders, setMaxOrders] = useState('');
  const [minVolume, setMinVolume] = useState('');
  const [maxVolume, setMaxVolume] = useState('');
  const [err, setErr] = useState('');

  const [name, setName] = useState('');
  const [last4, setLast4] = useState('');
  const [bank, setBank] = useState('');
  const [purchase, setPurchase] = useState('');
  const [createTraderId, setCreateTraderId] = useState('');

  const [cat, setCat] = useState('warm');
  const [amountRub, setAmountRub] = useState('');
  const [cardId, setCardId] = useState('');
  const [comment, setComment] = useState('');
  const [expTraderId, setExpTraderId] = useState('');

  const traderIdNum = traderFilter ? Number(traderFilter) : undefined;

  const { data: adminUsers } = useQuery({
    queryKey: ['admin-users'],
    queryFn: api.adminUsers,
    enabled: !isTeamlead,
  });
  const { data: teamTraders } = useQuery({
    queryKey: ['teamlead-traders'],
    queryFn: api.teamleadTraders,
    enabled: isTeamlead,
  });

  const traders = useMemo(() => {
    if (isTeamlead) {
      return (teamTraders ?? []).map((t) => ({ id: t.id, label: `${t.full_name} (${t.login})` }));
    }
    return (adminUsers ?? [])
      .filter((u) => u.role === 'trader')
      .map((u) => ({ id: u.id, label: `${u.full_name} (${u.login})` }));
  }, [adminUsers, isTeamlead, teamTraders]);

  const { data: cards } = useQuery({
    queryKey: ['admin-cards', traderIdNum],
    queryFn: () => api.adminCards(traderIdNum),
  });
  const { data: expenses } = useQuery({
    queryKey: ['admin-expenses', traderIdNum],
    queryFn: () => api.adminExpenses(traderIdNum),
  });
  const { data: cats } = useQuery({ queryKey: ['expense-categories'], queryFn: api.expenseCategories });

  const createCard = useMutation({
    mutationFn: () =>
      api.createAdminCard(Number(createTraderId), {
        name,
        last4: last4 || undefined,
        bank: bank || undefined,
        purchase_cost_rub: purchase ? parseFloat(purchase) : 0,
        record_purchase_expense: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-cards'] });
      qc.invalidateQueries({ queryKey: ['admin-expenses'] });
      setCardOpen(false);
      setName('');
      setLast4('');
      setBank('');
      setPurchase('');
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const createExp = useMutation({
    mutationFn: () =>
      api.createAdminExpense({
        trader_id: Number(expTraderId),
        category: cat,
        amount_rub: parseFloat(amountRub),
        card_id: cardId ? Number(cardId) : null,
        comment: comment || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-expenses'] });
      qc.invalidateQueries({ queryKey: ['admin-cards'] });
      setExpOpen(false);
      setAmountRub('');
      setCardId('');
      setComment('');
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const openTraffic = (c: TraderCard) => {
    setTrafficCard(c);
    setMinOrders(c.traffic_min_orders != null ? String(c.traffic_min_orders) : '');
    setMaxOrders(c.traffic_max_orders != null ? String(c.traffic_max_orders) : '');
    setMinVolume(c.traffic_min_volume_rub != null ? String(Number(c.traffic_min_volume_rub)) : '');
    setMaxVolume(c.traffic_max_volume_rub != null ? String(Number(c.traffic_max_volume_rub)) : '');
    setErr('');
  };

  const saveTraffic = useMutation({
    mutationFn: () => {
      if (!trafficCard) throw new Error('no card');
      const numOrNull = (v: string) => (v.trim() === '' ? null : Number(v));
      return api.updateAdminCardTraffic(trafficCard.id, {
        traffic_min_orders: numOrNull(minOrders),
        traffic_max_orders: numOrNull(maxOrders),
        traffic_min_volume_rub: numOrNull(minVolume),
        traffic_max_volume_rub: numOrNull(maxVolume),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-cards'] });
      setTrafficCard(null);
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const traderName = (id: number) => traders.find((t) => t.id === id)?.label ?? `#${id}`;

  const cardCols: Column<TraderCard>[] = [
    { key: 'trader', header: 'Трейдер', render: (c) => traderName(c.trader_id) },
    {
      key: 'name',
      header: 'Карта',
      render: (c) => (
        <div>
          <div className="font-medium text-[#fafafa]">{c.name}</div>
          <div className="text-xs text-muted">
            {[c.bank, c.last4 ? `•••• ${c.last4}` : null].filter(Boolean).join(' · ') || '—'}
          </div>
        </div>
      ),
    },
    { key: 'status', header: 'Статус', render: (c) => CARD_STATUSES[c.status] || c.status },
    { key: 'purchase', header: 'Закупка', render: (c) => formatMoney(c.purchase_cost_rub) },
    {
      key: 'exp',
      header: 'Затраты ₽ / USDT',
      render: (c) => formatDual(c.expenses_rub, c.expenses_usdt),
    },
    {
      key: 'traffic',
      header: 'Трафик',
      render: (c) => (
        <div className="flex flex-col gap-1 items-start">
          <span className="text-sm">{trafficAudienceLabel(c)}</span>
          {!isTeamlead && (
            <button type="button" className="text-xs text-accent" onClick={() => openTraffic(c)}>
              Настроить
            </button>
          )}
        </div>
      ),
    },
  ];

  const expCols: Column<TraderExpense>[] = [
    { key: 'id', header: 'ID', render: (e) => `#${e.id}` },
    { key: 'trader', header: 'Трейдер', render: (e) => traderName(e.trader_id) },
    { key: 'cat', header: 'Категория', render: (e) => CAT_LABELS[e.category] || e.category },
    {
      key: 'amt',
      header: 'Сумма ₽ / USDT',
      render: (e) => formatDual(e.amount_rub, e.amount_usdt),
    },
    { key: 'deb', header: 'Debit', render: (e) => (e.debited ? 'да' : 'учёт') },
    { key: 'cmt', header: 'Коммент', render: (e) => e.comment || '—' },
    {
      key: 'at',
      header: 'Когда',
      render: (e) => new Date(e.created_at).toLocaleString('ru-RU'),
    },
  ];

  const filteredCardsForExp = (cards ?? []).filter(
    (c) => !expTraderId || c.trader_id === Number(expTraderId),
  );

  return (
    <AppShell title="Активы">
      <PageHeader
        title={isTeamlead ? 'Карты и затраты команды' : 'Карты и затраты трейдеров'}
        subtitle="Фильтр по трейдеру · dual ₽ / USDT"
        action={
          <div className="flex flex-wrap gap-2">
            {tab === 'cards' ? (
              <button className="btn-primary" onClick={() => { setCardOpen(true); setErr(''); setCreateTraderId(traderFilter); }}>
                Добавить карту
              </button>
            ) : (
              <button className="btn-primary" onClick={() => { setExpOpen(true); setErr(''); setExpTraderId(traderFilter); }}>
                Добавить затрату
              </button>
            )}
          </div>
        }
      />

      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <select
          className="input text-[#fafafa]"
          value={traderFilter}
          onChange={(e) => setTraderFilter(e.target.value)}
        >
          <option value="">Все трейдеры</option>
          {traders.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
        <button
          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${tab === 'cards' ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`}
          onClick={() => setTab('cards')}
        >
          <CreditCard size={16} /> Карты
        </button>
        <button
          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${tab === 'expenses' ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`}
          onClick={() => setTab('expenses')}
        >
          <Receipt size={16} /> Затраты
        </button>
      </div>

      {tab === 'cards' ? (
        <DataTable columns={cardCols} data={cards ?? []} keyField="id" />
      ) : (
        <DataTable columns={expCols} data={expenses ?? []} keyField="id" />
      )}

      <Modal open={cardOpen} onClose={() => setCardOpen(false)} title="Карта для трейдера">
        <div className="space-y-3">
          <select className="input w-full" value={createTraderId} onChange={(e) => setCreateTraderId(e.target.value)}>
            <option value="">Трейдер</option>
            {traders.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
          <input className="input w-full" placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            <input className="input" placeholder="Банк" value={bank} onChange={(e) => setBank(e.target.value)} />
            <input className="input" placeholder="Last4" value={last4} onChange={(e) => setLast4(e.target.value)} />
          </div>
          <input
            className="input w-full"
            placeholder="Стоимость закупки ₽"
            value={purchase}
            onChange={(e) => setPurchase(e.target.value)}
          />
          {err && <p className="text-danger text-sm">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={!name || !createTraderId || createCard.isPending}
            onClick={() => createCard.mutate()}
          >
            Создать
          </button>
        </div>
      </Modal>

      <Modal open={expOpen} onClose={() => setExpOpen(false)} title="Затрата трейдера">
        <div className="space-y-3">
          <select className="input w-full" value={expTraderId} onChange={(e) => setExpTraderId(e.target.value)}>
            <option value="">Трейдер</option>
            {traders.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
          <select className="input w-full" value={cat} onChange={(e) => setCat(e.target.value)}>
            {(cats ?? Object.entries(CAT_LABELS).map(([id, label]) => ({ id, label }))).map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>
          <input
            className="input w-full"
            placeholder="Сумма ₽"
            value={amountRub}
            onChange={(e) => setAmountRub(e.target.value)}
          />
          <select className="input w-full" value={cardId} onChange={(e) => setCardId(e.target.value)}>
            <option value="">Без карты</option>
            {filteredCardsForExp.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <input className="input w-full" placeholder="Комментарий" value={comment} onChange={(e) => setComment(e.target.value)} />
          {err && <p className="text-danger text-sm">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={!expTraderId || !amountRub || createExp.isPending}
            onClick={() => createExp.mutate()}
          >
            Записать
          </button>
        </div>
      </Modal>

      <Modal
        open={!!trafficCard}
        onClose={() => { setTrafficCard(null); setErr(''); }}
        title={trafficCard ? `Трафик · ${trafficCard.name}` : 'Трафик'}
      >
        <div className="space-y-3">
          <p className="text-sm text-muted">
            Пустое поле — без ограничения. Новые: макс. покупок 0. Постоянники: от 5 покупок или от 7000 ₽.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-sm">
              От покупок
              <input className="input mt-1 w-full" inputMode="numeric" value={minOrders} onChange={(e) => setMinOrders(e.target.value)} />
            </label>
            <label className="text-sm">
              До покупок
              <input className="input mt-1 w-full" inputMode="numeric" value={maxOrders} onChange={(e) => setMaxOrders(e.target.value)} />
            </label>
            <label className="text-sm">
              От оборота ₽
              <input className="input mt-1 w-full" inputMode="numeric" value={minVolume} onChange={(e) => setMinVolume(e.target.value)} />
            </label>
            <label className="text-sm">
              До оборота ₽
              <input className="input mt-1 w-full" inputMode="numeric" value={maxVolume} onChange={(e) => setMaxVolume(e.target.value)} />
            </label>
          </div>
          {err && <p className="text-danger text-sm">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={!trafficCard || saveTraffic.isPending}
            onClick={() => saveTraffic.mutate()}
          >
            Сохранить
          </button>
        </div>
      </Modal>
    </AppShell>
  );
}
