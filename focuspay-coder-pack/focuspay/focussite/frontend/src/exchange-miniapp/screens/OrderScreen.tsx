import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { normalizeBillFields } from "@/lib/exchangerDeal";
import {
  cancelOrder,
  confirmPaid,
  getActiveOrder,
  getPayoutTrack,
  parseCryptoSymbol,
  pushPayout,
  uploadReceipt,
  type Order,
  type PayoutPushOption,
  type PayoutTrack,
} from "@/lib/orders";
import { coin, orderStatusText, rub } from "../format";
import { PREVIEW, PREVIEW_ORDER_EMPTY } from "../preview";
import { openExternal } from "../telegram";
import { WalletConfirmCard } from "@/components/WalletConfirmNotice";
import { Card, GhostButton, PageTitle, PrimaryButton } from "../ui";

const PREVIEW_ORDER: Order = {
  order_id: "FP-1842",
  status: "CREATED",
  direction: "buy",
  crypto: "USDT_TRC20",
  crypto_amount: 541.1256,
  fiat_amount: 50000,
  rate: 92.4,
  requisites: "TXYZ9focuspaywalletpreview",
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 14 * 60 * 1000 + 32 * 1000).toISOString(),
  required_receipt_type: 1,
  deposit_wallet: null,
  payment: {
    type: "buy",
    fiat_amount: 50000,
    bill: { bank: "Сбербанк", phone: "+7 900 000-00-00", fio: "Иван И." },
  },
};

