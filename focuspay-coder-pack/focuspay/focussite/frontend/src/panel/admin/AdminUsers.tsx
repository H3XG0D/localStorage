import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getCasinoPlayerHistory, getCasinoPlayerProfile, getUserDetail, getUsers, type Dict } from "@/panel/lib/adminApi";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import type { CasinoClientProfile } from "@/panel/lib/casinoClientProfile";
import { BuyerAvatar } from "@/panel/ui/BuyerAvatar";
import { ClientCasinoTab } from "@/panel/ui/ClientCasinoTab";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, Tabs, cx, type BadgeTone, type Column } from "@/panel/ui/primitives";

function fmtMoney(v: unknown, digits = 0) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(v ?? 0));
}
function fmtDate(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU");
}
function channelTone(ch: unknown): BadgeTone {
  const c = String(ch ?? "").toLowerCase();
  if (c === "bot") return "blue";
  if (c === "web") return "purple";
  if (c.includes("+")) return "green";
  return "default";
}

const CHANNEL_OPTIONS = [
  { value: "all", label: "Все" },
  { value: "bot", label: "Бот" },
  { value: "web", label: "Веб" },
  { value: "web+bot", label: "Веб + бот" },
];

const LIMIT = 50;

export function AdminUsers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryUser = searchParams.get("user");
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState("all");
  const [offset, setOffset] = useState(0);

  const [rows, setRows] = useState<Dict[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Dict | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const q: Record<string, unknown> = { limit: LIMIT, offset, sort_by: "last_order_at", sort_dir: "desc" };
    if (search.trim()) q.search = search.trim();
    if (channel !== "all") q.channel = channel;
    getUsers(q)
      .then((d) => {
        setRows((d.users as Dict[]) ?? []);
        setTotal(Number(d.total ?? (d.users as Dict[])?.length ?? 0));
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [search, channel, offset]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!queryUser) return;
    const fromList = rows.find((r) => String(r.user_id) === queryUser);
    setSelected(fromList ?? { user_id: Number(queryUser) || queryUser });
  }, [queryUser, rows]);

  function applyFilters() {
    if (offset === 0) load();
    else setOffset(0);
  }

  function openUser(row: Dict) {
    setSelected(row);
    if (row.user_id != null) setSearchParams({ user: String(row.user_id) });
  }

  function closeUser() {
    setSelected(null);
    if (searchParams.has("user")) {
      const next = new URLSearchParams(searchParams);
      next.delete("user");
      setSearchParams(next);
    }
  }

  const cols: Column<Dict>[] = [
    { key: "user_id", label: "ID", width: "168px", render: (r) => (
      <span className="flex min-w-0 items-center gap-2">
        <BuyerAvatar
          avatarUrl={typeof r.avatar_url === "string" ? r.avatar_url : null}
          name={typeof r.first_name === "string" ? r.first_name : null}
          username={typeof r.username === "string" ? r.username : null}
          userId={typeof r.user_id === "number" ? r.user_id : Number(r.user_id) || null}
          size="sm"
        />
        <span className="font-mono">{String(r.user_id ?? "—")}</span>
      </span>
    ) },
    { key: "username", label: "Юзернейм", render: (r) => (r.username ? `@${String(r.username)}` : "—") },
    { key: "channel", label: "Канал", width: "110px", render: (r) => <Badge tone={channelTone(r.channel)}>{String(r.channel ?? "—")}</Badge> },
    { key: "total_orders", label: "Заявок", width: "90px", align: "right", render: (r) => String(r.total_orders ?? 0) },
    { key: "paid_orders", label: "Оплачено", width: "100px", align: "right", render: (r) => String(r.paid_orders ?? 0) },
    { key: "total_fiat", label: "Оборот ₽", width: "120px", align: "right", render: (r) => <span className="font-mono">{fmtMoney(r.total_fiat)}</span> },
    { key: "conversion_pct", label: "Конверсия", width: "100px", align: "right", render: (r) => `${Number(r.conversion_pct ?? 0)}%` },
    { key: "last_order_at", label: "Посл. заявка", width: "150px", render: (r) => fmtDate(r.last_order_at) },
  ];

  const page = Math.floor(offset / LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <>
      <PageHeader title="Пользователи" subtitle="Клиенты платформы" />

      <Card>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Поиск">
            <Input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && applyFilters()} placeholder="ID / юзернейм" />
          </Field>
          <Field label="Канал">
            <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
              {CHANNEL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex items-end">
            <Button variant="primary" onClick={applyFilters} className="w-full">
              Найти
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет пользователей"} onRowClick={openUser} />
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

      {selected && <UserDetail user={selected} onClose={closeUser} />}
    </>
  );
}

