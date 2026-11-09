import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarDays, RefreshCw } from "lucide-react";
import { isLocalDev } from "@/lib/isLocalDev";
import { ANALYTICS_TABS, PERIOD_PRESETS, isYmd, localRange, type AnalyticsTab, type PeriodPreset } from "@/panel/lib/analyticsPeriod";
import { useAnalyticsData } from "@/panel/lib/useAnalyticsData";
import { Badge, Button, Card, Field, Input, PageHeader, cx } from "@/panel/ui/primitives";
import { ChannelsTab } from "@/panel/admin/analytics/ChannelsTab";
import { CasinoTab } from "@/panel/admin/analytics/CasinoTab";
import { ClientsTab } from "@/panel/admin/analytics/ClientsTab";
import { FinanceTab } from "@/panel/admin/analytics/FinanceTab";
import { OverviewTab } from "@/panel/admin/analytics/OverviewTab";
import { TrafficTab } from "@/panel/admin/analytics/TrafficTab";

function parseTab(raw: string | null): AnalyticsTab {
  return ANALYTICS_TABS.some((t) => t.key === raw) ? (raw as AnalyticsTab) : "overview";
}

function parsePreset(raw: string | null): PeriodPreset {
  return PERIOD_PRESETS.some((p) => p.key === raw) ? (raw as PeriodPreset) : "week";
}

function TabWait({ text }: { text: string }) {
  return (
    <Card>
      <div className="py-10 text-center text-[13px] text-[var(--text-muted)]">{text}</div>
    </Card>
  );
}

export function AdminDashboard() {
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const preset = parsePreset(params.get("period"));
  const fallback = useMemo(() => localRange("week"), []);
  const [customFrom, setCustomFrom] = useState(() => params.get("from") || fallback.from);
  const [customTo, setCustomTo] = useState(() => params.get("to") || fallback.to);
  const dateFrom = preset === "custom" && isYmd(customFrom) ? customFrom : fallback.from;
  const dateTo = preset === "custom" && isYmd(customTo) ? customTo : fallback.to;

  const data = useAnalyticsData(
    preset,
    preset === "custom" ? customFrom : dateFrom,
    preset === "custom" ? customTo : dateTo,
    tab,
  );

  function setTab(next: AnalyticsTab) {
    const nextParams = new URLSearchParams(params);
    if (next === "overview") nextParams.delete("tab");
    else nextParams.set("tab", next);
    setParams(nextParams, { replace: true });
  }

  function setPreset(next: PeriodPreset) {
    const nextParams = new URLSearchParams(params);
    if (next === "week") nextParams.delete("period");
    else nextParams.set("period", next);
    if (next === "custom") {
      const from = isYmd(data.from) ? data.from : customFrom;
      const to = isYmd(data.to) ? data.to : customTo;
      setCustomFrom(from);
      setCustomTo(to);
      nextParams.set("from", from);
      nextParams.set("to", to);
    } else {
      nextParams.delete("from");
      nextParams.delete("to");
    }
    setParams(nextParams, { replace: true });
  }

  function setCustomDate(kind: "from" | "to", value: string) {
    const nextFrom = kind === "from" ? value : customFrom;
    const nextTo = kind === "to" ? value : customTo;
    if (kind === "from") setCustomFrom(value);
    else setCustomTo(value);
    const nextParams = new URLSearchParams(params);
    nextParams.set("period", "custom");
    if (isYmd(nextFrom)) nextParams.set("from", nextFrom);
    if (isYmd(nextTo)) nextParams.set("to", nextTo);
    setParams(nextParams, { replace: true });
  }

  const subtitle = data.stale
    ? "данные могут быть устаревшими"
    : data.updatedAt
      ? `обновлено ${data.updatedAt.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
      : "загрузка";

  return (
    <>
      <PageHeader
        title="Аналитика"
        subtitle={`${subtitle} · ${data.from} — ${data.to} · Москва · доход ≠ оборот`}
        actions={
          <Button size="sm" variant="secondary" onClick={() => void data.reload()} disabled={data.loading || data.refreshing}>
            <RefreshCw className={data.loading || data.refreshing ? "size-3.5 animate-spin" : "size-3.5"} /> Обновить
          </Button>
        }
      />

      <Card className="grid gap-3 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-end">
        <div className="flex items-center gap-2 text-[12px] text-[var(--text-secondary)] md:pb-1">
          <CalendarDays className="size-4" /> Период
        </div>
        <div className="flex min-w-0 flex-wrap gap-1 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-1">
          {PERIOD_PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => setPreset(p.key)}
              className={cx(
                "rounded-[var(--radius-sm)] px-3 py-1.5 text-[12px] font-medium transition-colors",
                preset === p.key ? "bg-[var(--accent)] text-[var(--text-inverse)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        {preset === "custom" ? (
          <div className="grid grid-cols-2 gap-2">
            <Field label="С">
              <Input type="date" value={customFrom} onChange={(e) => setCustomDate("from", e.target.value)} />
            </Field>
            <Field label="По">
              <Input type="date" value={customTo} onChange={(e) => setCustomDate("to", e.target.value)} />
            </Field>
          </div>
        ) : (
          <span className="rounded-full border border-[var(--border)] px-2.5 py-1.5 text-[11px] tabular-nums text-[var(--text-muted)]">
            {data.from} — {data.to}
          </span>
        )}
      </Card>

      <div className="flex w-fit flex-wrap gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        {ANALYTICS_TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={cx(
              "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
              tab === item.key ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {data.loading ? <Badge tone="blue">Загрузка…</Badge> : data.refreshing ? <Badge tone="blue">Обновление…</Badge> : null}
      {isLocalDev() ? (
        <div className="text-[11px] text-[var(--text-muted)]">
          Локальный снимок: неделя дампа, не боевые цифры. Если пропусков нет в дампе — это «нет данных», не ноль.
        </div>
      ) : null}

      {tab === "overview" ? <OverviewTab data={data} period={preset} loading={data.loading} /> : null}
      {tab === "finance" ? data.loading ? <TabWait text="Считаем финансы…" /> : <FinanceTab data={data} /> : null}
      {tab === "casino" ? data.loading ? <TabWait text="Считаем казино…" /> : <CasinoTab data={data} /> : null}
      {tab === "traffic" ? data.loading || (!data.traffic && !data.errors.traffic) ? <TabWait text="Считаем трафик…" /> : <TrafficTab data={data} /> : null}
      {tab === "clients" ? data.loading ? <TabWait text="Считаем клиентов…" /> : <ClientsTab data={data} /> : null}
      {tab === "channels" ? data.loading ? <TabWait text="Считаем каналы…" /> : <ChannelsTab data={data} /> : null}
    </>
  );
}
