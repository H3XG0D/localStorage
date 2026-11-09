import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  cancelAdminOrder,
  confirmAdminPayout,
  fetchOrderReceiptBlob,
  getOrder,
  getOrders,
  getOrderVerification,
  setOrderStatus,
  syncCryptoToPayin,
  type AdminOrder,
  type AdminPartnerOption,
  type AutopayCheck,
  type AutopayPreview,
  type OrderVerification,
  type ReuseHit,
  type VerificationCheck,
} from "@/panel/lib/adminApi";
import { isLocalDevPanel } from "@/panel/lib/devHost";
import { usePanelSession } from "@/panel/lib/panelSession";
import { CHECK_LABELS, MOMENT_BADGE, reasonLabel } from "@/panel/admin/autopilotReasons";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import { BuyerAvatar } from "@/panel/ui/BuyerAvatar";
import { CopyField } from "@/panel/ui/CopyField";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Select, Table, cx, type Column } from "@/panel/ui/primitives";

function fmtMoney(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}
function fmtProfit(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(Number(v ?? 0));
}
function fmtCrypto(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 8 }).format(Number(v ?? 0));
}
function fmtDate(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU");
}
function buyerName(o: AdminOrder) {
  return (o.buyer_first_name as string) || o.buyer_username || `ID ${o.user_id ?? "—"}`;
}
function referrerName(o: AdminOrder) {
  if (o.referrer_first_name) return String(o.referrer_first_name);
  if (o.referrer_username) return String(o.referrer_username);
  if (o.referrer_user_id) return `ID ${o.referrer_user_id}`;
  return "—";
}
function profitText(o: AdminOrder) {
  if (typeof o.service_profit_rub !== "number" || !Number.isFinite(o.service_profit_rub)) return "—";
  return `${fmtProfit(o.service_profit_rub)} ₽`;
}
function DealBubble({ order, showProfit }: { order: AdminOrder; showProfit?: boolean }) {
  const tone = orderStatusTone(order.status);
  const status = order.status_label || statusLabel(order.status);
  const profitNegative =
    typeof order.service_profit_rub === "number" &&
    Number.isFinite(order.service_profit_rub) &&
    order.service_profit_rub < 0;
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
        {showProfit && (
          <>
            <span className="opacity-40" aria-hidden>
              ·
            </span>
            <span>
              <span className={profitNegative ? "text-[var(--red)]" : "opacity-70"}>чистая </span>
              <span className={cx("font-mono font-semibold", profitNegative && "text-[var(--red)]")}>
                {profitText(order)}
              </span>
            </span>
          </>
        )}
      </span>
    </Badge>
  );
}
function ProfileLink({ userId, children }: { userId?: number | null; children: ReactNode }) {
  if (userId == null) return <>{children}</>;
  return (
    <Link
      to={`/x8/users?user=${userId}`}
      className="min-w-0 truncate text-[var(--accent)] hover:underline"
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </Link>
  );
}
function OrderLink({ orderId, children }: { orderId?: string | null; children: ReactNode }) {
  const id = String(orderId || "").trim();
  if (!id) return <>{children}</>;
  return (
    <Link
      to={`/x8/orders?order=${encodeURIComponent(id)}`}
      className="min-w-0 truncate font-mono text-[var(--accent)] hover:underline"
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </Link>
  );
}
function BuyerCell({ order }: { order: AdminOrder }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <BuyerAvatar
        avatarUrl={typeof order.buyer_avatar_url === "string" ? order.buyer_avatar_url : null}
        name={typeof order.buyer_first_name === "string" ? order.buyer_first_name : null}
        username={typeof order.buyer_username === "string" ? order.buyer_username : null}
        userId={typeof order.user_id === "number" ? order.user_id : null}
        size="sm"
      />
      <ProfileLink userId={typeof order.user_id === "number" ? order.user_id : null}>{buyerName(order)}</ProfileLink>
    </span>
  );
}
function ReferrerCell({ order }: { order: AdminOrder }) {
  const id = typeof order.referrer_user_id === "number" ? order.referrer_user_id : null;
  if (id == null) return <span>—</span>;
  return <ProfileLink userId={id}>{referrerName(order)}</ProfileLink>;
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
function isActionable(order: AdminOrder) {
  return ["CREATED", "AWAITING_CHECK", "PENDING", "OPERATOR_PENDING", "DISPUTE"].includes(String(order.status));
}

const STATUS_OPTIONS = ["CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED", "PAID", "FAILED", "CANCELED", "EXPIRED", "DISPUTE", "OPERATOR_PENDING"];
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

export function AdminOrders() {
  const { account } = usePanelSession();
  const canFinance = !!account?.can_view_finance;
  const [searchParams, setSearchParams] = useSearchParams();
  const queryOrder = (searchParams.get("order") || "").trim();
  const [status, setStatus] = useState("all");
  const [direction, setDirection] = useState("all");
  const [crypto, setCrypto] = useState("all");
  const [origin, setOrigin] = useState("all");
  const [partnerId, setPartnerId] = useState("all");
  const [search, setSearch] = useState("");
  const [searchField, setSearchField] = useState<"client" | "referrer">("client");
  const [offset, setOffset] = useState(0);

  const [rows, setRows] = useState<AdminOrder[]>([]);
  const [partnerOptions, setPartnerOptions] = useState<AdminPartnerOption[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<AdminOrder | null>(null);

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
    const local = isLocalDevPanel();
    if (needle && searchField === "client") q.search = needle;
    if (needle && searchField === "referrer" && local) {
      q.search = needle;
      q.search_field = "referrer";
    }
    getOrders(q)
      .then((d) => {
        let list = d.orders ?? [];
        let n = d.total ?? 0;
        if (needle && searchField === "referrer" && !local) {
          const s = needle.toLowerCase();
          list = list.filter((o) =>
            `${o.referrer_user_id ?? ""} ${o.referrer_username ?? ""} ${o.referrer_first_name ?? ""}`.toLowerCase().includes(s),
          );
          n = list.length;
        }
        setRows(list);
        setTotal(n);
        if (Array.isArray(d.partner_options)) setPartnerOptions(d.partner_options);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [baseQuery, status, search, searchField, offset]);

  const loadCounts = useCallback(() => {
    const q = baseQuery();
    Promise.all(
      STATUS_KPI.map((item) =>
        getOrders({ ...q, ...(item.status === "all" ? {} : { status: item.status }), limit: 1, offset: 0 }).then((d) => [
          item.status,
          d.total ?? 0,
        ] as const),
      ),
    )
      .then((pairs) => setCounts(Object.fromEntries(pairs)))
      .catch(() => undefined);
  }, [baseQuery]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadCounts();
  }, [loadCounts]);

  useEffect(() => {
    if (!queryOrder) return;
    let cancelled = false;
    getOrder(queryOrder)
      .then((d) => {
        if (!cancelled) setSelected(d);
      })
      .catch((e) => {
        if (!cancelled) toast.error(e instanceof PanelApiError ? e.message : "Заявка не найдена");
      });
    return () => {
      cancelled = true;
    };
  }, [queryOrder]);

  function openOrder(row: AdminOrder) {
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

  const cols: Column<AdminOrder>[] = [
    { key: "priority", label: "", width: "8px", render: (r) => isActionable(r) ? <span className="block size-1.5 rounded-full bg-[var(--yellow)]" title="Требует действия" /> : null },
    { key: "order_id", label: "#", width: "120px", render: (r) => <span className="font-mono">{r.order_id}</span> },
    { key: "buyer", label: "Клиент", render: (r) => <BuyerCell order={r} /> },
    { key: "referrer", label: "Реферер", render: (r) => <ReferrerCell order={r} /> },
    { key: "direction", label: "Тип", width: "80px", render: (r) => (r.direction === "buy" ? "Покупка" : "Продажа") },
    { key: "crypto", label: "Актив", width: "90px", render: (r) => <span className="font-mono">{String(r.crypto).toUpperCase()}</span> },
    { key: "deal", label: canFinance ? "Оборот / статус / чистая" : "Оборот / статус", render: (r) => <DealBubble order={r} showProfit={canFinance} /> },
    { key: "operator_name", label: "Оператор", render: (r) => r.operator_name || "—" },
    { key: "age", label: "Возраст", width: "90px", render: (r) => <span className={cx("font-mono text-[12px]", isActionable(r) && "text-[var(--yellow)]")}>{ageSince(r.created_at)}</span> },
    { key: "source", label: "Канал", width: "110px", render: (r) => String(r.source_label ?? r.order_source ?? "—") },
    { key: "autopay", label: "Авто", width: "130px", render: (r) => <AutopayBadge preview={r.autopay_preview} /> },
  ];

  const page = Math.floor(offset / LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <>
      <PageHeader title="Заявки" subtitle="Клик по KPI фильтрует по статусу" />

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
            <Select value={direction} onChange={(e) => { setDirection(e.target.value); setOffset(0); }}>
              {DIRECTION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Актив">
            <Select value={crypto} onChange={(e) => { setCrypto(e.target.value); setOffset(0); }}>
              {CRYPTO_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c === "all" ? "Все" : c.toUpperCase()}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Источник">
            <Select value={origin} onChange={(e) => { setOrigin(e.target.value); setOffset(0); }}>
              {ORIGIN_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Партнёры">
            <Select value={partnerId} onChange={(e) => { setPartnerId(e.target.value); setOffset(0); }}>
              <option value="all">Все</option>
              {partnerOptions.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Искать по">
            <Select value={searchField} onChange={(e) => setSearchField(e.target.value as "client" | "referrer")}>
              <option value="client">Клиент / ник</option>
              <option value="referrer">Реферер</option>
            </Select>
          </Field>
          <Field label="Поиск">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applyFilters()}
              placeholder={searchField === "referrer" ? "ID / ник реферера" : "ID / клиент"}
            />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" onClick={applyFilters} className="w-full">
              Найти
            </Button>
          </div>
        </div>
        {searchField === "referrer" && !isLocalDevPanel() ? (
          <div className="mt-2 text-[11px] text-[var(--text-muted)]">
            На проде поиск по рефереру фильтрует текущую страницу — бэкенд это поле не ищет.
          </div>
        ) : null}
      </Card>

      <Card>
        <div className="hidden md:block">
          <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет заявок"} onRowClick={openOrder} />
        </div>
        <div className="flex flex-col gap-2 md:hidden">
          {loading ? <div className="py-10 text-center text-[12px] text-[var(--text-muted)]">Загрузка…</div> : rows.length === 0 ? <div className="py-10 text-center text-[12px] text-[var(--text-muted)]">Нет заявок</div> : rows.map((row) => <OrderMobileRow key={row.order_id} order={row} showProfit={canFinance} onClick={() => openOrder(row)} />)}
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

      {selected && (
        <OrderDetail
          key={selected.order_id}
          order={selected}
          showProfit={canFinance}
          onClose={closeOrder}
          onChanged={() => {
            closeOrder();
            load();
          }}
        />
      )}
    </>
  );
}

function OrderMobileRow({ order, showProfit, onClick }: { order: AdminOrder; showProfit?: boolean; onClick: () => void }) {
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
            <ProfileLink userId={typeof order.user_id === "number" ? order.user_id : null}>{buyerName(order)}</ProfileLink>
          </div>
          </div>
        </div>
      </div>
      <div className="mt-3">
        <DealBubble order={order} showProfit={showProfit} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">
        <MobileMeta label="Тип" value={order.direction === "buy" ? "Покупка" : "Продажа"} />
        <MobileMeta label="Актив" value={String(order.crypto || "—").toUpperCase()} mono />
        <MobileMeta label="Реферер" value={<ReferrerCell order={order} />} />
        <MobileMeta label="Оператор" value={order.operator_name || "—"} />
        <MobileMeta label="Канал" value={String(order.source_label ?? order.order_source ?? "—")} />
        <MobileMeta label="Режим" value={String(order.origin ?? "—")} />
        <MobileMeta label="Создана" value={fmtDate(order.created_at)} />
      </div>
    </div>
  );
}

function MobileMeta({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return <div className="min-w-0"><div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div><div className={cx("truncate text-[12px] text-[var(--text-primary)]", mono && "font-mono")}>{value}</div></div>;
}

function AutopayBadge({ preview }: { preview?: AutopayPreview }) {
  if (!preview || preview.verdict === "n/a" || preview.moment?.key === "n/a") {
    return <span className="text-[var(--text-muted)]">—</span>;
  }
  const moment = preview.moment;
  const badge = moment ? MOMENT_BADGE[moment.key] : undefined;
  const title = moment?.headline || preview.reasons.map(reasonLabel).join("\n");
  if (badge) {
    return (
      <span title={title}>
        <Badge tone={badge.tone} className="whitespace-nowrap">
          {badge.label}
        </Badge>
      </span>
    );
  }
  if (preview.verdict === "auto") {
    return (
      <Badge tone="green" className="whitespace-nowrap">
        Авто
      </Badge>
    );
  }
  if (preview.verdict === "waiting") {
    return (
      <span title={reasonLabel("payfast_waiting")}>
        <Badge tone="yellow" className="whitespace-nowrap">
          Ждёт Payfast
        </Badge>
      </span>
    );
  }
  return (
    <span title={title}>
      <Badge className="whitespace-nowrap">Вручную</Badge>
    </span>
  );
}

function AutopayCheckRow({ c }: { c: AutopayCheck }) {
  return (
    <li className="flex items-center justify-between gap-3 text-[13px]">
      <span className="flex items-center gap-2">
        <span
          className={cx(
            "size-1.5 rounded-full",
            c.ok ? "bg-[var(--green)]" : c.pending ? "bg-[var(--yellow)]" : "bg-[var(--red)]",
          )}
        />
        {CHECK_LABELS[c.key] ?? c.key}
      </span>
      <span className="font-mono text-[12px] text-[var(--text-muted)]">{c.detail || (c.ok ? "да" : "нет")}</span>
    </li>
  );
}

function momentTone(key: string | undefined): string {
  if (key === "would_send_now" || key === "would_send") return "text-[var(--green)]";
  if (key === "waiting_payfast" || key === "blocked_now") return "text-[var(--yellow)]";
  return "";
}

function stepDot(state: string): string {
  if (state === "done" || state === "now") return "bg-[var(--green)]";
  if (state === "wait") return "bg-[var(--yellow)]";
  return "bg-[var(--red)]";
}

function AutopayPane({ preview }: { preview?: AutopayPreview }) {
  if (!preview) return null;
  const off = preview.toggles && !(preview.toggles.mode && preview.toggles.payout);
  const moment = preview.moment;
  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Автопилот (тест)</span>
        {off && <Badge>сейчас выключен</Badge>}
      </div>
      {preview.verdict === "n/a" ? (
        <div className="text-[13px] text-[var(--text-secondary)]">{moment?.headline || "Продажа — автовывод не применяется"}</div>
      ) : (
        <>
          <div className={cx("text-[14px] font-semibold", momentTone(moment?.key))}>
            {moment?.headline ||
              (preview.verdict === "auto"
                ? "Payfast подтвердил — выплата ушла бы автоматически"
                : preview.verdict === "waiting"
                  ? "Ждём подтверждения Payfast — потом выплата уйдёт сама"
                  : "Ушло бы оператору")}
          </div>
          {moment?.steps?.length ? (
            <ol className="flex flex-col gap-1.5">
              {moment.steps.map((step, i) => (
                <li key={step.key} className="flex items-start gap-2 text-[13px]">
                  <span className={cx("mt-1.5 size-1.5 shrink-0 rounded-full", stepDot(step.state))} />
                  <span>
                    <span className="text-[var(--text-muted)]">{i + 1}. </span>
                    {step.text}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
          {preview.verdict === "manual" && (
            <div className="text-[12px] text-[var(--text-secondary)]">{preview.reasons.map(reasonLabel).join(" · ")}</div>
          )}
          <ul className="flex flex-col gap-1.5">
            {preview.checks.map((c) => (
              <AutopayCheckRow key={c.key} c={c} />
            ))}
          </ul>
          {preview.live_checks?.length ? (
            <>
              <div className="border-t border-[var(--border)] pt-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Сейчас: Payfast и кошелёк</div>
              <ul className="flex flex-col gap-1.5">
                {preview.live_checks.map((c) => (
                  <AutopayCheckRow key={c.key} c={c} />
                ))}
              </ul>
              {preview.live_blocked?.length ? (
                <div className="text-[12px] text-[var(--yellow)]">
                  Клиент подходит, но сейчас выплата бы не ушла: {preview.live_blocked.map(reasonLabel).join(", ")}
                </div>
              ) : null}
            </>
          ) : null}
        </>
      )}
      <div className="text-[11px] text-[var(--text-muted)]">Оценка как при включённом автопилоте. Ничего не отправляется.</div>
    </div>
  );
}

function OrderDetail({ order, showProfit, onClose, onChanged }: { order: AdminOrder; showProfit?: boolean; onClose: () => void; onChanged: () => void }) {
  const [full, setFull] = useState<AdminOrder>(order);
  const [ver, setVer] = useState<OrderVerification | null>(null);
  const [verError, setVerError] = useState<string | null>(null);
  const [verLoading, setVerLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [nextStatus, setNextStatus] = useState(order.status);
  const [txHash, setTxHash] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  useEffect(() => {
    getOrder(order.order_id)
      .then((d) => {
        setFull(d);
        setNextStatus(d.status);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"));
    setVerLoading(true);
    setVerError(null);
    getOrderVerification(order.order_id)
      .then(setVer)
      .catch((e) => setVerError(e instanceof PanelApiError ? e.message : "Проверки недоступны"))
      .finally(() => setVerLoading(false));
  }, [order.order_id]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка операции");
    } finally {
      setBusy(false);
    }
  }

  const isBuy = full.direction === "buy";
  const wallet = String(full.wallet_address || "").trim();
  const requisites = String(full.requisites || "").trim();
  const walletShown = wallet || (isBuy ? requisites : "");
  const tx = typeof full.payout_tx_hash === "string" ? full.payout_tx_hash : "";

  return (
    <Modal
      open
      size="xl"
      title={`Заявка #${full.order_id}`}
      onClose={onClose}
      footer={
        <Button variant="ghost" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
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
                  <ProfileLink userId={typeof full.user_id === "number" ? full.user_id : null}>{buyerName(full)}</ProfileLink>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-[13px]">
              <Info label="Тип" value={isBuy ? "Покупка" : "Продажа"} />
              <Info label="Актив" value={`${String(full.crypto).toUpperCase()}${full.network ? " · " + full.network : ""}`} mono />
              <div className="col-span-2">
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{showProfit ? "Оборот / статус / чистая" : "Оборот / статус"}</div>
                <div className="mt-1">
                  <DealBubble order={full} showProfit={showProfit} />
                </div>
              </div>
              <Info label="Крипта" value={fmtCrypto(full.crypto_amount)} mono />
              <Info label="Курс" value={fmtMoney(full.rate)} mono />
              <Info label="Реферер" value={<ReferrerCell order={full} />} />
              <Info label="Оператор" value={full.operator_name || "—"} />
              <Info label="Канал" value={String(full.source_label ?? full.order_source ?? "—")} />
              <Info label="Режим" value={String(full.origin ?? "—")} />
              <Info label="Создана" value={fmtDate(full.created_at)} />
            </div>
            {walletShown ? <CopyField label="Кошелёк" value={walletShown} /> : null}
            {requisites && requisites !== walletShown ? <CopyField label="Реквизиты" value={requisites} /> : null}
            {tx ? <CopyField label="Tx hash" value={tx} /> : null}
            {full.cancel_reason ? <Info label="Причина отмены" value={String(full.cancel_reason)} full /> : null}
            <TimelineList items={ver?.timeline ?? []} />
          </div>
          <div className="flex flex-col gap-4">
            <ReceiptPane orderId={full.order_id} hasReceipt={!!full.has_receipt} kind={(ver?.receipt.kind || full.receipt_kind || null) as string | null} receipt={ver?.receipt} />
            <AutopayPane preview={full.autopay_preview} />
            <ChecksPane loading={verLoading} error={verError} data={ver} />
          </div>
        </div>

        <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-4">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Новый статус">
              <Select value={nextStatus} onChange={(e) => setNextStatus(e.target.value)}>
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {statusLabel(s)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex items-end">
              <Button
                variant="primary"
                disabled={busy || nextStatus === full.status}
                onClick={() => run(() => setOrderStatus(full.order_id, nextStatus), "Статус изменён")}
                className="w-full"
              >
                Сменить статус
              </Button>
            </div>
          </div>

          {full.status === "AWAITING_CHECK" && (
            <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
              {isBuy && (
                <div className="flex flex-col gap-2">
                  <Field label="Tx hash выплаты">
                    <Input
                      value={txHash}
                      onChange={(e) => setTxHash(e.target.value)}
                      placeholder="Хэш уже отправленной транзакции"
                      autoComplete="off"
                    />
                  </Field>
                  <Button
                    variant="primary"
                    disabled={busy || txHash.trim().length < 8}
                    onClick={() => {
                      if (!window.confirm("Крипта уже ушла клиенту? Заявка станет «оплачено».")) return;
                      run(() => confirmAdminPayout(full.order_id, txHash.trim()), "Выплата подтверждена");
                    }}
                  >
                    Подтвердить выплату
                  </Button>
                </div>
              )}
              <div className="flex flex-col gap-2">
                <Field label="Причина отмены">
                  <textarea
                    value={cancelReason}
                    onChange={(e) => setCancelReason(e.target.value)}
                    placeholder="Почему снимаем заявку без выплаты"
                    rows={3}
                    className="w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--text-muted)]"
                  />
                </Field>
                <Button
                  variant="danger"
                  disabled={busy || cancelReason.trim().length < 3}
                  onClick={() => {
                    if (!window.confirm("Отменить заявку без выплаты?")) return;
                    run(() => cancelAdminOrder(full.order_id, cancelReason.trim()), "Заявка отменена");
                  }}
                >
                  Отменить заявку
                </Button>
              </div>
            </div>
          )}

          {isBuy && full.status !== "PAID" && (
            <Button variant="secondary" disabled={busy} onClick={() => run(() => syncCryptoToPayin(full.order_id), "Крипта пересчитана")}>
              Пересчитать крипту
            </Button>
          )}
        </div>
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

function checkTone(severity: string | undefined): "green" | "yellow" | "red" | "default" {
  if (severity === "danger") return "red";
  if (severity === "warn") return "yellow";
  if (severity === "ok") return "green";
  return "default";
}

function riskTone(level: string | null | undefined): "green" | "yellow" | "red" | "default" {
  if (level === "ДОСКОНАЛЬНО") return "red";
  if (level === "СМОТРЕТЬ") return "yellow";
  if (level === "OK") return "green";
  return "default";
}

function TimelineList({ items }: { items: { key: string; label: string; at: string }[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Таймлайн</div>
      <ol className="flex flex-col gap-1.5">
        {items.map((ev) => (
          <li key={ev.key} className="flex items-baseline justify-between gap-3 text-[12px]">
            <span className="text-[var(--text-secondary)]">{ev.label}</span>
            <span className="shrink-0 font-mono text-[var(--text-muted)]">{fmtDate(ev.at)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ReuseList({ title, hits }: { title: string; hits: ReuseHit[] }) {
  if (!hits.length) return null;
  return (
    <div>
      <div className="text-[11px] font-semibold text-[var(--text-secondary)]">{title}</div>
      <ul className="mt-1 flex flex-col gap-0.5 text-[12px] text-[var(--text-muted)]">
        {hits.map((h, i) => {
          const name = h.username || (h.user_id != null ? `id ${h.user_id}` : "—");
          return (
            <li key={`${h.order_id ?? h.user_id ?? i}`} className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
              <ProfileLink userId={typeof h.user_id === "number" ? h.user_id : null}>{name}</ProfileLink>
              {h.order_id ? (
                <>
                  <span aria-hidden>·</span>
                  <OrderLink orderId={h.order_id}>{h.order_id}</OrderLink>
                </>
              ) : null}
              {h.status ? (
                <>
                  <span aria-hidden>·</span>
                  <span>{statusLabel(h.status)}</span>
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ReceiptPane({
  orderId,
  hasReceipt,
  kind,
  receipt,
}: {
  orderId: string;
  hasReceipt: boolean;
  kind: string | null;
  receipt?: OrderVerification["receipt"];
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
    fetchOrderReceiptBlob(orderId)
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
    kind ||
    (blobType.includes("pdf") ? "pdf" : blobType.startsWith("video/") ? "video" : null);
  const title = effectiveKind === "video" ? "Видео-чек клиента" : effectiveKind === "pdf" ? "PDF-чек клиента" : "Чек клиента";

  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{title}</div>
      {!hasReceipt ? (
        <p className="text-[13px] text-[var(--text-muted)]">
          {kind === "video" ? "Ожидается видео-чек" : kind === "pdf" ? "Ожидается PDF-чек" : "Чек не приложен"}
        </p>
      ) : loading ? (
        <div className="h-[220px] animate-pulse rounded bg-[var(--bg-overlay)]" />
      ) : error ? (
        <p className="text-[13px] text-[var(--red)]">{error}</p>
      ) : blobUrl && effectiveKind === "pdf" ? (
        <iframe title="PDF чек" src={blobUrl} className="h-[360px] w-full rounded border border-[var(--border)] bg-white" />
      ) : blobUrl && effectiveKind === "video" ? (
        <video controls src={blobUrl} className="max-h-[360px] w-full rounded bg-black" />
      ) : blobUrl ? (
        <p className="text-[13px] text-[var(--text-secondary)]">Файл загружен, предпросмотр этого формата недоступен.</p>
      ) : null}
      {hasReceipt && blobUrl ? (
        <div className="mt-2 flex flex-wrap gap-3 text-[13px]">
          <a href={blobUrl} target="_blank" rel="noreferrer" className="text-[var(--blue)] underline-offset-4 hover:underline">
            Открыть в новой вкладке
          </a>
          <a href={blobUrl} download={receipt?.filename || `receipt-${orderId}`} className="text-[var(--blue)] underline-offset-4 hover:underline">
            Скачать
          </a>
        </div>
      ) : null}
      {receipt?.sha256 ? <div className="mt-2"><CopyField label="SHA256 чека" value={receipt.sha256} /></div> : null}
      {receipt?.upload_sec != null ? (
        <div className="mt-2 text-[11px] text-[var(--text-muted)]">Загружен за {receipt.upload_sec} сек после выдачи реквизитов</div>
      ) : null}
    </div>
  );
}

function ChecksPane({
  loading,
  error,
  data,
}: {
  loading: boolean;
  error: string | null;
  data: OrderVerification | null;
}) {
  if (loading) {
    return (
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
        <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Проверки</div>
        <div className="h-24 animate-pulse rounded bg-[var(--bg-overlay)]" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
        <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Проверки</div>
        <p className="text-[13px] text-[var(--text-muted)]">{error || "Проверки недоступны"}</p>
      </div>
    );
  }
  const audit = data.payout_audit;
  const checks: VerificationCheck[] = data.checks ?? [];
  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Проверки</span>
        {data.risk.level ? (
          <Badge tone={riskTone(data.risk.level)}>
            Риск {data.risk.level} · {data.risk.score}
          </Badge>
        ) : (
          <Badge>Риск не считался</Badge>
        )}
        {!data.reuse.available ? <Badge>Повторы из снимка</Badge> : null}
      </div>
      {audit && audit.crypto_ok === false ? (
        <p className="mb-2 text-[12px] text-[var(--red)]">
          Крипта в заявке больше оплаченной суммы
          {audit.expected_crypto != null ? ` (ожидалось ${fmtCrypto(audit.expected_crypto)})` : ""}
        </p>
      ) : null}
      {data.client.paid_count != null ? (
        <p className="mb-2 text-[12px] text-[var(--text-muted)]">Оплаченных сделок: {data.client.paid_count}</p>
      ) : null}
      {data.device.ip || data.device.platform ? (
        <p className="mb-2 font-mono text-[11px] text-[var(--text-muted)]">
          {[data.device.platform, data.device.ip, data.device.fingerprint_short ? `FP ${data.device.fingerprint_short}…` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
      {checks.length === 0 ? (
        <p className="text-[13px] text-[var(--text-muted)]">Нет сохранённых проверок по этой заявке</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {checks.map((c) => (
            <li key={c.key} className="flex items-start gap-2 text-[12.5px]">
              <Badge tone={checkTone(String(c.severity))} className="mt-0.5 shrink-0">
                {c.severity === "danger" ? "стоп" : c.severity === "ok" ? "ок" : "смотр."}
              </Badge>
              <span>
                {c.label}
                {c.detail ? <span className="mt-0.5 block text-[11px] text-[var(--text-muted)]">{c.detail}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-col gap-2">
        <ReuseList title="Повтор кошелька" hits={data.reuse.wallet} />
        <ReuseList title="Повтор IP" hits={data.reuse.ip} />
        <ReuseList title="Повтор отпечатка" hits={data.reuse.fingerprint} />
        <ReuseList title="Повтор файла чека" hits={data.reuse.receipt_hash} />
      </div>
    </div>
  );
}
