import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, KeyRound, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { CredentialsModal, ExchangerApiBlock, reissueExchangerCredentials } from "@/panel/admin/AdminExternal";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  completePayout,
  createExchangerClerk,
  createExchangerPayout,
  fetchExchangerDealReceiptBlob,
  getExchanger,
  getExchangerAccounts,
  getExchangerDeals,
  getExchangerLedger,
  getExchangerPayouts,
  getExchangerStats,
  getExternalDeal,
  issueExchangerCredentials,
  patchExchanger,
  patchExchangerAccount,
  rejectPayout,
  resetExchangerAccountPassword,
  type Dict,
} from "@/panel/lib/adminApi";
import { isoDate, shiftIso } from "@/panel/lib/analyticsPeriod";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Select, Table, cx, type Column, type BadgeTone } from "@/panel/ui/primitives";

type PeriodKey = "month" | 7 | 30 | 90;
type PageTab = "deals" | "ledger" | "payouts" | "access";
type DealFilter = "all" | "open" | "confirmed" | "cancelled";

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: "month", label: "Месяц" },
  { key: 7, label: "7 дней" },
  { key: 30, label: "30 дней" },
  { key: 90, label: "90 дней" },
];
const TABS: { key: PageTab; label: string }[] = [
  { key: "deals", label: "Сделки" },
  { key: "ledger", label: "Плюса" },
  { key: "payouts", label: "Выплаты" },
  { key: "access", label: "Доступ" },
];
const PAGE_SIZE = 50;

