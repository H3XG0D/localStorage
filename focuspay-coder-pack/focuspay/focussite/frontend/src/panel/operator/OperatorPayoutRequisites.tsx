import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AlertCircle, ChevronDown, ChevronUp, CircleCheck, Clock3, Copy, Eye, EyeOff, RefreshCw, X } from "lucide-react";
import { PanelApiError } from "@/panel/lib/panelApi";
import { OpsClientLink, opsClientId } from "@/panel/lib/opsClientPath";
import {
  addPayoutDoliv,
  attachPayoutAllocationReceipt,
  cancelPayoutAllocation,
  cancelPayoutRequisite,
  closePayoutRequisite,
  confirmPayinFiatReceived,
  confirmPayoutRequisite,
  createPayoutRequisite,
  createPayoutRequisiteFromSell,
  fetchOperatorOrderReceiptBlob,
  getOrders,
  getPayoutRequisite,
  getPayoutRequisitePlan,
  getUser,
  listPayoutRequisites,
  markPayoutAllocationPaid,
  quotePayoutPayoff,
  rejectPayinReceipt,
  reservePayoutRequisite,
  updatePayoutRequisiteMaxChecks,
  type OrderRow,
  type OrdersBuckets,
  type PayoutAllocation,
  type PayoutCrypto,
  type PayoutPayoffQuote,
  type PayoutPlan,
  type PayoutPlanSplit,
  type PayoutPoolOrder,
  type PayoutRequisite,
} from "@/panel/lib/operatorApi";
import { panelMe } from "@/panel/lib/panelAuth";
import { fillTank } from "@/panel/lib/payoutRequisiteFill";
import { CopyField } from "@/panel/ui/CopyField";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Select, cx } from "@/panel/ui/primitives";

function money(v: unknown) {
  if (v == null || v === "" || !Number.isFinite(Number(v))) return "—";
  return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(v));
}

function pct(v: unknown) {
  const n = Number(v ?? 0);
  return `${n > 0 ? "+" : ""}${n}%`;
}

const STATUS_TONE: Record<string, "green" | "yellow" | "red" | "blue" | "default"> = {
  QUEUED: "yellow",
  OPEN: "blue",
  RESERVED: "yellow",
  PARTIAL: "yellow",
  CLOSED: "green",
  EXPIRED: "red",
  CANCELED: "default",
};

const STATUS_LABEL: Record<string, string> = {
  QUEUED: "Ждёт включения",
  OPEN: "В работе",
  RESERVED: "В работе",
  PARTIAL: "Частично закрыта",
  CLOSED: "Закрыта",
  EXPIRED: "Просрочена",
  CANCELED: "Снята",
};

const ORDER_STATUS_LABEL: Record<string, string> = {
  CREATED: "Создана",
  AWAITING_CHECK: "Ждёт чек",
  PENDING: "На проверке",
  COMPLETED: "Подтверждена",
  PAID: "Выплачена",
  CANCELED: "Отменена",
  EXPIRED: "Истекла",
};

function methodLabel(method: string) {
  return method === "sbp" ? "СБП" : "Карта";
}

function holderShort(name?: string | null) {
  const parts = String(name ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "";
  if (parts.length === 1) return parts[0];
  return parts[1] || parts[0];
}

function cardTitle(r: PayoutRequisite) {
  if (r.label) return r.label;
  const bits = [methodLabel(r.method), r.bank, holderShort(r.holder_name)].filter(Boolean);
  return bits.join(" · ") || r.requisites_masked || "Карта";
}

const CRYPTO_OPTIONS: { value: PayoutCrypto; label: string }[] = [
  { value: "btc", label: "BTC" },
  { value: "usdt", label: "USDT" },
  { value: "ltc", label: "LTC" },
  { value: "trx", label: "TRX" },
];

const AMOUNT_CHIPS = [5000, 7000, 10000];
const MAX_CHECKS_CHIPS = [1, 2, 3, 4, 5];

const COST_PRESETS = [-3, -1, -0.5, 0, 1, 1.5, 3];

function cryptoLabel(code: unknown) {
  return String(code ?? "usdt").toUpperCase();
}

function cryptoDigits(crypto: string) {
  const coin = crypto.toLowerCase();
  if (coin === "btc" || coin === "ltc") return 8;
  if (coin === "trx") return 4;
  return 2;
}

function cryptoAmount(v: unknown, crypto = "usdt") {
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: cryptoDigits(crypto),
    maximumFractionDigits: cryptoDigits(crypto),
  }).format(Number(v ?? 0));
}

function cryptoPlain(v: unknown, crypto = "usdt") {
  return Number(v ?? 0).toFixed(cryptoDigits(crypto));
}

function orderHref(orderId: unknown) {
  const id = String(orderId ?? "").trim();
  if (!id || id.startsWith("typ:")) return null;
  return `/ops/orders?order=${encodeURIComponent(id)}`;
}

const SELL_DONE = new Set(["PAID", "COMPLETED", "CANCELED", "EXPIRED", "FAILED"]);

function pickOpenSellWithoutCrypto(data: OrdersBuckets): { id: string; amount: number } | null {
  const rows: OrderRow[] = [...(data.incoming ?? []), ...(data.orders ?? [])];
  for (const row of rows) {
    if (String(row.direction || "").toLowerCase() !== "sell") continue;
    if (row.crypto_confirmed_at) continue;
    if (SELL_DONE.has(String(row.status || "").toUpperCase())) continue;
    const id = String(row.order_id || "").trim();
    if (!id) continue;
    return { id, amount: Number(row.fiat_amount || 0) };
  }
  return null;
}

function OrderLink({ orderId, children }: { orderId: unknown; children?: ReactNode }) {
  const href = orderHref(orderId);
  const label = children ?? `#${orderId}`;
  if (!href) return <span className="font-mono">{label}</span>;
  return (
    <Link to={href} className="font-mono text-[var(--blue)] underline-offset-4 hover:underline">
      {label}
    </Link>
  );
}

/** Живой пересчёт «рубли + процент → крипта» по курсу CoinGecko. */
function usePayoffQuote(amountRub: number, costPct: number, crypto: PayoutCrypto, direction: "payout" | "payin") {
  const [quote, setQuote] = useState<PayoutPayoffQuote | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(amountRub) || amountRub <= 0 || !Number.isFinite(costPct)) {
      setQuote(null);
      setError(null);
      return;
    }
    let alive = true;
    const timer = window.setTimeout(() => {
      quotePayoutPayoff(amountRub, costPct, crypto, direction)
        .then((q) => {
          if (!alive) return;
          setQuote(q);
          setError(null);
        })
        .catch((e) => {
          if (!alive) return;
          setQuote(null);
          setError(e instanceof PanelApiError ? e.message : "Курс недоступен");
        });
    }, 400);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [amountRub, costPct, crypto, direction]);

  return { quote, error };
}

function useCountdown(deadline?: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  if (!deadline) return null;
  const left = new Date(deadline).getTime() - now;
  if (!Number.isFinite(left)) return null;
  if (left <= 0) return "истекло";
  const total = Math.floor(left / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h} ч ${m} мин` : `${m}:${String(s).padStart(2, "0")}`;
}

function planOrderLabel(order: { order_id?: string; amount_rub?: number; synthetic?: boolean }) {
  const synthetic = Boolean(order.synthetic) || String(order.order_id || "").startsWith("typ:");
  if (synthetic) return `чек ≈ ${money(order.amount_rub)} ₽`;
  return `#${order.order_id}`;
}

function moneyInt(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

function splitLabel(split: PayoutPlanSplit | number[] | undefined) {
  const checks = Array.isArray(split) ? split : Array.isArray(split?.checks) ? split.checks : [];
  const amounts = checks.map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0);
  if (!amounts.length) return "";
  return amounts.map((v) => moneyInt(v)).join(" + ") + " ₽";
}

function closingSplits(plan: PayoutPlan): PayoutPlanSplit[] {
  return Array.isArray(plan.splits) ? plan.splits.filter((s) => splitLabel(s)) : [];
}

function FillBar({ paid, reserved, total }: { paid: number; reserved: number; total: number }) {
  const safeTotal = Number.isFinite(total) && total > 0 ? total : 0;
  const safePaid = Number.isFinite(paid) ? Math.max(0, paid) : 0;
  const safeReserved = Number.isFinite(reserved) ? Math.max(0, reserved) : 0;
  const occupied = safePaid + safeReserved;
  const ratio = safeTotal > 0 ? Math.min(100, (occupied / safeTotal) * 100) : 0;
  const left = Math.max(0, safeTotal - occupied);
  const paidRatio = safeTotal > 0 ? Math.min(100, safePaid / safeTotal * 100) : 0;
  return (
    <div className="flex flex-col gap-2">
      <div><span className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Получено</span><div className="flex flex-wrap items-baseline gap-2"><strong className="text-[28px] font-semibold tabular-nums tracking-tight">{money(safePaid)} ₽</strong><span className="text-[13px] text-[var(--text-muted)]">из {money(safeTotal)} ₽</span></div></div>
      <div className="grid grid-cols-3 overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] text-[12px]">
        <div className="border-r border-[var(--border)] px-3 py-2"><div className="text-[var(--text-muted)]">Получено</div><strong className="tabular-nums text-[var(--green)]">{money(safePaid)} ₽</strong></div>
        <div className="border-r border-[var(--border)] px-3 py-2"><div className="text-[var(--text-muted)]">Ожидается</div><strong className="tabular-nums text-[var(--yellow)]">{money(safeReserved)} ₽</strong></div>
        <div className="px-3 py-2"><div className="text-[var(--text-muted)]">Свободно</div><strong className="tabular-nums">{money(left)} ₽</strong></div>
      </div>
      <div className="flex items-center justify-between text-[12px] text-[var(--text-muted)]"><span>Цель {money(safeTotal)} ₽</span><span className="tabular-nums">{Math.round(ratio)}% занято</span></div>
      <div aria-label={`Получено ${money(safePaid)}, ожидается ${money(safeReserved)}, свободно ${money(left)} рублей`} className="flex h-2 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
        <div
          data-payin-progress="paid" className="h-full bg-[var(--green)] transition-[width] motion-reduce:transition-none"
          style={{ width: `${paidRatio}%` }}
        />
        <div data-payin-progress="reserved" className="h-full bg-[var(--yellow)] transition-[width] motion-reduce:transition-none" style={{ width: `${Math.max(0, ratio - paidRatio)}%` }} />
      </div>
    </div>
  );
}

