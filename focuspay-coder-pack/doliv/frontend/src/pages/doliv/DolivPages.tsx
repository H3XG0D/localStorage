import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bell,
  CheckCircle,
  Clock,
  Download,
  Droplets,
  FileText,
  ListChecks,
  Wallet,
} from 'lucide-react';
import { api, ApiError, formatMoney, formatUsdt } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { FileUploadField } from '../../components/ui/FileUploadField';
import { StatCard } from '../../components/ui/StatCard';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { SearchInput } from '../../components/ui/SearchInput';
import { isDolivSoundEnabled, setDolivSoundEnabled, useDolivAlert, useDolivPolling } from '../../hooks/useDolivAlert';
import { translateApiError } from '../../utils/apiMessages';
import type { DolivRequest, Receipt } from '../../api/client';

interface HistoryRow {
  id: number;
  amount: string;
  rate: string;
  receipt_path: string;
  completed_at: string;
  dolivshchik_name?: string | null;
}

function amountsMatch(input: string, required: string): boolean {
  const a = parseFloat(input.replace(',', '.'));
  const b = parseFloat(required.replace(',', '.'));
  return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 0.005;
}

function RequestRow({
  request,
  onTake,
  onComplete,
  takingId,
  onSelect,
  selected,
}: {
  request: DolivRequest;
  onTake: (id: number) => void;
  onComplete: (id: number) => void;
  takingId: number | null;
  onSelect?: (id: number) => void;
  selected?: boolean;
}) {
  const isTaking = takingId === request.id;

  return (
    <div
      className={`grid gap-3 rounded-2xl border p-3 text-sm md:grid-cols-[1.25fr_0.75fr_0.65fr_0.85fr_auto] md:items-center ${
        selected ? 'border-accent/50 bg-accent/10' : 'border-border bg-elevated/40'
      }`}
    >
      <button
        type="button"
        className={`min-w-0 text-left ${onSelect ? 'cursor-pointer hover:opacity-90' : 'cursor-default'}`}
        onClick={onSelect ? () => onSelect(request.id) : undefined}
        disabled={!onSelect}
      >
        <p className="font-semibold">{request.requisite_name ?? `Заявка #${request.id}`}</p>
        <p className="mt-0.5 text-xs text-muted">Трейдер: {request.trader_name ?? 'Не назначен'}</p>
      </button>
      <span className="font-medium">{formatMoney(request.required_amount)}</span>
      <span className="text-muted">{request.target_rate ?? '—'}</span>
      <div>
        <StatusBadge status={request.status} />
      </div>
      {request.status === 'pending' ? (
        <button
          type="button"
          className="rounded-xl bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-60"
          onClick={() => onTake(request.id)}
          disabled={isTaking}
        >
          {isTaking ? 'Загрузка...' : 'Взять'}
        </button>
      ) : request.status === 'in_progress' ? (
        <button
          type="button"
          className="rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
          onClick={() => onComplete(request.id)}
        >
          Выполнить
        </button>
      ) : (
        <span className="text-xs text-muted">Готово</span>
      )}
    </div>
  );
}

