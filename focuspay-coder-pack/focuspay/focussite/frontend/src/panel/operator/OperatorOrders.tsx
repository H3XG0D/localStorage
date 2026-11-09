import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { OpsClientLink, opsClientId } from "@/panel/lib/opsClientPath";
import { CopyField } from "@/panel/ui/CopyField";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import {
  cancelOrder,
  closeClientHold,
  claimOrder,
  cancelWithdrawal,
  claimWithdrawal,
  confirmSellCryptoReceived,
  confirmPayinFiatReceived,
  getOrders,
  markOrderPaid,
  orderReceiptUrl,
  paidWithdrawal,
  payoutOrder,
  payoutWithdrawal,
  getDolivCardBalances,
  pushDolivPayout,
  transferOrderToFinance,
  transferWithdrawalToFinance,
  getMe,
  getUser,
  requestOrderVideo,
  sendOrderReceiptToPayfast,
  sendOrderWalletConfirmEarly,
  reviewAccount,
  type OperatorMe,
  type OrderRow,
} from "@/panel/lib/operatorApi";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import { initiateChat } from "@/panel/lib/chatApi";
import { Badge, Button, Card, Field, Input, PageHeader, cx } from "@/panel/ui/primitives";
import {
  getPayoutWalletMode,
  previewOrderWalletSend,
  sendOrderFromProjectWallet,
  type WalletPayoutMode,
} from "@/panel/lib/operatorApi";
import { ProjectWalletSendModal } from "@/panel/operator/ProjectWalletSendModal";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v ?? 0));
}
function crypto(v: unknown) {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n)) return "0";
  // Dot decimal, no grouping — paste into wallets/explorers.
  return n.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 8 });
}

const OPERATOR_PENDING_CANCEL_REASON =
  "Если актуально — пересоздайте заявку или напишите оператору @focus_operator";

type Item = OrderRow & { assigned_to_me?: boolean; payment_summary?: string };
type Side = "buy" | "sell";
type SelKind = "order" | "wd";
type StatusBucket = "awaiting_check" | "pending" | "operator_pending" | "payout" | "other";

const STATUS_BUCKETS: { id: StatusBucket; title: string }[] = [
  { id: "awaiting_check", title: "Ожидает чек" },
  { id: "pending", title: "На проверке" },
  { id: "operator_pending", title: "Ждёт оператора" },
  { id: "payout", title: "К выплате" },
  { id: "other", title: "Спор / прочее" },
];

function statusBucket(status: unknown): StatusBucket {
  switch (String(status || "").toUpperCase()) {
    case "AWAITING_CHECK":
      return "awaiting_check";
    case "PENDING":
      return "pending";
    case "OPERATOR_PENDING":
      return "operator_pending";
    case "COMPLETED":
      return "payout";
    default:
      return "other";
  }
}

function orderSide(item: Pick<Item, "direction">): Side {
  return String(item.direction || "").toLowerCase() === "buy" ? "buy" : "sell";
}

function asDict(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function trustLabel(paid: unknown): string {
  const n = Number(paid ?? 0);
  if (!Number.isFinite(n) || n <= 0) return "Новый";
  if (n <= 3) return "Начинающий";
  if (n <= 9) return "Постоянный";
  if (n <= 19) return "Доверенный";
  return "VIP";
}

function relativeWhen(iso: unknown): string {
  if (!iso) return "—";
  const t = new Date(String(iso)).getTime();
  if (!Number.isFinite(t)) return "—";
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days <= 0) return "сегодня";
  if (days === 1) return "вчера";
  if (days < 7) return `${days} дн. назад`;
  if (days < 30) return `${Math.floor(days / 7)} нед. назад`;
  return `${Math.floor(days / 30)} мес. назад`;
}

