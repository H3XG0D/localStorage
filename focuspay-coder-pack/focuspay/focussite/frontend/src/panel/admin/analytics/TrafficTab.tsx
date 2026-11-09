import { useMemo, useState } from "react";
import type { AnalyticsBundle } from "@/panel/lib/useAnalyticsData";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Card, Kpi } from "@/panel/ui/primitives";
import { DataIssues } from "@/panel/admin/analytics/DataIssues";
import { asDict, asList, dateFull, money, num, ordersTotalLabel } from "@/panel/admin/analytics/format";

const AMOUNT_BUCKETS = [
  { key: "0-1", label: "до 1 000", min: 0, max: 1000 },
  { key: "1-2", label: "1–2 000", min: 1000, max: 2000 },
  { key: "2-3", label: "2–3 000", min: 2000, max: 3000 },
  { key: "3-5", label: "3–5 000", min: 3000, max: 5000 },
  { key: "5-10", label: "5–10 000", min: 5000, max: 10000 },
  { key: "10-25", label: "10–25 000", min: 10000, max: 25000 },
  { key: "25-50", label: "25–50 000", min: 25000, max: 50000 },
  { key: "50-100", label: "50–100 000", min: 50000, max: 100000 },
  { key: "100+", label: "100 000+", min: 100000, max: Infinity },
];

function isPaid(status: unknown) {
  const s = String(status || "").toUpperCase();
  return s === "PAID" || s === "COMPLETED";
}

function eachDay(from: string, to: string): string[] {
  const out: string[] = [];
  let cur = from;
  while (cur <= to) {
    out.push(cur);
    const [y, m, d] = cur.split("-").map(Number);
    cur = new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
  }
  return out;
}

function hourRange(hour: number) {
  const start = String(hour).padStart(2, "0");
  const end = String((hour + 1) % 24).padStart(2, "0");
  return `${start}:00–${end}:00`;
}

function avgLabel(value: number) {
  if (!Number.isFinite(value)) return "0";
  return value >= 10 ? String(Math.round(value)) : value.toFixed(1).replace(".0", "");
}

function ChartLegend({ items }: { items: { color: string; label: string; dashed?: boolean }[] }) {
  return (
    <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-[var(--text-muted)]">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3.5"
            style={{ borderTop: `${item.dashed ? "1.5px dashed" : "2px solid"} ${item.color}` }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function BucketBars({
  rows,
}: {
  rows: { key: string; label: string; count: number; fiat: number }[];
}) {
  const max = Math.max(...rows.map((r) => r.count), 1);
  const totalCount = rows.reduce((s, r) => s + r.count, 0);
  const totalFiat = rows.reduce((s, r) => s + r.fiat, 0);
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row) => (
        <div key={row.key} className="grid grid-cols-[7.5rem_1fr_auto] items-center gap-3 text-[12px]">
          <span className="text-[var(--text-secondary)]">{row.label}</span>
          <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
            <div className="h-full rounded-full bg-[var(--green)]" style={{ width: `${Math.max((row.count / max) * 100, row.count ? 4 : 0)}%` }} />
          </div>
          <span className="font-mono tabular-nums">
            {row.count} шт · {money(row.fiat)} ₽
          </span>
        </div>
      ))}
      <div className="mt-1 flex justify-end font-mono text-[12px] font-semibold tabular-nums">
        {totalCount} заявок · {money(totalFiat)} ₽
      </div>
    </div>
  );
}

