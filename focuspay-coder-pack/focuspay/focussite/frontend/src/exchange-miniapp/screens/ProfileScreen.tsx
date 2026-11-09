import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { parseCryptoSymbol } from "@/lib/orders";
import {
  getBalance,
  getDiscounts,
  getMyOrders,
  promoRedeemedText,
  redeemPromo,
  setCashbackOnNext,
  type BalanceStats,
  type HistoryOrder,
} from "@/lib/user";
import { formatDate } from "@/lib/utils";
import { TransferSheet } from "../TransferSheet";
import type { TransferReceipt } from "../transfer";
import { WithdrawForm } from "../WithdrawForm";
import { orderStatusText, rub } from "../format";
import { PREVIEW } from "../preview";
import { Card, Field, PageTitle, TextInput } from "../ui";

const PREVIEW_BALANCE: BalanceStats = {
  balance_rub: 1240.5,
  available_rub: 980,
  cashback_rub: 160.5,
  promo_rub: 0,
  referral_rub: 100,
  total_accrued_rub: 1240.5,
  saved_rub: 80,
  use_on_next: true,
  has_pending_withdrawal: false,
  min_withdraw_card_rub: 20000,
  ref_token: "preview",
  telegram_link: "",
  web_invite_link: "",
  referred_count: 12,
  paid_orders_count: 7,
  referral_total_accrual_rub: 3400,
};

const PREVIEW_ORDERS: HistoryOrder[] = [
  { id: 1, order_id: "FP-1801", status: "PAID", direction: "buy", crypto: "USDT_TRC20", crypto_amount: 100, fiat_amount: 9200, rate: 92, requisites: "", created_at: "2026-10-07T12:00:00Z", expires_at: null, required_receipt_type: null, deposit_wallet: null, payment: null },
  { id: 2, order_id: "FP-1760", status: "CANCELED", direction: "sell", crypto: "BTC", crypto_amount: 0.01, fiat_amount: 58000, rate: 5800000, requisites: "", created_at: "2026-10-05T09:00:00Z", expires_at: null, required_receipt_type: null, deposit_wallet: null, payment: null },
  { id: 3, order_id: "FP-1702", status: "PAID", direction: "buy", crypto: "LTC", crypto_amount: 2, fiat_amount: 15000, rate: 7500, requisites: "", created_at: "2026-10-01T18:00:00Z", expires_at: null, required_receipt_type: null, deposit_wallet: null, payment: null },
];

const PREVIEW_DISCOUNTS = [
  { id: 1, promo_code: "FOCUS100", amount_rub: 100, min_order_rub: 5000 },
  { id: 2, promo_code: "WEEK", amount_rub: 250, min_order_rub: 10000 },
];

