import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { applyReferral, getReferral, type BalanceStats } from "@/lib/user";
import { WithdrawForm } from "../WithdrawForm";
import { rub } from "../format";
import { PREVIEW } from "../preview";
import { Card, Field, PageTitle, Stat, TextInput } from "../ui";

const PREVIEW_REFERRAL: BalanceStats = {
  balance_rub: 1240.5,
  available_rub: 980,
  cashback_rub: 160.5,
  promo_rub: 0,
  referral_rub: 100,
  total_accrued_rub: 3400,
  saved_rub: 0,
  use_on_next: false,
  has_pending_withdrawal: false,
  min_withdraw_card_rub: 20000,
  ref_token: "focus",
  telegram_link: "https://t.me/focuspay1_bot?start=ref_focus",
  web_invite_link: "https://focuspay.org/ref/focus",
  referred_count: 12,
  paid_orders_count: 7,
  referral_total_accrual_rub: 3400,
};

export function ReferralScreen() {
  const [data, setData] = useState<BalanceStats | null>(PREVIEW ? PREVIEW_REFERRAL : null);
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(!PREVIEW);
  const link = data?.web_invite_link || data?.telegram_link || "";

  useEffect(() => {
    if (PREVIEW) return;
    getReferral().then(setData).catch(() => undefined).finally(() => setLoading(false));
  }, []);

  async function apply() {
    if (!token.trim()) return;
    if (PREVIEW) {
      toast.success("Код друга применён");
      setToken("");
      return;
    }
    try {
      const result = await applyReferral(token.trim());
      toast[result.applied ? "success" : "info"](result.applied ? "Код друга применён" : "Реферер уже назначен");
      setToken("");
      setData(await getReferral());
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось применить");
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Загружаем рефералку…</p>;

  return (
    <div className="flex flex-col gap-4">
      <Link to="/wallet" className="text-sm font-medium text-muted-foreground">Назад в кошелёк</Link>
      <PageTitle title="Рефералка" hint="Бонус начисляется за оплаченные заявки друзей и за их VPN." />
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Приглашено" value={String(data?.referred_count ?? 0)} />
        <Stat label="Оплачено" value={String(data?.paid_orders_count ?? 0)} />
        <Stat label="Начислено" value={`${rub(data?.referral_total_accrual_rub, 0)} ₽`} />
      </div>
      <Card>
        <p className="text-sm font-semibold">Ваша ссылка</p>
        <button
          type="button"
          className="ex-mono mt-3 w-full truncate rounded-xl border border-border bg-background px-3 py-3 text-left text-xs"
          onClick={() => link && navigator.clipboard?.writeText(link).then(() => toast.success("Скопировано"), () => toast.error("Не удалось скопировать"))}
        >
          {link || "Ссылка появится после входа"}
        </button>
        <p className="mt-2 text-xs text-muted-foreground">Нажмите, чтобы скопировать</p>
      </Card>
      <Card>
        <Field label="Код друга">
          <div className="flex gap-2">
            <TextInput value={token} onChange={(event) => setToken(event.target.value)} placeholder="Код" />
            <button type="button" onClick={() => void apply()} className="h-12 shrink-0 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground">
              Применить
            </button>
          </div>
        </Field>
      </Card>
      <Card>
        <p className="mb-3 text-sm font-semibold">Вывод реферальных</p>
        <WithdrawForm kind="referral" pending={data?.has_pending_withdrawal} onDone={() => { if (!PREVIEW) void getReferral().then(setData); }} />
      </Card>
    </div>
  );
}