function fmtDay(iso: unknown): string {
  if (!iso) return "—";
  const d = new Date(String(iso));
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function fmtExpires(iso: unknown): string {
  if (!iso) return "без окна";
  const d = new Date(String(iso));
  if (!Number.isFinite(d.getTime())) return "без окна";
  return `до ${d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}

function operatorLabel(item: Pick<Item, "assigned_operator" | "operator_name" | "operator_id">): string {
  const assigned = item.assigned_operator as { display_name?: string; username?: string } | null | undefined;
  return String(assigned?.display_name || assigned?.username || item.operator_name || "без оператора");
}

function orderGroup(item: Item, meId?: number): string {
  if (item.operator_id == null) return "Входящие";
  if (item.assigned_to_me || (meId != null && Number(item.operator_id) === meId)) return "Мои";
  const name = operatorLabel(item);
  return name !== "без оператора" ? name : "Команда";
}

function groupTone(group: string): "blue" | "green" | "default" {
  if (group === "Входящие") return "blue";
  if (group === "Мои") return "green";
  return "default";
}

function withdrawalUserId(w: Record<string, unknown>): number | null {
  return opsClientId(w.user_id ?? w.referrer_user_id);
}

function withdrawalClientName(w: Record<string, unknown>): string {
  return String(w.buyer_first_name || w.buyer_username || `ID ${w.user_id ?? w.referrer_user_id ?? "—"}`);
}

function withdrawalPayoutRub(w: Record<string, unknown>): number {
  const stored = Number(w.payout_amount_rub);
  if (Number.isFinite(stored)) return stored;
  const amount = Number(w.amount_rub ?? 0);
  const fee = Number(w.network_fee_rub ?? 0);
  return Math.max(0, Math.round((amount - fee) * 100) / 100);
}

function withdrawalCryptoLabel(w: Record<string, unknown>): string {
  return String(w.method ?? "") === "crypto" ? String(w.crypto ?? "crypto").toUpperCase() : "Карта";
}

export function OperatorOrders() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [selId, setSelId] = useState<string | null>(null);
  const [selKind, setSelKind] = useState<SelKind>("order");
  const [side, setSide] = useState<Side>("buy");
  const sideTouched = useRef(false);
  const [statusTab, setStatusTab] = useState<StatusBucket>("awaiting_check");
  const statusTouched = useRef(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [me, setMe] = useState<OperatorMe | null>(null);
  const [shiftLoaded, setShiftLoaded] = useState(false);
  const [dolivFloat, setDolivFloat] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const [closingHoldId, setClosingHoldId] = useState<string | null>(null);

  const load = useCallback(() => {
    setRefreshing(true);
    Promise.allSettled([getOrders(200, 0), getMe(), getDolivCardBalances()]).then(([ordersResult, meResult, dolivResult]) => {
      if (ordersResult.status === "fulfilled") setData(ordersResult.value as Record<string, unknown>);
      else toast.error(ordersResult.reason instanceof PanelApiError ? ordersResult.reason.message : "Ошибка загрузки заявок");
      if (meResult.status === "fulfilled") setMe(meResult.value);
      else toast.error(meResult.reason instanceof PanelApiError ? meResult.reason.message : "Ошибка проверки смены");
      if (dolivResult.status === "fulfilled") setDolivFloat(String(dolivResult.value.total_float_rub ?? "0"));
      else setDolivFloat(null);
      setLastUpdated(Date.now());
      setShiftLoaded(true);
    }).finally(() => {
      setLoading(false);
      setRefreshing(false);
    });
  }, []);

  useAuthedPoll("operator", load, 7000, [load]);

  async function closeHold(orderId: string) {
    if (!shiftOpen) {
      toast.error("Откройте смену на дашборде");
      return;
    }
    if (!window.confirm(`Закрыть заявку #${orderId}? Клиент сможет начать новый обмен.`)) return;
    setClosingHoldId(orderId);
    try {
      await closeClientHold(orderId);
      toast.success("Заявка закрыта");
      if (selId === orderId) setSelId(null);
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось закрыть");
    } finally {
      setClosingHoldId(null);
    }
  }

  // Unified open queue: all live orders on shift, then incoming/team for older API payloads.
  const incoming = (data?.incoming ?? []) as Item[];
  const openOrders = (data?.orders ?? []) as Item[];
  const team = (data?.team_orders ?? []) as Item[];
  const holds = (data?.client_holds ?? []) as Item[];
  const retries = (data?.requisite_retries ?? []) as Array<Record<string, unknown>>;
  const holdIds = useMemo(() => new Set(holds.map((h) => h.order_id)), [holds]);
  const wdIncoming = (data?.withdrawals_incoming ?? []) as Record<string, unknown>[];
  const wdMine = (data?.withdrawals ?? []) as Record<string, unknown>[];
  const wdTeam = (data?.team_withdrawals ?? []) as Record<string, unknown>[];
  const meId = me?.operator?.id;
  const all = useMemo(() => {
    const seen = new Set<string>();
    const out: { group: string; item: Item }[] = [];
    const push = (item: Item) => {
      if (!item?.order_id || seen.has(item.order_id) || holdIds.has(item.order_id)) return;
      seen.add(item.order_id);
      out.push({ group: orderGroup(item, meId), item });
    };
    for (const it of openOrders) push(it);
    for (const it of incoming) push(it);
    for (const it of team) push(it);
    return out;
  }, [openOrders, incoming, team, holdIds, meId]);
  const liveRequisites = useMemo(
    () => all.filter((x) => Boolean(x.item.live_requisites)),
    [all],
  );

  const allWd = useMemo(() => {
    const seen = new Set<string>();
    const out: { group: string; item: Record<string, unknown> }[] = [];
    for (const [group, list] of [
      ["Входящие", wdIncoming],
      ["Мои", wdMine],
      ["Команда", wdTeam],
    ] as const) {
      for (const it of list) {
        const id = String(it.id ?? "");
        if (!id || seen.has(id)) continue;
        seen.add(id);
        out.push({ group, item: it });
      }
    }
    return out;
  }, [wdIncoming, wdMine, wdTeam]);

  const buyCount = all.filter((x) => orderSide(x.item) === "buy").length;
  const sellCount = all.length - buyCount;
  const incomingBuy = incoming.filter((it) => orderSide(it) === "buy").length;
  const incomingSell = incoming.filter((it) => orderSide(it) === "sell").length;
  const sideOrders = useMemo(
    () => all.filter((x) => orderSide(x.item) === side),
    [all, side],
  );
  const bucketCounts = useMemo(() => {
    const counts: Record<StatusBucket, number> = {
      awaiting_check: 0,
      pending: 0,
      operator_pending: 0,
      payout: 0,
      other: 0,
    };
    for (const row of sideOrders) counts[statusBucket(row.item.status)] += 1;
    return counts;
  }, [sideOrders]);
  const visible = sideOrders.filter((x) => statusBucket(x.item.status) === statusTab);

  const selected = selKind === "order"
    ? all.find((x) => x.item.order_id === selId)?.item
      ?? holds.find((h) => h.order_id === selId)
      ?? null
    : null;
  const selectedWd = selKind === "wd" ? allWd.find((x) => String(x.item.id) === selId) ?? null : null;
  const requestedOrder = searchParams.get("order");
  const requestedWd = searchParams.get("wd");
  const shiftOpen = !!me?.active_shift;
  const operatorRoles = Array.isArray(me?.operator?.operator_roles)
    ? me.operator.operator_roles
    : [me?.operator?.operator_role ?? "client"];
  const isFinance = operatorRoles.includes("finance");
  const mePerms = me?.operator?.permissions;
  const canConfirmPayin = Array.isArray(mePerms) && mePerms.includes("payout.requisites.confirm");
  const shiftLocked = shiftLoaded && !shiftOpen;

  useEffect(() => {
    if (!requestedOrder) return;
    const match = all.find((x) => x.item.order_id === requestedOrder)
      ?? (holds.find((h) => h.order_id === requestedOrder)
        ? { item: holds.find((h) => h.order_id === requestedOrder)! }
        : undefined);
    if (!match) return;
    setSelKind("order");
    if (match.item.order_id !== selId) setSelId(match.item.order_id);
    setSide(orderSide(match.item));
    setStatusTab(statusBucket(match.item.status));
  }, [all, holds, requestedOrder, selId]);

  useEffect(() => {
    if (!requestedWd) return;
    const match = allWd.find((x) => String(x.item.id) === requestedWd);
    if (!match) return;
    setSelKind("wd");
    const id = String(match.item.id);
    if (id !== selId) setSelId(id);
  }, [allWd, requestedWd, selId]);

  useEffect(() => {
    if (requestedOrder || requestedWd || sideTouched.current) return;
    if (incomingBuy > 0) setSide("buy");
    else if (incomingSell > 0) setSide("sell");
  }, [incomingBuy, incomingSell, requestedOrder, requestedWd]);

  useEffect(() => {
    if (requestedOrder || requestedWd || statusTouched.current) return;
    const first = STATUS_BUCKETS.find((bucket) => bucketCounts[bucket.id] > 0);
    if (first && first.id !== statusTab) setStatusTab(first.id);
  }, [bucketCounts, requestedOrder, requestedWd, statusTab]);

  useEffect(() => {
    if (requestedOrder || requestedWd) return;
    if (selKind === "order" && selId && all.some((x) => x.item.order_id === selId)) return;
    if (selKind === "wd" && selId && allWd.some((x) => String(x.item.id) === selId)) return;
    if (allWd.length > 0 && sideOrders.length === 0) {
      setSelKind("wd");
      setSelId(String(allWd[0].item.id));
    }
  }, [all, allWd, requestedOrder, requestedWd, selId, selKind, sideOrders.length]);

  return (
    <>
      <PageHeader
        title="Заявки"
        subtitle={`Покупка ${buyCount} · Продажа ${sellCount} · входящих ${incoming.length}`}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[var(--text-muted)]" aria-live="polite">
              {refreshing ? "Обновление…" : lastUpdated ? `Обновлено ${new Date(lastUpdated).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}` : "—"}
            </span>
            <Button size="sm" variant="ghost" onClick={load} disabled={refreshing} aria-label="Обновить заявки">↻</Button>
          </div>
        }
      />

      {dolivFloat != null && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-3 text-[13px] text-[var(--text-secondary)]">
          Doliv float на картах: {Number(dolivFloat).toLocaleString("ru-RU")} ₽
        </div>
      )}

      {shiftLocked && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-4 py-3 text-[13px] text-[var(--yellow)]">
          Смена не открыта. Заявки доступны для просмотра, рабочие действия разблокируются после открытия смены.
        </div>
      )}

      {retries.length > 0 && (
        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div>
              <div className="text-[13.5px] font-semibold">Повторный запрос реквизитов</div>
              <div className="text-[12px] text-[var(--text-muted)]">
                Висит 30 минут. В заявки не попадает.
              </div>
            </div>
            <Badge tone="yellow">{retries.length}</Badge>
          </div>
          <div className="max-h-[min(280px,36dvh)] overflow-y-auto">
            {retries.map((item) => {
              const leftSec = Number(item.seconds_left ?? 0);
              const leftMin = Math.max(0, Math.ceil(leftSec / 60));
              const who = String(item.buyer_first_name || (item.buyer_username ? `@${item.buyer_username}` : `ID ${item.user_id ?? "—"}`));
              const pay = item.sub_token === "CARDRUB" ? "Карта" : item.sub_token === "SBPRUB" ? "СБП" : String(item.sub_token || "—");
              const coin = String(item.crypto || "").split("_").join(" ");
              return (
                <div key={String(item.id)} className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-4 py-3 last:border-0">
                  <span className="text-[13px] font-medium">{who}</span>
                  <span className="font-mono text-[12px] text-[var(--text-secondary)]">
                    {Number(item.fiat_amount || 0).toLocaleString("ru-RU")} ₽ · {coin} · {pay}
                  </span>
                  <span className="text-[12px] text-[var(--text-muted)]">
                    {leftMin} мин · нажатий {Number(item.attempt_count || 1)}
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {holds.length > 0 && (
        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div>
              <div className="text-[13.5px] font-semibold">Держат клиента</div>
              <div className="text-[12px] text-[var(--text-muted)]">
                Бот не даёт создать новый обмен. Закройте, если заявка уже не нужна.
              </div>
            </div>
            <Badge tone="yellow">{holds.length}</Badge>
          </div>
          <div className="max-h-[min(360px,40dvh)] overflow-y-auto">
            {holds.map((item) => (
              <div
                key={item.order_id}
                className={cx(
                  "flex w-full items-center gap-3 border-b border-[var(--border)] px-4 py-3 last:border-0",
                  selKind === "order" && selId === item.order_id ? "bg-[var(--bg-elevated)]" : "",
                )}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 cursor-pointer text-left"
                  onClick={() => {
                    setSelKind("order");
                    setSelId(item.order_id);
                    setSide(orderSide(item));
                    setStatusTab(statusBucket(item.status));
                  }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[13px] font-medium">#{item.order_id}</span>
                    <Badge tone={orderStatusTone(item.status)}>{item.status_label || statusLabel(item.status)}</Badge>
                  </div>
                  <div className="mt-0.5 truncate text-[12px] text-[var(--text-muted)]">
                    {item.hold_reason_label || "Блокирует обмен"}
                    {" · "}
                    <OpsClientLink userId={item.user_id}>
                      {item.buyer_first_name || item.buyer_username || `ID ${item.user_id ?? "—"}`}
                    </OpsClientLink>
                    {" · "}
                    {money(item.fiat_amount)} ₽
                  </div>
                </button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={shiftLocked || closingHoldId === item.order_id}
                  onClick={() => closeHold(item.order_id)}
                >
                  {closingHoldId === item.order_id ? "…" : "Закрыть"}
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {liveRequisites.length > 0 && (
        <Card className="p-0" data-live-requisites="">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div>
              <div className="text-[13.5px] font-semibold">С реквизитами</div>
              <div className="text-[12px] text-[var(--text-muted)]">
                Кто сейчас сидит с выданными реквизитами. Клик открывает карточку.
              </div>
            </div>
            <Badge tone="yellow">{liveRequisites.length}</Badge>
          </div>
          <div className="flex gap-2 overflow-x-auto px-3 py-2">
            {liveRequisites.map(({ item }) => (
              <button
                key={`req-${item.order_id}`}
                type="button"
                className={cx(
                  "min-w-[180px] shrink-0 rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-left transition-colors",
                  selKind === "order" && selId === item.order_id
                    ? "bg-[var(--bg-elevated)]"
                    : "hover:bg-[var(--bg-elevated)]",
                )}
                onClick={() => {
                  setSelKind("order");
                  setSelId(item.order_id);
                  setSide(orderSide(item));
                  setStatusTab(statusBucket(item.status));
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[13px] font-medium">#{item.order_id}</span>
                  <span className="font-mono text-[12px]">{money(item.fiat_amount)} ₽</span>
                </div>
                <div className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">
                  {operatorLabel(item)} · {fmtExpires(item.expires_at)}
                </div>
              </button>
            ))}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-4 max-lg:grid-cols-1">
        {/* LEFT: unified list */}
        <div className="flex flex-col gap-4">
        <Card className="p-0">
          <div className="grid grid-cols-2 gap-1 border-b border-[var(--border)] p-2" role="tablist" aria-label="Направление заявки">
            {(
              [
                ["buy", "Покупка крипты", buyCount, incomingBuy],
                ["sell", "Продажа крипты", sellCount, incomingSell],
              ] as const
            ).map(([id, title, count, fresh]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={side === id}
                onClick={() => {
                  sideTouched.current = true;
                  setSide(id);
                }}
                className={cx(
                  "flex items-center justify-between gap-2 rounded-[var(--radius)] px-3 py-2.5 text-left transition-colors",
                  side === id
                    ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
                )}
              >
                <span className="text-[13px] font-semibold">{title}</span>
                <span className="flex items-center gap-1.5">
                  {fresh > 0 && (
                    <Badge tone="yellow">{fresh} нов.</Badge>
                  )}
                  <Badge tone={side === id ? "blue" : "default"}>{count}</Badge>
                </span>
              </button>
            ))}
          </div>
          <div className="grid grid-cols-5 gap-1 border-b border-[var(--border)] p-2 max-md:grid-cols-3 max-[520px]:grid-cols-2" role="tablist" aria-label="Статус заявки">
            {STATUS_BUCKETS.map((bucket) => {
              const count = bucketCounts[bucket.id];
              const active = statusTab === bucket.id;
              return (
                <button
                  key={bucket.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => {
                    statusTouched.current = true;
                    setStatusTab(bucket.id);
                  }}
                  className={cx(
                    "rounded-[var(--radius)] px-2 py-2 text-left text-[12px] font-semibold transition-colors",
                    active ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
                  )}
                >
                  {bucket.title} <span className="text-[var(--text-muted)]">{count}</span>
                </button>
              );
            })}
          </div>
          <div className="max-h-[calc(100dvh-200px)] overflow-y-auto">
            {visible.length === 0 ? (
              <p className="p-8 text-center text-[13px] text-[var(--text-muted)]">
                {loading
                  ? "Загрузка…"
                  : sideOrders.length === 0
                    ? side === "buy" ? "Покупок нет" : "Продаж нет"
                    : `Нет заявок · ${STATUS_BUCKETS.find((bucket) => bucket.id === statusTab)?.title ?? ""}`}
              </p>
            ) : (
              visible.map(({ group, item }) => (
                <div
                  key={item.order_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setSelKind("order");
                    setSelId(item.order_id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelKind("order");
                      setSelId(item.order_id);
                    }
                  }}
                  className={cx(
                    "flex w-full cursor-pointer items-center gap-3 border-b border-[var(--border)] px-4 py-3 text-left transition-colors last:border-0",
                    selKind === "order" && selId === item.order_id ? "bg-[var(--bg-elevated)]" : "hover:bg-[var(--bg-elevated)]",
                    shiftLocked && "opacity-60 grayscale-[.15]",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[13px] font-medium">#{item.order_id}</span>
                      <Badge tone={groupTone(group)}>{group}</Badge>
                      {item.source_label && <Badge tone="default">{item.source_label}</Badge>}
                    </div>
                    <div className="mt-0.5 truncate text-[12px] text-[var(--text-muted)]">
                      {item.direction === "buy" ? "Покупка" : "Продажа"} {String(item.crypto).toUpperCase()}
                      {" · "}
                      <OpsClientLink userId={item.user_id}>
                        {item.buyer_first_name || item.buyer_username || `ID ${item.user_id ?? "—"}`}
                      </OpsClientLink>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-[13px]">{money(item.fiat_amount)} ₽</div>
                    <Badge tone={orderStatusTone(item.status)}>{item.status_label || statusLabel(item.status)}</Badge>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>

        {allWd.length > 0 && (
          <Card className="p-0">
            <div className="border-b border-[var(--border)] px-4 py-3 text-[13.5px] font-semibold">
              Выводы средств · {allWd.length}
            </div>
            <div className="max-h-[calc(100dvh-200px)] overflow-y-auto">
              {allWd.map(({ group, item }) => {
                const id = String(item.id);
                const isCrypto = String(item.method ?? "") === "crypto";
                const cryptoAmt = Number(item.payout_crypto_amount);
                const hasCrypto = isCrypto && Number.isFinite(cryptoAmt) && cryptoAmt > 0;
                const coin = withdrawalCryptoLabel(item);
                return (
                  <div
                    key={`${group}-${id}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      setSelKind("wd");
                      setSelId(id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelKind("wd");
                        setSelId(id);
                      }
                    }}
                    className={cx(
                      "flex w-full cursor-pointer items-center gap-3 border-b border-[var(--border)] px-4 py-3 text-left transition-colors last:border-0",
                      selKind === "wd" && selId === id ? "bg-[var(--bg-elevated)]" : "hover:bg-[var(--bg-elevated)]",
                      shiftLocked && "opacity-60 grayscale-[.15]",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[13px] font-medium">#{id}</span>
                        <Badge tone={group === "Входящие" ? "blue" : group === "Мои" ? "yellow" : "default"}>{group}</Badge>
                      </div>
                      <div className="mt-0.5 truncate text-[12px] text-[var(--text-muted)]">
                        {coin}
                        {" · "}
                        <OpsClientLink userId={withdrawalUserId(item)}>{withdrawalClientName(item)}</OpsClientLink>
                      </div>
                      {String(item.triangle_label || "") ? (
                        <div className="mt-0.5 text-[12px] text-[var(--text-secondary)]">{String(item.triangle_label)}</div>
                      ) : null}
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[13px]">
                        {hasCrypto ? `${crypto(cryptoAmt)} ${coin}` : `${money(withdrawalPayoutRub(item))} ₽`}
                      </div>
                      {!hasCrypto ? (
                        <Badge tone="default">{coin}</Badge>
                      ) : (
                        <div className="text-[11px] text-[var(--text-muted)]">{money(withdrawalPayoutRub(item))} ₽</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        )}
        </div>

        {/* RIGHT: detail + actions */}
        <div className="max-lg:order-first">
          {selected ? (
            <OrderPanel order={selected} shiftOpen={shiftLoaded && shiftOpen} onChanged={load} isFinance={isFinance} canConfirmPayin={canConfirmPayin} currentOperatorId={me?.operator?.id} />
          ) : selectedWd ? (
            <WithdrawalPanel
              w={selectedWd.item}
              group={selectedWd.group}
              shiftOpen={shiftLoaded && shiftOpen}
              onChanged={load}
              isFinance={isFinance}
              canTransfer={Number(selectedWd.item.operator_id) === me?.operator?.id}
            />
          ) : (
            <Card>
              <p className="py-12 text-center text-[13px] text-[var(--text-muted)]">Выберите заявку или вывод</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function fmtCountdown(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

function WalletConfirmTimerBlock({
  orderId,
  ops,
  actionDisabled,
  shiftOpen,
  onSendEarly,
}: {
  orderId: string;
  ops: NonNullable<OrderRow["wallet_confirm_ops"]>;
  actionDisabled: boolean;
  shiftOpen: boolean;
  onSendEarly: () => void;
}) {
  const stage = String(ops.stage || "");
  const [secondsLeft, setSecondsLeft] = useState<number>(() => Math.max(0, Number(ops.seconds_left ?? 0)));

  useEffect(() => {
    if (stage !== "waiting_timer") {
      setSecondsLeft(0);
      return;
    }
    const sendAtMs = ops.send_at ? Date.parse(String(ops.send_at)) : NaN;
    const calc = () => {
      if (Number.isFinite(sendAtMs)) {
        return Math.max(0, Math.ceil((sendAtMs - Date.now()) / 1000));
      }
      return Math.max(0, Number(ops.seconds_left ?? 0));
    };
    setSecondsLeft(calc());
    const id = window.setInterval(() => {
      setSecondsLeft((prev) => {
        if (Number.isFinite(sendAtMs)) {
          return Math.max(0, Math.ceil((sendAtMs - Date.now()) / 1000));
        }
        return Math.max(0, prev - 1);
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [orderId, stage, ops.send_at, ops.seconds_left]);

  if (stage === "confirmed") {
    return (
      <div
        className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12.5px]"
        data-wallet-confirm-ops="confirmed"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium">Payfast подтвердил · Кошелёк подтверждён</span>
          <Badge tone="green">Подтверждён</Badge>
        </div>
        <div className="mt-1 text-[12px] text-[var(--text-muted)]">
          Покупатель подтвердил адрес получения {ops.coin ? `(${ops.coin})` : ""}.
        </div>
      </div>
    );
  }

  if (stage === "asked") {
    return (
      <div
        className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12.5px]"
        data-wallet-confirm-ops="asked"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium">Payfast подтвердил · Запрос кошелька отправлен</span>
          <Badge tone="yellow">Ждём ответ клиента</Badge>
        </div>
        <div className="mt-1 text-[12px] text-[var(--text-muted)]">
          Покупателю отправлен запрос уточнения кошелька. Ожидаем подтверждение адреса перед выплатой.
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex flex-col gap-2.5 rounded-[var(--radius)] border border-[var(--yellow)]/40 bg-[var(--yellow-bg)] p-3 text-[12.5px]"
      data-wallet-confirm-ops="waiting_timer"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">Payfast подтвердил оплату</span>
        <Badge tone="yellow">
          {secondsLeft > 0 ? `Таймер ${fmtCountdown(secondsLeft)}` : "Отправка запроса…"}
        </Badge>
      </div>
      <div className="text-[12px] text-[var(--text-secondary)]">
        {secondsLeft > 0
          ? `Через ${fmtCountdown(secondsLeft)} (5 минут после подтверждения Payfast) покупателю автоматически придёт запрос уточнения кошелька.`
          : "5 минут истекли — запрос уточнения кошелька отправляется покупателю."}
      </div>
      <div>
        <Button
          size="sm"
          variant="primary"
          disabled={actionDisabled}
          title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
          onClick={onSendEarly}
        >
          Убрать таймер · Отправить досрочно
        </Button>
      </div>
    </div>
  );
}

function OrderPanel({ order, shiftOpen, onChanged, isFinance, canConfirmPayin, currentOperatorId }: { order: Item; shiftOpen: boolean; onChanged: () => void; isFinance: boolean; canConfirmPayin: boolean; currentOperatorId?: number }) {
  const [busy, setBusy] = useState(false);
  const [tx, setTx] = useState("");
  const [reason, setReason] = useState("");
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [walletMode, setWalletMode] = useState<WalletPayoutMode | null>(null);
  const [walletSendOpen, setWalletSendOpen] = useState(false);
  useEffect(() => {
    if (!isFinance) return;
    getPayoutWalletMode()
      .then(setWalletMode)
      .catch(() => setWalletMode(null));
  }, [isFinance]);
  // Prefill hash saved at create time so a timed-out finalize does not force re-entry.
  useEffect(() => {
    setTx(String(order.payout_tx_hash ?? "").trim());
    setReason(order.status === "OPERATOR_PENDING" ? OPERATOR_PENDING_CANCEL_REASON : "");
  }, [order.order_id, order.payout_tx_hash, order.status]);

  const userId = opsClientId(order.user_id);
  useEffect(() => {
    if (userId == null) {
      setProfile(null);
      return;
    }
    let alive = true;
    getUser(userId)
      .then((row) => {
        if (alive) setProfile(asDict(row));
      })
      .catch(() => {
        if (alive) setProfile(null);
      });
    return () => {
      alive = false;
    };
  }, [userId, order.order_id]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      if (userId != null) {
        try {
          setProfile(asDict(await getUser(userId)));
        } catch {
          /* keep previous snapshot */
        }
      }
      onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка операции");
    } finally {
      setBusy(false);
    }
  }

  const isBuy = order.direction === "buy";
  const projectWallet =
    walletMode?.mode === "project" && walletMode.coins.includes(String(order.crypto ?? "").split("_")[0].toLowerCase());
  const canProjectSend =
    isFinance && isBuy && projectWallet && (order.status === "COMPLETED" || order.status === "OPERATOR_PENDING");
  const claimable = !order.operator_id && ["PENDING", "COMPLETED", "OPERATOR_PENDING"].includes(order.status);
  const financeOnlyBuy = isBuy && ["COMPLETED", "OPERATOR_PENDING"].includes(order.status);
  const canClaim = claimable && (!financeOnlyBuy || isFinance);
  const canTransfer = !isFinance
    && currentOperatorId != null
    && Number(order.operator_id) === currentOperatorId
    && ["PENDING", "COMPLETED", "OPERATOR_PENDING"].includes(order.status);
  const actionDisabled = busy || !shiftOpen;
  const receiptHref = order.has_receipt ? orderReceiptUrl(order.order_id) : null;
  const identity = asDict(profile?.identity);
  const summary = asDict(profile?.summary);
  const lastDeal = asDict(profile?.last_deal);
  const reviewStatus = String(identity.account_review_status ?? "none");
  const paidCount = Number(summary.paid_orders ?? 0);
  const buyConv = summary.buy_conversion_pct;
  const canRequestVideo = isBuy && !["PAID", "FAILED"].includes(String(order.status || "").toUpperCase());
  const payfastId = isBuy && !order.payin_requisite_id
    ? String(
      order.payfast_id
        || asDict(order.payment_summary).merchant_uuid
        || "",
    ).trim()
    : "";
  const canSendReceipt =
    order.can_send_receipt_to_payfast === true
    || (
      isBuy
      && String(order.status || "").toUpperCase() === "AWAITING_CHECK"
      && Boolean(order.has_receipt)
      && !order.payin_requisite_id
      && Number(order.required_receipt_type || 2) !== 3
      && order.receipt_ops_pending === true
    );

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-mono text-[15px] font-semibold">#{order.order_id}</span>
          {payfastId ? <PayfastIdChip value={payfastId} /> : null}
        </div>
        <Badge tone={orderStatusTone(order.status)}>{order.status_label || statusLabel(order.status)}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[13px]">
        <Mini label="Тип" value={isBuy ? "Покупка" : "Продажа"} />
        <Mini label="Актив" value={`${String(order.crypto).toUpperCase()}${order.network ? " · " + order.network : ""}`} mono />
        <Mini label="Сумма ₽" value={money(order.fiat_amount)} mono />
        <Mini label="Крипта" value={crypto(order.crypto_amount)} mono />
        <Mini label="Курс" value={money(order.rate)} mono />
        <Mini
          label="Клиент"
          value={
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <OpsClientLink userId={order.user_id}>
                {order.buyer_first_name || order.buyer_username || `ID ${order.user_id ?? "—"}`}
              </OpsClientLink>
              {opsClientId(order.user_id) != null ? (
                <OpsClientLink userId={order.user_id} className="text-[12px] text-[var(--blue)] underline-offset-2 hover:underline">
                  Профиль →
                </OpsClientLink>
              ) : null}
            </span>
          }
        />
        <Mini label="Источник" value={String(order.source_label ?? order.order_source ?? "manual")} />
        {order.operator_id != null ? <Mini label="Оператор" value={operatorLabel(order)} /> : null}
        {order.expires_at ? <Mini label="Окно" value={fmtExpires(order.expires_at)} /> : null}
      </div>

      <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[12.5px]" data-order-stat="">
        <div className="mb-2 text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Сводка клиента</div>
        <div className="grid grid-cols-2 gap-2">
          <Mini label="Оплачено" value={profile ? String(paidCount) : "…"} mono />
          <Mini label="Уровень" value={profile ? String(summary.trust_level || trustLabel(paidCount)) : "…"} />
          <Mini label="Последняя оплата" value={profile ? relativeWhen(summary.last_paid_at || lastDeal.created_at) : "…"} />
          <Mini
            label="Конверсия BUY"
            value={
              profile
                ? buyConv == null
                  ? "—"
                  : `${buyConv}% (${Number(summary.buy_paid ?? 0)}/${Number(summary.buy_paid ?? 0) + Number(summary.buy_failed ?? 0)})`
                : "…"
            }
          />
          <Mini
            label="Всего / оплачено / отмен"
            value={
              profile
                ? `${summary.total_orders ?? 0} / ${paidCount} / ${summary.canceled_orders ?? summary.buy_failed ?? 0}`
                : "…"
            }
            mono
          />
          <Mini label="Оборот, ₽" value={profile ? money(summary.turnover_rub) : "…"} mono />
          <Mini label="С нами с" value={profile ? fmtDay(summary.first_order_at || identity.first_seen_at) : "…"} />
        </div>
      </div>

      {reviewStatus === "pending" && userId != null && (
        <div className="flex flex-col gap-2 rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] p-3">
          <div className="text-[12.5px] text-[var(--yellow)]">Проверка аккаунта: ждёт решения</div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={actionDisabled}
              onClick={() => run(() => reviewAccount(userId, "approve"), "Аккаунт одобрен")}
            >
              Одобрить
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={actionDisabled}
              onClick={() => {
                if (!window.confirm("Отклонить проверку и заблокировать клиента?")) return;
                void run(() => reviewAccount(userId, "reject"), "Аккаунт отклонён");
              }}
            >
              Отклонить
            </Button>
          </div>
        </div>
      )}

      {/* copy-able values */}
      <div className="flex flex-col gap-2">
        {order.requisites && <CopyField label="Реквизиты" value={String(order.requisites)} />}
        {order.wallet_address && <CopyField label="Кошелёк клиента" value={String(order.wallet_address)} />}
        <CopyField label="Сумма к переводу, ₽" value={String(order.fiat_amount ?? "")} />
        <CopyField label="Крипта" value={crypto(order.crypto_amount)} />
      </div>

      {receiptHref && (
        <a href={receiptHref} target="_blank" rel="noreferrer" className="text-[13px] text-[var(--blue)] underline-offset-4 hover:underline">
          Открыть чек клиента →
        </a>
      )}

      {/* actions */}
      <div className="flex flex-col gap-3 border-t border-[var(--border)] pt-4">
        {order.wallet_confirm_ops && (
          <WalletConfirmTimerBlock
            orderId={order.order_id}
            ops={order.wallet_confirm_ops}
            actionDisabled={actionDisabled}
            shiftOpen={shiftOpen}
            onSendEarly={() =>
              run(
                () => sendOrderWalletConfirmEarly(order.order_id),
                "Таймер снят — запрос уточнения кошелька отправлен покупателю",
              )
            }
          />
        )}
        {canSendReceipt && (
          <div className="flex flex-col gap-2">
            <Button
              variant="primary"
              disabled={actionDisabled}
              title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
              onClick={() => run(() => sendOrderReceiptToPayfast(order.order_id), "Чек отправлен в Payfast")}
            >
              Отправить чек в Payfast
            </Button>
            <div className="text-[11px] text-[var(--text-muted)]">
              PDF уйдёт трейдерам. Если Payfast уже подтвердил оплату — заявка снимется с проверки.
            </div>
          </div>
        )}
        {canClaim && (
          <Button
            variant="primary"
            disabled={actionDisabled}
            title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
            onClick={() => run(() => claimOrder(order.order_id), "Заявка взята")}
          >
            Взять в работу
          </Button>
        )}
        {claimable && !canClaim && financeOnlyBuy && (
          <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[12px] text-[var(--text-muted)]">
            Заявку принимает только финансовый оператор.
          </div>
        )}

        {canRequestVideo && (
          <Button
            variant="secondary"
            disabled={actionDisabled}
            title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
            onClick={() => run(() => requestOrderVideo(order.order_id), "Запрошено видео")}
          >
            Запросить видео
          </Button>
        )}

        {canProjectSend && (
          <Button
            variant="primary"
            disabled={actionDisabled}
            title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
            onClick={() => setWalletSendOpen(true)}
          >
            Отправить {String(order.crypto ?? "").toUpperCase()} с кошелька проекта
          </Button>
        )}
        {walletSendOpen && (
          <ProjectWalletSendModal
            open
            onClose={() => setWalletSendOpen(false)}
            loadPreview={() => previewOrderWalletSend(order.order_id)}
            send={(body) => sendOrderFromProjectWallet(order.order_id, body)}
            onDone={() => {
              toast.success("Крипта отправлена, заявка закрыта");
              onChanged();
            }}
          />
        )}

        {isBuy && order.status === "COMPLETED" && isFinance && (
          <div className="flex flex-col gap-2">
            <Field label="TX hash выплаты (вставьте)">
              <Input disabled={!shiftOpen} value={tx} onChange={(e) => setTx(e.target.value)} placeholder="hash транзакции" className="font-mono" />
            </Field>
            <Button variant="primary" disabled={actionDisabled || !tx.trim()} onClick={() => run(() => payoutOrder(order.order_id, tx.trim()), "Выплата отмечена")}>
              Подтвердить выплату
            </Button>
          </div>
        )}
        {canTransfer && (
          <Button variant="secondary" disabled={actionDisabled} onClick={() => run(() => transferOrderToFinance(order.order_id), "Заявка передана финансам")}>
            Передать финансовому оператору
          </Button>
        )}

        {isFinance && isBuy && order.status === "OPERATOR_PENDING" && (
          <div className="flex flex-col gap-2">
            <Field label={projectWallet ? "Или TX hash со своего кошелька" : "TX hash (вставьте)"}>
            <Input disabled={!shiftOpen} value={tx} onChange={(e) => setTx(e.target.value)} className="font-mono" placeholder="hash транзакции" />
            </Field>
            <Button variant="secondary" disabled={actionDisabled || !tx.trim()} onClick={() => run(() => markOrderPaid(order.order_id, tx.trim()), "Отмечено оплаченным")}>
              Отметить оплаченным
            </Button>
          </div>
        )}

        {!isFinance && canTransfer && (
          <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[12px] text-[var(--text-muted)]">
            Финансовые действия и выплата доступны только роли «Финансы».
          </div>
        )}

        {canConfirmPayin && isBuy && order.payin_requisite_id && ["PENDING", "AWAITING_CHECK"].includes(order.status) && (
          <div className="flex flex-col gap-2">
            <Button
              variant="primary"
              disabled={actionDisabled}
              onClick={() => run(() => confirmPayinFiatReceived(order.order_id), "Приход рублей подтверждён")}
            >
              Рубли получены
            </Button>
            <div className="text-[11px] text-[var(--text-muted)]">
              Клиент платил на карту реквизитчика. После подтверждения заявка уйдёт в выплату крипты.
            </div>
          </div>
        )}

        {isFinance && !isBuy && ["PENDING", "OPERATOR_PENDING", "AWAITING_CHECK"].includes(order.status) && (
          <SellPayoutRail
            order={order}
            actionDisabled={actionDisabled}
            onConfirmCrypto={() => run(() => confirmSellCryptoReceived(order.order_id), "Приход крипты подтверждён")}
            onDoliv={() => run(() => pushDolivPayout(order.order_id, { pay_method: "sbp" }), "SELL ушёл трейдерам Doliv")}
          />
        )}

        {order.hold_reason && (
          <Button
            variant="danger"
            disabled={actionDisabled}
            onClick={() => run(() => closeClientHold(order.order_id), "Заявка закрыта")}
          >
            Снять блокировку
          </Button>
        )}

        {["CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED", "OPERATOR_PENDING", "DISPUTE"].includes(order.status) && (
          <div className="flex flex-col gap-2">
            <Field label="Причина отмены">
              <Input disabled={!shiftOpen} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Минимум 3 символа" />
            </Field>
            <Button variant="danger" disabled={actionDisabled || reason.trim().length < 3} onClick={() => run(() => cancelOrder(order.order_id, reason.trim()), "Заявка отменена")}>
              Отменить заявку
            </Button>
          </div>
        )}

        <InitiateChatBlock orderId={order.order_id} disabled={busy} />
      </div>
    </Card>
  );
}

function InitiateChatBlock({ orderId, disabled }: { orderId: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  if (!open) {
    return (
      <Button variant="secondary" disabled={disabled} onClick={() => setOpen(true)}>
        Написать клиенту
      </Button>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3">
      <div className="text-[12px] text-[var(--text-muted)]">Первое сообщение создаст чат с клиентом. Клиент получит уведомление, чат откроется у него на сайте.</div>
      <Field label="Сообщение клиенту">
        <Input disabled={sending} value={text} onChange={(e) => setText(e.target.value)} placeholder="Здравствуйте! …" />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={sending || disabled || text.trim().length < 1}
          onClick={() => {
            setSending(true);
            initiateChat("operator", orderId, text.trim())
              .then((r) => {
                toast.success("Чат создан, клиент уведомлён");
                setOpen(false);
                setText("");
                const tid = (r as { thread?: { id?: number } })?.thread?.id;
                if (tid) window.location.href = `/ops/chat?thread=${tid}`;
              })
              .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось создать чат"))
              .finally(() => setSending(false));
          }}
        >
          {sending ? "Отправка…" : "Отправить и открыть чат"}
        </Button>
        <Button variant="secondary" disabled={sending} onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>
    </div>
  );
}

function sellPayoutStage(order: Item): string {
  const rail = order.payout_rail;
  if (rail?.stage) return String(rail.stage);
  if (order.status === "PAID" || rail?.client_confirmed) return "closed";
  if (rail?.allocation_status === "PAID") return "paid_awaiting_client";
  if (rail?.allocation_status === "RESERVED") return "reserved";
  if (order.crypto_confirmed_at) return "awaiting_funding";
  return "awaiting_crypto";
}

function SellPayoutRail({
  order,
  actionDisabled,
  onConfirmCrypto,
  onDoliv,
}: {
  order: Item;
  actionDisabled: boolean;
  onConfirmCrypto: () => void;
  onDoliv: () => void;
}) {
  const stage = sellPayoutStage(order);
  const cryptoAmt = crypto(order.crypto_amount);
  const coin = String(order.crypto || "").toUpperCase() || "CRYPTO";
  return (
    <div className="flex flex-col gap-3">
      {stage === "awaiting_crypto" ? (
        <>
          <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-3">
            <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Клиент должен прислать</div>
            <div className="mt-1 font-mono text-[20px] font-semibold tabular-nums">
              {cryptoAmt} {coin}
            </div>
            <div className="mt-1 text-[13px] text-[var(--text-muted)]">
              За продажу {money(order.fiat_amount)} ₽. После прихода нажмите «Оплата получена» — реквизиты продавца уйдут в приём.
            </div>
            <div className="mt-2">
              <CopyField label={`${coin}`} value={String(order.crypto_amount ?? "")} />
            </div>
          </div>
          <Button variant="primary" disabled={actionDisabled} onClick={onConfirmCrypto}>
            Оплата получена
          </Button>
        </>
      ) : null}
      {stage === "awaiting_funding" ? (
        <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] leading-5">
          <div className="font-medium text-[var(--text-primary)]">Активный реквизит</div>
          <div className="mt-1 text-[var(--text-muted)]">
            Крипта подтверждена. Карта продавца в приёме — покупки платят на неё.
          </div>
          <Link
            to="/ops/payout-requisites"
            className="mt-2 inline-block text-[12px] text-[var(--blue)] underline-offset-4 hover:underline"
          >
            Открыть Реквизиты →
          </Link>
        </div>
      ) : null}
      {stage === "reserved" ? (
        <div className="rounded-[var(--radius)] bg-[var(--yellow-bg)] px-3 py-2 text-[12px] text-[var(--yellow)]">
          Карта взяла заявку — ждём перевод
        </div>
      ) : null}
      {stage === "paid_awaiting_client" ? (
        <div className="rounded-[var(--radius)] bg-[var(--green-bg)] px-3 py-2 text-[12px] text-[var(--green)]">
          Оплата произведена — ждём подтверждение клиента
        </div>
      ) : null}
      {stage === "closed" ? (
        <div className="rounded-[var(--radius)] bg-[var(--green-bg)] px-3 py-2 text-[12px] text-[var(--green)]">
          Клиент подтвердил получение — заявка закрыта
        </div>
      ) : null}
      {stage !== "awaiting_crypto" && stage !== "awaiting_funding" ? (
        <Link
          to="/ops/payout-requisites"
          className="text-[12px] text-[var(--blue)] underline-offset-4 hover:underline"
        >
          Чек и выплата на Реквизитах →
        </Link>
      ) : null}
      {stage === "awaiting_funding" || stage === "awaiting_crypto" ? (
        <Button variant="secondary" disabled={actionDisabled} onClick={onDoliv}>
          Отправить выплату трейдерам Doliv
        </Button>
      ) : null}
    </div>
  );
}

function WithdrawalPanel({
  w,
  group,
  shiftOpen,
  onChanged,
  isFinance,
  canTransfer = false,
}: {
  w: Record<string, unknown>;
  group: string;
  shiftOpen: boolean;
  onChanged: () => void;
  isFinance: boolean;
  canTransfer?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [tx, setTx] = useState("");
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const id = String(w.id);
  const method = String(w.method ?? "");
  const claimed = w.operator_id != null;
  const isCrypto = method === "crypto";
  const readOnly = group === "Команда";
  const coin = withdrawalCryptoLabel(w);
  const cryptoAmt = Number(w.payout_crypto_amount);
  const hasCrypto = isCrypto && Number.isFinite(cryptoAmt) && cryptoAmt > 0;
  const payoutRub = withdrawalPayoutRub(w);
  const fee = Number(w.network_fee_rub ?? 0);
  const userId = withdrawalUserId(w);
  const actionDisabled = busy || !shiftOpen;
  const summary = asDict(profile?.summary);
  const referral = asDict(profile?.referral);
  const balances = asDict(profile?.balances);

  useEffect(() => {
    setTx("");
  }, [id]);

  useEffect(() => {
    if (userId == null) {
      setProfile(null);
      return;
    }
    let alive = true;
    getUser(userId)
      .then((row) => {
        if (alive) setProfile(asDict(row));
      })
      .catch(() => {
        if (alive) setProfile(null);
      });
    return () => {
      alive = false;
    };
  }, [userId]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[15px] font-semibold">#{id}</span>
        <Badge tone={claimed ? "yellow" : "blue"}>{coin}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[13px]">
        <Mini label="Списано ₽" value={money(w.amount_rub)} mono />
        <Mini label="Комиссия сети ₽" value={money(fee)} mono />
        <Mini label="К выплате ₽" value={money(payoutRub)} mono />
        <Mini label="Метод" value={coin} />
        {hasCrypto ? <Mini label="К отправке" value={`${crypto(cryptoAmt)} ${coin}`} mono /> : null}
        {hasCrypto && w.rate_rub != null ? <Mini label="Курс" value={`${money(w.rate_rub)} ₽`} mono /> : null}
        <Mini
          label="Клиент"
          value={
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <OpsClientLink userId={userId}>{withdrawalClientName(w)}</OpsClientLink>
              {userId != null ? (
                <OpsClientLink userId={userId} className="text-[12px] text-[var(--blue)] underline-offset-2 hover:underline">
                  Профиль →
                </OpsClientLink>
              ) : null}
            </span>
          }
        />
        <Mini label="Заявок" value={String(summary.total_orders ?? "—")} mono />
        <Mini label="Оплачено" value={String(summary.paid_orders ?? "—")} mono />
        <Mini label="Оборот, ₽" value={profile ? money(summary.turnover_rub) : "—"} mono />
        <Mini label="Привёл" value={String(referral.referred_count ?? "—")} mono />
        <Mini label="Оплаченных у рефов" value={String(referral.paid_orders_count ?? "—")} mono />
        <Mini label="Баланс, ₽" value={profile ? money(balances.available_rub ?? balances.balance_rub) : "—"} mono />
      </div>

      {hasCrypto ? <CopyField label={`К отправке, ${coin}`} value={crypto(cryptoAmt)} /> : null}
      <CopyField label="К выплате, ₽" value={String(payoutRub)} />
      <CopyField label={isCrypto ? "Адрес кошелька" : "Реквизиты"} value={String(w.requisites ?? "")} />
      {String(w.triangle_label || "") ? (
        <div className="text-[13px]">
          <span>{String(w.triangle_label)}</span>
          {String(w.triangle_label).startsWith("В приёме") || String(w.triangle_label) === "Ждёт включения" ? (
            <Link to="/ops/payout-requisites" className="ml-2 text-[var(--blue)] underline-offset-2 hover:underline">
              Открыть приём
            </Link>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-3 border-t border-[var(--border)] pt-4">
        {readOnly ? (
          <div className="text-[12px] text-[var(--text-muted)]">
            В работе у {String((w.assigned_operator as Record<string, unknown> | undefined)?.display_name ?? "другого оператора")}
          </div>
        ) : !claimed && isFinance ? (
          <Button
            variant="primary"
            disabled={actionDisabled}
            title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
            onClick={() => run(() => claimWithdrawal(id), "Взято в работу")}
          >
            Взять в работу
          </Button>
        ) : !claimed ? (
          <div className="text-[12px] text-[var(--text-muted)]">Доступно финансовому оператору.</div>
        ) : null}
        {!readOnly && !isFinance && canTransfer ? (
          <Button variant="secondary" disabled={actionDisabled} onClick={() => run(() => transferWithdrawalToFinance(id), "Вывод передан финансам")}>
            Передать финансовому оператору
          </Button>
        ) : null}
        {!readOnly && isFinance && claimed && isCrypto ? (
          <div className="flex flex-col gap-2">
            <Field label="TX hash выплаты (вставьте)">
              <Input disabled={!shiftOpen} value={tx} onChange={(e) => setTx(e.target.value)} placeholder="hash транзакции" className="font-mono" />
            </Field>
            <Button variant="primary" disabled={actionDisabled || !tx.trim()} onClick={() => run(() => payoutWithdrawal(id, tx.trim()), "Выплата отмечена")}>
              Подтвердить выплату
            </Button>
          </div>
        ) : null}
        {!readOnly && isFinance && claimed && !isCrypto ? (
          <Button variant="primary" disabled={actionDisabled} onClick={() => run(() => paidWithdrawal(id), "Отмечено оплаченным")}>
            Отметить оплаченным
          </Button>
        ) : null}
        {!readOnly && isFinance ? (
          <Button
            variant="danger"
            disabled={actionDisabled}
            title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
            onClick={() => {
              if (!window.confirm(`Отменить вывод #${id}? Деньги останутся на балансе клиента.`)) return;
              void run(() => cancelWithdrawal(id), "Вывод отменён");
            }}
          >
            Отменить
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

function PayfastIdChip({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      title="Скопировать Payfast ID"
      onClick={() => {
        navigator.clipboard?.writeText(value).then(
          () => {
            setDone(true);
            toast.success("Payfast ID скопирован");
            window.setTimeout(() => setDone(false), 1200);
          },
          () => toast.error("Не удалось скопировать"),
        );
      }}
      className="inline-flex min-w-0 max-w-full flex-wrap items-baseline gap-x-1.5 rounded-[var(--radius)] border border-[var(--green)]/30 bg-[var(--green-bg)] px-2 py-0.5 text-left transition-colors hover:bg-[var(--green)]/15"
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--green)]">Payfast</span>
      <span className="break-all font-mono text-[13px] font-semibold text-[var(--green)]">{value}</span>
      {done ? (
        <Check className="size-3.5 shrink-0 text-[var(--green)]" />
      ) : (
        <Copy className="size-3.5 shrink-0 text-[var(--green)]/70" />
      )}
    </button>
  );
}

function Mini({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={cx("mt-0.5 break-words text-[13px]", mono && "font-mono")}>{value}</div>
    </div>
  );
}
