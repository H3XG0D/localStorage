import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { OpsClientLink, opsClientId } from "@/panel/lib/opsClientPath";
import {
  fetchOperatorOrderReceiptBlob,
  getOrderHistory,
  getOrderHistoryItem,
  orderReceiptUrl,
  type HistoryPartnerOption,
  type OrderRow,
} from "@/panel/lib/operatorApi";
import { panelMe } from "@/panel/lib/panelAuth";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import { BuyerAvatar } from "@/panel/ui/BuyerAvatar";
import { CopyField } from "@/panel/ui/CopyField";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Select, Table, cx, type Column } from "@/panel/ui/primitives";

function fmtMoney(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}
function fmtCrypto(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 8 }).format(Number(v ?? 0));
}
function fmtDate(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU");
}
function buyerName(o: OrderRow) {
  return (o.buyer_first_name as string) || o.buyer_username || `ID ${o.user_id ?? "—"}`;
}
function referrerName(o: OrderRow) {
  if (o.referrer_first_name) return String(o.referrer_first_name);
  if (o.referrer_username) return String(o.referrer_username);
  if (o.referrer_user_id) return `ID ${o.referrer_user_id}`;
  return "—";
}
function ageSince(value: unknown) {
  const time = new Date(String(value ?? "")).getTime();
  if (!Number.isFinite(time)) return "—";
  const minutes = Math.max(0, Math.floor((Date.now() - time) / 60000));
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч`;
  return `${Math.floor(hours / 24)} д`;
}
function isLive(order: OrderRow) {
  if (order.in_live_queue === true) return true;
  return ["CREATED", "AWAITING_CHECK", "PENDING", "OPERATOR_PENDING", "DISPUTE", "COMPLETED"].includes(
    String(order.status),
  );
}

function DealBubble({ order }: { order: OrderRow }) {
  const tone = orderStatusTone(order.status);
  const status = order.status_label || statusLabel(order.status);
  return (
    <Badge tone={tone} className="max-w-full gap-1.5 whitespace-normal px-2.5 py-1 font-medium leading-tight">
      <span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span>
          <span className="opacity-70">оборот </span>
          <span className="font-mono font-semibold">{fmtMoney(order.fiat_amount)} ₽</span>
        </span>
        <span className="opacity-40" aria-hidden>
          ·
        </span>
        <span className="font-semibold">{status}</span>
      </span>
    </Badge>
  );
}

function BuyerCell({ order }: { order: OrderRow }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <BuyerAvatar
        avatarUrl={typeof order.buyer_avatar_url === "string" ? order.buyer_avatar_url : null}
        name={typeof order.buyer_first_name === "string" ? order.buyer_first_name : null}
        username={typeof order.buyer_username === "string" ? order.buyer_username : null}
        userId={typeof order.user_id === "number" ? order.user_id : null}
        size="sm"
      />
      <OpsClientLink userId={order.user_id}>{buyerName(order)}</OpsClientLink>
    </span>
  );
}

function ReferrerCell({ order }: { order: OrderRow }) {
  const id = opsClientId(order.referrer_user_id);
  if (id == null) return <span>—</span>;
  return <OpsClientLink userId={id}>{referrerName(order)}</OpsClientLink>;
}

const STATUS_KPI: { status: string; label: string }[] = [
  { status: "all", label: "Всего" },
  { status: "AWAITING_CHECK", label: "Чеки" },
  { status: "PENDING", label: "На проверке" },
  { status: "CREATED", label: "Новые" },
  { status: "DISPUTE", label: "Споры" },
  { status: "PAID", label: "Оплачено" },
  { status: "CANCELED", label: "Отменено" },
  { status: "EXPIRED", label: "Истекло" },
];
const DIRECTION_OPTIONS = [
  { value: "all", label: "Все" },
  { value: "buy", label: "Покупка" },
  { value: "sell", label: "Продажа" },
];
const CRYPTO_OPTIONS = ["all", "usdt", "btc", "trx", "ltc"];
const ORIGIN_OPTIONS = [
  { value: "all", label: "Все" },
  { value: "manual", label: "Ручные" },
  { value: "auto", label: "Авто" },
];
const LIMIT = 50;

export function OperatorOrderHistory() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const queryOrder = (searchParams.get("order") || "").trim();
  const [status, setStatus] = useState("all");
  const [direction, setDirection] = useState("all");
  const [crypto, setCrypto] = useState("all");
  const [origin, setOrigin] = useState("all");
  const [partnerId, setPartnerId] = useState("all");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<OrderRow[]>([]);
  const [partnerOptions, setPartnerOptions] = useState<HistoryPartnerOption[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<OrderRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    panelMe("operator")
      .then((me) => {
        if (!cancelled) {
          const perms = Array.isArray(me.permissions) ? me.permissions.map(String) : [];
          setAllowed(perms.includes("orders.history"));
        }
      })
      .catch(() => {
        if (!cancelled) setAllowed(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const baseQuery = useCallback(() => {
    const q: Record<string, unknown> = {};
    if (direction !== "all") q.direction = direction;
    if (crypto !== "all") q.crypto = crypto;
    if (origin !== "all") q.origin = origin;
    if (partnerId !== "all") q.partner_id = Number(partnerId);
    return q;
  }, [direction, crypto, origin, partnerId]);

  const load = useCallback(() => {
    setLoading(true);
    const q: Record<string, unknown> = { ...baseQuery(), limit: LIMIT, offset };
    if (status !== "all") q.status = status;
    const needle = search.trim();
    if (needle) q.search = needle;
    getOrderHistory(q)
      .then((d) => {
        setRows(d.orders ?? []);
        setTotal(d.total ?? 0);
        if (d.counts) setCounts(d.counts);
        if (Array.isArray(d.partner_options)) setPartnerOptions(d.partner_options);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [baseQuery, status, search, offset]);

  useEffect(() => {
    if (allowed !== true) return;
    load();
  }, [allowed, load]);

  useEffect(() => {
    if (allowed !== true || !queryOrder) return;
    let cancelled = false;
    getOrderHistoryItem(queryOrder)
      .then((d) => {
        if (!cancelled) setSelected(d);
      })
      .catch((e) => {
        if (!cancelled) toast.error(e instanceof PanelApiError ? e.message : "Заявка не найдена");
      });
    return () => {
      cancelled = true;
    };
  }, [allowed, queryOrder]);

  if (allowed === false) return <Navigate to="/ops" replace />;
  if (allowed !== true) {
    return <PageHeader title="История" subtitle="Проверяем доступ…" />;
  }

  function openOrder(row: OrderRow) {
    setSelected(row);
    setSearchParams({ order: row.order_id }, { replace: true });
  }

  function closeOrder() {
    setSelected(null);
    if (searchParams.get("order")) {
      const next = new URLSearchParams(searchParams);
      next.delete("order");
      setSearchParams(next, { replace: true });
    }
  }

  function applyFilters() {
    if (offset === 0) load();
    else setOffset(0);
  }

  const cols: Column<OrderRow>[] = [
    { key: "order_id", label: "#", width: "120px", render: (r) => <span className="font-mono">{r.order_id}</span> },
    { key: "buyer", label: "Клиент", render: (r) => <BuyerCell order={r} /> },
    { key: "referrer", label: "Реферер", render: (r) => <ReferrerCell order={r} /> },
    { key: "direction", label: "Тип", width: "80px", render: (r) => (r.direction === "buy" ? "Покупка" : "Продажа") },
    { key: "crypto", label: "Актив", width: "90px", render: (r) => <span className="font-mono">{String(r.crypto).toUpperCase()}</span> },
    { key: "deal", label: "Оборот / статус", render: (r) => <DealBubble order={r} /> },
    { key: "operator_name", label: "Оператор", render: (r) => String(r.operator_name || "—") },
    {
      key: "age",
      label: "Возраст",
      width: "90px",
      render: (r) => <span className={cx("font-mono text-[12px]", isLive(r) && "text-[var(--yellow)]")}>{ageSince(r.created_at)}</span>,
    },
    { key: "source", label: "Канал", width: "110px", render: (r) => String(r.source_label ?? r.order_source ?? "—") },
  ];

  const page = Math.floor(offset / LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <div data-ops-order-history="">
      <PageHeader title="История" subtitle="Все заявки. Клик по KPI фильтрует по статусу" />

      <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        {STATUS_KPI.map((item) => (
          <Kpi
            key={item.status}
            label={item.label}
            value={counts[item.status] == null ? "—" : String(counts[item.status])}
            hint={item.status === "all" ? "все статусы" : statusLabel(item.status)}
            active={status === item.status}
            onClick={() => {
              setStatus(item.status);
              setOffset(0);
            }}
          />
        ))}
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          <Field label="Тип">
            <Select
              value={direction}
              onChange={(e) => {
                setDirection(e.target.value);
                setOffset(0);
              }}
            >
              {DIRECTION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Актив">
            <Select
              value={crypto}
              onChange={(e) => {
                setCrypto(e.target.value);
                setOffset(0);
              }}
            >
              {CRYPTO_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c === "all" ? "Все" : c.toUpperCase()}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Источник">
            <Select
              value={origin}
              onChange={(e) => {
                setOrigin(e.target.value);
                setOffset(0);
              }}
            >
              {ORIGIN_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Партнёры">
            <Select
              value={partnerId}
              onChange={(e) => {
                setPartnerId(e.target.value);
                setOffset(0);
              }}
            >
              <option value="all">Все</option>
              {partnerOptions.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Поиск">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applyFilters()}
              placeholder="ID / клиент"
            />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" onClick={applyFilters} className="w-full">
              Найти
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <div className="hidden md:block">
          <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет заявок"} onRowClick={openOrder} />
        </div>
        <div className="flex flex-col gap-2 md:hidden">
          {loading ? (
            <div className="py-10 text-center text-[12px] text-[var(--text-muted)]">Загрузка…</div>
          ) : rows.length === 0 ? (
            <div className="py-10 text-center text-[12px] text-[var(--text-muted)]">Нет заявок</div>
          ) : (
            rows.map((row) => <HistoryMobileRow key={row.order_id} order={row} onClick={() => openOrder(row)} />)
          )}
        </div>
        <div className="mt-4 flex items-center justify-between text-[12.5px] text-[var(--text-muted)]">
          <span>
            Всего: {total} · стр. {page}/{pages}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}>
              Назад
            </Button>
            <Button variant="secondary" size="sm" disabled={offset + LIMIT >= total} onClick={() => setOffset((o) => o + LIMIT)}>
              Вперёд
            </Button>
          </div>
        </div>
      </Card>

      {selected && <HistoryDetail key={selected.order_id} order={selected} onClose={closeOrder} />}
    </div>
  );
}

function HistoryMobileRow({ order, onClick }: { order: OrderRow; onClick: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      className="w-full cursor-pointer rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-left transition-colors hover:border-[var(--border-strong)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <BuyerAvatar
            avatarUrl={typeof order.buyer_avatar_url === "string" ? order.buyer_avatar_url : null}
            name={typeof order.buyer_first_name === "string" ? order.buyer_first_name : null}
            username={typeof order.buyer_username === "string" ? order.buyer_username : null}
            userId={typeof order.user_id === "number" ? order.user_id : null}
            size="md"
          />
          <div className="min-w-0">
            <div className="truncate font-mono text-[12px] text-[var(--text-secondary)]">#{order.order_id}</div>
            <div className="mt-1 truncate text-[13px] font-semibold">
              <OpsClientLink userId={order.user_id}>{buyerName(order)}</OpsClientLink>
            </div>
          </div>
        </div>
      </div>
      <div className="mt-3">
        <DealBubble order={order} />
      </div>
    </div>
  );
}

function HistoryDetail({ order, onClose }: { order: OrderRow; onClose: () => void }) {
  const [full, setFull] = useState<OrderRow>(order);

  useEffect(() => {
    getOrderHistoryItem(order.order_id)
      .then(setFull)
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"));
  }, [order.order_id]);

  const isBuy = full.direction === "buy";
  const wallet = String(full.wallet_address || "").trim();
  const requisites = String(full.requisites || "").trim();
  const walletShown = wallet || (isBuy ? requisites : "");
  const tx = typeof full.payout_tx_hash === "string" ? full.payout_tx_hash : "";

  return (
    <Modal
      open
      size="lg"
      title={`Заявка #${full.order_id}`}
      onClose={onClose}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          {isLive(full) ? (
            <Link to={`/ops/orders?order=${encodeURIComponent(full.order_id)}`} className="text-[13px] text-[var(--blue)] underline-offset-4 hover:underline">
              Открыть в очереди
            </Link>
          ) : (
            <span />
          )}
          <Button variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4" data-ops-order-history-detail="">
        <div className="flex items-center gap-3">
          <BuyerAvatar
            avatarUrl={typeof full.buyer_avatar_url === "string" ? full.buyer_avatar_url : null}
            name={typeof full.buyer_first_name === "string" ? full.buyer_first_name : null}
            username={typeof full.buyer_username === "string" ? full.buyer_username : null}
            userId={typeof full.user_id === "number" ? full.user_id : null}
            size="md"
          />
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Клиент</div>
            <div className="truncate text-[14px] font-semibold">
              <OpsClientLink userId={full.user_id}>{buyerName(full)}</OpsClientLink>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 text-[13px]">
          <Info label="Тип" value={isBuy ? "Покупка" : "Продажа"} />
          <Info label="Актив" value={`${String(full.crypto).toUpperCase()}${full.network ? " · " + full.network : ""}`} mono />
          <div className="col-span-2">
            <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Оборот / статус</div>
            <div className="mt-1">
              <DealBubble order={full} />
            </div>
          </div>
          <Info label="Крипта" value={fmtCrypto(full.crypto_amount)} mono />
          <Info label="Курс" value={fmtMoney(full.rate)} mono />
          <Info label="Реферер" value={<ReferrerCell order={full} />} />
          <Info label="Оператор" value={String(full.operator_name || "—")} />
          <Info label="Канал" value={String(full.source_label ?? full.order_source ?? "—")} />
          <Info label="Режим" value={String(full.origin ?? "—")} />
          <Info label="Создана" value={fmtDate(full.created_at)} />
        </div>
        {walletShown ? <CopyField label="Кошелёк" value={walletShown} /> : null}
        {requisites && requisites !== walletShown ? <CopyField label="Реквизиты" value={requisites} /> : null}
        {tx ? <CopyField label="Tx hash" value={tx} /> : null}
        {full.cancel_reason ? <Info label="Причина отмены" value={String(full.cancel_reason)} full /> : null}
        <ReceiptPane orderId={full.order_id} hasReceipt={!!full.has_receipt} kind={typeof full.receipt_kind === "string" ? full.receipt_kind : null} />
      </div>
    </Modal>
  );
}