function money(v: unknown, digits = 2) {
  if (v == null || v === "") return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(v));
}
function asRows(r: unknown, ...keys: string[]): Dict[] {
  if (Array.isArray(r)) return r as Dict[];
  if (r && typeof r === "object") {
    const rec = r as Dict;
    for (const key of keys) {
      const val = rec[key];
      if (Array.isArray(val)) return val as Dict[];
    }
  }
  return [];
}
function asDict(v: unknown): Dict {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Dict) : {};
}
function dt(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function dayLabel(ymd: unknown) {
  const raw = String(ymd ?? "");
  const d = new Date(`${raw}T12:00:00`);
  if (Number.isNaN(d.getTime())) return raw || "—";
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short", weekday: "short" });
}
function periodRange(key: PeriodKey): { from: string; to: string } {
  const to = isoDate(new Date());
  if (key === "month") return { from: `${to.slice(0, 7)}-01`, to };
  return { from: shiftIso(to, -(key - 1)), to };
}
function dealTone(status: unknown): BadgeTone {
  const s = String(status ?? "");
  if (s === "confirmed") return "green";
  if (s === "cancelled" || s === "canceled") return "red";
  if (s === "pending") return "yellow";
  if (s === "awaiting_receipt") return "blue";
  return "default";
}
function dealStatusLabel(status: unknown) {
  const s = String(status ?? "");
  if (s === "confirmed") return "подтверждена";
  if (s === "cancelled" || s === "canceled") return "отмена";
  if (s === "pending") return "проверка";
  if (s === "awaiting_receipt") return "ждёт чек";
  return s || "—";
}
function payoutTone(status: unknown): BadgeTone {
  const s = String(status ?? "");
  if (s === "paid") return "green";
  if (s === "rejected" || s === "canceled" || s === "cancelled") return "red";
  return "yellow";
}
function ledgerTypeLabel(t: unknown) {
  const key = String(t || "");
  if (key === "principal") return "Начисление";
  if (key === "reward") return "Награда";
  if (key === "payout") return "Вывод";
  if (key === "adjust") return "Корректировка";
  return key || "—";
}
function creditedUsd(row: Dict) {
  const principal = Number(row.principal_usdt ?? 0);
  const reward = Number(row.reward_usdt ?? 0);
  if (principal || reward) return principal + reward;
  return Number(row.amount_usd ?? 0);
}

export function AdminExchangerDetail() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const eid = Number(id);
  const openAccess = searchParams.get("tab") === "access";
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [tab, setTab] = useState<PageTab>(openAccess ? "access" : "deals");
  const [ex, setEx] = useState<Dict | null>(null);
  const [lifetime, setLifetime] = useState<Dict>({});
  const [periodStats, setPeriodStats] = useState<Dict>({});
  const [daily, setDaily] = useState<Dict[]>([]);
  const [range, setRange] = useState({ from: "", to: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [credentials, setCredentials] = useState<Dict | null>(null);
  const [dealOpen, setDealOpen] = useState<Dict | null>(null);

  const [markupPct, setMarkupPct] = useState("");
  const [markupMode, setMarkupMode] = useState<"on_deal" | "on_turnover">("on_deal");
  const [contact, setContact] = useState("");
  const [note, setNote] = useState("");
  const [trusted, setTrusted] = useState(false);
  const [autoCredit, setAutoCredit] = useState(false);

  const load = useCallback(() => {
    if (!Number.isFinite(eid)) return;
    const { from, to } = periodRange(period);
    setRange({ from, to });
    setLoading(true);
    Promise.all([
      getExchanger(eid),
      getExchangerStats(eid, { date_from: from, date_to: to }).catch(() => null),
    ])
      .then(([detail, stats]) => {
        setEx(detail);
        const life = asDict(stats?.lifetime ?? detail.stats);
        const per = asDict(stats?.period);
        setLifetime(Object.keys(life).length ? life : asDict(detail.stats));
        setPeriodStats(Object.keys(per).length ? per : asDict(detail.stats));
        setDaily(asRows(stats?.daily));
        setMarkupPct(String(detail.effective_markup_pct ?? detail.markup_pct ?? ""));
        setMarkupMode((detail.effective_markup_mode ?? detail.markup_mode ?? "on_deal") === "on_turnover" ? "on_turnover" : "on_deal");
        setContact(String(detail.contact ?? ""));
        setNote(String(detail.note ?? ""));
        setTrusted(Boolean(detail.is_trusted_client));
        setAutoCredit(Boolean(detail.auto_credit_on_payfast));
      })
      .catch((e) => {
        setEx(null);
        toast.error(e instanceof PanelApiError ? e.message : "Внештатник не найден");
      })
      .finally(() => setLoading(false));
  }, [eid, period]);

  useEffect(() => load(), [load]);

  useEffect(() => {
    setTab(openAccess ? "access" : "deals");
  }, [eid, openAccess]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const name = String(ex?.name ?? `Внештатник ${id}`);
  const active = Boolean(ex?.is_active);
  const dailyChrono = useMemo(
    () => [...daily].sort((a, b) => String(a.date).localeCompare(String(b.date))),
    [daily],
  );
  const chartPoints = dailyChrono.map((d) => ({ key: String(d.date), label: dayLabel(d.date) }));
  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "период";

  return (
    <>
      <PageHeader
        title={name}
        subtitle={ex?.contact ? String(ex.contact) : undefined}
        actions={
          <>
            {Boolean(ex?.has_account) && (
              <Button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const issued = await reissueExchangerCredentials(eid);
                    if (!issued) return;
                    setCredentials(issued);
                    toast.success("Новые данные готовы — сохраните и передайте");
                  } catch (e) {
                    toast.error(e instanceof PanelApiError ? e.message : "Не удалось перевыдать доступ");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <KeyRound className="size-4" /> Перевыдать доступ
              </Button>
            )}
            <Button variant="ghost" onClick={() => navigate("/x8/external")}>
              <ArrowLeft className="size-4" /> К списку
            </Button>
          </>
        }
      />

      {loading || !ex ? (
        <Card>{loading ? "Загрузка…" : "Нет данных"}</Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {PERIODS.map((p) => (
              <Button key={String(p.key)} size="sm" variant={period === p.key ? "primary" : "secondary"} onClick={() => setPeriod(p.key)}>
                {p.label}
              </Button>
            ))}
            <span className="text-[12px] text-[var(--text-muted)]">{range.from} — {range.to}</span>
            <Badge tone={active ? "green" : "red"}>{active ? "активен" : "выключен"}</Badge>
            {trusted && <Badge tone="blue">доверенный</Badge>}
            {autoCredit && <Badge tone="green">автоначисление</Badge>}
          </div>

          <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
            <Kpi label="Баланс $" value={money(lifetime.balance_usd ?? ex.balance_usd)} hint="текущий долг" />
            <Kpi label="Оборот база, ₽" value={money(periodStats.turnover_base_rub, 0)} hint={`клиент ${money(periodStats.turnover_client_rub, 0)} ₽ · ${periodLabel.toLowerCase()}`} />
            <Kpi label="Начислено $" value={money(periodStats.total_credited_usd)} hint={`lifetime ${money(lifetime.total_credited_usd)}`} />
            <Kpi label="Выплачено $" value={money(periodStats.total_paid_out_usd)} hint={`lifetime ${money(lifetime.total_paid_out_usd)}`} />
            <Kpi label="Прибыль дома $" value={money(periodStats.house_profit_usd)} hint={`сделки ${money(periodStats.deal_profit_usd)} · комиссия выводов ${money(periodStats.payout_fee_usd)}`} />
            <Kpi label="Подтверждено" value={String(periodStats.deals_confirmed ?? periodStats.deal_count ?? 0)} hint={`отмен ${periodStats.deals_cancelled ?? 0} · в работе ${periodStats.deals_open ?? 0}`} />
            <Kpi label="Конверсия" value={periodStats.conversion_pct != null ? `${periodStats.conversion_pct}%` : "—"} hint={`lifetime ${lifetime.conversion_pct != null ? `${lifetime.conversion_pct}%` : "—"}`} />
            <Kpi label="Комиссия выводов $" value={money(periodStats.payout_fee_usd)} hint={`${periodStats.payout_count ?? 0} выплат за период`} />
          </div>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Оборот и прибыль</div>
            {chartPoints.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Нет данных за период</p>
            ) : (
              <LineAreaChart
                points={chartPoints}
                series={[
                  { key: "turnover", label: "Оборот ₽", color: "var(--blue)", values: dailyChrono.map((d) => Number(d.turnover_rub ?? 0)), fill: true },
                ]}
                hover={hover}
                onHover={setHover}
                summary={`${daily.reduce((s, d) => s + Number(d.deal_count ?? 0), 0)} сделок · ${money(daily.reduce((s, d) => s + Number(d.turnover_rub ?? 0), 0), 0)} ₽`}
                tooltip={(i) => {
                  const d = dailyChrono[i];
                  if (!d) return null;
                  return (
                    <div className="text-[12px]">
                      <div className="font-medium">{dayLabel(d.date)}</div>
                      <div>{Number(d.deal_count ?? 0)} сделок · отмен {Number(d.cancelled_count ?? 0)}</div>
                      <div>оборот {money(d.turnover_rub, 0)} ₽ · прибыль {money(d.profit_usd)} $</div>
                    </div>
                  );
                }}
              />
            )}
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Условия</div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Button size="sm" variant={active ? "danger" : "primary"} disabled={busy} onClick={() => run(() => patchExchanger(eid, { is_active: !active }), active ? "Внештатник отключён" : "Внештатник включён")}>
                {active ? "Отключить" : "Включить"}
              </Button>
            </div>
            <div className="grid max-w-3xl grid-cols-2 gap-3 max-sm:grid-cols-1">
              <Field label="Наценка %">
                <Input inputMode="decimal" value={markupPct} onChange={(e) => setMarkupPct(e.target.value)} className="font-mono" />
              </Field>
              <Field label="Режим наценки">
                <Select value={markupMode} onChange={(e) => setMarkupMode(e.target.value as "on_deal" | "on_turnover")}>
                  <option value="on_deal">К базе — процент сверху к сумме на баланс</option>
                  <option value="on_turnover">С оборота — процент вычитается из суммы клиента</option>
                </Select>
              </Field>
              <Field label="Контакт">
                <Input value={contact} onChange={(e) => setContact(e.target.value)} />
              </Field>
              <Field label="Заметка">
                <Input value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
            </div>
            <p className="mt-2 text-[12px] text-[var(--text-muted)]">
              {markupMode === "on_turnover"
                ? "Внештатник вводит сумму, которую платит клиент. Процент вычитается — остаток идёт на баланс."
                : "Внештатник вводит сумму на баланс. К оплате клиентом добавляется процент сверху."}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-[13px]">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={trusted} onChange={(e) => { setTrusted(e.target.checked); if (!e.target.checked) setAutoCredit(false); }} />
                Доверенный
              </label>
              <label className={cx("flex items-center gap-2", !trusted && "opacity-50")}>
                <input type="checkbox" checked={autoCredit} disabled={!trusted} onChange={(e) => setAutoCredit(e.target.checked)} />
                Автоначисление после Payfast
              </label>
            </div>
            <div className="mt-3">
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => {
                  const pct = markupPct.trim() === "" ? null : Number(markupPct.replace(",", "."));
                  if (pct != null && !Number.isFinite(pct)) {
                    toast.error("Наценка — число");
                    return;
                  }
                  void run(
                    () =>
                      patchExchanger(eid, {
                        markup_pct: pct,
                        markup_mode: markupMode,
                        contact: contact.trim() || null,
                        note: note.trim() || null,
                        is_trusted_client: trusted,
                        auto_credit_on_payfast: autoCredit,
                      }),
                    "Условия сохранены",
                  );
                }}
              >
                Сохранить условия
              </Button>
            </div>
          </Card>

          <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cx(
                  "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
                  tab === t.key ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "deals" && (
            <DealsTab
              exchangerId={eid}
              from={range.from}
              to={range.to}
              onOpenDeal={(row) => {
                getExternalDeal(Number(row.id)).then(setDealOpen).catch(() => setDealOpen(row));
              }}
            />
          )}
          {tab === "ledger" && <LedgerTab exchangerId={eid} from={range.from} to={range.to} />}
          {tab === "payouts" && (
            <PayoutsTab
              exchangerId={eid}
              from={range.from}
              to={range.to}
              balanceUsd={Number(lifetime.balance_usd ?? ex.balance_usd ?? 0)}
              onChanged={load}
            />
          )}
          {tab === "access" && <AccessTab exchangerId={eid} hasOwner={Boolean(ex.has_account)} onCredentials={setCredentials} />}
        </>
      )}

      {credentials && <CredentialsModal credentials={credentials} onClose={() => setCredentials(null)} />}
      {dealOpen && <DealModal deal={dealOpen} onClose={() => setDealOpen(null)} />}
    </>
  );
}

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (n: number) => void }) {
  return (
    <div className="mt-4 flex items-center justify-between text-[12px] text-[var(--text-muted)]">
      <span>Стр. {page}/{pages}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(Math.max(1, page - 1))}>Назад</Button>
        <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => onPage(Math.min(pages, page + 1))}>Вперёд</Button>
      </div>
    </div>
  );
}