export function ProfileScreen() {
  const [balance, setBalance] = useState<BalanceStats | null>(PREVIEW ? PREVIEW_BALANCE : null);
  const [orders, setOrders] = useState<HistoryOrder[]>(PREVIEW ? PREVIEW_ORDERS : []);
  const [discounts, setDiscounts] = useState<{ promo_code?: string; amount_rub: number; min_order_rub?: number }[]>(PREVIEW ? PREVIEW_DISCOUNTS : []);
  const [promo, setPromo] = useState("");
  const [loading, setLoading] = useState(!PREVIEW);
  const [panel, setPanel] = useState<"send" | "withdraw" | "promo" | null>(null);
  const [receipt, setReceipt] = useState<TransferReceipt | null>(null);

  async function reload() {
    const [nextBalance, nextOrders, nextDiscounts] = await Promise.all([
      getBalance(),
      getMyOrders(10, 0),
      getDiscounts().catch(() => ({ active: [] })),
    ]);
    setBalance(nextBalance);
    setOrders(nextOrders.orders || []);
    const active = (nextDiscounts as { active?: typeof discounts }).active;
    setDiscounts(Array.isArray(active) ? active : []);
  }

  useEffect(() => {
    if (PREVIEW) return;
    reload().catch(() => undefined).finally(() => setLoading(false));
  }, []);

  async function toggleCashback() {
    if (!balance) return;
    const next = !balance.use_on_next;
    setBalance({ ...balance, use_on_next: next });
    if (PREVIEW) return;
    try {
      await setCashbackOnNext(next);
    } catch (error) {
      setBalance({ ...balance, use_on_next: !next });
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить");
    }
  }

  async function applyPromo() {
    if (!promo.trim()) return;
    if (PREVIEW) {
      toast.success("Промокод применён");
      setPromo("");
      return;
    }
    try {
      const res = await redeemPromo(promo.trim());
      toast.success(promoRedeemedText(res));
      setPromo("");
      await reload();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось применить");
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Загружаем профиль…</p>;

  return (
    <div className="flex flex-col gap-4">
      <section className="ex-hero">
        <p className="ex-kicker">Доступно</p>
        <p className="ex-hero-rate"><span className="ex-mono">{rub(balance?.available_rub)}</span> <small>₽</small></p>
        <p className="mt-2 text-xs text-muted-foreground">
          Баланс {rub(balance?.balance_rub)} · кэшбэк {rub(balance?.cashback_rub)} · реферальные {rub(balance?.referral_rub)}
        </p>
      </section>
      <div className="grid grid-cols-3 gap-2">
        <button type="button" className="ex-chip w-full" onClick={() => setPanel("send")}>Отправить</button>
        <button type="button" className="ex-chip w-full" onClick={() => setPanel(panel === "withdraw" ? null : "withdraw")}>Вывести</button>
        <button type="button" className="ex-chip w-full" onClick={() => setPanel(panel === "promo" ? null : "promo")}>Промокод</button>
      </div>
      {receipt ? (
        <Card>
          <p className="text-sm font-semibold">Перевод отправлен</p>
          <p className="mt-2 text-sm text-muted-foreground">
            {receipt.recipient_label} получит {rub(receipt.net_rub)} ₽. Списано {rub(receipt.amount_rub)} ₽, комиссия {rub(receipt.fee_rub)} ₽.
          </p>
        </Card>
      ) : null}
      <button type="button" onClick={() => void toggleCashback()} className="flex items-center justify-between gap-3 rounded-2xl border border-border bg-card px-4 py-3 text-left">
        <span>
          <span className="block text-sm font-semibold">Списать при следующем обмене</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">Кэшбэк и бонусы уменьшат сумму к оплате</span>
        </span>
        <span className={`relative h-7 w-12 shrink-0 rounded-full ${balance?.use_on_next ? "bg-foreground" : "bg-muted"}`}>
          <span className={`absolute top-0.5 size-6 rounded-full bg-background ${balance?.use_on_next ? "left-5" : "left-0.5"}`} />
        </span>
      </button>
      {panel === "promo" ? (
        <Card>
          <Field label="Промокод">
            <div className="flex gap-2">
              <TextInput value={promo} onChange={(event) => setPromo(event.target.value.toUpperCase())} placeholder="КОД" className="uppercase" />
              <button type="button" onClick={() => void applyPromo()} className="h-12 shrink-0 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground">
                Применить
              </button>
            </div>
          </Field>
        </Card>
      ) : null}
      {panel === "withdraw" ? (
        <Card>
          <p className="mb-3 text-sm font-semibold">Вывод</p>
          <WithdrawForm kind="balance" pending={balance?.has_pending_withdrawal} onDone={() => void reload()} />
        </Card>
      ) : null}
      <Card>
        <p className="text-sm font-semibold">Скидки</p>
        {discounts.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">Активных скидок нет</p> : (
          <ul className="mt-3 flex flex-col gap-2">
            {discounts.map((item, index) => (
              <li key={`${item.promo_code}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                <span>{item.promo_code || "Скидка"}</span>
                <span className="ex-mono">{rub(item.amount_rub, 0)} ₽{item.min_order_rub ? ` от ${rub(item.min_order_rub, 0)}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <p className="text-sm font-semibold">История</p>
        {orders.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">Заявок пока нет</p> : (
          <ul className="mt-3 divide-y divide-border">
            {orders.slice(0, 8).map((order) => {
              const crypto = parseCryptoSymbol(order.crypto);
              return (
                <li key={order.order_id} className="flex items-center justify-between gap-3 py-3">
                  <span className="min-w-0">
                    <span className="block text-sm">{order.direction === "buy" ? "Покупка" : "Продажа"} {crypto.base}</span>
                    <span className="block text-xs text-muted-foreground">{formatDate(order.created_at)}</span>
                  </span>
                  <span className="text-right">
                    <span className="ex-mono block text-sm">{rub(order.fiat_amount, 0)} ₽</span>
                    <span className="block text-xs text-muted-foreground">{orderStatusText(order.status, order.status_label)}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <Link to="/wallet/referral" className="flex h-12 items-center justify-center rounded-xl border border-border text-sm font-semibold">
        Реферальная программа
      </Link>
      {panel === "send" ? (
        <TransferSheet
          available={Number(balance?.available_rub ?? 0)}
          onClose={() => setPanel(null)}
          onDone={(next) => {
            setReceipt(next);
            setPanel(null);
            if (balance) setBalance({ ...balance, available_rub: Math.max(0, Number(balance.available_rub) - next.amount_rub) });
            if (!PREVIEW) void reload();
          }}
        />
      ) : null}
    </div>
  );
}