const DETAIL_FIELDS: { key: string; label: string; kind?: "money" | "pct" | "date" }[] = [
  { key: "username", label: "Юзернейм" },
  { key: "first_name", label: "Имя" },
  { key: "channel", label: "Канал" },
  { key: "total_orders", label: "Всего заявок" },
  { key: "paid_orders", label: "Оплачено" },
  { key: "total_fiat", label: "Оборот ₽", kind: "money" },
  { key: "conversion_pct", label: "Конверсия", kind: "pct" },
  { key: "first_seen_at", label: "Первый визит", kind: "date" },
  { key: "last_seen_at", label: "Последний визит", kind: "date" },
  { key: "cashback_rub", label: "Кэшбэк ₽", kind: "money" },
  { key: "referral_rub", label: "Реферальные ₽", kind: "money" },
];

function UserDetail({ user, onClose }: { user: Dict; onClose: () => void }) {
  const [full, setFull] = useState<Dict>(user);
  const [profile, setProfile] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("exchange");
  const [casino, setCasino] = useState<CasinoClientProfile | null>(null);
  const [casinoLoading, setCasinoLoading] = useState(false);
  const [casinoError, setCasinoError] = useState<string | null>(null);
  const [casinoTried, setCasinoTried] = useState(false);
  const [casinoMore, setCasinoMore] = useState(false);

  useEffect(() => {
    const id = user.user_id;
    setFull(user);
    setProfile(null);
    setError(null);
    setTab("exchange");
    setCasino(null);
    setCasinoTried(false);
    setCasinoError(null);
    if (id === undefined || id === null) {
      setLoading(false);
      setError("У пользователя нет идентификатора");
      return;
    }
    setLoading(true);
    getUserDetail(id as number | string)
      .then((payload) => {
        setProfile(payload);
        const identity = (payload.identity ?? {}) as Dict;
        const summary = (payload.summary ?? {}) as Dict;
        const balances = (payload.balances ?? {}) as Dict;
        const referral = (payload.referral ?? {}) as Dict;
        setFull({
          ...user,
          ...identity,
          ...summary,
          ...balances,
          user_id: identity.user_id ?? user.user_id,
          total_fiat: summary.turnover_rub ?? user.total_fiat,
          cashback_rub: balances.cashback_rub ?? user.cashback_rub,
          referral_rub: balances.referral_rub ?? referral.referral_balance_rub ?? user.referral_rub,
        });
      })
      .catch((e) => {
        const message = e instanceof PanelApiError ? e.message : "Не удалось загрузить профиль";
        setError(message);
        toast.error(message);
      })
      .finally(() => setLoading(false));
  }, [user]);

  const playerId = full.user_id ?? user.user_id;

  useEffect(() => {
    if (tab !== "casino" || playerId == null || casinoTried) return;
    setCasinoTried(true);
    setCasinoLoading(true);
    setCasinoError(null);
    getCasinoPlayerProfile(playerId as number | string)
      .then((payload) => setCasino(payload))
      .catch((e) => {
        if (e instanceof PanelApiError && e.status === 404) {
          setCasino(null);
          setCasinoError(null);
          return;
        }
        setCasinoError(e instanceof PanelApiError ? e.message : "Не удалось загрузить казино");
      })
      .finally(() => setCasinoLoading(false));
  }, [tab, playerId, casinoTried]);

  async function loadMoreCasino() {
    if (playerId == null || !casino?.history_next_before) return;
    setCasinoMore(true);
    try {
      const page = await getCasinoPlayerHistory(playerId as number | string, {
        before: String(casino.history_next_before),
      });
      setCasino((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          recent_games: [...(prev.recent_games ?? []), ...(page.items ?? [])],
          history_next_before: page.next_before ?? null,
        };
      });
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось догрузить историю");
    } finally {
      setCasinoMore(false);
    }
  }

  function fmtValue(key: string, kind?: "money" | "pct" | "date") {
    const v = full[key];
    if (v === undefined || v === null || v === "") return "—";
    if (kind === "money") return fmtMoney(v);
    if (kind === "pct") return `${Number(v)}%`;
    if (kind === "date") return fmtDate(v);
    if (key === "username") return `@${String(v)}`;
    return String(v);
  }

  const referral = (profile?.referral ?? {}) as Dict;
  const referrer = (referral.referrer ?? full.invited_by ?? null) as Dict | null;
  const ledgers = (profile?.ledgers ?? {}) as Dict;
  const cashbackLedger = (ledgers.cashback ?? []) as Dict[];
  const referralLedger = (ledgers.referral ?? []) as Dict[];
  const recent = (profile?.recent_orders ?? []) as Dict[];
  const reviews = (profile?.reviews ?? []) as Dict[];
  const finance = (profile?.finance ?? null) as Dict | null;
  const activeOrder = (profile?.active_order ?? null) as Dict | null;
  const promo = (profile?.promo ?? null) as Dict | null;

  return (
    <Modal open title={`Пользователь ${full.user_id ?? ""}`} onClose={onClose} size="lg" footer={<Button variant="ghost" onClick={onClose}>Закрыть</Button>}>
      {loading && <div className="mb-3 text-[12px] text-[var(--text-muted)]">Загрузка профиля…</div>}
      {error && <div className="mb-3 rounded-[var(--radius)] border border-[var(--red)]/30 bg-[var(--red-bg)] p-3 text-[12px] text-[var(--red)]">{error}</div>}
      <div className="mb-3 flex items-center gap-3">
        <BuyerAvatar
          avatarUrl={typeof full.avatar_url === "string" ? full.avatar_url : null}
          name={typeof full.first_name === "string" ? full.first_name : null}
          username={typeof full.username === "string" ? full.username : null}
          userId={typeof full.user_id === "number" ? full.user_id : Number(full.user_id) || null}
          size="md"
        />
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold">{typeof full.first_name === "string" && full.first_name ? full.first_name : "Клиент"}</div>
          <div className="truncate font-mono text-[12.5px] text-[var(--text-muted)]">{full.username ? `@${String(full.username)}` : `ID ${String(full.user_id ?? "—")}`}</div>
        </div>
      </div>
      <div data-client-profile-tabs="" className="mb-3">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { id: "exchange", label: "Обменник" },
            { id: "casino", label: "Казино" },
          ]}
        />
      </div>
      {tab === "casino" ? (
        <div data-client-tab="casino">
          <ClientCasinoTab
            data={casino}
            scope="admin"
            loading={casinoLoading}
            error={casinoError}
            onLoadMore={loadMoreCasino}
            loadingMore={casinoMore}
            gamesHref={playerId != null ? `/x8/casino/games?player_id=${playerId}` : undefined}
          />
        </div>
      ) : (
      <div data-client-tab="exchange">
      <div className="grid grid-cols-2 gap-3 text-[13px]">
        {DETAIL_FIELDS.map((f) => (
          <Info key={f.key} label={f.label} value={fmtValue(f.key, f.kind)} mono={f.kind === "money"} />
        ))}
      </div>

      <Section title="Рефералка">
        <div className="grid grid-cols-2 gap-2">
          <Info label="Привёл" value={String(referral.referred_count ?? "—")} />
          <Info label="Оплаченных у рефов" value={String(referral.paid_orders_count ?? "—")} />
          <Info label="Баланс реф., ₽" value={fmtMoney(referral.referral_balance_rub ?? full.referral_rub, 2)} mono />
          <Info label="Начислено, ₽" value={fmtMoney(referral.total_accrual_rub, 2)} mono />
        </div>
        {referrer && typeof referrer === "object" && (
          <div className="mt-2 text-[12.5px] text-[var(--text-secondary)]">
            Кто пригласил:{" "}
            {referrer.user_id != null ? (
              <Link className="text-[var(--accent)] hover:underline" to={`/x8/users?user=${referrer.user_id}`}>
                {referrer.username ? `@${String(referrer.username)}` : `ID ${String(referrer.user_id)}`}
              </Link>
            ) : (
              "—"
            )}
          </div>
        )}
        {promo && <div className="mt-1 text-[12.5px] text-[var(--text-muted)]">Промо: {String(promo.promo_code ?? "—")}</div>}
      </Section>

      {finance && (
        <Section title="Прибыль по клиенту">
          <div className="grid grid-cols-2 gap-2">
            <Info label="Gross, ₽" value={fmtMoney(finance.gross_profit_rub, 2)} mono />
            <Info label="Net, ₽" value={fmtMoney(finance.net_profit_rub, 2)} mono />
          </div>
        </Section>
      )}

      {activeOrder && activeOrder.order_id != null && (
        <Section title="Активная заявка">
          <div className="font-mono text-[13px]">#{String(activeOrder.order_id)} · {statusLabel(String(activeOrder.status ?? ""))}</div>
        </Section>
      )}

      {recent.length > 0 && (
        <Section title="Последние заявки">
          <ul className="m-0 max-h-48 list-none space-y-1 overflow-y-auto p-0 text-[12.5px]">
            {recent.slice(0, 15).map((o) => (
              <li key={String(o.order_id)} className="flex items-center justify-between gap-2">
                <Link
                  to={`/x8/orders?order=${encodeURIComponent(String(o.order_id ?? ""))}`}
                  className="font-mono text-[var(--accent)] hover:underline"
                  onClick={onClose}
                >
                  #{String(o.order_id)}
                </Link>
                <span className="whitespace-nowrap text-[var(--text-muted)]">{fmtDate(o.created_at)}</span>
                <Badge tone={orderStatusTone(String(o.status))}>{String(o.status_label ?? statusLabel(String(o.status)))}</Badge>
                <span className="font-mono">{fmtMoney(o.fiat_amount)} ₽</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {(cashbackLedger.length > 0 || referralLedger.length > 0) && (
        <Section title="Ledger">
          <LedgerBlock title="Кешбэк" rows={cashbackLedger} />
          <LedgerBlock title="Рефералка" rows={referralLedger} />
        </Section>
      )}

      {reviews.length > 0 && (
        <Section title="Отзывы">
          <ul className="m-0 list-none space-y-2 p-0 text-[12.5px]">
            {reviews.slice(0, 8).map((r) => (
              <li key={String(r.id)} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2">
                <div className="flex justify-between gap-2">
                  <Badge tone={r.status === "published" ? "green" : r.status === "rejected" ? "red" : "yellow"}>{String(r.status ?? "—")}</Badge>
                  <span className="text-[var(--text-muted)]">{fmtDate(r.created_at)}</span>
                </div>
                {r.review_text ? <div className="mt-1 text-[var(--text-secondary)]">{String(r.review_text)}</div> : null}
              </li>
            ))}
          </ul>
        </Section>
      )}
      </div>
      )}
    </Modal>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4 border-t border-[var(--border)] pt-3">
      <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</div>
      {children}
    </div>
  );
}

function LedgerBlock({ title, rows }: { title: string; rows: Dict[] }) {
  if (!rows.length) return null;
  return (
    <div className="mb-2">
      <div className="mb-1 text-[12px] text-[var(--text-secondary)]">{title}</div>
      <ul className="m-0 max-h-36 list-none space-y-1 overflow-y-auto p-0 text-[12px]">
        {rows.slice(0, 12).map((r, i) => (
          <li key={Number(r.id) || i} className="flex justify-between gap-2">
            <span>{String(r.type ?? "—")}</span>
            <span className="font-mono">{fmtMoney(r.amount_rub, 2)} ₽</span>
            <span className="text-[var(--text-muted)]">{fmtDate(r.created_at)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Info({ label, value, mono, full }: { label: string; value: string; mono?: boolean; full?: boolean }) {
  return (
    <div className={cx("rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5", full && "col-span-2")}>
      <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={cx("mt-0.5 break-words text-[13px]", mono && "font-mono")}>{value}</div>
    </div>
  );
}