function weekdayPastLabel(label: string): string {
  const map: Record<string, string> = {
    воскресенье: "воскресеньям",
    понедельник: "понедельникам",
    вторник: "вторникам",
    среда: "средам",
    четверг: "четвергам",
    пятница: "пятницам",
    суббота: "субботам",
  };
  return map[label] || label;
}

function forecastTypicalLine(plan: PayoutPlan, typical: number[], hour: string | null): string | null {
  if (!hour || typical.length === 0) return null;
  const sums = typical.map((v) => money(v)).join(" · ");
  const src = String(plan.source || "");
  if ((src === "weekday_history" || src === "weekday_mixed") && plan.weekday_label) {
    return `По прошлым ${weekdayPastLabel(String(plan.weekday_label))} · ${hour}:00 МСК · чаще ${sums} ₽`;
  }
  return `${hour}:00 МСК · чаще ${sums} ₽`;
}

function PlanView({ plan, isPayin }: { plan?: PayoutPlan | null; isPayin?: boolean }) {
  const forecast = plan?.kind === "forecast";
  if (!plan) {
    return (
      <p className="m-0 text-[13px] text-[var(--text-muted)]">
        {forecast ? "Прогноз ещё не рассчитан." : "План ещё не рассчитан."}
      </p>
    );
  }
  const splits = closingSplits(plan);
  if (forecast && splits.length > 0) {
    const primary = splits[0];
    const checks = Number(primary.checks_count) || (Array.isArray(primary.checks) ? primary.checks.length : 0);
    const primaryEta = String(primary.fill_eta_label || "").trim();
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="green">
            {primaryEta
              ? `Закроет за ${checks} чек(а) · ${primaryEta}`
              : `Закроет за ${checks} чек(а)`}
          </Badge>
        </div>
        <div className="flex flex-col gap-1">
          {splits.map((split, index) => {
            const eta = String(split.fill_eta_label || "").trim();
            const label = splitLabel(split);
            return (
            <div
              key={`${label}-${index}`}
              className="flex items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
            >
              <span className="text-[var(--text-muted)]">{index === 0 ? "Вариант" : "Или"}</span>
              <span className="font-mono tabular-nums text-right">
                {label}
                {eta ? ` · ${eta}` : ""}
              </span>
            </div>
            );
          })}
        </div>
        {typeof plan.now_hint === "string" && plan.now_hint.trim() && (
          <p className="m-0 text-[13px] leading-5 text-[var(--text-muted)]">{plan.now_hint}</p>
        )}
        {(plan.source === "weekday_history" || plan.source === "weekday_mixed") && plan.weekday_label && (
          <p className="m-0 text-[12px] text-[var(--text-muted)]">
            Ориентир: по прошлым {weekdayPastLabel(String(plan.weekday_label))}
            {plan.weeks_looked ? ` (${plan.weeks_looked} нед.)` : ""}
          </p>
        )}
        {typeof plan.commission_note === "string" && plan.commission_note.trim() && (
          <p className="m-0 text-[13px] leading-5 text-[var(--text-muted)]">{plan.commission_note}</p>
        )}
      </div>
    );
  }
  const orders = plan.orders ?? [];
  const typical = Array.isArray(plan.typical_rub) ? plan.typical_rub.map((v) => Number(v)).filter((v) => v > 0) : [];
  const hour = plan.hour_msk != null ? String(plan.hour_msk).padStart(2, "0") : null;
  if (orders.length === 0 && !plan.doliv_rub) {
    return (
      <div className="flex flex-col gap-2">
        {typical.length > 0 && hour && (
          <p className="m-0 text-[13px] text-[var(--text-muted)]">
            {forecastTypicalLine(plan, typical, hour) ||
              `В ${hour}:00 МСК чаще ${typical.map((v) => money(v)).join(" · ")} ₽`}
            {plan.source === "fallback" ? " · мало живых покупок, ориентир обычный" : ""}
            {plan.source === "mixed" ? " · мало статистики, смешан с обычными суммами" : ""}
            {plan.source === "weekday_mixed" ? " · мало данных за этот день, смешано с общим часом" : ""}
          </p>
        )}
        <p className="m-0 text-[13px] text-[var(--text-muted)]">
          {forecast
            ? String(plan.hint || "Типичные чеки этого часа не складываются в карту.")
            : "Подходящих заявок нет: нужна продажа в работе, крипта подтверждена, сумма не больше остатка."}
        </p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={plan.closes ? "green" : "yellow"}>
          {plan.closes
            ? orders.length === 0 && Number(plan.doliv_rub) > 0
              ? "Доплата закрывает остаток"
              : orders.length === 1 && Number(plan.doliv_rub) > 0
              ? "Один чек + доплата с нашей стороны"
              : orders.length === 1
                ? forecast
                  ? "Закроет одним типичным чеком"
                  : "Закрывает одним чеком"
                : forecast
                  ? `Ожидай ${plan.checks_count} чек(а)`
                  : `Закрывает за ${plan.checks_count} чек(а)`
            : forecast
              ? "Частично — карта больше типичных чеков"
              : "Закрывает частично"}
        </Badge>
        {Number(plan.doliv_rub) > 0 && <Badge tone="orange">Доплата {money(plan.doliv_rub)} ₽</Badge>}
        {Number(plan.leftover_rub) > 0 && <Badge tone="red">Остаток {money(plan.leftover_rub)} ₽</Badge>}
      </div>
      {hour && typical.length > 0 && (
        <p className="m-0 text-[13px] text-[var(--text-muted)]">
          {forecastTypicalLine(plan, typical, hour)}
          {plan.source === "fallback" ? " · мало живых покупок, ориентир обычный" : ""}
          {plan.source === "mixed" ? " · мало статистики, смешан с обычными суммами" : ""}
          {plan.source === "weekday_mixed" ? " · мало данных за этот день, смешано с общим часом" : ""}
        </p>
      )}
      <div className="flex flex-col gap-1">
        {orders.map((o) => {
          const href = orderHref(o.order_id);
          return (
            <div
              key={String(o.order_id)}
              className="flex items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
            >
              {href ? <OrderLink orderId={o.order_id}>{planOrderLabel(o)}</OrderLink> : <span className="font-mono">{planOrderLabel(o)}</span>}
              <span className="font-mono tabular-nums">{money(o.amount_rub)} ₽</span>
            </div>
          );
        })}
      </div>
      {typeof plan.hint === "string" && plan.hint.trim() && (
        <p className="m-0 text-[13px] leading-5 text-[var(--text-muted)]">{plan.hint}</p>
      )}
    </div>
  );
}

