import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getPartners, getTierSettings, patchTierSettings, type Dict } from "@/panel/lib/adminApi";
import { BuyerAvatar } from "@/panel/ui/BuyerAvatar";
import { Badge, Button, Card, Field, Input, Kpi, PageHeader, Select, Table, type Column } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}
function pct(v: unknown) {
  return v == null || v === "" ? "—" : `${Number(v)}%`;
}
async function copyText(value: string, ok = "Скопировано") {
  try {
    await navigator.clipboard.writeText(value);
    toast.success(ok);
  } catch {
    toast.error("Не удалось скопировать");
  }
}

type KpiKey = "all" | "active" | "balance" | "accrued" | "paid_out" | "turnover" | "profit_gross" | "profit_net";
type StatusFilter = "all" | "active" | "off";

function num(v: unknown): number {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}
function parseBound(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

export function AdminPartners() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Dict[]>([]);
  const [summary, setSummary] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [kpi, setKpi] = useState<KpiKey>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [refsFrom, setRefsFrom] = useState("");
  const [refsTo, setRefsTo] = useState("");
  const [turnFrom, setTurnFrom] = useState("");
  const [turnTo, setTurnTo] = useState("");
  const [profitFrom, setProfitFrom] = useState("");
  const [profitTo, setProfitTo] = useState("");
  const [balFrom, setBalFrom] = useState("");
  const [balTo, setBalTo] = useState("");
  const [pctFrom, setPctFrom] = useState("");
  const [pctTo, setPctTo] = useState("");
  const PAGE_SIZE = 20;

  const load = useCallback(() => {
    setLoading(true);
    getPartners()
      .then((r) => {
        if (Array.isArray(r)) {
          setRows(r);
          setSummary(null);
          return;
        }
        setRows((r.partners as Dict[]) || []);
        setSummary((r.summary as Dict) || null);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  function clickKpi(next: KpiKey) {
    setKpi(next);
    setPage(1);
    if (next === "active") setStatus("active");
    if (next === "all") setStatus("all");
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rf = parseBound(refsFrom);
    const rt = parseBound(refsTo);
    const tf = parseBound(turnFrom);
    const tt = parseBound(turnTo);
    const pf = parseBound(profitFrom);
    const pt = parseBound(profitTo);
    const bf = parseBound(balFrom);
    const bt = parseBound(balTo);
    const xf = parseBound(pctFrom);
    const xt = parseBound(pctTo);
    let list = rows.filter((row) => {
      const active = row.is_active && row.partner_is_active !== false;
      if (status === "active" && !active) return false;
      if (status === "off" && active) return false;
      if (q && !`${row.code ?? ""} ${row.name ?? ""} ${row.partner_username ?? ""} ${row.partner_display_name ?? ""}`.toLowerCase().includes(q)) {
        return false;
      }
      const refs = num(row.attracted_users);
      const turn = num(row.paid_fiat_sum);
      const profit = num(row.service_profit_net_rub);
      const bal = num(row.balance_rub);
      const percent = num(row.effective_percent ?? row.partner_commission_percent);
      if (rf != null && refs < rf) return false;
      if (rt != null && refs > rt) return false;
      if (tf != null && turn < tf) return false;
      if (tt != null && turn > tt) return false;
      if (pf != null && profit < pf) return false;
      if (pt != null && profit > pt) return false;
      if (bf != null && bal < bf) return false;
      if (bt != null && bal > bt) return false;
      if (xf != null && percent < xf) return false;
      if (xt != null && percent > xt) return false;
      if (kpi === "balance" && bal <= 0) return false;
      if (kpi === "accrued" && num(row.total_accrued) <= 0) return false;
      if (kpi === "paid_out" && num(row.total_paid_out) <= 0) return false;
      if (kpi === "turnover" && turn <= 0) return false;
      if (kpi === "profit_gross" && num(row.service_profit_gross_rub) <= 0) return false;
      if (kpi === "profit_net" && profit <= 0) return false;
      return true;
    });
    const sortKey: Record<KpiKey, string | null> = {
      all: null,
      active: null,
      balance: "balance_rub",
      accrued: "total_accrued",
      paid_out: "total_paid_out",
      turnover: "paid_fiat_sum",
      profit_gross: "service_profit_gross_rub",
      profit_net: "service_profit_net_rub",
    };
    const sk = sortKey[kpi];
    if (sk) list = list.slice().sort((a, b) => num(b[sk]) - num(a[sk]));
    return list;
  }, [rows, search, status, kpi, refsFrom, refsTo, turnFrom, turnTo, profitFrom, profitTo, balFrom, balTo, pctFrom, pctTo]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const cols: Column<Dict>[] = [
    {
      key: "avatar",
      label: "",
      width: "44px",
      render: (r) => (
        <BuyerAvatar
          avatarUrl={typeof r.avatar_url === "string" ? r.avatar_url : null}
          name={typeof r.partner_display_name === "string" ? r.partner_display_name : typeof r.name === "string" ? r.name : null}
          username={typeof r.partner_username === "string" ? r.partner_username : null}
          userId={typeof r.telegram_user_id === "number" ? r.telegram_user_id : null}
          size="sm"
        />
      ),
    },
    { key: "code", label: "Код", render: (r) => <span className="font-mono">{String(r.code || `#${r.id}`)}</span> },
    { key: "name", label: "Название", render: (r) => String(r.name || r.partner_display_name || "—") },
    { key: "effective_percent", label: "Эффект. %", width: "100px", align: "right", render: (r) => pct(r.effective_percent ?? r.partner_commission_percent) },
    { key: "attracted_users", label: "Рефы", width: "80px", align: "right", render: (r) => String(r.attracted_users ?? "—") },
    { key: "paid_fiat_sum", label: "Оборот ₽", width: "120px", align: "right", render: (r) => <span className="font-mono">{money(r.paid_fiat_sum)}</span> },
    { key: "service_profit_gross_rub", label: "Gross ₽", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.service_profit_gross_rub)}</span> },
    { key: "service_profit_net_rub", label: "Net ₽", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.service_profit_net_rub)}</span> },
    { key: "balance_rub", label: "Баланс ₽", width: "120px", align: "right", render: (r) => <span className="font-mono">{money(r.balance_rub)}</span> },
    {
      key: "tier",
      label: "След. уровень",
      render: (r) =>
        r.at_max_tier ? (
          "макс."
        ) : r.next_tier_percent != null ? (
          <span>
            {pct(r.next_tier_percent)} · ещё {String(r.refs_until_next_tier ?? "—")}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "links",
      label: "Ссылки",
      width: "90px",
      render: (r) => {
        const web = String(r.referral_web_link ?? "");
        const tg = String(r.referral_link ?? "");
        return (
          <div className="flex gap-1">
            {web ? (
              <Button size="sm" variant="ghost" title="Сайт" onClick={(e) => { e.stopPropagation(); void copyText(web, "Ссылка сайта"); }}>
                <Copy size={13} />
              </Button>
            ) : null}
            {tg ? (
              <Button size="sm" variant="ghost" title="Telegram" onClick={(e) => { e.stopPropagation(); void copyText(tg, "Ссылка Telegram"); }}>
                TG
              </Button>
            ) : null}
          </div>
        );
      },
    },
    { key: "is_active", label: "Статус", width: "110px", render: (r) => <Badge tone={r.is_active && r.partner_is_active !== false ? "green" : "red"}>{r.is_active && r.partner_is_active !== false ? "активен" : "выключен"}</Badge> },
  ];

  return (
    <>
      <PageHeader title="Партнёры" subtitle="Реферальные партнёры, уровни и кабинет · клик по KPI фильтрует список" />
      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Kpi label="Всего" value={String(summary?.count ?? rows.length)} active={kpi === "all"} onClick={() => clickKpi("all")} />
        <Kpi label="Активных" value={String(summary?.active_count ?? "—")} active={kpi === "active"} onClick={() => clickKpi("active")} />
        <Kpi label="К выплате, ₽" value={money(summary?.total_balance_rub)} hint="баланс > 0" active={kpi === "balance"} onClick={() => clickKpi("balance")} />
        <Kpi label="Начислено, ₽" value={money(summary?.total_accrued_rub)} hint="начисления > 0" active={kpi === "accrued"} onClick={() => clickKpi("accrued")} />
        <Kpi label="Выплачено, ₽" value={money(summary?.total_paid_out_rub)} hint="выплаты > 0" active={kpi === "paid_out"} onClick={() => clickKpi("paid_out")} />
        <Kpi label="Оборот, ₽" value={money(summary?.total_turnover_rub)} hint="оборот > 0" active={kpi === "turnover"} onClick={() => clickKpi("turnover")} />
        <Kpi label="Прибыль gross, ₽" value={money(summary?.total_service_profit_gross_rub)} hint="gross > 0" active={kpi === "profit_gross"} onClick={() => clickKpi("profit_gross")} />
        <Kpi label="Прибыль net, ₽" value={money(summary?.total_service_profit_net_rub)} hint="net > 0" active={kpi === "profit_net"} onClick={() => clickKpi("profit_net")} />
      </div>
      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Фильтры по метрикам</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <RangeField label="Рефы" from={refsFrom} to={refsTo} onFrom={setRefsFrom} onTo={setRefsTo} />
          <RangeField label="Оборот ₽" from={turnFrom} to={turnTo} onFrom={setTurnFrom} onTo={setTurnTo} />
          <RangeField label="Прибыль net ₽" from={profitFrom} to={profitTo} onFrom={setProfitFrom} onTo={setProfitTo} />
          <RangeField label="Баланс ₽" from={balFrom} to={balTo} onFrom={setBalFrom} onTo={setBalTo} />
          <RangeField label="Эффект. %" from={pctFrom} to={pctTo} onFrom={setPctFrom} onTo={setPctTo} />
          <Field label="Статус">
            <Select value={status} onChange={(e) => { setStatus(e.target.value as StatusFilter); setPage(1); }}>
              <option value="all">Все</option>
              <option value="active">Активные</option>
              <option value="off">Выключенные</option>
            </Select>
          </Field>
        </div>
      </Card>
      <TierCard />
      <Card>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div className="text-[13.5px] font-semibold">Список партнёров · {filtered.length}</div>
          <Field label="Поиск">
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Код / имя / логин" className="w-[220px]" />
          </Field>
        </div>
        <Table columns={cols} rows={visible} empty={loading ? "Загрузка…" : "Пусто"} onRowClick={(r) => navigate(`/x8/partners/${r.id}`)} />
        <div className="mt-4 flex items-center justify-between text-[12px] text-[var(--text-muted)]">
          <span>Стр. {page}/{pages}</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>Назад</Button>
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>Вперёд</Button>
          </div>
        </div>
      </Card>
    </>
  );
}

function RangeField({
  label,
  from,
  to,
  onFrom,
  onTo,
}: {
  label: string;
  from: string;
  to: string;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
}) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-1">
        <Input inputMode="decimal" value={from} onChange={(e) => onFrom(e.target.value)} placeholder="от" className="font-mono" />
        <span className="text-[var(--text-muted)]">–</span>
        <Input inputMode="decimal" value={to} onChange={(e) => onTo(e.target.value)} placeholder="до" className="font-mono" />
      </div>
    </Field>
  );
}