function countdown(expiresAt: string | null | undefined, now: number) {
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - now;
  if (diff <= 0) return "00:00";
  const total = Math.floor(diff / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

const PREVIEW_TRACK: PayoutTrack = {
  visible: true,
  order_id: "FP-1808",
  coin: "btc",
  crypto: "BTC",
  crypto_amount: 0.012,
  txid: "aa".repeat(32),
  explorer_url: `https://mempool.space/tx/${"aa".repeat(32)}`,
  confirmations: 0,
  confirmed: false,
  confirmations_label: "0 подтверждений",
  eta_label: "около 20–30 минут",
  can_push: true,
  push_price_rub: 62,
  push_options: [
    { eta_label: "около 10 минут", price_rub: 62, fee_rate_sat_vb: 8 },
    { eta_label: "около 20–30 минут", price_rub: 28, fee_rate_sat_vb: 2 },
    { eta_label: "около часа", price_rub: 12, fee_rate_sat_vb: 1.05 },
  ],
  push_pending: false,
  available_rub: 980,
  shortfall_rub: 0,
};

let payoutAckGeneration = 0;

function ackKey(orderId: string) {
  return `fp-payout-ack:${orderId}`;
}

function wasAcked(orderId: string) {
  try {
    return window.sessionStorage.getItem(ackKey(orderId)) === "1";
  } catch {
    return false;
  }
}

// services/buyer_access_guards.py: UNPAID_COOLDOWN_MINUTES
const CANCEL_COOLDOWN_MINUTES = 30;

function operatorChatUrl(message: string) {
  const handle = message.match(/@([A-Za-z0-9_]+)/)?.[1] || "focus_operator";
  return `https://t.me/${handle}`;
}

function rubPay(value: number) {
  const rounded = Math.round(value * 100) / 100;
  const whole = Math.abs(rounded - Math.round(rounded)) < 0.001;
  return rub(rounded, whole ? 0 : 2);
}

function pushDetail(error: unknown): { code?: string; message?: string } {
  if (!(error instanceof ApiError) || !error.payload || typeof error.payload !== "object") return {};
  const detail = (error.payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return {};
  const row = detail as { code?: unknown; message?: unknown };
  return {
    code: typeof row.code === "string" ? row.code : undefined,
    message: typeof row.message === "string" ? row.message : undefined,
  };
}

function optionTitle(label: string) {
  const text = label.trim();
  if (!text) return "Ускорить";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function PayoutCard({
  track,
  onTrack,
}: {
  track: PayoutTrack;
  onTrack: (next: PayoutTrack) => void;
}) {
  const [picked, setPicked] = useState<PayoutPushOption | null>(null);
  const [busy, setBusy] = useState(false);
  const options = (track.push_options ?? []).filter((item) => Number(item.price_rub) > 0 && item.eta_label);
  const price = Number(picked?.price_rub ?? (options.length ? 0 : track.push_price_rub ?? 0));
  const available = Number(track.available_rub ?? 0);
  const shortfall = options.length
    ? 0
    : Number(track.shortfall_rub ?? 0);
  const amount = track.crypto_amount != null ? `${coin(track.crypto_amount)} ${parseCryptoSymbol(track.crypto || "").base}` : "";

  async function pay(option?: PayoutPushOption | null) {
    const chosen = option ?? picked;
    const charge = Number(chosen?.price_rub ?? price);
    if (!track.order_id || !charge) return;
    if (PREVIEW) {
      toast.success(`Списали ${rubPay(charge)} ₽`);
      onTrack({
        ...track,
        confirmed: true,
        confirmations: 1,
        confirmations_label: "В сети · 1 подтверждение",
        eta_label: null,
        can_push: false,
        push_options: [],
        push_pending: false,
        shortfall_rub: 0,
      });
      setPicked(null);
      return;
    }
    setBusy(true);
    try {
      const result = await pushPayout(track.order_id, charge, chosen?.fee_rate_sat_vb);
      toast.success(`Списали ${rubPay(result.charged_rub)} ₽`);
      if (result.track) onTrack(result.track);
      setPicked(null);
    } catch (error) {
      const detail = pushDetail(error);
      if (detail.code === "price_changed") {
        toast.error("Цена изменилась");
        const next = await getPayoutTrack().catch(() => null);
        if (next) onTrack(next);
        setPicked(null);
        return;
      }
      toast.error(detail.message || (error instanceof ApiError ? error.message : "Не удалось ускорить"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <p className="text-base font-semibold">Выплачено</p>
      <p className="ex-mono mt-1 text-xs text-muted-foreground">{track.order_id}</p>
      {amount ? <p className="ex-mono mt-3 text-sm">{amount}</p> : null}
      <p className="mt-3 text-sm font-semibold">{track.confirmations_label}</p>
      {track.eta_label ? <p className="mt-1 text-sm text-muted-foreground">{track.eta_label}</p> : null}
      {track.explorer_url ? (
        <a
          href={track.explorer_url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 flex h-11 items-center justify-center rounded-xl border border-border text-sm font-semibold"
        >
          Открыть транзакцию
        </a>
      ) : null}
      {track.push_pending ? (
        <p className="mt-3 text-sm text-muted-foreground">{track.push_pending_label || "Ускоряем транзакцию…"}</p>
      ) : null}
      {track.can_push && options.length > 0 ? (
        picked ? (
          <div className="mt-3 flex flex-col gap-2">
            <p className="text-sm">
              {optionTitle(picked.eta_label)} — спишем {rubPay(picked.price_rub)} ₽ с баланса
            </p>
            <PrimaryButton disabled={busy} onClick={() => void pay(picked)}>Оплатить</PrimaryButton>
            <GhostButton onClick={() => setPicked(null)}>Назад</GhostButton>
          </div>
        ) : (
          <div className="mt-3 flex flex-col gap-2">
            {options.map((option) => {
              const gap = Math.max(0, Math.round((Number(option.price_rub) - available) * 100) / 100);
              return (
                <div key={`${option.eta_label}-${option.fee_rate_sat_vb}`} className="flex flex-col gap-1">
                  <PrimaryButton disabled={busy || gap > 0} onClick={() => setPicked(option)}>
                    {optionTitle(option.eta_label)} — {rubPay(option.price_rub)} ₽
                  </PrimaryButton>
                  {gap > 0 ? (
                    <p className="text-center text-xs text-muted-foreground">На балансе не хватает {rubPay(gap)} ₽</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        )
      ) : track.can_push && price > 0 ? (
        shortfall > 0 ? (
          <div className="mt-3 flex flex-col gap-2">
            <PrimaryButton disabled>Ускорить за {rubPay(price)} ₽</PrimaryButton>
            <p className="text-center text-xs text-muted-foreground">На балансе не хватает {rubPay(shortfall)} ₽</p>
          </div>
        ) : picked ? (
          <div className="mt-3 flex flex-col gap-2">
            <p className="text-sm">Спишем {rubPay(price)} ₽ с баланса</p>
            <PrimaryButton disabled={busy} onClick={() => void pay()}>Оплатить</PrimaryButton>
            <GhostButton onClick={() => setPicked(null)}>Назад</GhostButton>
          </div>
        ) : (
          <div className="mt-3">
            <PrimaryButton
              disabled={busy}
              onClick={() => setPicked({ eta_label: "Ускорить", price_rub: price, fee_rate_sat_vb: 0 })}
            >
              Ускорить за {rubPay(price)} ₽
            </PrimaryButton>
          </div>
        )
      ) : null}
    </Card>
  );
}

function CopyLine({ label, value }: { label: string; value: string }) {
  return (
    <button
      type="button"
      className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-background px-3 py-3 text-left"
      onClick={() => navigator.clipboard?.writeText(value).then(() => toast.success("Скопировано"), () => toast.error("Не удалось скопировать"))}
    >
      <span className="min-w-0">
        <span className="block text-[11px] text-muted-foreground">{label}</span>
        <span className="ex-mono mt-0.5 block truncate text-sm">{value}</span>
      </span>
      <span className="shrink-0 text-xs font-semibold">Копировать</span>
    </button>
  );
}

export function OrderScreen() {
  const [order, setOrder] = useState<Order | null>(PREVIEW && !PREVIEW_ORDER_EMPTY ? PREVIEW_ORDER : null);
  const [track, setTrack] = useState<PayoutTrack | null>(PREVIEW ? PREVIEW_TRACK : null);
  const [loading, setLoading] = useState(!PREVIEW);
  const [busy, setBusy] = useState(false);
  const [cancelAsk, setCancelAsk] = useState(false);
  const [clock, setClock] = useState(() => Date.now());
  const timer = countdown(order?.expires_at, clock);
  const showTrack = Boolean(
    track?.visible &&
      track.order_id &&
      !(track.confirmed && wasAcked(track.order_id)),
  );

  useEffect(() => {
    const id = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!track?.confirmed || !track.order_id) return;
    const orderId = track.order_id;
    const generation = ++payoutAckGeneration;
    return () => {
      window.setTimeout(() => {
        if (payoutAckGeneration !== generation) return;
        try {
          window.sessionStorage.setItem(ackKey(orderId), "1");
        } catch {
          /* ignore */
        }
      }, 50);
    };
  }, [track?.confirmed, track?.order_id]);

  useEffect(() => {
    if (PREVIEW) return;
    let alive = true;
    const load = () => getActiveOrder()
      .then((page) => alive && setOrder(page.active && page.order ? page.order : null))
      .catch(() => undefined)
      .finally(() => alive && setLoading(false));
    load();
    const id = window.setInterval(load, 8000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (PREVIEW) return;
    let alive = true;
    const load = () => getPayoutTrack()
      .then((next) => alive && setTrack(next))
      .catch(() => undefined);
    load();
    const id = window.setInterval(load, 20000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  async function act(kind: "paid" | "cancel" | "receipt", file?: File) {
    if (!order) return;
    if (PREVIEW) {
      toast.success(kind === "cancel" ? "Заявка отменена" : kind === "receipt" ? "Чек отправлен" : "Отметили оплату");
      return;
    }
    setBusy(true);
    try {
      if (kind === "paid") await confirmPaid(order.order_id);
      else if (kind === "cancel") await cancelOrder(order.order_id);
      else if (file) await uploadReceipt(order.order_id, file);
      toast.success(kind === "cancel" ? "Заявка отменена" : "Отправлено");
      const page = await getActiveOrder();
      setOrder(page.active && page.order ? page.order : null);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось выполнить действие");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Загружаем заявку…</p>;

  if (!order) {
    return (
      <div className="flex flex-col gap-3">
        <PageTitle title="Заявка" />
        {showTrack && track ? <PayoutCard track={track} onTrack={setTrack} /> : null}
        {!showTrack ? (
          <Card>
            <p className="text-base font-semibold">Активной заявки нет</p>
            <p className="mt-1 text-sm text-muted-foreground">Создайте обмен — статус и реквизиты появятся здесь.</p>
            <Link to="/" className="mt-4 flex h-12 items-center justify-center rounded-xl bg-primary text-sm font-semibold text-primary-foreground">
              Перейти к обмену
            </Link>
          </Card>
        ) : (
          <Link to="/" className="flex h-11 items-center justify-center rounded-xl border border-border text-sm font-semibold">
            Новый обмен
          </Link>
        )}
      </div>
    );
  }

  const crypto = parseCryptoSymbol(order.crypto);
  const bill = order.payment?.type === "buy" ? normalizeBillFields(order.payment.bill, order.sub_token) : [];
  const wallet = order.deposit_wallet || (order.payment?.type === "deposit" ? order.payment.deposit_wallet : "");
  const needsVideo = order.direction === "buy"
    && order.status === "AWAITING_CHECK"
    && Number(order.required_receipt_type) === 3;
  const buyReceiptIn = !needsVideo && order.direction === "buy" && (
    Boolean(order.receipt_submitted)
    || order.status === "PENDING"
    || order.status === "PAID"
    || order.status === "COMPLETED"
  );
  const statusText = buyReceiptIn && order.status === "AWAITING_CHECK"
    ? "На проверке"
    : orderStatusText(order.status, order.status_label);
  const operatorPayment = order.payment?.type === "operator" ? order.payment : null;
  const operatorMessage = operatorPayment
    ? operatorPayment.message || order.operator_message || "Реквизитов сейчас нет. Напишите оператору — попробуем что-нибудь придумать."
    : "";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">Заявка</p>
          <h1 className="ex-mono text-[22px] font-medium tracking-tight">{order.order_id}</h1>
        </div>
        <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold">{statusText}</span>
      </div>
      {order.wallet_confirm ? (
        <WalletConfirmCard
          orderId={order.order_id}
          confirm={order.wallet_confirm}
          cryptoAmount={order.crypto_amount}
          fiatAmount={order.fiat_amount}
          onResolved={() => {
            getActiveOrder()
              .then((page) => setOrder(page.active && page.order ? page.order : null))
              .catch(() => undefined);
          }}
        />
      ) : null}
      <Card className="ex-hero">
        <p className="ex-kicker">{order.direction === "buy" ? "К оплате" : "Вы получите"}</p>
        <p className="ex-hero-rate"><span className="ex-mono">{rub(order.fiat_amount, 0)}</span> <small>₽</small></p>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div>
            <p className="text-[11px] text-muted-foreground">Монета</p>
            <p className="ex-mono mt-1 text-sm">{coin(order.crypto_amount)} {crypto.base}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Курс</p>
            <p className="ex-mono mt-1 text-sm">1 {crypto.base} ≈ {rub(order.rate, order.rate >= 1000 ? 0 : 2)} ₽</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Таймер</p>
            <p className="ex-mono mt-1 text-lg">{timer || "—"}</p>
          </div>
        </div>
      </Card>
      {operatorPayment ? (
        <Card>
          <p className="text-sm leading-6">{operatorMessage}</p>
          <div className="mt-4">
            <PrimaryButton onClick={() => openExternal(operatorChatUrl(operatorMessage))}>Написать оператору</PrimaryButton>
          </div>
        </Card>
      ) : null}
      <div className="flex flex-col gap-2">
        {bill.map((field) => <CopyLine key={`${field.label}:${field.value}`} label={field.label} value={field.value} />)}
        {wallet ? <CopyLine label={order.direction === "sell" ? "Адрес для крипты" : "Реквизиты для оплаты"} value={wallet} /> : null}
        {order.requisites ? <CopyLine label={order.direction === "buy" ? "Ваш кошелёк" : "Куда отправить рубли"} value={order.requisites} /> : null}
      </div>
      {operatorPayment ? null : buyReceiptIn ? (
        <Card>
          <p className="text-base font-semibold">Чек принят, ожидайте проверки</p>
          <p className="mt-1 text-sm text-muted-foreground">Мы сообщим, когда оплата будет подтверждена.</p>
        </Card>
      ) : (
        <>
          {needsVideo ? null : (
            <PrimaryButton disabled={busy} onClick={() => void act("paid")}>Я оплатил</PrimaryButton>
          )}
          <label className="flex h-11 cursor-pointer items-center justify-center rounded-xl border border-border text-sm font-semibold">
            {needsVideo ? "Загрузить видео" : "Загрузить чек"}
            <input
              type="file"
              accept={needsVideo ? "video/*" : "image/*,application/pdf,video/*"}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void act("receipt", file);
              }}
            />
          </label>
        </>
      )}
      <GhostButton onClick={() => setCancelAsk(true)}>Отменить заявку</GhostButton>
      {cancelAsk ? (
        <CancelConfirmSheet
          busy={busy}
          onClose={() => setCancelAsk(false)}
          onConfirm={() => {
            setCancelAsk(false);
            void act("cancel");
          }}
        />
      ) : null}
      {showTrack && track ? <PayoutCard track={track} onTrack={setTrack} /> : null}
    </div>
  );
}

function CancelConfirmSheet({
  busy,
  onClose,
  onConfirm,
}: {
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="ex-sheet" role="dialog" aria-modal="true" aria-label="Отмена заявки">
      <div className="ex-sheet-card">
        <p className="text-lg font-semibold">Отменить заявку?</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          После отмены вы не сможете запросить реквизиты ещё {CANCEL_COOLDOWN_MINUTES} минут.
        </p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Если возникли трудности с переводом — напишите в поддержку, вам помогут.
        </p>
        <div className="mt-4 flex flex-col gap-2">
          <GhostButton onClick={() => openExternal(operatorChatUrl(""))}>Написать в поддержку</GhostButton>
          <PrimaryButton disabled={busy} onClick={onConfirm}>Всё равно отменить</PrimaryButton>
          <GhostButton onClick={onClose}>Вернуться к оплате</GhostButton>
        </div>
      </div>
    </div>
  );
}