function DealsTab({
  exchangerId,
  from,
  to,
  onOpenDeal,
}: {
  exchangerId: number;
  from: string;
  to: string;
  onOpenDeal: (row: Dict) => void;
}) {
  const [filter, setFilter] = useState<DealFilter>("all");
  const [rows, setRows] = useState<Dict[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    const q: Dict = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, date_from: from, date_to: to };
    if (filter !== "all") q.status = filter;
    getExchangerDeals(exchangerId, q)
      .then((r) => {
        setRows(asRows(r, "deals", "items"));
        setTotal(Number((r as Dict).total ?? asRows(r, "deals").length));
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить сделки"))
      .finally(() => setLoading(false));
  }, [exchangerId, filter, from, to, page]);

  useEffect(() => setPage(1), [filter, from, to]);
  useEffect(() => load(), [load]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const cols: Column<Dict>[] = [
    { key: "id", label: "#", width: "64px", render: (r) => <span className="font-mono">{String(r.id)}</span> },
    { key: "created_at", label: "Дата", width: "140px", render: (r) => dt(r.created_at) },
    { key: "status", label: "Статус", width: "120px", render: (r) => <Badge tone={dealTone(r.status)}>{dealStatusLabel(r.status)}</Badge> },
    { key: "amount_rub", label: "База ₽", align: "right", render: (r) => <span className="font-mono">{money(r.amount_rub, 0)}</span> },
    { key: "client_pays_rub", label: "Клиент ₽", align: "right", render: (r) => <span className="font-mono">{money(r.client_pays_rub, 0)}</span> },
    { key: "markup_pct", label: "%", width: "70px", align: "right", render: (r) => (r.markup_pct != null ? `${r.markup_pct}` : "—") },
    { key: "crypto", label: "Крипта", width: "80px", render: (r) => String(r.crypto ?? "—").toUpperCase() },
    { key: "credited", label: "Начисл. $", align: "right", render: (r) => <span className="font-mono">{money(creditedUsd(r))}</span> },
    { key: "house_profit_usd", label: "Дом $", align: "right", render: (r) => <span className="font-mono">{money(r.house_profit_usd)}</span> },
    { key: "receipt", label: "Чек", width: "70px", render: (r) => (r.has_receipt ? <Badge tone="green">есть</Badge> : "—") },
  ];

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13.5px] font-semibold">Сделки · {total}</div>
        <div className="flex flex-wrap gap-1">
          {([
            ["all", "Все"],
            ["open", "В работе"],
            ["confirmed", "Подтверждены"],
            ["cancelled", "Отмены"],
          ] as const).map(([key, label]) => (
            <Button key={key} size="sm" variant={filter === key ? "primary" : "secondary"} onClick={() => setFilter(key)}>
              {label}
            </Button>
          ))}
        </div>
      </div>
      <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет сделок"} onRowClick={onOpenDeal} />
      <Pager page={page} pages={pages} onPage={setPage} />
    </Card>
  );
}

