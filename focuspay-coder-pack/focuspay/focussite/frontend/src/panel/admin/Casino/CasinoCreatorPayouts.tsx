import { useCallback, useEffect, useState } from "react";
import { CheckCircle, XCircle } from "lucide-react";
import { toast } from "sonner";
import {
  approveCasinoCreatorWithdrawal,
  getCasinoCreatorWithdrawals,
  rejectCasinoCreatorWithdrawal,
  type AdminCasinoCreatorWithdrawal,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  Badge,
  Button,
  Card,
  Input,
  Modal,
  PageHeader,
  type BadgeTone,
} from "@/panel/ui/primitives";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

function statusTone(status: string): BadgeTone {
  if (status === "approved") return "green";
  if (status === "pending") return "yellow";
  if (status === "rejected") return "red";
  return "default";
}

function statusLabel(status: string): string {
  if (status === "approved") return "Одобрена";
  if (status === "pending") return "Ожидает";
  if (status === "rejected") return "Отклонена";
  return status || "Неизвестно";
}

function methodLabel(method: string): string {
  if (method === "crypto") return "Криптовалюта";
  if (method === "card") return "Карта";
  if (method === "sbp") return "СБП";
  return method || "—";
}

function formatRub(value: number): string {
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function CasinoCreatorPayouts() {
  const [withdrawals, setWithdrawals] = useState<AdminCasinoCreatorWithdrawal[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedWithdrawal, setSelectedWithdrawal] =
    useState<AdminCasinoCreatorWithdrawal | null>(null);
  const [modalMode, setModalMode] = useState<"approve" | "reject" | null>(null);
  const [txHash, setTxHash] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [processing, setProcessing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadWithdrawals = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setWithdrawals(await getCasinoCreatorWithdrawals());
    } catch (error) {
      setWithdrawals([]);
      setLoadError(getErrorMessage(error, "Не удалось загрузить заявки на выплату"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWithdrawals();
  }, [loadWithdrawals]);

  const openModal = (
    withdrawal: AdminCasinoCreatorWithdrawal,
    mode: "approve" | "reject",
  ) => {
    if (processing) return;
    setSelectedWithdrawal(withdrawal);
    setModalMode(mode);
    setTxHash("");
    setRejectionReason("");
    setActionError(null);
  };

  const closeModal = () => {
    if (processing) return;
    setSelectedWithdrawal(null);
    setModalMode(null);
    setTxHash("");
    setRejectionReason("");
    setActionError(null);
  };

  const approveWithdrawal = async () => {
    if (!selectedWithdrawal || processing) return;
    const normalizedTxHash = txHash.trim();
    if (!normalizedTxHash) {
      setActionError("Укажите хэш транзакции или подтверждение платежа");
      return;
    }

    setProcessing(true);
    setActionError(null);
    try {
      await approveCasinoCreatorWithdrawal(
        selectedWithdrawal.withdrawal_id,
        normalizedTxHash,
      );
      toast.success("Выплата одобрена");
      setSelectedWithdrawal(null);
      setModalMode(null);
      setTxHash("");
      await loadWithdrawals();
    } catch (error) {
      const message = getErrorMessage(error, "Не удалось одобрить выплату");
      setActionError(message);
      toast.error(message);
    } finally {
      setProcessing(false);
    }
  };

  const rejectWithdrawal = async () => {
    if (!selectedWithdrawal || processing) return;
    const normalizedReason = rejectionReason.trim();
    if (!normalizedReason) {
      setActionError("Укажите причину отклонения");
      return;
    }

    setProcessing(true);
    setActionError(null);
    try {
      await rejectCasinoCreatorWithdrawal(
        selectedWithdrawal.withdrawal_id,
        normalizedReason,
      );
      toast.success("Выплата отклонена");
      setSelectedWithdrawal(null);
      setModalMode(null);
      setRejectionReason("");
      await loadWithdrawals();
    } catch (error) {
      const message = getErrorMessage(error, "Не удалось отклонить выплату");
      setActionError(message);
      toast.error(message);
    } finally {
      setProcessing(false);
    }
  };

  const modalOpen = selectedWithdrawal !== null && modalMode !== null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Казино — Выплаты создателю"
        subtitle="Проверка и обработка заявок на вывод"
        actions={
          <Button type="button" size="sm" onClick={() => void loadWithdrawals()} disabled={loading || processing}>
            Обновить
          </Button>
        }
      />

      <Card className="overflow-hidden p-0">
        {loading ? (
          <div className="p-10 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
            Загрузка заявок…
          </div>
        ) : loadError ? (
          <div className="space-y-3 p-6" role="alert">
            <div className="text-[13px] text-[var(--red)]">{loadError}</div>
            <Button type="button" size="sm" onClick={() => void loadWithdrawals()}>
              Повторить
            </Button>
          </div>
        ) : withdrawals.length === 0 ? (
          <div className="p-10 text-center text-[13px] text-[var(--text-muted)]">
            Заявок на выплату пока нет
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">ID</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Дата</th>
                  <th className="px-3 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Сумма</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Метод</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Реквизиты</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Статус</th>
                  <th className="px-3 py-2.5 text-center text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Действия</th>
                </tr>
              </thead>
              <tbody>
                {withdrawals.map((withdrawal) => (
                  <tr
                    key={withdrawal.withdrawal_id}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-elevated)]"
                  >
                    <td className="px-3 py-2.5 font-mono">#{withdrawal.withdrawal_id}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-[var(--text-secondary)]">
                      {formatDate(withdrawal.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono font-semibold tabular-nums">
                      {formatRub(withdrawal.amount_rub)}
                    </td>
                    <td className="px-3 py-2.5 text-[var(--text-secondary)]">
                      {methodLabel(withdrawal.method)}
                    </td>
                    <td
                      className="max-w-xs truncate px-3 py-2.5 font-mono text-[var(--text-secondary)]"
                      title={withdrawal.requisites}
                    >
                      {withdrawal.requisites}
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={statusTone(withdrawal.status)}>
                        {statusLabel(withdrawal.status)}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5">
                      {withdrawal.status === "pending" ? (
                        <div className="flex items-center justify-center gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => openModal(withdrawal, "approve")}
                            disabled={processing}
                            title="Одобрить"
                            aria-label={`Одобрить выплату ${withdrawal.withdrawal_id}`}
                          >
                            <CheckCircle className="h-4 w-4 text-[var(--green)]" aria-hidden />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => openModal(withdrawal, "reject")}
                            disabled={processing}
                            title="Отклонить"
                            aria-label={`Отклонить выплату ${withdrawal.withdrawal_id}`}
                          >
                            <XCircle className="h-4 w-4 text-[var(--red)]" aria-hidden />
                          </Button>
                        </div>
                      ) : withdrawal.status === "approved" && withdrawal.tx_hash ? (
                        <div
                          className="mx-auto max-w-[150px] truncate text-center font-mono text-[11px] text-[var(--text-muted)]"
                          title={withdrawal.tx_hash}
                        >
                          {withdrawal.tx_hash}
                        </div>
                      ) : withdrawal.status === "rejected" && withdrawal.rejection_reason ? (
                        <div
                          className="mx-auto max-w-[150px] truncate text-center text-[11px] text-[var(--red)]"
                          title={withdrawal.rejection_reason}
                        >
                          {withdrawal.rejection_reason}
                        </div>
                      ) : (
                        <div className="text-center text-[var(--text-muted)]">—</div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={modalOpen}
        title={modalMode === "approve" ? "Одобрить выплату" : "Отклонить выплату"}
        onClose={closeModal}
        footer={
          <>
            <Button type="button" onClick={closeModal} disabled={processing}>
              Отмена
            </Button>
            {modalMode === "approve" ? (
              <Button
                type="button"
                variant="primary"
                onClick={() => void approveWithdrawal()}
                disabled={processing || !txHash.trim()}
              >
                {processing ? "Обработка…" : "Одобрить"}
              </Button>
            ) : (
              <Button
                type="button"
                variant="danger"
                onClick={() => void rejectWithdrawal()}
                disabled={processing || !rejectionReason.trim()}
              >
                {processing ? "Обработка…" : "Отклонить"}
              </Button>
            )}
          </>
        }
      >
        {selectedWithdrawal && (
          <div className="space-y-4" aria-busy={processing}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Info label="Сумма" value={formatRub(selectedWithdrawal.amount_rub)} />
              <Info label="Метод" value={methodLabel(selectedWithdrawal.method)} />
            </div>
            <Info label="Реквизиты" value={selectedWithdrawal.requisites} mono />

            {modalMode === "approve" ? (
              <label className="flex flex-col gap-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                  Хэш транзакции или подтверждение
                </span>
                <Input
                  type="text"
                  value={txHash}
                  onChange={(event) => {
                    setTxHash(event.target.value);
                    setActionError(null);
                  }}
                  placeholder="0x…"
                  disabled={processing}
                  className="font-mono"
                />
              </label>
            ) : (
              <label className="flex flex-col gap-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                  Причина отклонения
                </span>
                <textarea
                  value={rejectionReason}
                  onChange={(event) => {
                    setRejectionReason(event.target.value);
                    setActionError(null);
                  }}
                  rows={4}
                  placeholder="Укажите причину…"
                  disabled={processing}
                  className="w-full resize-none rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--text-muted)] disabled:opacity-50"
                />
              </label>
            )}

            {actionError && (
              <div
                className="rounded-[var(--radius)] border border-[var(--red)]/30 bg-[var(--red-bg)] px-3 py-2.5 text-[13px] text-[var(--red)]"
                role="alert"
              >
                {actionError}
              </div>
            )}
            {processing && (
              <div className="text-[12px] text-[var(--text-muted)]">
                Запрос обрабатывается. Закрытие окна и остальные действия временно заблокированы.
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Info({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={`mt-1 break-all text-[13px] ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}