function asDict(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asList(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
}

function buyerLabel(allocation: PayoutAllocation) {
  const name = String(allocation.buyer_first_name || "").trim();
  const uname = String(allocation.buyer_username || "")
    .trim()
    .replace(/^@/, "");
  if (name && uname) return `${name} · @${uname}`;
  if (name) return name;
  if (uname) return `@${uname}`;
  return allocation.user_id ? `ID ${allocation.user_id}` : "Клиент";
}

function dtShort(v: unknown) {
  if (!v) return "—";
  return new Date(String(v)).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function payinCheckAwaiting(allocation: PayoutAllocation) {
  const orderStatus = String(allocation.order_status || "");
  return allocation.status === "RESERVED" && ["PENDING", "AWAITING_CHECK"].includes(orderStatus);
}

function payinCheckLive(allocation: PayoutAllocation) {
  return allocation.status === "RESERVED" || allocation.status === "PAID";
}

function payinCheckCanceled(allocation: PayoutAllocation) {
  const orderStatus = String(allocation.order_status || "").toUpperCase();
  return allocation.status === "CANCELED" || ["CANCELED", "EXPIRED", "FAILED"].includes(orderStatus);
}

async function downloadBuyerReceipt(orderId: string) {
  const { url, type } = await fetchOperatorOrderReceiptBlob(orderId);
  const ext = type.includes("pdf") ? "pdf" : type.startsWith("image/") ? "jpg" : "bin";
  const a = document.createElement("a");
  a.href = url;
  a.download = `receipt-${orderId}.${ext}`;
  a.rel = "noreferrer";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function PayinCheckRow({
  allocation,
  selected,
  onSelect,
}: {
  allocation: PayoutAllocation;
  selected: boolean;
  onSelect: () => void;
}) {
  const canceled = payinCheckCanceled(allocation);
  const awaiting = payinCheckAwaiting(allocation);
  const hasPdf = Boolean(allocation.has_buyer_receipt);
  const tone =
    allocation.status === "PAID" ? "green" : allocation.status === "RESERVED" ? "yellow" : "default";
  const orderStatus = String(allocation.order_status || "");
  const fiat = allocation.order_fiat_amount ?? allocation.amount_rub;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cx(
        "flex w-full flex-col gap-1 rounded-[var(--radius)] border px-3 py-2.5 text-left text-[13px] transition-colors",
        selected
          ? "border-[var(--border-strong)] bg-[var(--bg-overlay)]"
          : hasPdf && awaiting
            ? "border-[var(--accent)] bg-[var(--bg-elevated)] hover:border-[var(--border-strong)]"
            : "border-[var(--border)] bg-[var(--bg-elevated)] hover:border-[var(--border-strong)]",
        canceled && "opacity-60",
      )}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Badge tone={tone}>
          {allocation.status === "PAID" ? "Подтверждён" : canceled ? "Отменён" : awaiting && hasPdf ? "Проверить поступление" : "Ждём оплату"}
        </Badge>
        <span className="font-medium">{buyerLabel(allocation)}</span>
        <span className="font-mono tabular-nums">{money(fiat)} ₽</span>
        {allocation.order_crypto && (
          <span className="text-[var(--text-muted)]">{cryptoLabel(allocation.order_crypto)}</span>
        )}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-[var(--text-muted)]">
        <span className="font-mono">#{allocation.order_id}</span>
        {orderStatus && (
          <Badge tone={orderStatus === "COMPLETED" || orderStatus === "PAID" ? "green" : "default"}>
            {ORDER_STATUS_LABEL[orderStatus] ?? orderStatus}
          </Badge>
        )}
        {hasPdf && !canceled && <Badge tone="green">чек</Badge>}
        {awaiting && hasPdf && <Badge tone="yellow">открыть справа</Badge>}
        {allocation.status === "RESERVED" && !hasPdf && !canceled && (
          <span>ждём PDF</span>
        )}
      </div>
    </button>
  );
}

function PayinCheckPanel({
  allocation,
  requisite,
  canConfirm,
  onClose,
  onChanged,
}: {
  allocation: PayoutAllocation;
  requisite: PayoutRequisite;
  canConfirm: boolean;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<{ url: string; type: string } | null>(null);
  const [receiptFailed, setReceiptFailed] = useState(false);
  const userId = opsClientId(allocation.user_id);
  const orderId = String(allocation.order_id || "");
  const fiat = allocation.order_fiat_amount ?? allocation.amount_rub;
  const crypto = String(allocation.order_crypto || "btc");
  const awaiting = payinCheckAwaiting(allocation);
  const canceled = payinCheckCanceled(allocation);
  const hasPdf = Boolean(allocation.has_buyer_receipt);
  const identity = asDict(profile?.identity);
  const summary = asDict(profile?.summary);
  const balances = asDict(profile?.balances);
  const lastDeal = asDict(profile?.last_deal);
  const recent = asList(profile?.recent_orders).slice(0, 5);
  const displayName =
    String(identity.first_name || allocation.buyer_first_name || "").trim() ||
    (identity.username ? `@${String(identity.username).replace(/^@/, "")}` : buyerLabel(allocation));

  useEffect(() => {
    if (userId == null) {
      setProfile(null);
      setProfileError(null);
      return;
    }
    let alive = true;
    setProfile(null);
    setProfileError(null);
    getUser(userId)
      .then((d) => {
        if (alive) setProfile(asDict(d));
      })
      .catch((e) => {
        if (alive) setProfileError(e instanceof PanelApiError ? e.message : "Клиент не найден");
      });
    return () => {
      alive = false;
    };
  }, [userId]);

  useEffect(() => {
    if (!hasPdf || !orderId) {
      setReceipt(null);
      setReceiptFailed(false);
      return;
    }
    let alive = true;
    let objectUrl = "";
    setReceipt(null);
    setReceiptFailed(false);
    fetchOperatorOrderReceiptBlob(orderId)
      .then((blob) => {
        if (!alive) {
          URL.revokeObjectURL(blob.url);
          return;
        }
        objectUrl = blob.url;
        setReceipt(blob);
      })
      .catch(() => {
        if (alive) {
          setReceipt(null);
          setReceiptFailed(true);
        }
      });
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [hasPdf, orderId]);

  async function run(fn: () => Promise<unknown>, ok: string, close = true) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      if (close) await onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка операции");
      if (close) await onChanged();
    } finally {
      setBusy(false);
    }
  }

  const avatar = String(identity.avatar_url || "");
  const username = String(identity.username || allocation.buyer_username || "").replace(/^@/, "");
  const showConfirm = awaiting && canConfirm && !canceled;
  const statusBadge =
    allocation.status === "PAID" ? "Подтверждён" : canceled ? "Отменён" : awaiting && hasPdf ? "Проверить поступление" : "Ждём оплату";

  return (
    <Card className="flex max-h-[calc(100dvh-120px)] flex-col gap-4 overflow-y-auto lg:sticky lg:top-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[15px] font-semibold">#{orderId || "—"}</span>
            <Badge tone={allocation.status === "PAID" ? "green" : canceled ? "default" : "yellow"}>
              {statusBadge}
            </Badge>
          </div>
          <div className="mt-1 font-mono text-[13px] tabular-nums text-[var(--text-secondary)]">
            {money(fiat)} ₽
            {allocation.order_crypto_amount != null
              ? ` · ${cryptoAmount(allocation.order_crypto_amount, crypto)} ${cryptoLabel(crypto)}`
              : allocation.order_crypto
                ? ` · ${cryptoLabel(crypto)}`
                : ""}
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Вернуться к реквизитам">
          <X size={14} /> Назад
        </Button>
      </div>

      <div className="rounded-[var(--radius)] border border-[var(--border)] p-3 text-[13px]">
        <div className="font-medium">Получатель платежа · {requisite.bank ?? "—"}</div>
        <div>{requisite.holder_name ?? "—"}</div>
        <div className="break-all font-mono">{requisite.requisites ?? requisite.requisites_masked ?? "—"}</div>
      </div>
      <div className="flex items-center gap-3">
        {avatar ? (
          <img src={avatar} alt="" className="size-10 rounded-full object-cover" />
        ) : (
          <div className="flex size-10 items-center justify-center rounded-full bg-[var(--bg-elevated)] text-[12px] font-semibold">
            {displayName.slice(0, 2).toUpperCase()}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-semibold">{displayName}</div>
          <div className="flex flex-wrap items-center gap-x-2 text-[12px] text-[var(--text-muted)]">
            {username ? <span>@{username}</span> : null}
            {userId != null ? <span>ID {userId}</span> : null}
            {userId != null ? (
              <OpsClientLink userId={userId} className="text-[12px] text-[var(--blue)] underline-offset-2 hover:underline">
                Профиль →
              </OpsClientLink>
            ) : null}
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setProfileOpen((v) => !v)}>
          {profileOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {profileOpen ? "Скрыть статистику" : "Статистика"}
        </Button>
      </div>

      {profileError && <p className="m-0 text-[13px] text-[var(--red)]">{profileError}</p>}
      {profile && <p className="m-0 text-[12px] text-[var(--text-muted)]">Заявок: {String(summary.total_orders ?? "—")} · Оплачено: {String(summary.paid_orders ?? "—")} · Отменено: {String(summary.canceled_orders ?? "—")}</p>}
      {profileOpen && profile && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Kpi label="Заявок всего" value={String(summary.total_orders ?? "—")} />
            <Kpi label="Оплачено" value={String(summary.paid_orders ?? "—")} />
            <Kpi label="Оборот, ₽" value={money(summary.turnover_rub)} />
            <Kpi label="Конверсия" value={summary.conversion_pct == null ? "—" : `${summary.conversion_pct}%`} />
            <Kpi label="Отменено" value={String(summary.canceled_orders ?? "—")} />
            <Kpi label="Покупки / продажи" value={`${summary.buy_paid ?? "—"} / ${summary.sell_paid ?? "—"}`} />
            <Kpi label="Баланс, ₽" value={money(balances.available_rub ?? balances.balance_rub)} />
            <Kpi label="В боте с" value={dtShort(identity.first_seen_at)} />
          </div>
          {lastDeal.order_id != null && (
            <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]">
              <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Последняя заявка</div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                <span className="font-mono">#{String(lastDeal.order_id)}</span>
                <span>{lastDeal.direction === "buy" ? "Покупка" : "Продажа"}</span>
                <span className="font-mono tabular-nums">{money(lastDeal.fiat_amount)} ₽</span>
                <span className="text-[var(--text-muted)]">{dtShort(lastDeal.created_at)}</span>
              </div>
            </div>
          )}
          {recent.length > 0 && (
            <div>
              <div className="mb-1.5 text-[13px] font-semibold">Недавние заявки</div>
              <div className="flex flex-col gap-1">
                {recent.map((row) => (
                  <div
                    key={String(row.order_id)}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-2.5 py-1.5 text-[12px]"
                  >
                    <span className="font-mono">#{String(row.order_id)}</span>
                    <span className="text-[var(--text-muted)]">
                      {row.direction === "buy" ? "BUY" : "SELL"} · {money(row.fiat_amount)} ₽
                    </span>
                    <Badge tone={String(row.status) === "PAID" || String(row.status) === "COMPLETED" ? "green" : "default"}>
                      {ORDER_STATUS_LABEL[String(row.status)] ?? String(row.status_label || row.status || "")}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <CopyField label="Сумма, ₽" value={String(fiat ?? "")} />
      {allocation.order_crypto_amount != null && (
        <CopyField label={cryptoLabel(crypto)} value={cryptoPlain(allocation.order_crypto_amount, crypto)} />
      )}
      {allocation.order_wallet && <CopyField label="Кошелёк" value={String(allocation.order_wallet)} />}

      {hasPdf ? (
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <div className="text-[13px] font-semibold">Чек покупателя</div>
            <Button size="sm" disabled={busy || !orderId} onClick={() => run(() => downloadBuyerReceipt(orderId), "Чек скачан", false)}>
              Скачать
            </Button>
          </div>
          {receipt?.type.startsWith("image/") ? (
            <img src={receipt.url} alt="Чек покупателя" className="max-h-80 w-full rounded-[var(--radius)] object-contain bg-[var(--bg-elevated)]" />
          ) : receipt ? (
            <iframe title="Чек покупателя" src={receipt.url} className="h-80 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)]" />
          ) : (
            <p className="m-0 text-[13px] text-[var(--text-muted)]">
              {receiptFailed ? "Превью не открылось — скачайте чек." : "Превью загружается…"}
            </p>
          )}
        </div>
      ) : (
        <p className="m-0 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2.5 text-[13px] leading-5 text-[var(--text-secondary)]">
          {canceled ? "Заявка снята, принять нельзя." : "Ждём PDF от покупателя."}
        </p>
      )}

      {canceled && hasPdf && (
        <p className="m-0 text-[13px] leading-5 text-[var(--text-muted)]">Заявка снята, принять нельзя.</p>
      )}

      {showConfirm && (
        <div className="sticky bottom-0 z-10 -mx-2 flex flex-col gap-2 border-t border-[var(--border)] bg-[var(--bg-surface)] px-2 pb-2 pt-4 [&_button]:h-auto [&_button]:min-h-10 [&_button]:whitespace-normal [&_button]:py-2">
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              run(() => confirmPayinFiatReceived(orderId), "Чек принят — заявка в выплату крипты")
            }
          >
            Подтвердить поступление рублей
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() =>
              window.confirm("Заявка будет отменена, её резерв освобождён. Клиент получит уведомление. Отклонить чек?") && run(() => rejectPayinReceipt(orderId), "Заявка отменена, резерв освобождён")
            }
          >
            Отклонить чек и отменить заявку
          </Button>
          <p className="m-0 text-[12px] leading-5 text-[var(--text-muted)]">
            PDF не подтверждает получение денег. После подтверждения рублей покупка перейдёт к выплате крипты.
          </p>
        </div>
      )}
      {!canConfirm && awaiting && !canceled && (
        <p className="m-0 text-[13px] leading-5 text-[var(--text-muted)]">
          Принять чек может старший с правом подтверждения.
        </p>
      )}
    </Card>
  );
}

function AllocationRow({
  allocation,
  busy,
  onPaid,
  onCancel,
  onReceipt,
}: {
  allocation: PayoutAllocation;
  busy: boolean;
  onPaid: (file: File) => void;
  onCancel: () => void;
  onReceipt: (file: File) => void;
}) {
  const tone = allocation.status === "PAID" ? "green" : allocation.status === "RESERVED" ? "yellow" : "default";
  const receiptRef = useRef<HTMLInputElement>(null);
  const paidRef = useRef<HTMLInputElement>(null);
  const needsReceipt = allocation.status === "PAID" && allocation.kind === "order";
  const clientRequisites = String(allocation.order_requisites || "").trim();
  const reqLabel = String(allocation.order_sub_token || "").toUpperCase() === "SBPRUB" ? "СБП клиента" : "Карта клиента";
  const orderLabel =
    allocation.kind === "doliv"
      ? "Доплата с нашей стороны"
      : allocation.kind === "payin"
        ? `#${allocation.order_id}`
        : `#${allocation.order_id}`;
  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5 text-[13px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge tone={tone}>
            {allocation.status === "PAID" ? "Оплачен" : allocation.status === "RESERVED" ? "Бронь" : "Снят"}
          </Badge>
          {allocation.kind === "doliv" ? (
            <span>{orderLabel}</span>
          ) : (
            <OrderLink orderId={allocation.order_id}>{orderLabel}</OrderLink>
          )}
          <span className="font-mono tabular-nums">{money(allocation.amount_rub)} ₽</span>
          {allocation.has_receipt && <Badge tone="green">Чек клиенту</Badge>}
          {allocation.status === "PAID" && allocation.kind === "order" && !allocation.client_confirmed && (
            <Badge tone="yellow">ждём подтверждение</Badge>
          )}
          {allocation.client_confirmed && <Badge tone="green">клиент подтвердил</Badge>}
        </div>
        {allocation.status === "RESERVED" && allocation.kind === "order" && (
          <div className="flex gap-2">
            <input
              ref={paidRef}
              type="file"
              accept="image/*,application/pdf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) onPaid(file);
              }}
            />
            <Button size="sm" variant="primary" disabled={busy} onClick={() => paidRef.current?.click()}>
              Чек оплачен
            </Button>
            <Button size="sm" disabled={busy} onClick={onCancel}>
              Снять
            </Button>
          </div>
        )}
        {needsReceipt && (
          <div className="flex items-center gap-2">
            <input
              ref={receiptRef}
              type="file"
              accept="image/*,application/pdf"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && onReceipt(e.target.files[0])}
            />
            <Button size="sm" disabled={busy} onClick={() => receiptRef.current?.click()}>
              {allocation.has_receipt ? "Заменить чек" : "Приложить чек клиенту"}
            </Button>
          </div>
        )}
      </div>
      {allocation.kind === "order" && clientRequisites ? <CopyField label={reqLabel} value={clientRequisites} /> : null}
    </div>
  );
}

function pendingCheckCount(allocations: PayoutAllocation[], isPayin: boolean) {
  return allocations.filter((a) => {
    if (a.status === "CANCELED") return false;
    if (isPayin) {
      const orderStatus = String(a.order_status || "");
      return a.status === "RESERVED" && ["PENDING", "AWAITING_CHECK"].includes(orderStatus);
    }
    return a.status === "RESERVED" && a.kind === "order";
  }).length;
}

function cardNextStep(opts: {
  queued: boolean;
  canConfirm: boolean;
  isPayin: boolean;
  isTriangle: boolean;
  pending: number;
  pendingPdf: number;
  status: string;
  active: boolean;
}): string {
  const { queued, canConfirm, isPayin, isTriangle, pending, pendingPdf, status, active } = opts;
  if (queued) {
    return canConfirm ? "Следующий шаг: нажмите «Включить»" : "Следующий шаг: ждёт старшего";
  }
  if (isPayin && pendingPdf > 0) {
    return "Следующий шаг: откройте чек справа";
  }
  if (isPayin && pending > 0) {
    return "Ждём PDF покупателя";
  }
  if (!isPayin && status === "RESERVED") {
    return "Следующий шаг: закройте чек или запишите долив";
  }
  if (!isPayin && pending > 0) {
    return "Следующий шаг: закройте чек / долив";
  }
  if (isPayin && active) {
    return isTriangle
      ? "Ждём оплату покупателей на карту продавца"
      : "Ждём оплату покупателей на эту карту";
  }
  if (active) {
    return "Карта в работе — подбор и бронь в «Подробнее»";
  }
  return STATUS_LABEL[status] ?? status;
}

function PayinDiagnosticsView({ requisite }: { requisite: PayoutRequisite }) {
  const d = requisite.diagnostics;
  if (!d || d.unavailable) return <p role="status" className="text-[13px] text-[var(--text-muted)]">Прогноз и диагностика недоступны. Обновите реквизит; требуется API с поддержкой диагностики.</p>;
  const t = d.traffic;
  const f = d.issuance;
  const percent = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v * 100)}%`;
  return <section className="flex flex-col gap-3 rounded-[var(--radius)] border border-[var(--border)] p-3">
    <h3 className="m-0 text-[14px] font-semibold">Прогноз и диагностика</h3>
    <div className="text-[13px]">
      {d.readiness?.ready ? "Доступен для подбора по состоянию реквизита" : d.readiness?.reasons.join(" · ")}
    </div>
    {f && <>
      <Badge tone={f.health === "error" ? "red" : f.health === "working" ? "green" : "default"}>
        {f.health === "error" ? "Несогласованность назначений" : f.health === "working" ? "Есть факты назначения" : "Фактов назначения пока нет"}
      </Badge>
      <p className="m-0 text-[13px]">Назначено {f.assigned_count} · Подтверждено {f.paid_count} · Отменено {f.canceled_count}</p>
      <p className="m-0 text-[12px] text-[var(--text-muted)]">Первое: {dtShort(f.first_assigned_at)} · Последнее: {dtShort(f.last_assigned_at)}{f.last_order_id && <> · <OrderLink orderId={f.last_order_id}>#{f.last_order_id}</OrderLink></>}</p>
      {f.health === "no_data" && <p className="m-0 text-[13px]">Для этого реквизита назначений нет. Ниже — общий поток подходящих BUY, а не подтверждение работы выдачи в боте.</p>}
    </>}
    {t && <>
      <p className="m-0 text-[13px]">Подходящая заявка за 30 минут: <strong>{percent(t.probability_30m)}</strong> · оценка по истории, не гарантия оплаты.</p>
      <details><summary className="cursor-pointer text-[12px] text-[var(--text-secondary)]">Расчёт, варианты и ограничения</summary><div className="mt-3 flex flex-col gap-3">
      <div className="text-[13px] font-medium">Подходящая заявка: историческая частота появления</div>
      <div className="grid grid-cols-3 gap-2">
        <Kpi label="За 15 минут" value={percent(t.probability_15m)} />
        <Kpi label="За 30 минут" value={percent(t.probability_30m)} />
        <Kpi label="За 60 минут" value={percent(t.probability_60m)} />
      </div>
      {!d.readiness?.ready && <p className="m-0 text-[12px] text-[var(--text-muted)]">Это справка о потоке. Сейчас реквизит не принимает новые назначения.</p>}
      <p className="m-0 text-[13px]">Доля оплат среди завершённых подходящих заявок: {percent(t.payment_conversion)} ({t.matching_paid}/{t.resolved_orders}). Это не вероятность оплаты в ближайший час.</p>
      <p className="m-0 text-[13px]">Суммы оплаченных подходящих заявок: {t.typical_rub.length ? `${money(t.typical_rub[0])}–${money(t.typical_rub[1])} ₽` : "недостаточно данных"}.</p>
      {t.payment_sequences.length ? t.payment_sequences.map((seq, i) => <div key={i} className="text-[13px]">Пример закрытия за {seq.length} платежа: {seq.map(v => money(v)).join(" + ")} ₽</div>) : <p className="m-0 text-[13px]">В доступной выборке не найден пример полного закрытия в лимит платежей.</p>}
      <p className="m-0 text-[12px] text-[var(--text-muted)]">35 дней · {t.comparison_windows} интервалов, включая пустые · {t.matching_created} подходящих заявок. {t.source === "general_buy_history" ? "Тот же день недели и время МСК." : "Все дни, то же время МСК: данных по дню недели мало."} {t.confidence === "medium" ? "Историческая оценка, без гарантии." : "Мало данных — оценка ненадёжна."}</p>
      <details className="text-[12px] text-[var(--text-muted)]"><summary className="cursor-pointer">Как читать прогноз</summary><p>{t.limitations} Примеры закрытия предполагают последовательное подтверждение, без ожидания и конкуренции. Доставка сообщения Telegram не проверяется.</p></details>
      </div></details>
    </>}
    <span className="text-[11px] text-[var(--text-muted)]">Рассчитано: {dtShort(d.computed_at)}</span>
  </section>;
}

function RequisiteCard({
  requisite,
  onChanged,
  canConfirm,
  selectedAllocationId,
  onSelectCheck,
  onSelectRequisite,
  stale,
}: {
  requisite: PayoutRequisite;
  onChanged: () => void | Promise<void>;
  canConfirm: boolean;
  selectedAllocationId?: number | null;
  onSelectCheck?: (allocation: PayoutAllocation) => void;
  onSelectRequisite: () => void;
  stale: boolean;
}) {
  const [reveal, setReveal] = useState(() => Boolean(requisite.is_mine));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dolivAmount, setDolivAmount] = useState("");
  const [dolivNote, setDolivNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const countdown = useCountdown(requisite.deadline_at);

  const current = requisite;
  const isPayin = current.direction === "payin";
  const withdrawalId = current.source_withdrawal_id;
  const isTriangle = Boolean(current.source_sell_order_id || withdrawalId);
  const plan = current.plan;
  const queued = current.status === "QUEUED";
  const active = ["OPEN", "RESERVED", "PARTIAL"].includes(current.status);
  const allAllocations = current.allocations ?? [];
  const liveAllocations = allAllocations.filter(payinCheckLive).sort((a, b) => Number(payinCheckAwaiting(b) && b.has_buyer_receipt) - Number(payinCheckAwaiting(a) && a.has_buyer_receipt));
  const historyAllocations = allAllocations.filter((a) => !payinCheckLive(a));
  const pending = pendingCheckCount(allAllocations, isPayin);
  const pendingPdf = liveAllocations.filter((a) => payinCheckAwaiting(a) && a.has_buyer_receipt).length;
  const tank = fillTank({
    amountRub: Number(current.amount_rub),
    paidRub: Number(current.paid_rub),
    reservedRub: current.reserved_rub,
    freeRub: current.free_rub,
    allocations: allAllocations,
  });

  async function run(action: () => Promise<unknown>, okMessage: string) {
    if (stale) { toast.error("Обновите данные перед действием"); return; }
    setBusy(true);
    try {
      await action();
      toast.success(okMessage);

      await onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  const planOrders = plan?.orders ?? [];
  const cryptoCode = (CRYPTO_OPTIONS.find((c) => c.value === current.crypto)?.value) ?? "btc";
  const canExpand = Boolean(current.is_mine);
  const usedChecks = Number(
    current.used_checks ?? liveAllocations.filter((a) => a.status === "PAID" || a.status === "RESERVED").length,
  );
  const maxChecks = Number(current.max_checks || 1);
  const checksLeft = Number(current.checks_left ?? Math.max(0, maxChecks - usedChecks));
  const closeForN =
    isPayin && usedChecks >= 1 && tank.free > 0
      ? Math.min(5, Math.max(usedChecks + 1, usedChecks + Math.min(checksLeft || 1, 2)))
      : null;
  const showPlan = active || queued;
  const primaryAction = queued
    ? canConfirm ? "Включить приём" : "Ждёт включения старшим"
    : pendingPdf > 0 ? "Проверить поступление"
    : current.has_open_reserve ? "Ждём оплату по выданным реквизитам"
    : active ? "Ожидаем подходящую заявку" : "Приём завершён";

  return (
    <Card className="flex flex-col gap-5 border-[var(--border-strong)] p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-[15px] font-semibold">
            <span className="truncate">{cardTitle(current)}</span>
            <Badge tone={STATUS_TONE[current.status] ?? "default"}>{STATUS_LABEL[current.status] ?? current.status}</Badge>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px] text-[var(--text-muted)]">
            {isPayin && (
              <span>
                {current.source_sell_order_id
                  ? `Из продажи №${current.source_sell_order_id}`
                  : withdrawalId
                    ? `Из вывода №${withdrawalId}`
                    : "Свой реквизит"}
                {" ·"}
              </span>
            )}
            <span>{methodLabel(current.method)}</span>
            <span className="font-mono">{reveal ? current.requisites : current.requisites_masked}</span>
            {current.is_mine && current.requisites && (
              <button
                type="button"
                onClick={() => setReveal((v) => !v)}
                className="inline-flex items-center gap-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                aria-label={reveal ? "Скрыть реквизит" : "Показать реквизит"}
              >
                {reveal ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            )}
            {current.bank && <span>· {current.bank}</span>}
            {current.holder_name && <span>· {current.holder_name}</span>}
            <span>· Ответственный: {current.operator_display_name ?? (current.is_mine ? "Вы" : "—")}</span>
            {countdown && (active || queued) && <span>· ещё {countdown}</span>}
          </div>
        </div>
        <div className="text-right text-[13px] text-[var(--text-muted)]">
          {Number(current.cost_pct) !== 0 && <div>наценка {pct(current.cost_pct)}</div>}
          {isPayin && (
            <div className="font-medium tabular-nums text-[var(--text-primary)]">
              платежи {current.used_checks == null && !current.is_mine ? "—" : usedChecks}/{maxChecks} · осталось {current.checks_left == null && !current.is_mine ? "—" : checksLeft}
            </div>
          )}
        </div>
      </div>

      {current.amount_rub != null && current.paid_rub != null && current.reserved_rub != null
        ? <FillBar paid={tank.paid} reserved={tank.reserved} total={tank.amount} />
        : <p className="m-0 text-[13px] text-[var(--text-muted)]">Суммы недоступны —</p>}

      <div className={cx("flex items-start gap-3 rounded-[var(--radius)] border p-3", pendingPdf > 0 ? "border-[var(--yellow)]/30 bg-[var(--yellow-bg)]" : "border-[var(--border)] bg-[var(--bg-elevated)]")}>
        {pendingPdf > 0 ? <AlertCircle size={18} className="mt-0.5 shrink-0 text-[var(--yellow)]" /> : active ? <Clock3 size={18} className="mt-0.5 shrink-0 text-[var(--text-secondary)]" /> : <CircleCheck size={18} className="mt-0.5 shrink-0 text-[var(--green)]" />}
        <div className="min-w-0"><div className="text-[13px] font-semibold">Сейчас: {primaryAction}</div><p className="m-0 mt-0.5 text-[12px] leading-5 text-[var(--text-secondary)]">{cardNextStep({
          queued,
          canConfirm,
          isPayin,
          isTriangle,
          pending,
          pendingPdf,
          status: current.status,
          active,
        })}
        {pendingPdf > 0 && !open ? ` · ${pendingPdf} чек(а) с PDF` : ""}</p></div>
        {isPayin && pendingPdf > 0 && <Button className="ml-auto shrink-0" size="sm" onClick={() => { const check = liveAllocations.find(a => payinCheckAwaiting(a) && a.has_buyer_receipt && !payinCheckCanceled(a)); if (check) onSelectCheck?.(check); }}>Проверить</Button>}
      </div>

      {isPayin && liveAllocations.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between"><div className="text-[14px] font-semibold">Платежи</div><span className="text-[12px] text-[var(--text-muted)]">Сначала требующие проверки</span></div>
          <div className="flex flex-col gap-2">
            {liveAllocations.map((a) => (
              <PayinCheckRow
                key={a.id}
                allocation={a}
                selected={selectedAllocationId === a.id}
                onSelect={() => onSelectCheck?.(a)}
              />
            ))}
          </div>
        </div>
      )}

      {!isPayin && !isTriangle && (
      <PayoffHero
        compact
        amountRub={Number(current.amount_rub)}
        paidRub={Number(current.paid_rub)}
        costPct={Number(current.cost_pct)}
        crypto={cryptoCode}
        direction={isPayin ? "payin" : "payout"}
      />
      )}

      <div className="flex flex-wrap items-center gap-2">
        {queued && canConfirm && (
          <Button variant="primary" disabled={busy} onClick={() => run(() => confirmPayoutRequisite(requisite.id), "Карта включена")}>
            Включить
          </Button>
        )}
        {queued && !canConfirm && (
          <span className="text-[13px] text-[var(--text-muted)]">Ждёт включения старшим</span>
        )}
        {queued && current.is_mine && (
          <Button disabled={busy} onClick={() => window.confirm("Снять реквизит? Текущие резервы будут отменены. Если клиент уже переводит деньги, сначала разберите этот платёж.") && run(() => cancelPayoutRequisite(requisite.id), "Карта снята")}>
            Снять
          </Button>
        )}
        {canExpand && (
          <Button size="sm" onClick={() => { onSelectRequisite(); setOpen((v) => !v); }}>
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {open ? "Свернуть" : "Подробнее"}
          </Button>
        )}
      </div>

      {open && current.is_mine && (
        <div className="flex flex-col gap-5 border-t border-[var(--border)] pt-5">
          {isPayin && (active || queued) && (
            <div className="flex flex-col gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] font-medium">Макс. чеков</div>
                <div className="flex flex-wrap gap-1.5">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      disabled={busy || n < usedChecks}
                      className={cx(
                        "rounded-md border px-2.5 py-1 text-[12.5px]",
                        maxChecks === n
                          ? "border-[var(--accent)] bg-[var(--bg-overlay)] text-[var(--text-primary)]"
                          : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]",
                        n < usedChecks && "opacity-40",
                      )}
                      onClick={() =>
                        run(() => updatePayoutRequisiteMaxChecks(requisite.id, n), `Макс. чеков → ${n}`)
                      }
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
              {closeForN != null && closeForN < maxChecks && (
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () => updatePayoutRequisiteMaxChecks(requisite.id, closeForN),
                      `Закроем за ${closeForN} чек(а)`,
                    )
                  }
                >
                  Закрыть за {closeForN}
                </Button>
              )}
              <p className="m-0 text-[12px] text-[var(--text-muted)]">
                Это максимум платежей: остаток может закрыться раньше. Уже выданные суммы не меняются. Одновременно на реквизите одна бронь.
              </p>
            </div>
          )}

          {showPlan && (
            isPayin ? <PayinDiagnosticsView requisite={current} /> :
            <details>
              <summary className="cursor-pointer text-[14px] font-semibold">Как может заполниться</summary>
              <p className="text-[12px] text-[var(--text-muted)]">Приблизительный прогноз, не гарантия срока. Источник и варианты — ниже.</p>
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-[14px] font-semibold">{isPayin ? "Как закроется" : "Подбор заявок"}</div>
                <Button
                  size="sm"
                  disabled={busy || (!active && !queued)}
                  onClick={() =>
                    run(async () => {
                      await getPayoutRequisitePlan(requisite.id, true);
                    }, isPayin ? "Прогноз пересчитан" : "План пересчитан")
                  }
                >
                  <RefreshCw size={13} /> Пересчитать
                </Button>
              </div>
              <PlanView plan={plan} isPayin={isPayin} />
              {active && !isPayin && planOrders.length > 0 && (
                <Button
                  variant="primary"
                  className="mt-3"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () => reservePayoutRequisite(requisite.id, planOrders.map((o) => o.order_id)),
                      "Заявки забронированы",
                    )
                  }
                >
                  Забронировать {planOrders.length} чек(а)
                </Button>
              )}
            </details>
          )}

          {isPayin && historyAllocations.length > 0 && (
            <div>
              <div className="mb-2 text-[14px] font-semibold">История</div>
              <div className="flex flex-col gap-2">
                {historyAllocations.map((a) => (
                  <PayinCheckRow
                    key={a.id}
                    allocation={a}
                    selected={selectedAllocationId === a.id}
                    onSelect={() => onSelectCheck?.(a)}
                  />
                ))}
              </div>
            </div>
          )}

          {!isPayin && allAllocations.length > 0 && (
            <div>
              <div className="mb-2 text-[14px] font-semibold">Чеки по карте</div>
              <div className="flex flex-col gap-2">
                {allAllocations.map((a) => (
                  <AllocationRow
                    key={a.id}
                    allocation={a}
                    busy={busy}
                    onPaid={(file) =>
                      run(() => markPayoutAllocationPaid(requisite.id, a.id, file), "Чек закрыт")
                    }
                    onCancel={() => run(() => cancelPayoutAllocation(requisite.id, a.id), "Бронь снята")}
                    onReceipt={(file) =>
                      run(() => attachPayoutAllocationReceipt(requisite.id, a.id, file), "Чек приложен")
                    }
                  />
                ))}
              </div>
            </div>
          )}

          {active && (!isPayin || isTriangle) && (
            <div>
              <div className="mb-2 text-[14px] font-semibold">
                Доплатить с нашей стороны{" "}
                <span className="font-normal text-[var(--text-muted)]">(до {current.doliv_limit_rub} ₽)</span>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="w-32">
                  <Field label="Сумма, ₽">
                    <Input inputMode="decimal" value={dolivAmount} onChange={(e) => setDolivAmount(e.target.value)} className="font-mono" />
                  </Field>
                </div>
                <div className="min-w-[160px] flex-1">
                  <Field label="Комментарий">
                    <Input value={dolivNote} onChange={(e) => setDolivNote(e.target.value)} placeholder="Необязательно" />
                  </Field>
                </div>
                <input ref={fileRef} type="file" accept="image/*,application/pdf" className="text-[13px] text-[var(--text-muted)]" />
                <Button
                  disabled={busy}
                  onClick={() => {
                    const amount = Number(dolivAmount);
                    if (!Number.isFinite(amount) || amount <= 0) {
                      toast.error("Укажите сумму доплаты");
                      return;
                    }
                    run(async () => {
                      await addPayoutDoliv(requisite.id, amount, dolivNote.trim() || undefined, fileRef.current?.files?.[0]);
                      setDolivAmount("");
                      setDolivNote("");
                      if (fileRef.current) fileRef.current.value = "";
                    }, "Доплата записана");
                  }}
                >
                  Записать
                </Button>
              </div>
            </div>
          )}

          {active && (
            <div className="flex flex-wrap gap-2">
              <Button disabled={busy} onClick={() => window.confirm("Закрыть реквизит? Текущие резервы будут отменены. Если клиент уже переводит деньги, сначала разберите этот платёж.") && run(() => closePayoutRequisite(requisite.id), "Карта закрыта")}>
                Закрыть
              </Button>
              <Button
                disabled={busy}
                onClick={() => window.confirm("Снять реквизит? Текущие резервы будут отменены. Если клиент уже переводит деньги, сначала разберите этот платёж.") && run(() => cancelPayoutRequisite(requisite.id), "Карта снята")}
              >
                Снять с работы
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function CostPicker({
  value,
  onChange,
  direction,
}: {
  value: string;
  onChange: (next: string) => void;
  direction: "payout" | "payin";
}) {
  const numeric = Number(value);
  const isPreset = Number.isFinite(numeric) && COST_PRESETS.includes(numeric);
  const [manual, setManual] = useState(!isPreset);

  const cost = Number.isFinite(numeric) ? numeric : 0;
  const hint =
    direction === "payin"
      ? cost > 0
        ? "Берём процент с рублей на карте — крипты придёт меньше номинала."
        : cost < 0
          ? "За карту доплатим — крипты придёт больше номинала."
          : "Без наценки: сколько рублей на карте, столько крипты по курсу."
      : cost > 0
        ? "Доплатим сверх суммы карты — это расход."
        : cost < 0
          ? "Карта дешевле номинала — это доход."
          : "Без наценки: рубль в рубль.";

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[13px] font-medium text-[var(--text-secondary)]">Наценка</div>
      <div className="flex flex-wrap gap-1.5">
        {COST_PRESETS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={!manual && numeric === p ? "primary" : "secondary"}
            onClick={() => {
              setManual(false);
              onChange(String(p));
            }}
          >
            {pct(p)}
          </Button>
        ))}
        <Button size="sm" variant={manual ? "primary" : "secondary"} onClick={() => setManual(true)}>
          Другое
        </Button>
      </div>
      {manual && (
        <Input
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Например: -0.75"
          className="font-mono"
        />
      )}
      <p className="m-0 text-[13px] leading-snug text-[var(--text-muted)]">{hint}</p>
    </div>
  );
}

function PayoffHero({
  amountRub,
  costPct,
  crypto,
  direction,
  paidRub = 0,
  compact = false,
}: {
  amountRub: number;
  costPct: number;
  crypto: PayoutCrypto;
  direction: "payout" | "payin";
  paidRub?: number;
  compact?: boolean;
}) {
  const { quote, error } = usePayoffQuote(amountRub, costPct, crypto, direction);
  const showPaid = Number.isFinite(paidRub) && paidRub > 0 && Math.abs(paidRub - amountRub) > 0.009;
  const paid = usePayoffQuote(showPaid ? paidRub : 0, costPct, crypto, direction);

  function copyAmount(value: number) {
    const text = cryptoPlain(value, crypto);
    navigator.clipboard?.writeText(text).then(
      () => toast.success(`Скопировано: ${text} ${cryptoLabel(crypto)}`),
      () => toast.error("Не удалось скопировать"),
    );
  }

  if (compact) {
    if (error) return <div className="text-[13px] text-[var(--red)]">{error}</div>;
    if (!quote) return null;
    return (
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-[var(--text-muted)]">
        <span>{direction === "payin" ? "к получению" : "к отправке"}</span>
        <span className="font-mono tabular-nums text-[var(--text-primary)]">
          {cryptoAmount(quote.crypto_amount, crypto)} {cryptoLabel(crypto)}
        </span>
        <Button size="sm" onClick={() => copyAmount(quote.crypto_amount)} aria-label="Копировать">
          <Copy size={13} />
        </Button>
        {showPaid && paid.quote && (
          <span>
            уже {cryptoAmount(paid.quote.crypto_amount, crypto)} {cryptoLabel(crypto)}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3.5">
      <div className="text-[13px] text-[var(--text-muted)]">
        {direction === "payin" ? "Крипта, которую нам пришлют" : "Крипта, которую отправим"}
      </div>
      {error && <div className="text-[13px] text-[var(--red)]">{error}</div>}
      {!error && !quote && (
        <div className="text-[13px] text-[var(--text-muted)]">
          {direction === "payin"
            ? `Укажите сумму — посчитаем, сколько ${cryptoLabel(crypto)} придёт.`
            : `Укажите сумму — посчитаем ${cryptoLabel(crypto)} по курсу.`}
        </div>
      )}
      {!error && quote && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="font-mono text-[20px] font-semibold leading-tight tabular-nums">
              {cryptoAmount(quote.crypto_amount, crypto)} {cryptoLabel(crypto)}
            </div>
            <Button size="sm" onClick={() => copyAmount(quote.crypto_amount)}>
              <Copy size={13} /> Копировать
            </Button>
          </div>
          <div className="text-[13px] leading-snug text-[var(--text-muted)]">
            {money(quote.amount_rub)} ₽ · наценка {pct(costPct)} → {money(quote.payoff_rub)} ₽ · курс{" "}
            {money(quote.rate_rub)} ₽/{cryptoLabel(crypto)}
          </div>
          {showPaid && paid.quote && (
            <div className="mt-1 border-t border-[var(--border)] pt-2 text-[13px] text-[var(--text-muted)]">
              Уже по {money(paidRub)} ₽ — {cryptoAmount(paid.quote.crypto_amount, crypto)} {cryptoLabel(crypto)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function amountPrefill(v: unknown): string {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n) || n <= 0) return "";
  return String(Math.round(n));
}

function fromSellOkToast(req: PayoutRequisite) {
  if (req.status === "QUEUED") toast.success("Карта продавца в очереди — включите в пул");
  else toast.success("Карта продавца в приёме");
}

function poolBillMethod(order: Pick<PayoutPoolOrder, "sub_token" | "requisites">): "card" | "sbp" {
  const sub = String(order.sub_token || "").toUpperCase();
  if (sub === "CARDRUB") return "card";
  if (sub === "SBPRUB") return "sbp";
  const digits = String(order.requisites || "").replace(/\D/g, "");
  return digits.length >= 16 ? "card" : "sbp";
}

function leftoverBank(raw: string): string {
  const leftover = raw.replace(/[\d+\s\-().]+/g, " ").replace(/\s+/g, " ").trim();
  return leftover.length >= 2 ? leftover : "";
}

type FromSellFix = {
  order: PayoutPoolOrder;
  message: string;
  requisites: string;
  method: "card" | "sbp";
  bank: string;
};

function unparsedFromSellError(e: unknown, order: PayoutPoolOrder): FromSellFix | null {
  if (!(e instanceof PanelApiError) || e.status !== 400) return null;
  const payload = e.payload;
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : null;
  const coded =
    Boolean(detail) && typeof detail === "object" && (detail as { code?: unknown }).code === "unparsed_requisites";
  if (!coded && !/не разобрали/i.test(e.message)) return null;
  const d = coded && detail && typeof detail === "object" ? (detail as Record<string, unknown>) : {};
  const raw = String(d.requisites || order.requisites || "");
  return {
    order,
    message: String(d.message || e.message || "Не разобрали реквизиты продавца"),
    requisites: raw,
    method: poolBillMethod({
      requisites: raw,
      sub_token: String(d.sub_token || order.sub_token || ""),
    }),
    bank: leftoverBank(raw),
  };
}

function FromSellFixModal({
  fix,
  onClose,
  onSaved,
}: {
  fix: FromSellFix | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [method, setMethod] = useState<"card" | "sbp">("sbp");
  const [requisites, setRequisites] = useState("");
  const [bank, setBank] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!fix) return;
    setMethod(fix.method);
    setRequisites(fix.requisites);
    setBank(fix.bank);
    setBusy(false);
  }, [fix]);

  async function submit() {
    if (!fix) return;
    if (requisites.trim().length < 4) {
      toast.error("Укажите телефон или номер карты");
      return;
    }
    setBusy(true);
    try {
      const out = await createPayoutRequisiteFromSell(String(fix.order.order_id), {
        method,
        requisites: requisites.trim(),
        bank: bank.trim() || undefined,
        holder_name: "клиент",
      });
      fromSellOkToast(out.requisite);
      onSaved();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось поставить карту");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={Boolean(fix)}
      title="Исправьте реквизиты продавца"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={() => void submit()}>
            Поставить в приём
          </Button>
        </>
      }
    >
      <p className="m-0 text-[13px] leading-5 text-[var(--text-muted)]">{fix?.message}</p>
      <div className="mt-3 flex flex-col gap-3">
        <Field label="Способ">
          <Select value={method} onChange={(e) => setMethod(e.target.value === "card" ? "card" : "sbp")}>
            <option value="sbp">СБП</option>
            <option value="card">Карта</option>
          </Select>
        </Field>
        <Field label={method === "card" ? "Номер карты" : "Телефон СБП"}>
          <Input
            value={requisites}
            onChange={(e) => setRequisites(e.target.value)}
            placeholder={method === "card" ? "2202…" : "+7 900…"}
          />
        </Field>
        <Field label="Банк">
          <Input value={bank} onChange={(e) => setBank(e.target.value)} placeholder="Сбер" />
        </Field>
      </div>
    </Modal>
  );
}

function PayoutPoolBlock({
  orders,
  onPutUnderPayin,
}: {
  orders: PayoutPoolOrder[];
  onPutUnderPayin: (order: PayoutPoolOrder) => Promise<void> | void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  if (!orders.length) return null;
  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="text-[13px] font-semibold text-[var(--text-secondary)]">Продажи ждут выплаты</div>
        <p className="m-0 mt-1 text-[12.5px] leading-5 text-[var(--text-muted)]">
          Крипта подтверждена. Реквизиты продавца уходят в пул приёма — покупки платят на них.
        </p>
      </div>
      <Card>
        <div className="flex flex-col gap-3">
          {orders.map((order) => {
            const amount = Number(order.fiat_amount || 0);
            const oid = String(order.order_id);
            return (
              <div
                key={oid}
                className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3 last:border-b-0 last:pb-0"
              >
                <div className="min-w-0">
                  <div className="text-[14px] font-medium">
                    <OrderLink orderId={order.order_id}>#{order.order_id}</OrderLink>
                    <span className="ml-2 tabular-nums">{moneyInt(amount)} ₽</span>
                  </div>
                  <div className="mt-0.5 text-[13px] text-[var(--text-muted)]">{cryptoLabel(order.crypto)}</div>
                  {order.requisites ? (
                    <div className="mt-0.5 truncate text-[12px] text-[var(--text-muted)]">{String(order.requisites)}</div>
                  ) : null}
                </div>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={busyId === oid}
                  onClick={() => {
                    setBusyId(oid);
                    Promise.resolve(onPutUnderPayin(order)).finally(() => setBusyId(null));
                  }}
                >
                  В пул реквизитов
                </Button>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

function CreateForm({
  onCreated,
  poolOrders = [],
  direction,
}: {
  onCreated: () => void;
  poolOrders?: PayoutPoolOrder[];
  direction: "payin" | "payout";
}) {
  const [method, setMethod] = useState<"card" | "sbp">("sbp");
  const [requisites, setRequisites] = useState("");
  const [amount, setAmount] = useState("");
  const [costPct, setCostPct] = useState("0");
  const [crypto, setCrypto] = useState<PayoutCrypto>("btc");
  const [label, setLabel] = useState("");
  const [bank, setBank] = useState("");
  const [holder, setHolder] = useState("");
  const [windowMinutes, setWindowMinutes] = useState("180");
  const [maxChecks, setMaxChecks] = useState("2");
  const [dolivLimit, setDolivLimit] = useState("1000");
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sellHint, setSellHint] = useState<{ id: string; amount: number } | null>(null);

  useEffect(() => {
    let alive = true;
    getOrders(50, 0)
      .then((data) => {
        if (alive) setSellHint(pickOpenSellWithoutCrypto(data));
      })
      .catch(() => {
        if (alive) setSellHint(null);
      });
    return () => {
      alive = false;
    };
  }, []);

  const poolHint = poolOrders[0] ?? null;

  function validatedAmount(): number | null {
    const amountNum = Number(amount);
    const costNum = Number(costPct);
    if (!Number.isFinite(amountNum) || amountNum <= 0) {
      toast.error(direction === "payin" ? "Укажите сумму приёма" : "Укажите сумму выплаты");
      return null;
    }
    if (!Number.isFinite(costNum)) {
      toast.error("Наценка должна быть числом");
      return null;
    }
    if (requisites.trim().length < 4) {
      toast.error("Укажите телефон или номер карты");
      return null;
    }
    if (bank.trim().length < 2) {
      toast.error("Укажите банк");
      return null;
    }
    if (holder.trim().length < 2) {
      toast.error("Укажите ФИО");
      return null;
    }
    return amountNum;
  }

  async function postCard() {
    const amountNum = validatedAmount();
    if (amountNum == null) return;
    const costNum = Number(costPct);
    setBusy(true);
    try {
      // Never auto-include: create stays QUEUED until the operator presses «Включить».
      await createPayoutRequisite({
        method,
        direction,
        requisites: requisites.trim(),
        amount_rub: amountNum,
        cost_pct: costNum,
        crypto,
        label: label.trim() || undefined,
        bank: bank.trim(),
        holder_name: holder.trim(),
        window_minutes: Number(windowMinutes) || 180,
        max_checks: Number(maxChecks) || 3,
        doliv_limit_rub: Number(dolivLimit) || 0,
      });
      toast.success(direction === "payin" ? "Карта ждёт включения" : "Карта в работе");
      setConfirmOpen(false);
      setRequisites("");
      setAmount("");
      setLabel("");
      setBank("");
      setHolder("");
      onCreated();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  function submit() {
    if (validatedAmount() == null) return;
    if (direction === "payin") {
      setConfirmOpen(true);
      return;
    }
    void postCard();
  }

  return (
    <Card className="h-fit" id="payout-card-form">
      <div className="mb-1 text-[15px] font-semibold">Добавить реквизит</div>
      <div className="mb-5 text-[13px] leading-5 text-[var(--text-muted)]">
        {direction === "payin"
          ? "Клиенты будут платить на эти реквизиты. После постановки карта ждёт «Включить». Проверяйте поступления здесь, в карточке реквизита."
          : "С этой карты вы платите продавцам. Подбор чеков — на карточке. Проверяйте поступления здесь, в карточке реквизита."}
      </div>
      {direction === "payin" && !poolHint && sellHint && (
        <div className="mb-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5 text-[13px] leading-5">
          Продажа <OrderLink orderId={sellHint.id}>#{sellHint.id}</OrderLink> на {moneyInt(sellHint.amount)} ₽ — это{" "}
          <Link to={orderHref(sellHint.id) ?? "/ops/orders"} className="text-[var(--blue)] underline-offset-4 hover:underline">
            Заявки
          </Link>
          , не приём.
        </div>
      )}
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label={direction === "payin" ? "Целевая сумма, ₽" : "Сумма с карты, ₽"}>
            <Input
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="font-mono"
              placeholder="5000"
            />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {AMOUNT_CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="rounded-md border border-[var(--border)] px-2 py-0.5 text-[12.5px] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                  onClick={() => setAmount(String(chip))}
                >
                  {chip.toLocaleString("ru-RU")}
                </button>
              ))}
            </div>
          </Field>
          {more && <Field label="Крипта">
            <Select value={crypto} onChange={(e) => setCrypto(e.target.value as PayoutCrypto)}>
              {CRYPTO_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>}
        </div>
        {more && <CostPicker value={costPct} onChange={setCostPct} direction={direction} />}
        {more && <PayoffHero amountRub={Number(amount)} costPct={Number(costPct)} crypto={crypto} direction={direction} />}
        {direction === "payin" && (
          <Field label="Макс. чеков">
            <div className="flex flex-wrap gap-1.5">
              {MAX_CHECKS_CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className={cx(
                    "rounded-md border px-3 py-1 text-[13px]",
                    Number(maxChecks) === chip
                      ? "border-[var(--accent)] bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]",
                  )}
                  onClick={() => setMaxChecks(String(chip))}
                >
                  {chip}
                </button>
              ))}
            </div>
            <p className="m-0 mt-1.5 text-[12.5px] text-[var(--text-muted)]">
              Верхняя граница числа платежей. Если остаток закроется раньше, дополнительные платежи не нужны.
            </p>
          </Field>
        )}
        <Field label="Как платят">
          <Select value={method} onChange={(e) => setMethod(e.target.value as "card" | "sbp")}>
            <option value="card">Карта</option>
            <option value="sbp">СБП</option>
          </Select>
        </Field>
        <Field label={method === "sbp" ? "Телефон" : "Номер карты"}>
          <Input value={requisites} onChange={(e) => setRequisites(e.target.value)} className="font-mono" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Банк">
            <Input value={bank} onChange={(e) => setBank(e.target.value)} placeholder="Сбер" />
          </Field>
          <Field label="ФИО получателя">
            <Input
              value={holder}
              onChange={(e) => setHolder(e.target.value)}
              placeholder="Иванов Иван Иванович"
            />
          </Field>
        </div>
        <p className="m-0 -mt-1 text-[13px] text-[var(--text-muted)]">Банк и ФИО — как в чеке.</p>
        <Field label="Метка">
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Например: Сбер Иван" />
        </Field>
        <button
          type="button"
          className="self-start text-[13px] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          onClick={() => setMore((v) => !v)}
        >
          {more ? "Скрыть дополнительные настройки" : "Дополнительные настройки: крипта, стоимость, срок"}
        </button>
        {more && (
          <div className="grid grid-cols-3 gap-3">
            <Field label="Окно, мин">
              <Input
                inputMode="numeric"
                value={windowMinutes}
                onChange={(e) => setWindowMinutes(e.target.value)}
                className="font-mono"
              />
            </Field>
            {direction === "payout" ? (
              <>
                <Field label="Макс. чеков">
                  <Input
                    inputMode="numeric"
                    value={maxChecks}
                    onChange={(e) => setMaxChecks(e.target.value)}
                    className="font-mono"
                  />
                </Field>
                <Field label="Доплата, ₽">
                  <Input
                    inputMode="numeric"
                    value={dolivLimit}
                    onChange={(e) => setDolivLimit(e.target.value)}
                    className="font-mono"
                    placeholder="1000"
                  />
                </Field>
              </>
            ) : (
              <div />
            )}
          </div>
        )}
        <Button variant="primary" disabled={busy} onClick={submit}>
          Поставить карту
        </Button>
      </div>
      <Modal
        open={confirmOpen}
        title="Поставить карту в очередь?"
        onClose={() => !busy && setConfirmOpen(false)}
        footer={
          <>
            <Button variant="ghost" disabled={busy} onClick={() => setConfirmOpen(false)}>
              Отмена
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => void postCard()}>
              В очередь
            </Button>
          </>
        }
      >
        <p className="m-0 text-[13px] leading-5">
          Карта попадёт в очередь. Клиенты начнут платить только после «Включить». Сумма {moneyInt(Number(amount))} ₽.
        </p>
      </Modal>
    </Card>
  );
}

export function OperatorPayoutRequisites() {
  const [rows, setRows] = useState<PayoutRequisite[]>([]);
  const [payoutPool, setPayoutPool] = useState<PayoutPoolOrder[]>([]);
  const [unopenedWithdrawals, setUnopenedWithdrawals] = useState<{ id: number; triangle_label: string }[]>([]);
  const [direction, setDirection] = useState<"payin" | "payout">("payin");
  const [boardTab, setBoardTab] = useState<"review" | "active" | "queued" | "done">("active");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [canConfirm, setCanConfirm] = useState(false);
  const [selected, setSelected] = useState<{ requisiteId: number; allocationId?: number } | null>(null);
  const [detail, setDetail] = useState<PayoutRequisite | null>(null);
  const [detailError, setDetailError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [fromSellFix, setFromSellFix] = useState<FromSellFix | null>(null);
  const requestVersion = useRef(0);
  const checkPanelRef = useRef<HTMLDivElement>(null);
  const checkOpen = selected?.allocationId != null;
  useEffect(() => {
    if (!checkOpen) return;
    const previous = document.activeElement;
    const root = checkPanelRef.current;
    const narrow = window.matchMedia("(max-width: 1023px)").matches;
    const overflow = document.body.style.overflow;
    if (narrow) document.body.style.overflow = "hidden";
    root?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setSelected(null); }
      if (e.key !== "Tab" || !window.matchMedia("(max-width: 1023px)").matches) return;
      const nodes = Array.from(root?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input, select, summary, iframe") ?? []).filter(el => el.getClientRects().length);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === root)) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", keydown);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [checkOpen]);

  useEffect(() => {
    panelMe("operator")
      .then((me) => setCanConfirm(Array.isArray(me.permissions) && me.permissions.includes("payout.requisites.confirm")))
      .catch(() => setCanConfirm(false));
  }, []);

  const selectedId = selected?.requisiteId;
  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    const [listResult, detailResult] = await Promise.allSettled([
      listPayoutRequisites(boardTab === "done"),
      selectedId == null ? Promise.resolve(null) : getPayoutRequisite(selectedId),
    ]);
    if (version !== requestVersion.current) return;
    if (listResult.status === "fulfilled") {
      const r = listResult.value;
      setRows([...(r.mine ?? []), ...(r.team ?? [])]);
      setPayoutPool(Array.isArray(r.pool_orders) ? r.pool_orders : []);
      setUnopenedWithdrawals(Array.isArray(r.unopened_withdrawals) ? r.unopened_withdrawals : []);
      setError(null);
      setUpdatedAt(new Date());
    } else {
      setError(listResult.reason instanceof PanelApiError ? listResult.reason.message : "Не удалось обновить список");
    }
    setDetailError(detailResult.status === "rejected");
    setDetail(detailResult.status === "fulfilled" ? detailResult.value?.requisite ?? null : null);
    setLoaded(true);
  }, [boardTab, selectedId]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await load();
      if (!stopped) timer = window.setTimeout(() => void poll(), 8000);
    };
    void poll();
    return () => { stopped = true; window.clearTimeout(timer); requestVersion.current++; };
  }, [load]);

  const currentDetail = detail?.id === selectedId ? detail : null;
  const all = rows.map((r) => currentDetail?.id === r.id ? { ...r, ...currentDetail, operator_display_name: r.operator_display_name } : r).filter((r) => r.direction === direction);
  const activeRows = all.filter((r) => ["OPEN", "RESERVED", "PARTIAL"].includes(r.status));
  const queuedRows = all.filter((r) => r.status === "QUEUED");
  const doneRows = all.filter((r) => ["CLOSED", "EXPIRED", "CANCELED"].includes(r.status));
  const needsReview = (r: PayoutRequisite) => (r.allocations ?? []).some((a) => payinCheckAwaiting(a) && a.has_buyer_receipt && !payinCheckCanceled(a));
  const reviewRows = activeRows.filter(needsReview);
  const visible = (boardTab === "review" ? reviewRows : boardTab === "queued" ? queuedRows : boardTab === "done" ? doneRows : activeRows)
    .slice().sort((a, b) => Number(needsReview(b)) - Number(needsReview(a)));
  const selectedRequisite = currentDetail;
  const selectedAllocation = selectedRequisite?.allocations?.find((a) => a.id === selected?.allocationId);
  const stale = Boolean(error || detailError);

  const tab = (id: typeof boardTab, label: string, count?: number) => (
    <Button key={id} variant={boardTab === id ? "primary" : "ghost"} onClick={() => setBoardTab(id)}>
      {label}{count == null ? "" : ` · ${count}`}
    </Button>
  );

  return (
    <>
      <PageHeader title="Приём средств" subtitle="Один экран для реквизита, платежей и проверки поступлений." />
      <div className="mb-5 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          <Button variant={direction === "payin" ? "primary" : "ghost"} onClick={() => { setDirection("payin"); setSelected(null); setCreating(false); setBoardTab("active"); }}>Приём средств</Button>
          <Button variant={direction === "payout" ? "primary" : "ghost"} onClick={() => { setDirection("payout"); setSelected(null); setCreating(false); setBoardTab("active"); }}>Выплаты с карты</Button>
        </div>
        <Button variant="primary" onClick={() => { setSelected(null); setCreating(true); }}>Добавить реквизит</Button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
        {direction === "payin" && tab("review", "Проверить", reviewRows.reduce((n, r) => n + (r.allocations ?? []).filter(a => payinCheckAwaiting(a) && a.has_buyer_receipt && !payinCheckCanceled(a)).length, 0))}
        {tab("active", direction === "payin" ? "Принимают" : "В работе", activeRows.length)}
        {direction === "payin" && tab("queued", "Ждут включения", queuedRows.length)}
        {tab("done", "Завершённые")}
        <Button variant="ghost" size="sm" onClick={() => void load()} aria-label="Обновить список"><RefreshCw size={14} /></Button>
        <span className="ml-auto text-[12px] text-[var(--text-muted)]">{updatedAt ? `Обновлено ${updatedAt.toLocaleTimeString("ru-RU")}` : "Загрузка…"}</span>
      </div>
      </div>
      {stale && <div role="alert" className="mb-4 rounded-[var(--radius)] border border-[var(--border)] p-3 text-[var(--text-secondary)]">Данные устарели. {error ?? "Не удалось обновить выбранный реквизит."} Действия приостановлены до обновления.</div>}
      {direction === "payin" && <p className="text-[12px] text-[var(--text-muted)]">Счётчик проверки учитывает доступные вам платежи. Подробности чужих реквизитов ограничены правами.</p>}
      <div className={cx("grid items-start gap-5", (creating || selected?.allocationId != null) && "lg:grid-cols-[minmax(0,1fr)_minmax(320px,440px)]")}>
        <div className="flex min-w-0 flex-col gap-4">
          {direction === "payin" && payoutPool.length > 0 && <PayoutPoolBlock orders={payoutPool} onPutUnderPayin={async (order) => {
            if (stale) { toast.error("Сначала обновите данные"); return; }
            try {
              const out = await createPayoutRequisiteFromSell(String(order.order_id));
              fromSellOkToast(out.requisite);
              await load();
            } catch (e) {
              const fix = unparsedFromSellError(e, order);
              if (fix) { setFromSellFix(fix); return; }
              toast.error(e instanceof PanelApiError ? e.message : "Не удалось поставить реквизит");
            }
          }} />}
          {!loaded && <Card>Загружаем реквизиты…</Card>}
          {direction === "payin" && unopenedWithdrawals.length > 0 && (
            <Card>
              {unopenedWithdrawals.map((w) => (
                <div key={w.id} className="text-[13px]">
                  Вывод #{w.id}: {w.triangle_label}
                </div>
              ))}
            </Card>
          )}
          {loaded && visible.length === 0 && <Card>{error ? "Список недоступен. Повторите обновление." : boardTab === "review" ? "Нет доступных платежей, требующих проверки." : boardTab === "queued" ? "Нет реквизитов, ожидающих включения. Выводы на карту и телефон сразу в «Принимают»." : boardTab === "done" ? "Завершённых реквизитов пока нет." : "Нет активных реквизитов. Добавьте реквизит или выберите готовую продажу."}</Card>}
          {visible.map((r) => <RequisiteCard key={r.id} requisite={r} onChanged={load} canConfirm={canConfirm && !stale} stale={stale}
            onSelectRequisite={() => { setSelected({ requisiteId: r.id }); setCreating(false); }}
            selectedAllocationId={selected?.requisiteId === r.id ? selected.allocationId ?? null : null}
            onSelectCheck={(a) => { setSelected({ requisiteId: r.id, allocationId: a.id }); setCreating(false); }} />)}
          {boardTab === "done" && <p className="text-[12px] text-[var(--text-muted)]">API возвращает до 100 реквизитов. Это доступная выборка, а не полный архив.</p>}
        </div>
        {creating ? <div className="min-w-0 max-lg:order-first">
          <Button variant="ghost" onClick={() => setCreating(false)}>Закрыть форму</Button>
          <CreateForm direction={direction} poolOrders={payoutPool} onCreated={() => { setCreating(false); setBoardTab(direction === "payin" ? "queued" : "active"); void load(); }} />
        </div> : selected?.allocationId != null ? <div ref={checkPanelRef} tabIndex={-1} role="dialog" aria-label="Проверка платежа" className="min-w-0 lg:sticky lg:top-4 max-lg:order-first max-lg:fixed max-lg:inset-0 max-lg:z-50 max-lg:overflow-y-auto max-lg:bg-[var(--bg-base)] max-lg:p-3 max-lg:sm:p-5">
          {selectedAllocation && selectedRequisite ? <PayinCheckPanel key={selectedAllocation.id} allocation={selectedAllocation} requisite={selectedRequisite} canConfirm={canConfirm && !stale}
            onClose={() => setSelected(null)} onChanged={load} /> : <Card>
            <Button variant="ghost" onClick={() => setSelected(null)}>Закрыть</Button>
            <p>{detailError ? "Платёж недоступен. Обновите данные." : currentDetail ? "Платёж больше недоступен в этом реквизите." : "Загружаем платёж…"}</p>
          </Card>}
        </div> : null}
      </div>
      <FromSellFixModal fix={fromSellFix} onClose={() => setFromSellFix(null)} onSaved={() => { setFromSellFix(null); void load(); }} />
    </>
  );
}
