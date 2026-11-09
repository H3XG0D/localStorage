import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { CARD_WITHDRAW_PROMISE } from "@/lib/cardWithdrawCopy";
import { referralWithdraw, withdraw, type WithdrawMethod } from "@/lib/user";
import { PREVIEW } from "./preview";
import { Choice, Field, PrimaryButton, TextInput } from "./ui";

const CRYPTOS = ["usdt", "btc", "ltc", "trx"];

export function WithdrawForm({
  kind,
  pending,
  onDone,
}: {
  kind: "balance" | "referral";
  pending?: boolean;
  onDone?: () => void;
}) {
  const [method, setMethod] = useState<WithdrawMethod>("card");
  const [amount, setAmount] = useState("");
  const [requisites, setRequisites] = useState("");
  const [crypto, setCrypto] = useState("usdt");
  const [busy, setBusy] = useState(false);

  if (pending) {
    return (
      <p className="rounded-xl border border-border bg-muted px-3 py-3 text-sm">
        Заявка на вывод уже создана. Новую можно отправить после её обработки.
      </p>
    );
  }

  async function send() {
    if (Number(amount) <= 0) return toast.error("Укажите сумму");
    if (requisites.trim().length < 5) return toast.error("Укажите реквизиты");
    if (PREVIEW) {
      toast.success("Заявка на вывод создана");
      setAmount("");
      setRequisites("");
      return;
    }
    setBusy(true);
    try {
      const body = {
        amount_rub: Number(amount),
        method,
        requisites: requisites.trim(),
        crypto: method === "crypto" ? crypto : null,
        network: method === "crypto" && crypto === "usdt" ? "TRC20" : null,
      };
      if (kind === "referral") await referralWithdraw(body);
      else await withdraw(body);
      toast.success("Заявка на вывод создана");
      setAmount("");
      setRequisites("");
      onDone?.();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось создать вывод");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        <Choice active={method === "card"} title="Карта" onClick={() => setMethod("card")} />
        <Choice active={method === "crypto"} title="Крипта" onClick={() => setMethod("crypto")} />
      </div>
      {method === "crypto" ? (
        <div className="grid grid-cols-4 gap-2">
          {CRYPTOS.map((id) => (
            <Choice key={id} active={crypto === id} title={id.toUpperCase()} onClick={() => setCrypto(id)} />
          ))}
        </div>
      ) : null}
      <Field label="Сумма, ₽">
        <TextInput inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0" />
      </Field>
      {method === "card" ? (
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>{CARD_WITHDRAW_PROMISE}</p>
          <p>На карту может прийти меньше на 10% — недостающее зачислим на баланс. Если больше, разницу доплатит FocusPay.</p>
        </div>
      ) : null}
      <Field label={method === "card" ? "Карта" : "Адрес"}>
        <TextInput value={requisites} onChange={(event) => setRequisites(event.target.value)} placeholder="Реквизиты" className="text-sm" />
      </Field>
      <PrimaryButton disabled={busy} onClick={() => void send()}>Вывести</PrimaryButton>
    </div>
  );
}