function Info({ label, value, mono, full }: { label: string; value: ReactNode; mono?: boolean; full?: boolean }) {
  return (
    <div className={cx("rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5", full && "col-span-2")}>
      <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={cx("mt-0.5 break-words text-[13px]", mono && "font-mono")}>{value}</div>
    </div>
  );
}

function ReceiptPane({
  orderId,
  hasReceipt,
  kind,
}: {
  orderId: string;
  hasReceipt: boolean;
  kind: string | null;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [blobType, setBlobType] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    if (!hasReceipt) {
      setBlobUrl(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetchOperatorOrderReceiptBlob(orderId)
      .then((d) => {
        if (cancelled) {
          URL.revokeObjectURL(d.url);
          return;
        }
        url = d.url;
        setBlobUrl(d.url);
        setBlobType(d.type);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof PanelApiError ? e.message : "Файл чека недоступен");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [orderId, hasReceipt]);

  const effectiveKind =
    kind || (blobType.includes("pdf") ? "pdf" : blobType.startsWith("video/") ? "video" : null);
  const title = effectiveKind === "video" ? "Видео-чек клиента" : effectiveKind === "pdf" ? "PDF-чек клиента" : "Чек клиента";

  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{title}</div>
      {!hasReceipt ? (
        <p className="text-[13px] text-[var(--text-muted)]">Чек не приложен</p>
      ) : loading ? (
        <div className="h-[180px] animate-pulse rounded bg-[var(--bg-overlay)]" />
      ) : error ? (
        <p className="text-[13px] text-[var(--red)]">{error}</p>
      ) : blobUrl && effectiveKind === "pdf" ? (
        <iframe title="PDF чек" src={blobUrl} className="h-[280px] w-full rounded border border-[var(--border)] bg-white" />
      ) : blobUrl && effectiveKind === "video" ? (
        <video controls src={blobUrl} className="max-h-[280px] w-full rounded bg-black" />
      ) : blobUrl ? (
        <a href={orderReceiptUrl(orderId)} target="_blank" rel="noreferrer" className="text-[13px] text-[var(--blue)] underline-offset-4 hover:underline">
          Открыть чек клиента →
        </a>
      ) : null}
    </div>
  );
}
