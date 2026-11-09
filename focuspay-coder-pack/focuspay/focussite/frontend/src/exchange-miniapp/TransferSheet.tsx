import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { rub } from "./format";
import { PREVIEW } from "./preview";
import { quoteTransfer, sendTransfer, type TransferReceipt } from "./transfer";
import { Field, GhostButton, PrimaryButton, TextInput } from "./ui";

export function TransferSheet({
  available,
  onClose,
  onDone,
}: {
  available: number;
  onClose: () => void;
  onDone: (receipt: TransferReceipt) => void;
}) {
  const [recipient, setRecipient] = useState("");
  const [amount, setAmount] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const parsed = Number(String(amount).replace(",", "."));
  const quote = quoteTransfer(parsed);

  async function send() {
    if (!quote) return toast.error("Минимум 100 ₽");
    if (recipient.trim().length < 2) return toast.error("Укажите @username или Telegram ID");
    if (parsed > available + 0.001) return toast.error("Недостаточно средств");
    if (!confirming) {
      setConfirming(true);
      return;
    }
    if (PREVIEW) {
      onDone({
        id: 1,
        recipient_label: recipient.trim().startsWith("@") ? recipient.trim() : `@${recipient.trim()}`,
        amount_rub: parsed,
        fee_rub: quote.fee,
        net_rub: quote.net,
      });
      return;
    }
    setBusy(true);
    try {
      const receipt = await sendTransfer(recipient.trim(), parsed);
      onDone(receipt);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось отправить");
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ex-sheet" role="dialog" aria-modal="true" aria-label="Перевод">
      <div className="ex-sheet-card">
        <p className="text-lg font-semibold">{confirming ? "Подтвердите перевод" : "Отправить"}</p>
        <p className="mt-1 text-sm text-muted-foreground">Доступно {rub(available)} ₽. Комиссия 10%, минимум 100 ₽.</p>
        {confirming && quote ? (
          <div className="mt-4 flex flex-col gap-2 text-sm">
            <Row label="Кому" value={recipient.trim()} />
            <Row label="Спишется" value={`${rub(parsed)} ₽`} />
            <Row label="Комиссия" value={`${rub(quote.fee)} ₽`} />
            <Row label="Дойдёт" value={`${rub(quote.net)} ₽`} />
          </div>
        ) : (
          <div className="mt-4 flex flex-col gap-3">
            <Field label="Кому">
              <TextInput value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder="@username или ID" className="text-sm" />
            </Field>
            <Field label="Сумма, ₽">
              <TextInput inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="100" />
            </Field>
            {quote ? <p className="text-xs text-muted-foreground">Получатель получит {rub(quote.net)} ₽, комиссия {rub(quote.fee)} ₽.</p> : null}
          </div>
        )}
        <div className="mt-4 flex flex-col gap-2">
          <PrimaryButton disabled={busy} onClick={() => void send()}>{confirming ? "Отправить" : "Дальше"}</PrimaryButton>
          <GhostButton onClick={confirming ? () => setConfirming(false) : onClose}>{confirming ? "Назад" : "Закрыть"}</GhostButton>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="ex-mono">{value}</span>
    </div>
  );
}
