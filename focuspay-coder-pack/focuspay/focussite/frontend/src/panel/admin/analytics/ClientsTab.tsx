import { useMemo, useState } from "react";
import type { AdminOrder } from "@/panel/lib/adminApi";
import type { AnalyticsBundle } from "@/panel/lib/useAnalyticsData";
import { previousRange } from "@/panel/lib/analyticsPeriod";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Badge, Card, Kpi } from "@/panel/ui/primitives";
import { DataIssues } from "@/panel/admin/analytics/DataIssues";
import { asDict, asList, dateShort, money, num, sum } from "@/panel/admin/analytics/format";

const CYCLE = [
  { key: "1", label: "1 заявка", test: (n: number) => n === 1 },
  { key: "2-4", label: "2–4 заявки", test: (n: number) => n >= 2 && n <= 4 },
  { key: "5-9", label: "5–9 заявок", test: (n: number) => n >= 5 && n <= 9 },
  { key: "10+", label: "10+ заявок", test: (n: number) => n >= 10 },
];

function isPaid(status: unknown) {
  const s = String(status || "").toUpperCase();
  return s === "PAID" || s === "COMPLETED";
}

/** Paid orders only — retention on the backend counts paid deals, so counting
 *  cancelled ones here would put two different metrics side by side. */
function cycleOf(orders: AdminOrder[]) {
  const perUser = new Map<string, number>();
  for (const o of orders) {
    if (!isPaid(o.status)) continue;
    const uid = String(o.user_id ?? "");
    if (!uid) continue;
    perUser.set(uid, (perUser.get(uid) || 0) + 1);
  }
  const total = perUser.size || 1;
  return CYCLE.map((row) => {
    const count = [...perUser.values()].filter(row.test).length;
    return { ...row, count, share: Math.round((count / total) * 100), unique: perUser.size };
  });
}

function deltaPct(now: number, before: number) {
  if (before <= 0) return now > 0 ? 100 : 0;
  return Math.round(((now - before) / before) * 100);
}

/** Same segment, same source, current vs previous window. */
function segment(cohorts: unknown, prevCohorts: unknown, key: "new_clients" | "repeaters" | "frequent") {
  const current = asDict(asDict(asDict(cohorts).retention)[key]).period;
  const before = asDict(asDict(asDict(prevCohorts).retention)[key]).period;
  const has = current !== null && current !== undefined;
  return {
    value: has ? String(current) : "—",
    trend: has && before !== null && before !== undefined && num(before) > 0 ? deltaPct(num(current), num(before)) : undefined,
  };
}