export default function DolivDashboard() {
  const [soundOn, setSoundOn] = useState(isDolivSoundEnabled());
  const [myDolivsSearch, setMyDolivsSearch] = useState('');
  const [actionError, setActionError] = useState('');
  const [formError, setFormError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [takingId, setTakingId] = useState<number | null>(null);
  const completeSectionRef = useRef<HTMLElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: requests, isLoading, isError, refetch } = useQuery({
    queryKey: ['doliv-requests'],
    queryFn: () => api.listDolivRequests(),
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
  const { data: stats } = useQuery({
    queryKey: ['doliv-stats'],
    queryFn: api.dolivStats,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
  });
  const { data: receipts } = useQuery({
    queryKey: ['doliv-receipts'],
    queryFn: api.dolivReceipts,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  }) as { data: Receipt[] | undefined };
  const qc = useQueryClient();

  useDolivPolling();

  const [activeId, setActiveId] = useState<number | null>(null);
  const [amount, setAmount] = useState('');
  const [rate, setRate] = useState('');
  const [file, setFile] = useState<File | null>(null);

  const selectRequest = (request: DolivRequest, scroll = true) => {
    setActionError('');
    setFormError('');
    setSuccessMessage('');
    setActiveId(request.id);
    setAmount(String(request.required_amount));
    setRate(request.target_rate ? String(request.target_rate) : '');
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (scroll) {
      completeSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const inProgress = requests?.filter((r) => r.status === 'in_progress') ?? [];

  useEffect(() => {
    if (!requests?.length || activeId != null) return;
    const first = requests.find((r) => r.status === 'in_progress');
    if (first) {
      setActiveId(first.id);
      setAmount(String(first.required_amount));
      setRate(first.target_rate ? String(first.target_rate) : '');
      setFile(null);
    }
  }, [requests, activeId]);

  const take = useMutation({
    mutationFn: (id: number) => api.takeRequest(id),
    onMutate: (id) => {
      setActionError('');
      setTakingId(id);
    },
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ['doliv-requests'] });
      const req = requests?.find((r) => r.id === id);
      if (req) {
        selectRequest({ ...req, status: 'in_progress' });
      }
    },
    onError: (err) => {
      setActionError(translateApiError(err instanceof ApiError ? err.message : 'Не удалось взять заявку'));
    },
    onSettled: () => setTakingId(null),
  });

  const complete = useMutation({
    mutationFn: (payload: { requestId: number; amount: string; rate: string; file: File }) => {
      const form = new FormData();
      form.append('amount', payload.amount);
      form.append('rate', payload.rate);
      form.append('receipt', payload.file);
      return api.completeDoliv(payload.requestId, form);
    },
    onMutate: () => {
      setActionError('');
      setFormError('');
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['doliv-requests'] });
      qc.invalidateQueries({ queryKey: ['doliv-history'] });
      qc.invalidateQueries({ queryKey: ['doliv-receipts'] });
      qc.invalidateQueries({ queryKey: ['doliv-stats'] });
      setActiveId(null);
      setAmount('');
      setRate('');
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      setSuccessMessage('Долив успешно завершён');
      completeSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    onError: (err) => {
      const message = translateApiError(err instanceof ApiError ? err.message : 'Не удалось завершить долив');
      setFormError(message);
      setActionError(message);
      completeSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
  });

  const pending = requests?.filter((r) => r.status === 'pending') ?? [];
  const myDolivsQuery = myDolivsSearch.trim().toLowerCase();
  const filteredInProgress = inProgress.filter((r) =>
    !myDolivsQuery
    || r.requisite_name?.toLowerCase().includes(myDolivsQuery)
    || r.trader_name?.toLowerCase().includes(myDolivsQuery)
    || String(r.id).includes(myDolivsQuery)
  );
  useDolivAlert(pending.map((r) => r.id));
  const activeRequest =
    (activeId != null ? requests?.find((r) => r.id === activeId) : undefined)
    ?? inProgress[0]
    ?? pending[0];

  const handleSelectById = (id: number) => {
    const req = requests?.find((r) => r.id === id);
    if (req) selectRequest(req);
  };

  const handleCompleteSubmit = (request: DolivRequest) => {
    setFormError('');
    setActionError('');

    if (!amount.trim()) {
      setFormError('Укажите сумму');
      return;
    }
    if (!rate.trim()) {
      setFormError('Укажите курс');
      return;
    }
    if (!amountsMatch(amount, request.required_amount)) {
      setFormError(`Сумма должна точно совпадать: ${formatMoney(request.required_amount)}`);
      return;
    }
    const rateNum = parseFloat(rate.replace(',', '.'));
    if (!Number.isFinite(rateNum) || rateNum < 50 || rateNum > 200) {
      setFormError('Курс должен быть от 50 до 200');
      return;
    }
    if (!file) {
      setFormError('Прикрепите файл чека — без него заявку нельзя закрыть');
      return;
    }

    complete.mutate({
      requestId: request.id,
      amount: String(request.required_amount),
      rate: rate.trim(),
      file,
    });
  };

  const downloadReceipt = async (receipt: Receipt) => {
    try {
      const blob = await api.downloadDolivReceipt(receipt.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `doliv_${receipt.id}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setActionError(translateApiError(err instanceof ApiError ? err.message : 'Не удалось скачать чек'));
    }
  };
  const statTiles = [
    { label: 'Новые заявки', value: pending.length, icon: ListChecks, accent: '#2563eb' },
    { label: 'В работе', value: inProgress.length, icon: Clock, accent: '#f59e0b' },
    { label: 'Доливов сегодня', value: stats?.dolivs_today ?? 0, icon: CheckCircle, accent: '#22c55e' },
    { label: 'Ставка', value: stats?.salary_per_doliv_usdt ? `${stats.salary_per_doliv_usdt} USDT` : '—', icon: Wallet, accent: '#6366f1' },
    { label: 'Заработок сегодня', value: formatUsdt(stats?.earnings_today ?? '0'), icon: Bell, accent: '#10b981' },
    { label: 'Средний курс', value: String(stats?.avg_doliv_rate ?? '—'), icon: Droplets, accent: '#06b6d4' },
  ];

  return (
    <AppShell title="Главная">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Доливщик</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight">Рабочая очередь</h2>
          <p className="mt-1 text-sm text-muted">Новые заявки, выполнение долива, чеки и история в одном экране.</p>
        </div>
        <div className="rounded-2xl border border-border bg-elevated/40 px-4 py-2 text-sm flex items-center gap-3">
          <span className="text-muted">Сегодня: </span>
          <span className="font-semibold">{new Date().toLocaleDateString('ru')}</span>
          <button
            type="button"
            className="ml-2 text-xs text-accent hover:text-accent-hover"
            onClick={() => {
              const next = !soundOn;
              setSoundOn(next);
              setDolivSoundEnabled(next);
              if (next && typeof Notification !== 'undefined' && Notification.permission === 'default') {
                Notification.requestPermission();
              }
            }}
          >
            Звук: {soundOn ? 'вкл' : 'выкл'}
          </button>
        </div>
      </div>

      {isError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center justify-between gap-3">
          <span>Не удалось загрузить заявки</span>
          <button type="button" className="text-accent hover:text-accent-hover shrink-0" onClick={() => void refetch()}>
            Повторить
          </button>
        </div>
      )}

      {actionError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {actionError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        {statTiles.map((tile) => (
          <StatCard key={tile.label} {...tile} />
        ))}
      </div>

      {successMessage && (
        <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {successMessage}
        </div>
      )}

      <div className="mt-5 grid gap-4 xl:grid-cols-[1.1fr_0.9fr_0.85fr]">
        <section ref={completeSectionRef} className="card scroll-mt-4 order-first xl:order-none">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold">Выполнение долива</h3>
              <p className="text-xs text-muted">{activeRequest ? `Заявка #${activeRequest.id}` : 'Выберите заявку в работе'}</p>
            </div>
            {activeRequest && <StatusBadge status={activeRequest.status} />}
          </div>
          {activeRequest ? (
            <>
              <div className="rounded-2xl bg-elevated/40 p-4">
                <p className="font-semibold">{activeRequest.requisite_name ?? 'Реквизит'}</p>
                <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-muted">Трейдер</p>
                    <p className="font-medium">{activeRequest.trader_name ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Сумма</p>
                    <p className="font-medium">{formatMoney(activeRequest.required_amount)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Курс</p>
                    <p className="font-medium">{activeRequest.target_rate ?? '—'}</p>
                  </div>
                </div>
              </div>
              {activeRequest.status === 'in_progress' || activeId === activeRequest.id ? (
                <form
                  className="mt-4 space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleCompleteSubmit(activeRequest);
                  }}
                >
                  {formError && (
                    <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                      {formError}
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-3">
                    <input className="input" placeholder="Сумма" type="number" step="0.01" inputMode="decimal" value={amount} onChange={(e) => { setAmount(e.target.value); setFormError(''); }} />
                    <input className="input" placeholder="Курс" type="number" step="0.0001" inputMode="decimal" value={rate} onChange={(e) => { setRate(e.target.value); setFormError(''); }} />
                  </div>
                  <p className="text-xs text-muted">
                    Сумма должна точно совпадать: {formatMoney(activeRequest.required_amount)}
                  </p>
                  <FileUploadField
                    file={file}
                    inputRef={fileInputRef}
                    onChange={(f) => { setFile(f); setFormError(''); }}
                    requiredHint="Чек обязателен — без файла кнопка не отправит заявку"
                  />
                  <button type="submit" className="btn-primary w-full" disabled={complete.isPending}>
                    {complete.isPending ? 'Сохранение...' : 'Подтвердить выполнение'}
                  </button>
                </form>
              ) : (
                <button
                  type="button"
                  className="btn-primary mt-4 w-full disabled:opacity-60"
                  onClick={() => take.mutate(activeRequest.id)}
                  disabled={takingId === activeRequest.id}
                >
                  {takingId === activeRequest.id ? 'Загрузка...' : 'Взять заявку в работу'}
                </button>
              )}
            </>
          ) : (
            <p className="py-12 text-center text-sm text-muted">Активной заявки нет</p>
          )}
        </section>

        <section className="card order-2 xl:order-none">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold">Новые доливы</h3>
              <p className="text-xs text-muted">Заявки, доступные для взятия в работу</p>
            </div>
            <span className="rounded-full bg-accent/15 px-3 py-1 text-xs font-semibold text-accent">{pending.length} новых</span>
          </div>
          {isLoading && <p className="py-6 text-center text-sm text-muted">Загрузка...</p>}
          <div className="space-y-2">
            {pending.slice(0, 6).map((r) => (
              <RequestRow
                key={r.id}
                request={r}
                onTake={(id) => take.mutate(id)}
                onComplete={handleSelectById}
                takingId={takingId}
              />
            ))}
            {!pending.length && !isLoading && <p className="py-8 text-center text-sm text-muted">Нет новых заявок</p>}
          </div>
        </section>

        <section className="card order-3 xl:order-none">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold">Мои доливы</h3>
              <p className="text-xs text-muted">Заявки в работе</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-amber-500/15 px-3 py-1 text-xs font-semibold text-amber-400">
                {inProgress.length} в работе
              </span>
              <Link to="/doliv/history" className="text-xs font-medium text-accent hover:text-accent-hover">
                История
              </Link>
            </div>
          </div>
          <SearchInput
            value={myDolivsSearch}
            onChange={setMyDolivsSearch}
            placeholder="Поиск по реквизиту, трейдеру, №..."
            className="mb-3"
          />
          <div className="max-h-80 space-y-2 overflow-y-auto">
            {filteredInProgress.map((r) => (
              <RequestRow
                key={r.id}
                request={r}
                onTake={(id) => take.mutate(id)}
                onComplete={handleSelectById}
                takingId={takingId}
                onSelect={handleSelectById}
                selected={activeId === r.id}
              />
            ))}
            {!inProgress.length && <p className="py-8 text-center text-sm text-muted">Пока нет доливов в работе</p>}
            {inProgress.length > 0 && !filteredInProgress.length && (
              <p className="py-8 text-center text-sm text-muted">Ничего не найдено</p>
            )}
          </div>
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold">Чеки</h3>
            <FileText size={18} className="text-muted" />
          </div>
          <div className="space-y-2">
            {(receipts ?? []).slice(0, 4).map((receipt) => (
              <div key={receipt.id} className="flex items-center gap-3 rounded-2xl bg-elevated/35 p-3 text-sm">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15 text-accent">
                  <FileText size={17} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{receipt.requisite_name}</p>
                  <p className="text-xs text-muted">{formatMoney(receipt.amount)} · курс {receipt.rate}</p>
                </div>
                <button type="button" className="text-muted hover:text-accent" onClick={() => void downloadReceipt(receipt)} title="Скачать чек">
                  <Download size={16} />
                </button>
              </div>
            ))}
            {!receipts?.length && <p className="py-8 text-center text-sm text-muted">Нет чеков</p>}
          </div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold">Уведомления</h3>
            <Bell size={18} className="text-muted" />
          </div>
          <div className="space-y-2">
            {pending.slice(0, 3).map((r) => (
              <div key={r.id} className="rounded-2xl border border-accent/30 bg-accent/10 p-3 text-sm">
                <p className="font-medium">Новая заявка #{r.id}</p>
                <p className="mt-1 text-xs text-muted">{r.trader_name ?? 'Трейдер'} ожидает долив на {formatMoney(r.required_amount)}</p>
              </div>
            ))}
            {!pending.length && <p className="py-8 text-center text-sm text-muted">Новых уведомлений нет</p>}
          </div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold">Новая заявка на долив</h3>
            <Clock size={18} className="text-muted" />
          </div>
          <div className="rounded-2xl bg-elevated/40 p-4">
            <p className="text-sm text-muted">Последняя новая заявка</p>
            <p className="mt-2 font-semibold">{pending[0]?.requisite_name ?? 'Нет заявок'}</p>
            {pending[0] && (
              <p className="mt-1 text-xs text-muted">
                {formatMoney(pending[0].required_amount)} · курс {pending[0].target_rate ?? '—'}
              </p>
            )}
          </div>
          {pending[0] && (
            <button
              type="button"
              className="btn-primary mt-3 w-full disabled:opacity-60"
              onClick={() => take.mutate(pending[0].id)}
              disabled={takingId === pending[0].id}
            >
              {takingId === pending[0].id ? 'Загрузка...' : 'Принять заявку'}
            </button>
          )}
        </section>
      </div>
    </AppShell>
  );
}

export function DolivHistory() {
  const { data: history, isLoading, isError, refetch } = useQuery({
    queryKey: ['doliv-history'],
    queryFn: api.dolivHistory,
  }) as { data: HistoryRow[] | undefined; isLoading: boolean; isError: boolean; refetch: () => void };

  return (
    <AppShell title="История доливов">
      {isError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center justify-between gap-3">
          <span>Не удалось загрузить историю</span>
          <button type="button" className="text-accent hover:text-accent-hover shrink-0" onClick={() => void refetch()}>
            Повторить
          </button>
        </div>
      )}

      {isLoading && <p className="py-8 text-center text-sm text-muted">Загрузка...</p>}

      <div className="md:hidden space-y-3">
        {(history ?? []).map((h) => (
          <div key={h.id} className="rounded-2xl border border-border bg-elevated/40 p-4 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted">#{h.id}</span>
              <span className="text-xs text-muted">{new Date(h.completed_at).toLocaleString('ru')}</span>
            </div>
            <p className="mt-2 font-semibold">{formatMoney(h.amount)}</p>
            <p className="mt-1 text-muted">Курс: {h.rate}</p>
          </div>
        ))}
        {!isLoading && !history?.length && (
          <p className="py-8 text-center text-sm text-muted">Пусто</p>
        )}
      </div>

      <div className="table-wrap hidden md:block">
        <table className="data-table">
          <thead>
            <tr><th>ID</th><th>Сумма</th><th>Курс</th><th>Дата</th></tr>
          </thead>
          <tbody>
            {(history ?? []).map((h) => (
              <tr key={h.id}>
                <td className="text-muted">#{h.id}</td>
                <td>{formatMoney(h.amount)}</td>
                <td>{h.rate}</td>
                <td className="text-muted">{new Date(h.completed_at).toLocaleString('ru')}</td>
              </tr>
            ))}
            {!isLoading && !history?.length && <tr><td colSpan={4} className="text-center text-muted py-8">Пусто</td></tr>}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
