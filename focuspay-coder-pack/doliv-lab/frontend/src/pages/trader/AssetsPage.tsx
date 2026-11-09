import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  api,
  formatDual,
  formatMoney,
  formatUsdt,
  statusLabel,
  trafficAudienceLabel,
  type TraderCard,
} from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { Modal } from '../../components/ui/Modal';

const CARD_STATUSES = [
  { id: 'active', label: 'Активна' },
  { id: 'warming', label: 'Прогрев' },
  { id: 'blocked', label: 'Блок' },
  { id: 'archived', label: 'Архив' },
];

const MODE_LABELS: Record<string, string> = {
  manual: 'ручной',
  rapira_snap: 'снимок Rapira',
  fixed: 'фиксированный',
};

const REASON_LABELS: Record<string, string> = {
  disabled: 'Выключена',
  blocked: 'Блок',
  warming: 'Прогрев',
  no_session: 'Нет сессии',
  daily_limit_reached: 'Лимит суток',
  session_filled: 'Сессия заполнена',
  no_deposit: 'Нет депозита',
};

type Chip = 'all' | 'accepting' | 'off' | 'limit' | 'blocked' | 'warming';

function Toggle({ on, disabled, onClick }: { on: boolean; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        on ? 'bg-emerald-500' : 'bg-zinc-600'
      } disabled:opacity-40`}
      aria-pressed={on}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
          on ? 'translate-x-5' : 'translate-x-0.5'
        }`}
      />
    </button>
  );
}