function TierCard() {
  const [settings, setSettings] = useState<Dict | null>(null);
  const [preview, setPreview] = useState<Dict[]>([]);
  const [base, setBase] = useState("");
  const [step, setStep] = useState("");
  const [everyN, setEveryN] = useState("");
  const [maxPct, setMaxPct] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getTierSettings()
      .then((r) => {
        const s = ((r.settings as Dict | undefined) ?? r) as Dict;
        setSettings(s);
        setPreview(Array.isArray(r.preview) ? (r.preview as Dict[]) : []);
        setBase(s.partner_tier_base_percent == null ? "" : String(s.partner_tier_base_percent));
        setStep(s.partner_tier_step_percent == null ? "" : String(s.partner_tier_step_percent));
        setEveryN(s.partner_tier_every_n == null ? "" : String(s.partner_tier_every_n));
        setMaxPct(s.partner_tier_max_percent == null ? "" : String(s.partner_tier_max_percent));
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"));
  }, []);

  useEffect(() => load(), [load]);

  async function save() {
    setBusy(true);
    try {
      await patchTierSettings({
        partner_tier_base_percent: base === "" ? undefined : Number(base),
        partner_tier_step_percent: step === "" ? undefined : Number(step),
        partner_tier_every_n: everyN === "" ? undefined : Number(everyN),
        partner_tier_max_percent: maxPct === "" ? undefined : Number(maxPct),
      });
      toast.success("Сохранено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 text-[13.5px] font-semibold">Настройки уровней</div>
      <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Field label="Базовый процент">
          <Input inputMode="decimal" value={base} onChange={(e) => setBase(e.target.value)} className="font-mono" disabled={!settings} />
        </Field>
        <Field label="Шаг">
          <Input inputMode="decimal" value={step} onChange={(e) => setStep(e.target.value)} className="font-mono" disabled={!settings} />
        </Field>
        <Field label="Каждые N">
          <Input inputMode="numeric" value={everyN} onChange={(e) => setEveryN(e.target.value)} className="font-mono" disabled={!settings} />
        </Field>
        <Field label="Макс. процент">
          <Input inputMode="decimal" value={maxPct} onChange={(e) => setMaxPct(e.target.value)} className="font-mono" disabled={!settings} />
        </Field>
      </div>
      {preview.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-[12px] text-[var(--text-muted)]">
          {preview.map((p, i) => (
            <span key={i} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] px-2 py-1 font-mono">
              {String(p.refs ?? p.attracted ?? i)} реф. → {pct(p.percent ?? p.effective_percent)}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3">
        <Button variant="primary" disabled={busy || !settings} onClick={save}>Сохранить уровни</Button>
      </div>
    </Card>
  );
}
