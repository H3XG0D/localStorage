import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, Download, Eye, Pencil, Plus, Trash2 } from 'lucide-react';
import { api, FakeCheck, formatDual, formatMoney, formatUsdt } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { AppShell } from '../../components/layout/AppShell';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Tabs } from '../../components/ui/Tabs';
import { Modal } from '../../components/ui/Modal';
import { FakeCheckModal } from '../../components/ui/FakeCheckModal';
import { FileUploadField } from '../../components/ui/FileUploadField';
import { translateApiError } from '../../utils/apiMessages';

interface RequisiteDetailPageProps {
  role: 'admin' | 'trader' | 'teamlead';
}

export function RequisiteDetailPage({ role }: RequisiteDetailPageProps) {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const isStaffView = user?.role === 'admin' || user?.role === 'teamlead';
  const { id } = useParams<{ id: string }>();
  const reqId = id ? parseInt(id, 10) : NaN;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState('zalivs');
  const [modalOpen, setModalOpen] = useState(false);
  const [fakeCheckModalOpen, setFakeCheckModalOpen] = useState(false);
  const [editingFakeCheck, setEditingFakeCheck] = useState<FakeCheck | null>(null);
  const [amount, setAmount] = useState('');
  const [rate, setRate] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [mutError, setMutError] = useState('');
  const [chargeAmount, setChargeAmount] = useState('');
  const [chargeOpen, setChargeOpen] = useState(false);

  const chargeback = useMutation({
    mutationFn: () => api.chargebackRequisite(reqId, parseFloat(chargeAmount), 'Admin chargeback'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', reqId] });
      setChargeOpen(false);
      setChargeAmount('');
      setMutError('');
    },
    onError: (err: Error) => setMutError(translateApiError(err.message)),
  });

  const { data: traderSettings } = useQuery({
    queryKey: ['trader-settings'],
    queryFn: api.traderSettings,
    enabled: role === 'trader',
    staleTime: 5 * 60 * 1000,
  });

  const { data: traderCardsList } = useQuery({
    queryKey: ['trader-cards'],
    queryFn: () => api.traderCards({ limit: 500 }),
    enabled: role === 'trader',
  });
  const traderCards = traderCardsList?.items;

  const fetchFn = isStaffView
    ? () => api.adminRequisite(reqId)
    : () => api.getRequisite(reqId);

  const { data: req, isLoading, isError } = useQuery({
    queryKey: ['requisite', reqId, role],
    queryFn: fetchFn,
    enabled: !Number.isNaN(reqId),
  });
  const { data: dealResult } = useQuery({
    queryKey: ['deal-result', reqId, role],
    queryFn: () => isStaffView ? api.adminDealResult(reqId) : api.traderDealResult(reqId),
    enabled: isStaffView || role === 'trader',
  });
  const { data: fakeCheckHistory } = useQuery({
    queryKey: ['fake-check-history', reqId],
    queryFn: () => api.fakeCheckHistory(reqId),
    enabled: isAdmin && !Number.isNaN(reqId),
  });

  const addZaliv = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append('amount', amount);
      form.append('rate', rate);
      if (file) form.append('receipt', file);
      return api.addZaliv(reqId, form);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', reqId] });
      setModalOpen(false);
      setAmount(''); setRate(''); setFile(null); setMutError('');
    },
    onError: (err: Error) => setMutError(translateApiError(err.message)),
  });

  const sendDoliv = useMutation({
    mutationFn: () => api.sendToDoliv(reqId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', reqId] });
      setMutError('');
    },
    onError: (err: Error) => setMutError(translateApiError(err.message)),
  });

  const archiveReq = useMutation({
    mutationFn: () => api.archiveRequisite(reqId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', reqId] });
      qc.invalidateQueries({ queryKey: ['requisites'] });
    },
    onError: (err: Error) => setMutError(translateApiError(err.message)),
  });

  const deactivateReq = useMutation({
    mutationFn: () =>
      isStaffView ? api.adminDeactivateRequisite(reqId) : api.deactivateRequisite(reqId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', reqId] });
      qc.invalidateQueries({ queryKey: ['requisites'] });
      navigate(
        user?.role === 'teamlead'
          ? '/teamlead/requisites'
          : role === 'admin'
            ? '/admin/requisites'
            : '/trader/requisites',
      );
    },
    onError: (err: Error) => setMutError(translateApiError(err.message)),
  });

  const canDeactivate = req && req.status !== 'archive';

  const deleteFakeCheck = useMutation({
    mutationFn: (fcId: number) => api.deleteFakeCheck(fcId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', reqId] });
      qc.invalidateQueries({ queryKey: ['fake-check-history', reqId] });
      qc.invalidateQueries({ queryKey: ['admin-dashboard-stats'] });
      qc.invalidateQueries({ queryKey: ['admin-analytics'] });
    },
    onError: (err: Error) => setMutError(translateApiError(err.message)),
  });

  const actionLabels: Record<string, string> = {
    created: 'Добавлен фейк-чек',
    updated: 'Изменён фейк-чек',
    deleted: 'Удалён фейк-чек',
  };

  const downloadFakeCheckFile = async (fcId: number, fileName: string | null) => {
    const blob = await api.downloadFakeCheckFile(fcId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName || `fake_check_${fcId}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadPdf = async () => {
    const blob = isStaffView
      ? await api.downloadPdf(reqId)
      : await api.downloadTraderPdf(reqId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `requisite_${reqId}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadReceipt = async (type: 'zaliv' | 'doliv', receiptId: number) => {
    const blob = isStaffView
      ? await api.downloadReceipt(type, receiptId)
      : await api.downloadTraderReceipt(type, receiptId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${type}_${receiptId}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (Number.isNaN(reqId)) {
    return (
      <AppShell title="Реквизит">
        <p className="text-red-400 text-sm">Некорректный ID реквизита.</p>
      </AppShell>
    );
  }

  if (isLoading) {
    return (
      <AppShell title="Реквизит">
        <p className="text-muted text-sm">Загрузка...</p>
      </AppShell>
    );
  }

  if (isError || !req) {
    return (
      <AppShell title="Реквизит">
        <p className="text-red-400 text-sm">Не удалось загрузить реквизит. Проверьте подключение или обновите страницу.</p>
        <button className="btn-secondary mt-3 text-xs" onClick={() => navigate(-1)}>← Назад</button>
      </AppShell>
    );
  }

  const totalAmount = parseFloat(req.total_amount);
  const targetRate = parseFloat(req.target_rate);
  const progress = totalAmount > 0 ? (parseFloat(req.zaliv_total) / totalAmount) * 100 : 0;

  const toUsdt = (rub: string | number, rate?: string | number) => {
    const r = typeof rate !== 'undefined' ? parseFloat(String(rate)) : targetRate;
    const amount = typeof rub === 'string' ? parseFloat(rub) : rub;
    if (!r || r <= 0 || !Number.isFinite(amount)) return null;
    return formatUsdt(amount / r);
  };
  const listPath =
    user?.role === 'teamlead'
      ? '/teamlead/requisites'
      : isAdmin
        ? '/admin/requisites'
        : '/trader/requisites';
  const canEdit = role === 'trader' && !['closed', 'archive', 'doliv_in_progress'].includes(req.status);
  const canSendToDoliv = canEdit && req.status !== 'awaiting_doliv' && parseFloat(req.remaining) > 0;

  return (
    <AppShell title={req.name}>
      <button onClick={() => navigate(listPath)} className="text-xs text-muted hover:text-accent mb-4">
        ← Назад к списку
      </button>

      {isAdmin && (
        <div className="mb-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-danger flex items-center gap-2 text-sm"
            onClick={() => { setEditingFakeCheck(null); setFakeCheckModalOpen(true); }}
          >
            <AlertTriangle size={16} /> Добавить фейк-чек
          </button>
          <button
            type="button"
            className="btn-secondary text-sm"
            onClick={() => {
              setChargeAmount(req.hold_usdt || '');
              setChargeOpen(true);
            }}
          >
            Chargeback с депозита
          </button>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        {[
          { label: 'Сумма реквизита', rub: formatMoney(req.total_amount), usdt: toUsdt(req.total_amount) },
          { label: 'Залито', rub: formatMoney(req.zaliv_total), usdt: toUsdt(req.zaliv_total) },
          { label: 'Остаток', rub: formatMoney(req.remaining), usdt: toUsdt(req.remaining) },
          { label: 'На карте (float)', rub: formatMoney(req.float_rub || 0), usdt: null },
          { label: 'Hold USDT', rub: req.hold_usdt ? formatUsdt(req.hold_usdt) : '—', usdt: null },
          { label: 'Средний курс', rub: req.avg_rate ?? '—', usdt: null },
          { label: 'Текущая прибыль', rub: formatUsdt(req.current_profit), usdt: null },
          { label: 'Целевой курс', rub: req.target_rate, usdt: null },
        ].map((kpi) => (
          <div key={kpi.label} className="card">
            <p className="text-xs text-muted">{kpi.label}</p>
            <p className="text-lg font-bold mt-1">{kpi.rub}</p>
            {kpi.usdt && <p className="text-xs text-muted mt-0.5">{kpi.usdt}</p>}
          </div>
        ))}
      </div>

      {role === 'trader' && (
        <div className="card mb-6 p-4">
          <h3 className="font-semibold mb-2">Привязанные карты</h3>
          {(() => {
            const linked = (traderCards ?? []).filter((c) => c.linked_requisite_id === reqId);
            if (!linked.length) {
              return <p className="text-sm text-muted">Нет карт, привязанных к этому реквизиту. Привязку можно задать в «Карты».</p>;
            }
            return (
              <ul className="space-y-2 text-sm">
                {linked.map((c) => (
                  <li key={c.id} className="flex flex-wrap justify-between gap-2">
                    <span>
                      {c.name}
                      {c.last4 ? ` •••• ${c.last4}` : ''}
                      <span className="text-muted ml-2">{c.status}</span>
                    </span>
                    <span className="text-muted">{formatDual(c.expenses_rub, c.expenses_usdt)}</span>
                  </li>
                ))}
              </ul>
            );
          })()}
          <div className="mt-3 flex flex-wrap gap-2 items-center">
            <select
              className="input text-sm"
              id={`link-card-${reqId}`}
              defaultValue=""
              onChange={async (e) => {
                const cardId = Number(e.target.value);
                if (!cardId) return;
                try {
                  await api.updateTraderCard(cardId, { linked_requisite_id: reqId });
                  qc.invalidateQueries({ queryKey: ['trader-cards'] });
                  e.target.value = '';
                } catch (err) {
                  setMutError(err instanceof Error ? err.message : 'Ошибка привязки');
                }
              }}
            >
              <option value="">Привязать карту…</option>
              {(traderCards ?? [])
                .filter((c) => c.linked_requisite_id !== reqId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{c.last4 ? ` •••• ${c.last4}` : ''}
                  </option>
                ))}
            </select>
          </div>
        </div>
      )}

      <Modal open={chargeOpen} onClose={() => setChargeOpen(false)} title="Chargeback">
        <div className="space-y-3">
          <p className="text-sm text-muted">Списать USDT с work-токена (ориентир — float {formatMoney(req.float_rub || 0)}).</p>
          <input className="input w-full" value={chargeAmount} onChange={(e) => setChargeAmount(e.target.value)} placeholder="USDT" />
          <button className="btn-danger w-full" disabled={!chargeAmount || chargeback.isPending} onClick={() => chargeback.mutate()}>
            Списать
          </button>
        </div>
      </Modal>

      {mutError && (
        <p className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
          {mutError}
        </p>
      )}

      <div className="card mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-3">
            <StatusBadge status={req.status} />
            {req.trader_name && <span className="text-sm text-muted">Трейдер: {req.trader_name}</span>}
          </div>
          <div className="flex gap-2 flex-wrap">
            {req.status === 'closed' && (
              <button onClick={downloadPdf} className="btn-secondary flex items-center gap-2 text-xs">
                <Download size={14} /> PDF чеков
              </button>
            )}
            {req.status === 'closed' && role === 'trader' && (
              <button
                className="btn-secondary text-xs"
                onClick={() => {
                  if (confirm('Переместить реквизит в архив? Это действие необратимо.')) {
                    archiveReq.mutate();
                  }
                }}
                disabled={archiveReq.isPending}
              >
                В архив
              </button>
            )}
            {canDeactivate && (
              <button
                className="btn-secondary text-xs text-red-400 border-red-500/30 hover:bg-red-500/10"
                onClick={() => {
                  if (confirm('Реквизит будет отключён. Активная заявка на долив будет отменена. Продолжить?')) {
                    deactivateReq.mutate();
                  }
                }}
                disabled={deactivateReq.isPending}
              >
                Отключить рек
              </button>
            )}
            {canEdit && (
              <>
                <button
                  className="btn-secondary text-xs flex items-center gap-1"
                  onClick={() => setModalOpen(true)}
                >
                  <Plus size={14} /> Залив
                </button>
                <button
                  className="btn-primary text-xs"
                  onClick={() => sendDoliv.mutate()}
                  disabled={sendDoliv.isPending || !canSendToDoliv}
                >
                  {req.status === 'awaiting_doliv' ? 'На доливе' : 'На долив'}
                </button>
              </>
            )}
          </div>
        </div>
        <div className="flex justify-between text-xs text-muted mb-1">
          <span>{formatMoney(req.zaliv_total)}</span>
          <span>{formatMoney(req.total_amount)}</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${Math.min(progress, 100)}%` }} />
        </div>
      </div>

      {dealResult && (
        <div className="card mb-6">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold">Итог сделки</h3>
              <p className="text-xs text-muted">Расчет сформирован после завершения долива</p>
            </div>
            <span className="text-xs text-muted">{new Date(dealResult.calculated_at).toLocaleString('ru')}</span>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Оборот</p>
              <p className="mt-1 font-semibold">{formatMoney(dealResult.total_turnover)}</p>
              {toUsdt(dealResult.total_turnover, dealResult.avg_rate) && (
                <p className="text-xs text-muted mt-0.5">{toUsdt(dealResult.total_turnover, dealResult.avg_rate)}</p>
              )}
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Средний курс</p>
              <p className="mt-1 font-semibold">{dealResult.avg_rate}</p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Долив</p>
              <p className="mt-1 font-semibold">{formatMoney(dealResult.doliv_amount)}</p>
              {toUsdt(dealResult.doliv_amount, dealResult.doliv_rate ?? dealResult.avg_rate) && (
                <p className="text-xs text-muted mt-0.5">{toUsdt(dealResult.doliv_amount, dealResult.doliv_rate ?? dealResult.avg_rate)}</p>
              )}
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Курс долива</p>
              <p className="mt-1 font-semibold">{dealResult.doliv_rate ?? '—'}</p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Прибыль заливов</p>
              <p className="mt-1 font-semibold text-emerald-400">{formatUsdt(dealResult.zaliv_profit)}</p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Долив +/-</p>
              <p className={`mt-1 font-semibold ${parseFloat(dealResult.doliv_profit_loss) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatUsdt(dealResult.doliv_profit_loss)}
              </p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Финал</p>
              <p className={`mt-1 font-semibold ${parseFloat(dealResult.final_profit) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatUsdt(dealResult.final_profit)}
              </p>
            </div>
          </div>
        </div>
      )}

      {isAdmin && (
        <div className="card mb-6">
          <h3 className="font-semibold mb-3">Прибыль с учётом фейк-чеков</h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Валовая прибыль</p>
              <p className={`mt-1 font-semibold ${parseFloat(req.gross_profit ?? '0') >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatUsdt(req.gross_profit ?? '0')}
              </p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Потери на доливах</p>
              <p className="mt-1 font-semibold text-red-400">-{formatUsdt(req.doliv_loss ?? '0')}</p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3">
              <p className="text-xs text-muted">Потери по фейк-чекам</p>
              <p className="mt-1 font-semibold text-red-400">-{formatUsdt(req.fake_check_loss ?? '0')}</p>
            </div>
            <div className="rounded-xl bg-elevated/40 p-3 border border-border/80">
              <p className="text-xs text-muted font-medium">Чистая прибыль</p>
              <p className={`mt-1 font-bold text-lg ${parseFloat(req.net_profit ?? '0') >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatUsdt(req.net_profit ?? '0')}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <Tabs
          tabs={[
            { id: 'zalivs', label: `Заливы (${req.zalivs.length})` },
            ...(isAdmin ? [{ id: 'fake-checks', label: `Фейк-чеки (${req.fake_checks?.length ?? 0})` }] : []),
            { id: 'receipts', label: 'Чеки' },
            { id: 'history', label: 'История' },
          ]}
          active={tab}
          onChange={setTab}
        />

        {tab === 'zalivs' && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th><th>Сумма (₽)</th><th>Сумма (USDT)</th><th>Курс</th><th>% прибыли</th><th>Прибыль</th><th>Дата</th>
                </tr>
              </thead>
              <tbody>
                {req.zalivs.map((z, i) => (
                  <tr key={z.id}>
                    <td className="text-muted">{i + 1}</td>
                    <td>{formatMoney(z.amount)}</td>
                    <td className="text-muted">{toUsdt(z.amount, z.rate) ?? '—'}</td>
                    <td>{z.rate}</td>
                    <td className="text-emerald-400">+{z.profit_percent}%</td>
                    <td className="text-emerald-400">+{formatUsdt(parseFloat(req.target_rate) > 0 ? (parseFloat(z.amount) * parseFloat(z.profit_percent) / 100 / parseFloat(req.target_rate)) : 0)}</td>
                    <td className="text-muted">{new Date(z.created_at).toLocaleString('ru')}</td>
                  </tr>
                ))}
                {!req.zalivs.length && (
                  <tr><td colSpan={6} className="text-center text-muted py-6">Нет заливов</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'fake-checks' && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Дата</th>
                  <th>Сумма ₽</th>
                  <th>Курс</th>
                  <th>Сумма USDT</th>
                  <th>Кто добавил</th>
                  <th>Комментарий</th>
                  <th>Файл</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {(req.fake_checks ?? []).map((fc) => (
                  <tr key={fc.id}>
                    <td className="text-muted">#{fc.id}</td>
                    <td>{new Date(fc.operation_date).toLocaleDateString('ru')}</td>
                    <td className="text-red-400">-{formatMoney(fc.amount_rub)}</td>
                    <td>{fc.rate}</td>
                    <td className="text-red-400">-{formatUsdt(fc.amount_usdt)}</td>
                    <td className="text-muted">{fc.created_by_name ?? '—'}</td>
                    <td className="text-muted max-w-xs truncate">{fc.comment ?? '—'}</td>
                    <td>
                      {fc.file_path ? (
                        <div className="flex gap-1">
                          <button
                            className="text-accent hover:underline text-xs flex items-center gap-1"
                            onClick={() => void downloadFakeCheckFile(fc.id, fc.file_path)}
                          >
                            <Eye size={12} /> Файл
                          </button>
                        </div>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td>
                      <div className="flex gap-1">
                        <button
                          className="text-muted hover:text-accent p-1"
                          title="Редактировать"
                          onClick={() => {
                            setEditingFakeCheck(fc);
                            setFakeCheckModalOpen(true);
                          }}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          className="text-red-400 hover:text-red-300 p-1"
                          title="Удалить"
                          onClick={() => {
                            if (confirm('Удалить фейк-чек?')) deleteFakeCheck.mutate(fc.id);
                          }}
                          disabled={deleteFakeCheck.isPending}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!(req.fake_checks ?? []).length && (
                  <tr>
                    <td colSpan={9} className="text-center text-muted py-6">Нет фейк-чеков</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'receipts' && (
          <ul className="space-y-2">
            {req.zalivs.map((z) => (
              <li key={z.id} className="flex items-center justify-between py-2 border-b border-border/50 text-sm">
                <span>Залив {formatMoney(z.amount)}</span>
                <button
                  className="text-muted text-xs truncate max-w-xs hover:text-accent"
                  onClick={() => void downloadReceipt('zaliv', z.id)}
                >
                  {z.receipt_path.split('/').pop()}
                </button>
              </li>
            ))}
            {!req.zalivs.length && <p className="text-muted text-sm py-4">Нет чеков</p>}
          </ul>
        )}

        {tab === 'history' && (
          <div className="space-y-4 text-sm">
            <div className="text-muted space-y-1">
              <p>Создан: {new Date(req.created_at).toLocaleString('ru')}</p>
              <p>Обновлён: {new Date(req.updated_at).toLocaleString('ru')}</p>
              {req.comment && <p>Комментарий: {req.comment}</p>}
            </div>
            {isAdmin && (
              <div>
                <h4 className="font-medium mb-2">История фейк-чеков</h4>
                {(fakeCheckHistory ?? []).length ? (
                  <ul className="space-y-2">
                    {(fakeCheckHistory ?? []).map((log) => (
                      <li key={log.id} className="rounded-lg border border-border/60 bg-elevated/30 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-medium">{actionLabels[log.action] ?? log.action}</span>
                          <span className="text-xs text-muted">{new Date(log.created_at).toLocaleString('ru')}</span>
                        </div>
                        <p className="text-muted mt-1">
                          {log.user_name ?? '—'}
                          {log.amount_usdt != null && ` · -${formatUsdt(log.amount_usdt)}`}
                          {log.amount_rub != null && ` · ${formatMoney(log.amount_rub)}`}
                          {log.rate != null && ` · курс ${log.rate}`}
                        </p>
                        {log.comment && <p className="text-muted mt-1">{log.comment}</p>}
                        {log.file_path && <p className="text-xs text-muted mt-1">Файл: {log.file_path}</p>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted">Нет записей о фейк-чеках</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <FakeCheckModal
        open={fakeCheckModalOpen}
        onClose={() => { setFakeCheckModalOpen(false); setEditingFakeCheck(null); }}
        requisiteId={reqId}
        fakeCheck={editingFakeCheck}
      />

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Добавить залив">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!file) {
              setMutError('Прикрепите файл чека');
              return;
            }
            setMutError('');
            addZaliv.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-muted mb-1">Сумма</label>
              <input className="input" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Курс</label>
              <input className="input" type="number" step="0.0001" value={rate} onChange={(e) => setRate(e.target.value)} required />
            </div>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">% прибыли</label>
            <p className="input bg-elevated/40 text-emerald-400 cursor-default">
              {traderSettings?.profit_percent ?? '—'}%
            </p>
            <p className="text-xs text-muted mt-1">Фиксированный процент, задаётся администратором</p>
          </div>
          <FileUploadField
            file={file}
            onChange={setFile}
            label="Прикрепить чек (JPG, PNG, PDF или фото с телефона)"
            requiredHint="Чек обязателен"
          />
          <button type="submit" className="btn-primary w-full" disabled={addZaliv.isPending}>Добавить</button>
        </form>
      </Modal>
    </AppShell>
  );
}