export function TrafficTab({ data }: { data: AnalyticsBundle }) {
  const [hourHover, setHourHover] = useState<number | null>(null);
  const [paidHover, setPaidHover] = useState<number | null>(null);
  const [missHover, setMissHover] = useState<number | null>(null);
  const traffic = data.traffic;
  const missStatus = String(data.misses?.data_status ?? "unavailable");
  const missTotal = num(data.misses?.total);
  const days = eachDay(data.from, data.to);
  const dayCount = Math.max(1, days.length);
  const singleDay = dayCount <= 1;

  const hourBars = useMemo(
    () =>
      Array.from({ length: 24 }, (_, hour) => {
        const row = traffic?.by_hour.find((item) => item.hour === hour);
        const count = num(row?.orders);
        const fiat = num(row?.fiat_sum);
        const paid = num(row?.paid_orders);
        const paidFiat = num(row?.paid_fiat_sum);
        return {
          hour,
          label: String(hour).padStart(2, "0"),
          count,
          fiat,
          paid,
          paidFiat,
          avgCount: count / dayCount,
          avgFiat: fiat / dayCount,
          avgPaid: paid / dayCount,
          avgPaidFiat: paidFiat / dayCount,
        };
      }),
    [dayCount, traffic],
  );

  const amountRows = useMemo(
    () =>
      AMOUNT_BUCKETS.map((bucket) => {
        const row = traffic?.amount_buckets.find((item) => item.key === bucket.key);
        return { key: bucket.key, label: bucket.label, count: num(row?.orders), fiat: num(row?.fiat_sum) };
      }),
    [traffic],
  );

  const missHours = useMemo(() => {
    const buckets = Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0, fiat: 0, label: String(hour).padStart(2, "0") }));
    const raw = asList(data.misses?.by_hour);
    if (raw.length) {
      for (const row of raw) {
        const hour = Math.min(23, Math.max(0, Math.round(num(row.hour))));
        buckets[hour].count += num(row.count);
        buckets[hour].fiat += num(row.fiat_sum);
      }
    }
    return buckets.map((bucket) => ({ ...bucket, avgCount: bucket.count / dayCount, avgFiat: bucket.fiat / dayCount }));
  }, [data.misses, dayCount]);

  const statusRows = traffic?.by_status ?? [];
  const originRows = traffic?.by_source ?? [];
  const paidCount = num(traffic?.summary.paid_orders);
  const paidFiat = num(traffic?.summary.paid_fiat_sum);
  const totalOrders = num(traffic?.summary.orders);
  const totalFiat = num(traffic?.summary.fiat_sum);
  const chartCount = hourBars.reduce((sum, bucket) => sum + bucket.count, 0);
  const chartFiat = hourBars.reduce((sum, bucket) => sum + bucket.fiat, 0);
  const chartPaid = hourBars.reduce((sum, bucket) => sum + bucket.paid, 0);
  const chartPaidFiat = hourBars.reduce((sum, bucket) => sum + bucket.paidFiat, 0);
  const missFiat = data.misses?.fiat_sum;
  const missKnown = missStatus === "available" || missStatus === "empty";
  const missShareOk = missKnown && paidCount + missTotal > 0;

  return (
    <>
      <DataIssues data={data} slices={["traffic", "misses"]} />

      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2">
        <Kpi label="Заявок за период" value={String(totalOrders)} hint={`${data.from} — ${data.to} · ${money(totalFiat)} ₽`} />
        <Kpi label="Обработано" value={String(paidCount)} hint={`PAID + COMPLETED · ${money(paidFiat)} ₽`} />
        <Kpi
          label="Пропуски"
          value={
            missKnown
              ? missFiat == null
                ? String(missTotal)
                : `${missTotal} · ${money(missFiat)} ₽`
              : "нет данных"
          }
          hint={missKnown ? "1 клиент / час · сумма первой попытки" : String(asDict(data.misses).reason ?? "ручка недоступна")}
        />
        <Kpi
          label="Доля пропусков"
          value={missShareOk ? `${Math.round((missTotal / (paidCount + missTotal)) * 100)}%` : "—"}
          hint="пропуски / (обработано + пропуски)"
        />
      </div>

      <Card>
        <div className="text-[13.5px] font-semibold">Трафик по часам</div>
        <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
          {singleDay
            ? `Заявки за ${dateFull(data.from)} · часы по Москве`
            : `Среднее этого часа за сутки · по ${dayCount} дням окна · часы по Москве`}
        </div>
        <ChartLegend
          items={[
            { color: "var(--blue)", label: singleDay ? "Заявки" : "Заявки / сутки" },
            ...(missKnown ? [{ color: "var(--red)", label: singleDay ? "Пропуски" : "Пропуски / сутки", dashed: true }] : []),
          ]}
        />
        <LineAreaChart
          points={hourBars.map((b) => ({ key: b.label, label: b.label }))}
          series={[
            {
              key: "hours",
              label: singleDay ? "Заявки" : "Среднее / сутки",
              color: "var(--blue)",
              values: hourBars.map((b) => b.avgCount),
            },
            ...(missKnown
              ? [
                  {
                    key: "miss",
                    label: "Пропуски",
                    color: "var(--red)",
                    dashed: true,
                    fill: false,
                    values: missHours.map((b) => b.avgCount),
                  },
                ]
              : []),
          ]}
          height={200}
          hover={hourHover}
          onHover={setHourHover}
          formatTick={(v) => avgLabel(v)}
          summary={
            singleDay
              ? missKnown
                ? `${ordersTotalLabel(chartCount, chartFiat)} · ${missTotal} пропусков`
                : ordersTotalLabel(chartCount, chartFiat)
              : missKnown
                ? `среднее ${(chartCount / dayCount).toFixed(1)} заявок/сутки · ${avgLabel(missTotal / dayCount)} пропусков/сутки`
                : `среднее ${(chartCount / dayCount).toFixed(1)} заявок/сутки`
          }
          tooltip={(i) => (
            <div className="flex flex-col gap-0.5">
              <span>{hourRange(hourBars[i]?.hour ?? 0)}</span>
              {singleDay ? (
                <>
                  <span className="font-mono text-[var(--blue)]">
                    {hourBars[i]?.count ?? 0} заявок · {money(hourBars[i]?.fiat)} ₽
                  </span>
                  {missKnown ? (
                    <span className="font-mono text-[var(--red)]">
                      {missHours[i]?.count ?? 0} пропусков · {money(missHours[i]?.fiat)} ₽
                    </span>
                  ) : null}
                </>
              ) : (
                <>
                  <span className="font-mono text-[var(--blue)]">
                    среднее {avgLabel(hourBars[i]?.avgCount ?? 0)} заявок/сутки · {money(hourBars[i]?.avgFiat)} ₽/сутки
                  </span>
                  {missKnown ? (
                    <span className="font-mono text-[var(--red)]">
                      среднее {avgLabel(missHours[i]?.avgCount ?? 0)} пропусков/сутки · {money(missHours[i]?.avgFiat)} ₽/сутки
                    </span>
                  ) : null}
                  <span className="font-mono text-[var(--text-muted)]">
                    сумма за {dayCount} дн. {hourBars[i]?.count ?? 0} шт · {money(hourBars[i]?.fiat)} ₽
                    {missKnown ? ` · ${missHours[i]?.count ?? 0} проп. · ${money(missHours[i]?.fiat)} ₽` : ""}
                  </span>
                </>
              )}
            </div>
          )}
        />
      </Card>

      <Card>
        <div className="text-[13.5px] font-semibold">Лимиты по сумме</div>
        <div className="mt-0.5 mb-3 text-[11px] text-[var(--text-muted)]">Сколько заявок попало в коридор суммы, например 1–2 000 — 3 шт.</div>
        <BucketBars rows={amountRows} />
      </Card>

      <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
        <Card>
          <div className="text-[13.5px] font-semibold">Обработано</div>
          <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
            {singleDay ? "PAID + COMPLETED по часам Москвы" : `Среднее PAID + COMPLETED этого часа за ${dayCount} суток`}
          </div>
          <LineAreaChart
            points={hourBars.map((b) => ({ key: b.label, label: b.label }))}
            series={[{ key: "paid", label: "Обработано", color: "var(--green)", values: hourBars.map((b) => b.avgPaid) }]}
            height={188}
            hover={paidHover}
            onHover={setPaidHover}
            formatTick={(v) => avgLabel(v)}
            summary={ordersTotalLabel(chartPaid, chartPaidFiat)}
            tooltip={(i) =>
              singleDay ? (
                <span className="font-mono">
                  {hourRange(hourBars[i]?.hour ?? 0)} · {hourBars[i]?.paid ?? 0} шт · {money(hourBars[i]?.paidFiat)} ₽
                </span>
              ) : (
                <span className="font-mono">
                  {hourRange(hourBars[i]?.hour ?? 0)} · среднее {avgLabel(hourBars[i]?.avgPaid ?? 0)} шт/сутки · {money(hourBars[i]?.avgPaidFiat)} ₽/сутки
                </span>
              )
            }
          />
        </Card>
        <Card>
          <div className="text-[13.5px] font-semibold">Пропуски</div>
          <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
            {missKnown
              ? singleDay
                ? "уникальный клиент в этот час · сумма первой попытки"
                : `среднее этого часа за ${dayCount} суток · 1 клиент / час`
              : "нет данных"}
          </div>
          {!missKnown ? (
            <div className="mt-6 text-center text-[12px] text-[var(--text-muted)]">
              Нет данных по пропускам ({String(asDict(data.misses).reason ?? "ручка не задеплоена")}). Это не ноль.
            </div>
          ) : (
            <LineAreaChart
              points={missHours.map((b) => ({ key: b.label, label: b.label }))}
              series={[
                {
                  key: "miss",
                  label: "Клиенты",
                  color: "var(--red)",
                  values: missHours.map((b) => b.avgCount),
                },
              ]}
              height={188}
              hover={missHover}
              onHover={setMissHover}
              formatTick={(v) => avgLabel(v)}
              summary={missFiat == null ? `${missTotal} клиентов` : `${missTotal} клиентов · ${money(missFiat)} ₽`}
              tooltip={(i) => (
                <div className="flex flex-col gap-0.5">
                  <span>{hourRange(missHours[i]?.hour ?? 0)}</span>
                  {singleDay ? (
                    <span className="font-mono text-[var(--red)]">
                      {missHours[i]?.count ?? 0} кл. · {money(missHours[i]?.fiat)} ₽
                    </span>
                  ) : (
                    <span className="font-mono text-[var(--red)]">
                      среднее {avgLabel(missHours[i]?.avgCount ?? 0)} кл./сутки · {money(missHours[i]?.avgFiat)} ₽/сутки
                    </span>
                  )}
                </div>
              )}
            />
          )}
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">По статусам</div>
          {statusRows.map((row) => (
            <div key={row.status} className="flex justify-between border-b border-[var(--border)] py-1.5 text-[12px] last:border-0">
              <span>{row.status}</span>
              <span className="font-mono">{row.orders}</span>
            </div>
          ))}
        </Card>
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">По источнику</div>
          {originRows.map((row) => (
            <div key={row.source} className="flex justify-between border-b border-[var(--border)] py-1.5 text-[12px] last:border-0">
              <span>{row.source}</span>
              <span className="font-mono">{row.orders}</span>
            </div>
          ))}
        </Card>
      </div>
    </>
  );
}
