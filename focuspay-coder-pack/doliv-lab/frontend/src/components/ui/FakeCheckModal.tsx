import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, FakeCheck } from '../../api/client';
import { Modal } from './Modal';
import { FileUploadField } from './FileUploadField';

interface FakeCheckModalProps {
  open: boolean;
  onClose: () => void;
  requisiteId: number;
  fakeCheck?: FakeCheck | null;
}

export function FakeCheckModal({ open, onClose, requisiteId, fakeCheck }: FakeCheckModalProps) {
  const qc = useQueryClient();
  const isEdit = Boolean(fakeCheck);
  const [amountRub, setAmountRub] = useState('');
  const [rate, setRate] = useState('');
  const [amountUsdt, setAmountUsdt] = useState('');
  const [comment, setComment] = useState('');
  const [operationDate, setOperationDate] = useState(new Date().toISOString().slice(0, 10));
  const [file, setFile] = useState<File | null>(null);
  const [lastChanged, setLastChanged] = useState<'rub' | 'usdt' | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) {
      setAmountRub(''); setRate(''); setAmountUsdt('');
      setComment(''); setFile(null); setError('');
      setLastChanged(null);
      setOperationDate(new Date().toISOString().slice(0, 10));
      return;
    }
    if (fakeCheck) {
      setAmountRub(String(fakeCheck.amount_rub));
      setRate(String(fakeCheck.rate));
      setAmountUsdt(String(fakeCheck.amount_usdt));
      setComment(fakeCheck.comment ?? '');
      setOperationDate(fakeCheck.operation_date);
      setFile(null);
      setLastChanged(null);
      setError('');
    }
  }, [open, fakeCheck]);

  const recompute = (rub: string, r: string, usdt: string, changed: 'rub' | 'usdt') => {
    const rateNum = parseFloat(r);
    if (!rateNum || rateNum <= 0) return;
    if (changed === 'rub') {
      const rubNum = parseFloat(rub);
      if (rubNum > 0) setAmountUsdt((rubNum / rateNum).toFixed(2));
    } else {
      const usdtNum = parseFloat(usdt);
      if (usdtNum > 0) setAmountRub((usdtNum * rateNum).toFixed(2));
    }
  };

  const handleRubChange = (v: string) => {
    setAmountRub(v);
    setLastChanged('rub');
    recompute(v, rate, amountUsdt, 'rub');
  };

  const handleUsdtChange = (v: string) => {
    setAmountUsdt(v);
    setLastChanged('usdt');
    recompute(amountRub, rate, v, 'usdt');
  };

  const handleRateChange = (v: string) => {
    setRate(v);
    if (lastChanged === 'rub') recompute(amountRub, v, amountUsdt, 'rub');
    else if (lastChanged === 'usdt') recompute(amountRub, v, amountUsdt, 'usdt');
  };

  const saveFakeCheck = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append('rate', rate);
      form.append('operation_date', operationDate);
      if (amountRub) form.append('amount_rub', amountRub);
      if (amountUsdt) form.append('amount_usdt', amountUsdt);
      if (comment) form.append('comment', comment);
      if (file) form.append('file', file);
      return isEdit && fakeCheck
        ? api.updateFakeCheck(fakeCheck.id, form)
        : api.addFakeCheck(requisiteId, form);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['requisite', requisiteId] });
      qc.invalidateQueries({ queryKey: ['fake-check-history', requisiteId] });
      qc.invalidateQueries({ queryKey: ['admin-dashboard-stats'] });
      qc.invalidateQueries({ queryKey: ['admin-overview'] });
      qc.invalidateQueries({ queryKey: ['admin-analytics'] });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!amountRub && !amountUsdt) {
      setError('Укажите сумму в рублях или в USDT');
      return;
    }
    if (!rate || parseFloat(rate) <= 0) {
      setError('Укажите корректный курс');
      return;
    }
    setError('');
    saveFakeCheck.mutate();
  };

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Редактировать фейк-чек' : 'Добавить фейк-чек'}>
      <form className="space-y-4" onSubmit={handleSubmit}>
        {error && (
          <p className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-muted mb-1">Сумма (₽)</label>
            <input
              className="input"
              type="number"
              step="0.01"
              min="0.01"
              value={amountRub}
              onChange={(e) => handleRubChange(e.target.value)}
              placeholder="5000.00"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Курс</label>
            <input
              className="input"
              type="number"
              step="0.0001"
              min="0.0001"
              value={rate}
              onChange={(e) => handleRateChange(e.target.value)}
              placeholder="73.5"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Сумма (USDT)</label>
            <input
              className="input"
              type="number"
              step="0.01"
              min="0.01"
              value={amountUsdt}
              onChange={(e) => handleUsdtChange(e.target.value)}
              placeholder="68.03"
            />
          </div>
        </div>
        <p className="text-xs text-muted -mt-2">
          Заполните сумму в ₽ или USDT — второе поле рассчитается автоматически
        </p>
        <div>
          <label className="block text-xs text-muted mb-1">Дата операции</label>
          <input
            className="input"
            type="date"
            value={operationDate}
            onChange={(e) => setOperationDate(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Комментарий</label>
          <textarea
            className="input"
            rows={2}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Причина фейк-чека..."
          />
        </div>
        <FileUploadField
          file={file}
          onChange={setFile}
          label={isEdit ? 'Новый файл (необязательно)' : 'Прикрепить файл чека (необязательно)'}
        />
        <button
          type="submit"
          className="btn-primary w-full"
          disabled={saveFakeCheck.isPending}
        >
          {saveFakeCheck.isPending ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Добавить фейк-чек'}
        </button>
      </form>
    </Modal>
  );
}