export function ClientsTab({ data }: { data: AnalyticsBundle }) {
  const [hover, setHover] = useState<number | null>(null);
  const retention = asDict(data.cohorts?.retention);
  const newUsers = asDict(asDict(data.owner?.metrics).new_users);
  const breakdown = asDict(newUsers.breakdown);
  const buckets = asList(data.cohorts?.buckets);
  const prevWindow = previousRange(data.from, data.to);
  const ownerRange = data.ownerWindow ? `${data.ownerWindow.from} — ${data.ownerWindow.to}` : `${data.from} — ${data.to}`;

  const cycle = useMemo(() => cycleOf(data.orders), [data.orders]);
  const prevCycle = useMemo(() => cycleOf(data.prevOrders ?? []), [data.prevOrders]);

  const unique = cycle[0]?.unique ?? 0;
  const prevUnique = prevCycle[0]?.unique ?? 0;
  const newClients = segment(data.cohorts, data.prevCohorts, "new_clients");
  const repeaters = segment(data.cohorts, data.prevCohorts, "repeaters");
  const frequent = segment(data.cohorts, data.prevCohorts, "frequent");
  const chart = asList(retention.chart);
  const chartNew = sum(chart.map((r) => num(r.new_clients)));
  const chartRepeaters = sum(chart.map((r) => num(r.repeaters)));
  const chartFrequent = sum(chart.map((r) => num(r.frequent)));

  return (
    <>
      <DataIssues data={data} slices={["cohorts", "prevCohorts", "orders", "prevOrders", "owner"]} />

      {data.truncated ? (
        <Card>
          <div className="text-[12px] text-[var(--text-muted)]">
            Выборка заявок обрезана: {data.orders.length} из {data.ordersTotal}. «Уникальных клиентов» и «Цикличность»
            считаются по этой выборке, сегменты ниже — по полному периоду из /volume-cohorts.
          </div>
        </Card>
      ) : null}

      <div className="grid grid-cols-5 gap-4 max-xl:grid-cols-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Kpi
          label="Уникальных клиентов"
          value={String(unique)}
          hint="с оплаченной заявкой в периоде"
          trend={prevUnique > 0 ? deltaPct(unique, prevUnique) : undefined}
        />
        <Kpi label="Новые клиенты" value={newClients.value} hint="1-я оплаченная сделка в периоде" trend={newClients.trend} />
        <Kpi label="Вернувшиеся" value={repeaters.value} hint="2-я сделка в жизни попала в период" trend={repeaters.trend} />
        <Kpi label="Частые" value={frequent.value} hint="2+ сделок, средний интервал ≤3 дней" trend={frequent.trend} />
        <Kpi
          label="Регистрации"
          value={String(newUsers.current ?? "—")}
          hint={`бот ${breakdown.bot_new ?? "—"} · веб ${breakdown.web_new ?? "—"} · ${ownerRange}`}
          trend={typeof newUsers.pct_change === "number" ? num(newUsers.pct_change) : undefined}
        />
      </div>

      <Card>
        <div className="text-[13.5px] font-semibold">Цикличность</div>
        <div className="mt-0.5 mb-3 text-[11px] text-[var(--text-muted)]">
          Сколько клиентов сделали 1 / 2–4 / 5–9 / 10+ оплаченных заявок в этом окне. Прирост — к предыдущему окну{" "}
          {prevWindow.from} — {prevWindow.to}
        </div>
        <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
          {cycle.map((row) => {
            const before = prevCycle.find((p) => p.key === row.key)?.count ?? 0;
            const delta = row.count - before;
            const pct = deltaPct(row.count, before);
            return (
              <div key={row.key} className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[11px] text-[var(--text-muted)]">{row.label}</div>
                  <Badge tone={delta > 0 ? "green" : delta < 0 ? "red" : "default"}>
                    {delta > 0 ? "+" : ""}
                    {delta}
                  </Badge>
                </div>
                <div className="mt-1 font-mono text-[22px] font-semibold">{row.count}</div>
                <div className="text-[11px] text-[var(--text-secondary)]">{row.share}% клиентов</div>
                <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                  было {before}
                  {before > 0 ? ` · ${pct > 0 ? "+" : ""}${pct}%` : delta > 0 ? " · новые в этой корзине" : ""}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <Card>
        <div className="text-[13.5px] font-semibold">Когорты по объёму</div>
        <div className="mt-0.5 mb-3 text-[11px] text-[var(--text-muted)]">
          Пороги 50к / 100к / 200к ₽ из /dashboard/volume-cohorts · накопленный объём за всё время
        </div>
        <div className="grid grid-cols-3 gap-3">
          {buckets.length ? (
            buckets.map((b) => (
              <div key={String(b.threshold)} className="rounded-[var(--radius)] border border-[var(--border)] p-3">
                <div className="text-[11px] text-[var(--text-muted)]">{String(b.label ?? `${money(b.threshold)}+`)}</div>
                <div className="mt-1 font-mono text-[22px] font-semibold">{String(b.count ?? 0)}</div>
                <div className="text-[11px] text-[var(--text-secondary)]">клиентов</div>
              </div>
            ))
          ) : (
            <div className="col-span-3 py-8 text-center text-[12px] text-[var(--text-muted)]">Когорты недоступны</div>
          )}
        </div>
      </Card>

      <Card>
        <div className="text-[13.5px] font-semibold">Новые, вернувшиеся, частые по дням</div>
        <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
          Ряд из /volume-cohorts, дни по Москве · {data.from} — {data.to}
        </div>
        <LineAreaChart
          points={chart.map((row) => ({ key: String(row.date ?? ""), label: dateShort(row.date) }))}
          series={[
            { key: "new", label: "Новые", color: "var(--blue)", values: chart.map((r) => num(r.new_clients)) },
            { key: "rep", label: "Вернувшиеся", color: "var(--green)", values: chart.map((r) => num(r.repeaters)), fill: false },
            { key: "freq", label: "Частые", color: "var(--purple)", values: chart.map((r) => num(r.frequent)), fill: false },
          ]}
          height={220}
          hover={hover}
          onHover={setHover}
          formatTick={(v) => String(Math.round(v))}
          summary={`${chartNew} новых · ${chartRepeaters} вернувшихся · ${chartFrequent} частых`}
          tooltip={(i) => (
            <div className="flex flex-col gap-0.5">
              <span>{dateShort(chart[i]?.date)}</span>
              <span>новые {num(chart[i]?.new_clients)}</span>
              <span>вернувшиеся {num(chart[i]?.repeaters)}</span>
              <span>частые {num(chart[i]?.frequent)}</span>
            </div>
          )}
          emptyHint="Нет ряда retention"
        />
      </Card>
    </>
  );
}