function LimitBar({ received, limit }: { received: number; limit: number | null }) {
  if (!limit || limit <= 0) {
    return <span className="text-xs text-muted">лимит не задан</span>;
  }
  const pct = Math.min(100, Math.round((received / limit) * 100));
  const left = Math.max(0, limit - received);
  return (
    <div className="min-w-[9rem]">
      <div className="mb-0.5 flex justify-between gap-2 text-[11px]">
        <span className="text-[#fafafa]">{formatMoney(left)} ещё</span>
        <span className="text-muted">{pct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full ${pct >= 95 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-400' : 'bg-emerald-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-0.5 text-[10px] text-muted">
        {formatMoney(received)} / {formatMoney(limit)} за сутки
      </p>
    </div>
  );
}

const PAGE_SIZE = 50;

export default function TraderAssetsPage() {
  const qc = useQueryClient();
  const [cardOpen, setCardOpen] = useState(false);
  const [err, setErr] = useState('');
  const [q, setQ] = useState('');
  const [chip, setChip] = useState<Chip>('all');
  const [channel, setChannel] = useState('');
  const [sort, setSort] = useState('id');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [bulkLimit, setBulkLimit] = useState('');

  const [name, setName] = useState('');
  const [createChannel, setCreateChannel] = useState<'c2c' | 'sbp'>('c2c');
  const [recipient, setRecipient] = useState('');
  const [cardNumber, setCardNumber] = useState('');
  const [phone, setPhone] = useState('');
  const [bank, setBank] = useState('');
  const [purchase, setPurchase] = useState('');
  const [notes, setNotes] = useState('');
  const [dailyLimit, setDailyLimit] = useState('');
  const [bands, setBands] = useState<{ min: string; max: string }[]>([{ min: '', max: '' }]);
  const [goOnline, setGoOnline] = useState(true);

  const listParams = useMemo(() => {
    const params: Parameters<typeof api.traderCards>[0] = {
      q: q.trim() || undefined,
      channel: channel || undefined,
      sort,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
    if (chip === 'accepting') params.accepting = true;
    if (chip === 'off') params.accepting = false;
    if (chip === 'blocked') params.status = 'blocked';
    if (chip === 'warming') params.status = 'warming';
    return params;
  }, [q, chip, channel, sort, page]);

  const { data: list, isLoading } = useQuery({
    queryKey: ['trader-cards', listParams],
    queryFn: () => api.traderCards(listParams),
  });
  const cards = useMemo(() => {
    const items = list?.items ?? [];
    if (chip === 'limit') {
      return items.filter((c) => c.not_accepting_reason === 'daily_limit_reached');
    }
    return items;
  }, [list, chip]);
  const { data: net } = useQuery({ queryKey: ['trader-net'], queryFn: api.traderNet });
  const { data: wallet } = useQuery({ queryKey: ['trader-wallet'], queryFn: api.traderWallet });
  const { data: working } = useQuery({ queryKey: ['working-rate'], queryFn: api.workingRate });
  const { data: rapira } = useQuery({
    queryKey: ['rapira-rate'],
    queryFn: api.rapiraRate,
    refetchInterval: 60_000,
  });

  const primary = (net?.display_currency === 'USDT' ? 'USDT' : 'RUB') as 'RUB' | 'USDT';
  const officeRateLabel = working
    ? `${working.rate} (${MODE_LABELS[working.mode] || working.mode}${
        working.valid_until ? ` · до ${new Date(working.valid_until).toLocaleString('ru-RU')}` : ''
      })`
    : '—';

  const invalidateCardQueries = () => {
    qc.invalidateQueries({ queryKey: ['trader-cards'] });
    qc.invalidateQueries({ queryKey: ['trader-net'] });
    qc.invalidateQueries({ queryKey: ['trader-wallet'] });
    qc.invalidateQueries({ queryKey: ['requisites'] });
  };

  const setCurrency = useMutation({
    mutationFn: (c: 'RUB' | 'USDT') => api.setDisplayCurrency(c),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trader-net'] }),
  });

  const createCard = useMutation({
    mutationFn: () => {
      const payment_bands = bands
        .filter((b) => b.min && b.max)
        .map((b) => ({ min_rub: parseFloat(b.min), max_rub: parseFloat(b.max) }));
      return api.createTraderCard({
        name,
        channel: createChannel,
        bank: bank || undefined,
        card_number: createChannel === 'c2c' && cardNumber ? cardNumber : undefined,
        phone: createChannel === 'sbp' && phone ? phone : undefined,
        last4: createChannel === 'c2c' && cardNumber && cardNumber.length >= 4 ? cardNumber.slice(-4) : undefined,
        recipient_name: recipient || undefined,
        purchase_cost_rub: purchase ? parseFloat(purchase) : 0,
        notes: notes || undefined,
        record_purchase_expense: true,
        daily_limit_rub: dailyLimit ? parseFloat(dailyLimit) : undefined,
        payment_bands: payment_bands.length ? payment_bands : undefined,
        go_online: goOnline && !!dailyLimit,
      });
    },
    onSuccess: () => {
      invalidateCardQueries();
      setCardOpen(false);
      setName('');
      setCreateChannel('c2c');
      setRecipient('');
      setCardNumber('');
      setPhone('');
      setBank('');
      setPurchase('');
      setNotes('');
      setDailyLimit('');
      setBands([{ min: '', max: '' }]);
      setGoOnline(true);
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const toggleOne = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => api.setCardAccepting(id, enabled),
    onSuccess: () => invalidateCardQueries(),
    onError: (e: Error) => setErr(e.message),
  });

  const bulk = useMutation({
    mutationFn: (data: { ids: number[]; action: 'enable' | 'disable' | 'set_daily_limit'; value?: string }) =>
      api.bulkTraderCards(data),
    onSuccess: () => {
      invalidateCardQueries();
      setSelected(new Set());
      setBulkLimit('');
      setErr('');
    },
    onError: (e: Error) => setErr(e.message),
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.updateTraderCard(id, { status }),
    onSuccess: () => invalidateCardQueries(),
  });

  const selectedIds = [...selected];
  const total = list?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const receivingCount = cards.filter((c) => c.accepting).length;
  const remainingSum = cards.reduce((s, c) => s + Number(c.daily_remaining_rub || 0), 0);

  const chips: { id: Chip; label: string }[] = [
    { id: 'all', label: 'Все' },
    { id: 'accepting', label: 'Принимают' },
    { id: 'off', label: 'Выключены' },
    { id: 'limit', label: 'Лимит исчерпан' },
    { id: 'blocked', label: 'Блок' },
    { id: 'warming', label: 'Прогрев' },
  ];

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const masterOn = receivingCount > 0 && receivingCount === cards.filter((c) => c.status === 'active').length;

  return (
    <AppShell title="Карты">
      <div className="sticky top-0 z-10 mb-4 rounded-xl border border-border bg-elevated/95 px-4 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs text-muted">Рабочий курс офиса</p>
            <p className="text-lg font-semibold text-[#fafafa]">
              1 USDT = <span className="text-accent">{working?.rate ?? '—'}</span> ₽
            </p>
            <p className="text-xs text-muted">{officeRateLabel}</p>
            {rapira && (
              <p className="text-xs text-muted">
                Rapira {rapira.rate} ₽
                {rapira.source === 'fallback' ? ' · нет ответа, fallback' : ' · live'}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <Toggle
                on={masterOn}
                disabled={bulk.isPending || !cards.some((c) => c.status === 'active')}
                onClick={() => {
                  const ids = cards.filter((c) => c.status === 'active').map((c) => c.id);
                  if (!ids.length) return;
                  bulk.mutate({ ids, action: masterOn ? 'disable' : 'enable' });
                }}
              />
              Приём {masterOn ? 'вкл' : 'выкл'}
            </label>
            <div className="text-sm">
              <p className="text-xs text-muted">Депозит доступно</p>
              <p className="font-medium">{formatUsdt(wallet?.available ?? 0)}</p>
            </div>
            <div className="text-sm">
              <p className="text-xs text-muted">В холде</p>
              <p className="font-medium">{formatUsdt(wallet?.held ?? 0)}</p>
            </div>
            <div className="text-sm">
              <p className="text-xs text-muted">Ещё примут сегодня</p>
              <p className="font-medium">{formatMoney(remainingSum)}</p>
            </div>
          </div>
        </div>
      </div>

      <PageHeader
        title="Карты"
        subtitle={`${total} шт · принимают ${receivingCount} на этой странице`}
        action={
          <div className="flex flex-wrap gap-2 items-center">
            <div className="flex rounded-lg border border-border overflow-hidden text-sm">
              <button
                className={`px-3 py-1.5 ${primary === 'RUB' ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`}
                onClick={() => setCurrency.mutate('RUB')}
              >
                ₽
              </button>
              <button
                className={`px-3 py-1.5 ${primary === 'USDT' ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`}
                onClick={() => setCurrency.mutate('USDT')}
              >
                USDT
              </button>
            </div>
            <Link to="/trader/expenses" className="btn-ghost text-sm">Затраты</Link>
            <button className="btn-primary" onClick={() => { setCardOpen(true); setErr(''); }}>Добавить карту</button>
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3 mb-4">
        <div className="card p-4">
          <p className="text-xs text-muted mb-1">Комиссии</p>
          <p className="text-lg font-semibold text-[#fafafa]">{formatUsdt(net?.commissions_usdt ?? 0)}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-muted mb-1">Затраты</p>
          <p className="text-lg font-semibold text-[#fafafa]">{formatDual(net?.expenses_rub ?? 0, net?.expenses_usdt ?? 0, primary)}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-muted mb-1">Net</p>
          <p className="text-lg font-semibold text-accent">{formatUsdt(net?.net_usdt ?? 0)}</p>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        <input
          className="input min-w-[12rem] flex-1"
          placeholder="Поиск: банк, имя, телефон, последние цифры"
          value={q}
          onChange={(e) => { setQ(e.target.value); setPage(0); }}
        />
        <select className="input w-auto" value={channel} onChange={(e) => { setChannel(e.target.value); setPage(0); }}>
          <option value="">Все каналы</option>
          <option value="c2c">C2C</option>
          <option value="sbp">СБП</option>
        </select>
        <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="id">Новые сверху</option>
          <option value="daily_remaining">По остатку суток</option>
          <option value="received_today">По обороту сегодня</option>
          <option value="name">По имени</option>
          <option value="bank">По банку</option>
        </select>
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {chips.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`rounded-lg px-3 py-1.5 text-sm ${chip === c.id ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`}
            onClick={() => { setChip(c.id); setPage(0); }}
          >
            {c.label}
          </button>
        ))}
      </div>

      {selectedIds.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-sm">
          <span>Выбрано {selectedIds.length}</span>
          <button className="btn-primary text-xs" onClick={() => bulk.mutate({ ids: selectedIds, action: 'enable' })}>Включить</button>
          <button className="btn-secondary text-xs" onClick={() => bulk.mutate({ ids: selectedIds, action: 'disable' })}>Выключить</button>
          <input className="input w-28 py-1 text-sm" placeholder="лимит ₽" value={bulkLimit} onChange={(e) => setBulkLimit(e.target.value)} />
          <button
            className="btn-secondary text-xs"
            disabled={!bulkLimit}
            onClick={() => bulk.mutate({ ids: selectedIds, action: 'set_daily_limit', value: bulkLimit })}
          >
            Задать лимит
          </button>
          <button className="text-xs text-muted" onClick={() => setSelected(new Set())}>Снять</button>
        </div>
      )}

      {err && <p className="mb-3 text-sm text-red-400">{err}</p>}

      <div className="hidden md:block">
        <div className="table-wrap" style={{ maxHeight: '70vh', overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-10">
                  <input
                    type="checkbox"
                    checked={cards.length > 0 && cards.every((c) => selected.has(c.id))}
                    onChange={() => {
                      if (cards.every((c) => selected.has(c.id))) setSelected(new Set());
                      else setSelected(new Set(cards.map((c) => c.id)));
                    }}
                  />
                </th>
                <th>Карта</th>
                <th>Приём</th>
                <th>Сутки</th>
                <th>Статус</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr><td colSpan={6} className="py-8 text-center text-muted">Загрузка…</td></tr>
              )}
              {!isLoading && cards.length === 0 && (
                <tr><td colSpan={6} className="py-8 text-center text-muted">Нет карт</td></tr>
              )}
              {cards.map((c) => (
                <CardRows
                  key={c.id}
                  card={c}
                  selected={selected.has(c.id)}
                  expanded={expanded.has(c.id)}
                  primary={primary}
                  onSelect={() => toggleSelect(c.id)}
                  onExpand={() => setExpanded((prev) => {
                    const next = new Set(prev);
                    if (next.has(c.id)) next.delete(c.id);
                    else next.add(c.id);
                    return next;
                  })}
                  onToggle={() => toggleOne.mutate({ id: c.id, enabled: !c.accepting_enabled })}
                  onStatus={(status) => updateStatus.mutate({ id: c.id, status })}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-3 md:hidden">
        {cards.map((c) => (
          <div key={c.id} className="card p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium">{c.name}</p>
                <p className="text-xs text-muted">{c.channel === 'sbp' ? 'СБП' : 'C2C'} · {c.bank || '—'}</p>
              </div>
              <Toggle
                on={!!c.accepting}
                disabled={c.status !== 'active' || toggleOne.isPending}
                onClick={() => toggleOne.mutate({ id: c.id, enabled: !c.accepting_enabled })}
              />
            </div>
            <div className="mt-2">
              <LimitBar received={Number(c.received_today_rub || 0)} limit={c.daily_limit_rub ? Number(c.daily_limit_rub) : null} />
            </div>
            {!c.accepting && c.not_accepting_reason && (
              <p className="mt-1 text-xs text-amber-400">{REASON_LABELS[c.not_accepting_reason] || c.not_accepting_reason}</p>
            )}
          </div>
        ))}
      </div>

      {pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <button className="btn-ghost" disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>Назад</button>
          <span className="text-muted">стр. {page + 1} / {pages}</span>
          <button className="btn-ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Дальше</button>
        </div>
      )}

      <Modal open={cardOpen} onClose={() => setCardOpen(false)} title="Новая карта / реквизит">
        <div className="space-y-4">
          <div>
            <label className="field-label">Канал приёма</label>
            <div className="flex rounded-lg border border-border overflow-hidden text-sm">
              <button type="button" className={`flex-1 px-3 py-2 ${createChannel === 'c2c' ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`} onClick={() => setCreateChannel('c2c')}>C2C (карта)</button>
              <button type="button" className={`flex-1 px-3 py-2 ${createChannel === 'sbp' ? 'bg-accent text-white' : 'bg-elevated text-[#fafafa]'}`} onClick={() => setCreateChannel('sbp')}>СБП</button>
            </div>
          </div>
          <div>
            <label className="field-label">Название</label>
            <input className="input w-full" placeholder={createChannel === 'sbp' ? 'СБП Сбер' : 'Tinkoff **** 1234'} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Получатель (ФИО)</label>
            <input className="input w-full" placeholder="Иванов Иван" value={recipient} onChange={(e) => setRecipient(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">Банк</label>
              <input className="input" placeholder="Сбер" value={bank} onChange={(e) => setBank(e.target.value)} />
            </div>
            {createChannel === 'c2c' ? (
              <div>
                <label className="field-label">Номер карты</label>
                <input className="input" placeholder="4276…" value={cardNumber} onChange={(e) => setCardNumber(e.target.value)} />
              </div>
            ) : (
              <div>
                <label className="field-label">Телефон СБП</label>
                <input className="input" placeholder="+79001234567" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </div>
            )}
          </div>
          <div>
            <label className="field-label">Стоимость закупки ₽</label>
            <input className="input w-full" placeholder="0" value={purchase} onChange={(e) => setPurchase(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Лимит в сутки ₽</label>
            <input className="input w-full" placeholder="50000" value={dailyLimit} onChange={(e) => setDailyLimit(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Коридоры платежа ₽</label>
            <div className="space-y-2">
              {bands.map((b, i) => (
                <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                  <input className="input" placeholder="min 3000" value={b.min} onChange={(e) => {
                    const next = [...bands];
                    next[i] = { ...next[i], min: e.target.value };
                    setBands(next);
                  }} />
                  <input className="input" placeholder="max 5000" value={b.max} onChange={(e) => {
                    const next = [...bands];
                    next[i] = { ...next[i], max: e.target.value };
                    setBands(next);
                  }} />
                  <button type="button" className="text-xs text-muted" onClick={() => setBands(bands.filter((_, j) => j !== i))} disabled={bands.length <= 1}>✕</button>
                </div>
              ))}
              <button type="button" className="text-sm text-accent" onClick={() => setBands([...bands, { min: '', max: '' }])}>+ коридор</button>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-[#e4e4e7]">
            <input type="checkbox" checked={goOnline} onChange={(e) => setGoOnline(e.target.checked)} />
            Сразу в работу (откроет сессию и hold)
          </label>
          <div>
            <label className="field-label">Заметки</label>
            <textarea className="input w-full" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </div>
          {err && <p className="text-red-400 text-sm">{err}</p>}
          <button
            className="btn-primary w-full"
            disabled={
              !name
              || createCard.isPending
              || (goOnline && !dailyLimit)
              || (createChannel === 'c2c' && !cardNumber)
              || (createChannel === 'sbp' && (!phone || !recipient))
            }
            onClick={() => createCard.mutate()}
          >
            Создать
          </button>
        </div>
      </Modal>
    </AppShell>
  );
}

function CardRows({
  card: c,
  selected,
  expanded,
  primary,
  onSelect,
  onExpand,
  onToggle,
  onStatus,
}: {
  card: TraderCard;
  selected: boolean;
  expanded: boolean;
  primary: 'RUB' | 'USDT';
  onSelect: () => void;
  onExpand: () => void;
  onToggle: () => void;
  onStatus: (status: string) => void;
}) {
  const bands = c.payment_bands?.length
    ? c.payment_bands.map((b) => `${b.min_rub}–${b.max_rub}`).join(' · ')
    : '—';
  return (
    <>
      <tr className={selected ? 'bg-accent/10' : ''}>
        <td><input type="checkbox" checked={selected} onChange={onSelect} /></td>
        <td>
          <button type="button" className="text-left" onClick={onExpand}>
            <div className="font-medium text-[#fafafa]">{c.name}</div>
            <div className="text-xs text-muted">
              {[c.channel === 'sbp' ? 'СБП' : 'C2C', c.recipient_name, c.channel === 'sbp' ? c.phone : (c.card_number || (c.last4 ? `•••• ${c.last4}` : null)), c.bank].filter(Boolean).join(' · ')}
            </div>
          </button>
        </td>
        <td>
          <div className="flex items-center gap-2">
            <Toggle on={!!c.accepting} disabled={c.status !== 'active'} onClick={onToggle} />
            {!c.accepting && c.not_accepting_reason && (
              <span className="text-[11px] text-amber-400">{REASON_LABELS[c.not_accepting_reason] || c.not_accepting_reason}</span>
            )}
          </div>
        </td>
        <td>
          <LimitBar received={Number(c.received_today_rub || 0)} limit={c.daily_limit_rub ? Number(c.daily_limit_rub) : null} />
          <p className="text-[10px] text-muted">{bands}</p>
        </td>
        <td>
          <select className="input py-1 text-sm" value={c.status} onChange={(e) => onStatus(e.target.value)}>
            {CARD_STATUSES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </td>
        <td>
          {c.session_id ? (
            <Link className="text-sm text-accent" to={`/trader/requisites/${c.session_id}`}>Сессия</Link>
          ) : (
            <span className="text-xs text-muted">нет сессии</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="bg-elevated/40 text-sm">
            <div className="grid gap-3 sm:grid-cols-4 py-2">
              <div>
                <p className="text-xs text-muted">Сессия</p>
                <p>{c.session_id ? `#${c.session_id} · ${statusLabel(c.session_status || '')}` : '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted">Остаток сессии</p>
                <p>{c.session_remaining_rub != null ? formatMoney(c.session_remaining_rub) : '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted">Float / hold</p>
                <p>{formatMoney(c.session_float_rub ?? 0)} · {formatUsdt(c.session_hold_usdt ?? 0)}</p>
              </div>
              <div>
                <p className="text-xs text-muted">Трафик</p>
                <p>{trafficAudienceLabel(c)}</p>
              </div>
              <div>
                <p className="text-xs text-muted">Затраты</p>
                <p>{formatDual(c.expenses_rub, c.expenses_usdt, primary)}</p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