function LedgerTab({ exchangerId, from, to }: { exchangerId: number; from: string; to: string }) {
  const [rows, setRows] = useState<Dict[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    getExchangerLedger(exchangerId, { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, date_from: from, date_to: to })
      .then((r) => {
        setRows(asRows(r, "entries", "items"));
        setTotal(Number(r.total ?? asRows(r, "entries").length));
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить леджер"))
      .finally(() => setLoading(false));
  }, [exchangerId, from, to, page]);

  useEffect(() => setPage(1), [from, to]);
  useEffect(() => load(), [load]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const cols: Column<Dict>[] = [
    { key: "created_at", label: "Дата", width: "150px", render: (r) => dt(r.created_at) },
    { key: "type", label: "Тип", width: "140px", render: (r) => ledgerTypeLabel(r.type) },
    {
      key: "amount_usd",
      label: "$",
      width: "120px",
      align: "right",
      render: (r) => {
        const n = Number(r.amount_usd ?? 0);
        return <span className={cx("font-mono", n < 0 ? "text-[var(--red)]" : "text-[var(--green)]")}>{n > 0 ? "+" : ""}{money(n)}</span>;
      },
    },
    { key: "deal_id", label: "Сделка", width: "90px", render: (r) => (r.deal_id != null ? <span className="font-mono">#{String(r.deal_id)}</span> : "—") },
    { key: "payout_id", label: "Вывод", width: "90px", render: (r) => (r.payout_id != null ? <span className="font-mono">#{String(r.payout_id)}</span> : "—") },
    { key: "note", label: "Заметка", render: (r) => String(r.note ?? "—") },
  ];

  return (
    <Card>
      <div className="mb-3 text-[13.5px] font-semibold">Леджер · {total}</div>
      <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Пусто"} />
      <Pager page={page} pages={pages} onPage={setPage} />
    </Card>
  );
}

function PayoutsTab({
  exchangerId,
  from,
  to,
  balanceUsd,
  onChanged,
}: {
  exchangerId: number;
  from: string;
  to: string;
  balanceUsd: number;
  onChanged: () => void;
}) {
  const [rows, setRows] = useState<Dict[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [gross, setGross] = useState("");
  const [crypto, setCrypto] = useState("usdt");
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    getExchangerPayouts(exchangerId, { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, date_from: from, date_to: to })
      .then((r) => {
        setRows(asRows(r, "payouts", "items"));
        setTotal(Number(r.total ?? asRows(r, "payouts").length));
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить выплаты"))
      .finally(() => setLoading(false));
  }, [exchangerId, from, to, page]);

  useEffect(() => setPage(1), [from, to]);
  useEffect(() => load(), [load]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      load();
      onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const cols: Column<Dict>[] = [
    { key: "id", label: "#", width: "64px", render: (r) => <span className="font-mono">{String(r.id)}</span> },
    { key: "created_at", label: "Дата", width: "140px", render: (r) => dt(r.created_at) },
    { key: "gross_usd", label: "Списано $", align: "right", render: (r) => <span className="font-mono">{money(r.gross_usd)}</span> },
    { key: "fee_usd", label: "Комиссия $", align: "right", render: (r) => <span className="font-mono">{money(r.fee_usd)}</span> },
    { key: "net_usd", label: "На руки $", align: "right", render: (r) => <span className="font-mono">{money(r.net_usd)}</span> },
    { key: "crypto", label: "Крипта", width: "80px", render: (r) => String(r.crypto ?? "—").toUpperCase() },
    { key: "status", label: "Статус", width: "110px", render: (r) => <Badge tone={payoutTone(r.status)}>{String(r.status ?? "—")}</Badge> },
    {
      key: "act",
      label: "",
      width: "170px",
      render: (r) =>
        r.status === "pending" ? (
          <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
            <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => completePayout(Number(r.id), {}), "Выплата завершена")}>
              Завершить
            </Button>
            <Button size="sm" variant="danger" disabled={busy} onClick={() => act(() => rejectPayout(Number(r.id)), "Отклонено")}>
              Откл
            </Button>
          </div>
        ) : (
          <span className="font-mono text-[12px] text-[var(--text-muted)]">{r.tx_hash ? String(r.tx_hash) : "—"}</span>
        ),
    },
  ];

  return (
    <>
      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Ручной вывод</div>
        <p className="mb-3 text-[12.5px] text-[var(--text-muted)]">Баланс {money(balanceUsd)} $. Запись сразу станет paid и спишется с леджера.</p>
        <div className="grid max-w-lg grid-cols-2 gap-3">
          <Field label="Сумма $">
            <Input inputMode="decimal" value={gross} onChange={(e) => setGross(e.target.value)} className="font-mono" />
          </Field>
          <Field label="Монета">
            <Select value={crypto} onChange={(e) => setCrypto(e.target.value)}>
              <option value="usdt">USDT</option>
              <option value="btc">BTC</option>
              <option value="ltc">LTC</option>
              <option value="trx">TRX</option>
            </Select>
          </Field>
          <div className="col-span-2">
            <Field label="Заметка">
              <Input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          </div>
        </div>
        <div className="mt-3">
          <Button
            variant="primary"
            disabled={busy || Number(gross) <= 0}
            onClick={() =>
              act(async () => {
                await createExchangerPayout(exchangerId, { gross_usd: Number(gross), crypto, note: note.trim() || undefined });
                setGross("");
                setNote("");
              }, "Выплата проведена")
            }
          >
            Выплатить
          </Button>
        </div>
      </Card>
      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Выплаты · {total}</div>
        <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет выплат"} />
        <Pager page={page} pages={pages} onPage={setPage} />
      </Card>
    </>
  );
}

function AccessTab({
  exchangerId,
  hasOwner,
  onCredentials,
}: {
  exchangerId: number;
  hasOwner: boolean;
  onCredentials: (credentials: Dict) => void;
}) {
  const [accounts, setAccounts] = useState<Dict[]>([]);
  const [cabinetUsername, setCabinetUsername] = useState("");
  const [clerkUsername, setClerkUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [ownerIssued, setOwnerIssued] = useState(hasOwner);

  const loadAccounts = useCallback(() => {
    getExchangerAccounts(exchangerId)
      .then((r) => {
        const rows = asRows(r, "items");
        setAccounts(rows);
        setOwnerIssued(rows.some((row) => Boolean(row.is_owner)));
      })
      .catch(() => undefined);
  }, [exchangerId]);

  useEffect(() => loadAccounts(), [loadAccounts]);

  async function issueCabinet() {
    const username = cabinetUsername.trim();
    if (username.length < 3) return toast.error("Логин — минимум 3 символа");
    setBusy(true);
    try {
      const result = await issueExchangerCredentials(exchangerId, username);
      setCabinetUsername("");
      onCredentials(result);
      loadAccounts();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось выдать доступ");
    } finally {
      setBusy(false);
    }
  }

  async function issueClerk() {
    const username = clerkUsername.trim();
    if (username.length < 3) return toast.error("Логин — минимум 3 символа");
    setBusy(true);
    try {
      const result = await createExchangerClerk(exchangerId, { username });
      setClerkUsername("");
      if (result.credentials) onCredentials(result.credentials);
      loadAccounts();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось выдать логин кассира");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 text-[13.5px] font-semibold">
        <KeyRound size={16} /> Логины кабинета
      </div>
      {accounts.length > 0 && (
        <div className="mb-3 flex flex-col divide-y divide-[var(--border)]">
          {accounts.map((account) => (
            <div key={String(account.id)} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div className="text-[13px]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[var(--text-primary)]">{String(account.username ?? "—")}</span>
                  <Badge tone={account.is_owner ? "green" : "default"}>{account.is_owner ? "хозяин" : "кассир"}</Badge>
                  {!account.is_active && <Badge tone="red">отключён</Badge>}
                  {Boolean(account.totp_enabled) && <Badge tone="default">2FA</Badge>}
                </div>
                {Boolean(account.label) && <div className="mt-1 text-[12px] text-[var(--text-muted)]">{String(account.label)}</div>}
              </div>
              <div className="flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={async () => {
                    if (!window.confirm("Старый пароль сразу перестанет работать. Выдать новый случайный и показать данные входа?")) return;
                    setBusy(true);
                    try {
                      onCredentials(await resetExchangerAccountPassword(exchangerId, Number(account.id)));
                      toast.success("Новые данные готовы — сохраните и передайте");
                    } catch (e) {
                      toast.error(e instanceof PanelApiError ? e.message : "Не удалось сбросить пароль");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <RefreshCw size={14} /> Перевыдать пароль
                </Button>
                {!account.is_owner && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await patchExchangerAccount(exchangerId, Number(account.id), { is_active: !account.is_active });
                        loadAccounts();
                      } catch (e) {
                        toast.error(e instanceof PanelApiError ? e.message : "Не удалось изменить доступ");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    {account.is_active ? "Отключить" : "Включить"}
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {ownerIssued ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Логин кассира">
            <Input value={clerkUsername} onChange={(e) => setClerkUsername(e.target.value)} placeholder="например, kassa_night" className="font-mono" />
          </Field>
          <Button size="sm" variant="primary" disabled={busy || clerkUsername.trim().length < 3} onClick={issueClerk}>
            Добавить кассира
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="text-[12px] text-[var(--text-muted)]">Доступ ещё не выдан. Пароль сгенерируется автоматически.</div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Логин хозяина">
              <Input value={cabinetUsername} onChange={(e) => setCabinetUsername(e.target.value)} placeholder="например, exchanger_ivan" className="font-mono" />
            </Field>
            <Button size="sm" variant="primary" disabled={busy || cabinetUsername.trim().length < 3} onClick={issueCabinet}>
              Выдать доступ
            </Button>
          </div>
        </div>
      )}
      <div className="mt-2 mb-4 text-[12px] text-[var(--text-muted)]">
        Вход: /exchanger/login · «Перевыдать пароль» генерирует случайный и показывает его один раз · кассир не видит выводы
      </div>
      <ExchangerApiBlock exchangerId={exchangerId} />
    </Card>
  );
}

function DealModal({ deal, onClose }: { deal: Dict; onClose: () => void }) {
  const [opening, setOpening] = useState(false);
  const rows: { label: string; value: string }[] = [
    { label: "Статус", value: dealStatusLabel(deal.status) },
    { label: "Дата", value: dt(deal.created_at) },
    { label: "База ₽", value: money(deal.amount_rub, 0) },
    { label: "Клиент ₽", value: money(deal.client_pays_rub, 0) },
    { label: "Наценка", value: deal.markup_pct != null ? `${deal.markup_pct}% · ${deal.markup_mode === "on_turnover" ? "с оборота" : "к базе"}` : "—" },
    { label: "Комиссия Payfast ₽", value: money(deal.payfast_fee_rub) },
    { label: "Маржа ₽", value: money(deal.net_profit_rub) },
    { label: "Курс USDT", value: money(deal.usdt_rate_rub, 4) },
    { label: "Principal $", value: money(deal.principal_usdt) },
    { label: "Reward $", value: money(deal.reward_usdt) },
    { label: "Прибыль дома $", value: money(deal.house_profit_usd) },
    { label: "Оператор", value: String(deal.created_by ?? deal.operator_id ?? "—") },
    { label: "Merchant", value: String(deal.merchant_order_id ?? "—") },
    { label: "Крипта", value: String(deal.crypto ?? "—").toUpperCase() },
  ];

  async function openReceipt() {
    setOpening(true);
    try {
      const blob = await fetchExchangerDealReceiptBlob(Number(deal.id));
      window.open(blob.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Чек не открылся");
    } finally {
      setOpening(false);
    }
  }

  return (
    <Modal open title={`Сделка #${deal.id}`} onClose={onClose} size="lg">
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        {rows.map((row) => (
          <div key={row.label}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{row.label}</div>
            <div className="mt-0.5 font-mono text-[13px]">{row.value}</div>
          </div>
        ))}
      </div>
      {deal.note ? <p className="mt-3 text-[13px] text-[var(--text-secondary)]">{String(deal.note)}</p> : null}
      {deal.has_receipt ? (
        <div className="mt-4">
          <Button size="sm" variant="secondary" disabled={opening} onClick={() => void openReceipt()}>
            Открыть чек
          </Button>
        </div>
      ) : null}
    </Modal>
  );
}
