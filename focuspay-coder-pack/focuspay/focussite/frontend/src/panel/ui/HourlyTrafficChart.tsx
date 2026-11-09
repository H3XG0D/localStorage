import { useEffect, useMemo, useState } from "react";
import { getOrders, type AdminOrder } from "@/panel/lib/adminApi";
import { mskClock } from "@/panel/lib/analyticsPeriod";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Card } from "@/panel/ui/primitives";

type PeriodKey = "today" | "yesterday" | "week" | "month" | "year";
type Granularity = "hour" | "day" | "month";

const PAGE = 200;
const MAX_PAGES = 5;

type Bucket = {
  key: string;
  label: string;
  fullLabel: string;
  count: number;
  fiat: number;
  paid: number;
  canceled: number;
  check: number;
  other: number;
};

function money(v: number) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(v);
}

function dateFull(ymd: string) {
  const parsed = new Date(`${ymd}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return ymd;
  return parsed.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" });
}

function dateShort(ymd: string) {
  const parsed = new Date(`${ymd}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return ymd.slice(8);
  return parsed.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

function shiftDay(ymd: string, delta: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10);
}

/** Week on the owner dashboard is Monday→today; if today is Monday that is 1 day. Traffic uses a rolling window. */
function trafficRange(period: PeriodKey, from: string, to: string): { from: string; to: string } {
  if (period === "week") return { from: shiftDay(to, -6), to };
  return { from, to };
}

function eachDay(from: string, to: string): string[] {
  const out: string[] = [];
  const start = from.slice(0, 10);
  const end = to.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return out;
  let cur = start;
  while (cur <= end) {
    out.push(cur);
    const [y, m, d] = cur.split("-").map(Number);
    cur = new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
  }
  return out;
}

function eachMonth(from: string, to: string): string[] {
  const out: string[] = [];
  const start = from.slice(0, 7);
  const end = to.slice(0, 7);
  if (!/^\d{4}-\d{2}$/.test(start) || !/^\d{4}-\d{2}$/.test(end)) return out;
  let cur = start;
  while (cur <= end) {
    out.push(cur);
    const [y, m] = cur.split("-").map(Number);
    const next = new Date(Date.UTC(y, m, 1));
    cur = next.toISOString().slice(0, 7);
  }
  return out;
}

function emptyStats() {
  return { count: 0, fiat: 0, paid: 0, canceled: 0, check: 0, other: 0 };
}

function addOrder(acc: ReturnType<typeof emptyStats>, o: AdminOrder) {
  acc.count += 1;
  acc.fiat += Number(o.fiat_amount ?? 0) || 0;
  const st = String(o.status || "").toUpperCase();
  if (st === "PAID" || st === "COMPLETED") acc.paid += 1;
  else if (st === "CANCELED" || st === "EXPIRED" || st === "FAILED") acc.canceled += 1;
  else if (st === "AWAITING_CHECK" || st === "PENDING") acc.check += 1;
  else acc.other += 1;
}

function granularityOf(period: PeriodKey): Granularity {
  if (period === "today" || period === "yesterday") return "hour";
  if (period === "year") return "month";
  return "day";
}

export function HourlyTrafficChart({
  period,
  dateFrom,
  dateTo,
}: {
  period: PeriodKey;
  dateFrom?: string;
  dateTo?: string;
}) {
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hover, setHover] = useState<number | null>(null);
  const [hourHover, setHourHover] = useState<number | null>(null);

  const rawFrom = String(dateFrom || "").match(/^(\d{4}-\d{2}-\d{2})/)?.[1] || "";
  const rawTo = String(dateTo || "").match(/^(\d{4}-\d{2}-\d{2})/)?.[1] || "";
  const datesOk = /^\d{4}-\d{2}-\d{2}$/.test(rawFrom) && /^\d{4}-\d{2}-\d{2}$/.test(rawTo);
  const win = datesOk ? trafficRange(period, rawFrom, rawTo) : { from: rawFrom, to: rawTo };
  const [from, setFrom] = useState(win.from);
  const [to, setTo] = useState(win.to);

  useEffect(() => {
    if (datesOk) {
      setFrom(win.from);
      setTo(win.to);
    }
  }, [datesOk, win.from, win.to]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setHover(null);
    setHourHover(null);
    (async () => {
      const collected: AdminOrder[] = [];
      let reported = 0;
      const query: Record<string, unknown> = { limit: PAGE };
      if (datesOk) {
        query.date_from = shiftDay(win.from, -1);
        query.date_to = shiftDay(win.to, 1);
      }
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const chunk = await getOrders({ ...query, offset: page * PAGE });
        if (cancelled) return;
        reported = chunk.total ?? 0;
        collected.push(...(chunk.orders ?? []));
        if ((chunk.orders?.length ?? 0) < PAGE || collected.length >= reported) break;
      }
      const stamped = collected
        .map((o) => ({ o, p: mskClock(String(o.created_at ?? "")) }))
        .filter((row): row is { o: AdminOrder; p: NonNullable<ReturnType<typeof mskClock>> } => row.p != null);
      let lo = win.from;
      let hi = win.to;
      if (!datesOk && stamped.length) {
        hi = stamped.reduce((m, row) => (row.p.ymd > m ? row.p.ymd : m), stamped[0].p.ymd);
        lo = trafficRange(period, hi, hi).from;
        if (period !== "week") {
          lo = stamped.reduce((m, row) => (row.p.ymd < m ? row.p.ymd : m), stamped[0].p.ymd);
        }
        setFrom(lo);
        setTo(hi);
      }
      const inWindow = stamped.filter((row) => row.p.ymd >= lo && row.p.ymd <= hi).map((row) => row.o);
      setOrders(inWindow);
      setTotal(inWindow.length);
      setLoading(false);
    })().catch(() => {
      if (!cancelled) {
        setOrders([]);
        setTotal(0);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [datesOk, win.from, win.to, period]);

  const grain = granularityOf(period);
  const showHourProfile = grain === "day";

  const { bars, hourBars, sampledFiat, sampledCount } = useMemo(() => {
    const byKey = new Map<string, ReturnType<typeof emptyStats>>();
    const byHour = Array.from({ length: 24 }, () => emptyStats());
    let sampledFiat = 0;
    for (const o of orders) {
      const p = mskClock(String(o.created_at ?? ""));
      if (!p) continue;
      sampledFiat += Number(o.fiat_amount ?? 0) || 0;
      const key = grain === "hour" ? `${p.ymd}|${p.hour}` : grain === "month" ? p.month : p.ymd;
      if (!byKey.has(key)) byKey.set(key, emptyStats());
      addOrder(byKey.get(key)!, o);
      addOrder(byHour[p.hour], o);
    }

    const bars: Bucket[] = [];
    if (grain === "hour") {
      const day = from || to;
      for (let h = 0; h < 24; h += 1) {
        const st = byKey.get(`${day}|${h}`) ?? emptyStats();
        bars.push({
          key: `${day}-${h}`,
          label: String(h).padStart(2, "0"),
          fullLabel: `${dateFull(day)} · ${String(h).padStart(2, "0")}:00–${String((h + 1) % 24).padStart(2, "0")}:00`,
          ...st,
        });
      }
    } else if (grain === "month") {
      for (const m of eachMonth(from, to)) {
        const st = byKey.get(m) ?? emptyStats();
        const [y] = m.split("-");
        const label = new Date(`${m}-01T12:00:00`).toLocaleDateString("ru-RU", { month: "short" });
        bars.push({
          key: m,
          label,
          fullLabel: `${label} ${y}`,
          ...st,
        });
      }
    } else {
      for (const day of eachDay(from, to)) {
        const st = byKey.get(day) ?? emptyStats();
        bars.push({
          key: day,
          label: dateShort(day),
          fullLabel: dateFull(day),
          ...st,
        });
      }
    }

    const hourBars: Bucket[] = byHour.map((st, h) => ({
      key: `h-${h}`,
      label: String(h).padStart(2, "0"),
      fullLabel: `${String(h).padStart(2, "0")}:00–${String(h).padStart(2, "0")}:59`,
      ...st,
    }));

    return { bars, hourBars, sampledFiat, sampledCount: orders.length };
  }, [orders, grain, from, to]);

  const active = hover != null ? bars[hover] : null;
  const activeHour = hourHover != null ? hourBars[hourHover] : null;
  const truncated = total > sampledCount;
  const dayCount = Math.max(1, grain === "day" ? bars.length : 1);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[13.5px] font-semibold">Трафик заявок</div>
          <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
            {loading
              ? "Считаем…"
              : sampledCount === 0
                ? `нет заявок ${from} — ${to}`
                : `${sampledCount} заявок · ${money(sampledFiat)} ₽ оборот · ${from} — ${to}${truncated ? ` · показано ${sampledCount} из ${total}` : ""}`}
            {period === "week" ? " · последние 7 дней" : ""}
          </div>
        </div>
        <div className="text-[11px] text-[var(--text-secondary)]">
          {grain === "hour" ? "по часам" : grain === "month" ? "по месяцам" : "по дням"}
        </div>
      </div>

      <div className="mt-2">
        {loading ? (
          <div className="flex h-52 items-center justify-center rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] text-[12px] text-[var(--text-muted)]">
            Считаем заявки…
          </div>
        ) : sampledCount === 0 ? (
          <div className="flex h-52 items-center justify-center rounded-[var(--radius)] border border-dashed border-[var(--border-strong)] text-[12px] text-[var(--text-muted)]">
            Нет заявок за {from} — {to}
          </div>
        ) : (
          <LineAreaChart
            points={bars.map((b) => ({ key: b.key, label: b.label }))}
            series={[{ key: "orders", label: "Заявки", color: "var(--green)", values: bars.map((b) => b.count) }]}
            height={216}
            hover={hover}
            onHover={setHover}
            formatTick={(v) => String(Math.round(v))}
            summary={`${sampledCount} заявок · ${money(sampledFiat)} ₽`}
            tooltip={(i) => (
              <div className="flex flex-col gap-0.5">
                <span className="text-[var(--text-primary)]">{bars[i]?.fullLabel}</span>
                <span className="font-mono text-[var(--green)]">{bars[i]?.count ?? 0} заявок · {money(bars[i]?.fiat ?? 0)} ₽</span>
              </div>
            )}
          />
        )}
      </div>
      <DetailBox
        idle={
          grain === "hour"
            ? "Наведите на час: сколько заявок пришло в этот слот, оборот и статусы."
            : grain === "month"
              ? "Наведите на месяц: заявки, оборот, оплачено / отменено."
              : "Наведите на день: заявки, оборот, оплачено / отменено / в проверке."
        }
        bucket={active}
        shareOf={sampledCount}
      />

      {showHourProfile && sampledCount > 0 ? (
        <div className="mt-4 border-t border-[var(--border)] pt-4">
          <div className="mb-2 text-[12.5px] font-semibold">Какие часы живые</div>
          <div className="mb-2 text-[11px] text-[var(--text-muted)]">
            сумма заявок в этот час за все дни окна · среднее = сумма / {dayCount} сут.
          </div>
          <LineAreaChart
            points={hourBars.map((b) => ({ key: b.key, label: b.label }))}
            series={[{ key: "hours", label: "Заявки по часам", color: "var(--blue)", values: hourBars.map((b) => b.count) }]}
            height={168}
            hover={hourHover}
            onHover={setHourHover}
            formatTick={(v) => String(Math.round(v))}
            summary={`${sampledCount} заявок · ${money(sampledFiat)} ₽`}
            tooltip={(i) => (
              <div className="flex flex-col gap-0.5">
                <span className="text-[var(--text-primary)]">{hourBars[i]?.fullLabel}</span>
                <span className="font-mono text-[var(--blue)]">{hourBars[i]?.count ?? 0} заявок · {money(hourBars[i]?.fiat ?? 0)} ₽</span>
              </div>
            )}
          />
          <DetailBox
            idle="Наведите на час суток: сколько заявок суммарно приходило в это время."
            bucket={activeHour}
            shareOf={sampledCount}
            extra={
              activeHour
                ? `среднее ${ (activeHour.count / dayCount).toFixed(1) } заявок/сутки в этот час`
                : undefined
            }
          />
        </div>
      ) : null}
    </Card>
  );
}

function DetailBox({
  idle,
  bucket,
  shareOf,
  extra,
}: {
  idle: string;
  bucket: Bucket | null;
  shareOf: number;
  extra?: string;
}) {
  const pct = bucket && shareOf > 0 ? Math.round((bucket.count / shareOf) * 100) : 0;
  return (
    <div className="mt-3 min-h-[4.5rem] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">
      {bucket ? (
        <div className="flex flex-col gap-1">
          <span className="font-medium text-[var(--text-primary)]">{bucket.fullLabel}</span>
          <span className="text-[var(--text-secondary)]">
            Заявок: <span className="font-mono text-[var(--text-primary)]">{bucket.count}</span>
            {shareOf > 0 ? <span className="text-[var(--text-muted)]"> · {pct}% периода</span> : null}
            <span className="text-[var(--text-muted)]"> · оборот </span>
            <span className="font-mono text-[var(--text-primary)]">{money(bucket.fiat)} ₽</span>
          </span>
          <span className="text-[var(--text-muted)]">
            оплачено {bucket.paid} · отменено {bucket.canceled} · в проверке {bucket.check}
            {bucket.other ? ` · прочие ${bucket.other}` : ""}
          </span>
          {extra ? <span className="text-[var(--text-muted)]">{extra}</span> : null}
        </div>
      ) : (
        <span className="text-[var(--text-muted)]">{idle}</span>
      )}
    </div>
  );
}
