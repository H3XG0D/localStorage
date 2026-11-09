import { useEffect, useState } from "react";
import { getVpnSummary, type Dict } from "@/panel/lib/adminApi";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Badge, Card, Kpi, Table, type Column } from "@/panel/ui/primitives";
import { asDict, asList, dateShort, money, moneyRub, num, percent, sum } from "@/panel/admin/analytics/format";
import { NODE_STATE, bytes, loadTone, purchaseTitle } from "@/panel/admin/vpn/format";

type PlanRow = Dict & { plan_code: string };

const PLAN_COLUMNS: Column<PlanRow>[] = [
  { key: "plan_code", label: "Тариф", render: (p) => <span className="font-semibold">{purchaseTitle(p)}</span> },
  { key: "d1", label: "Сегодня", align: "right", render: (p) => `${num(p.count_1d)} · ${moneyRub(p.revenue_rub_1d)}` },
  { key: "d7", label: "7 дней", align: "right", render: (p) => `${num(p.count_7d)} · ${moneyRub(p.revenue_rub_7d)}` },
  { key: "d30", label: "30 дней", align: "right", render: (p) => `${num(p.count_30d)} · ${moneyRub(p.revenue_rub_30d)}` },
];

export function SummaryTab() {
  const [data, setData] = useState<Dict | null>(null);
  const [error, setError] = useState("");
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    getVpnSummary()
      .then(setData)
      .catch((e: Error) => setError(e.message || "не удалось загрузить отчёт"));
  }, []);
  if (error) return <Card className="text-[var(--red)]">{error}</Card>;
  if (!data) return <p className="text-[var(--text-muted)]">Загрузка…</p>;

  const sales = asDict(data.sales);
  const totals = asDict(sales.totals);
  const daily = asList(sales.daily);
  const nodes = asList(data.nodes);
  const byPlan = asList(sales.by_plan) as PlanRow[];
  const revenue = daily.map((d) => num(d.revenue_rub));
  const purchases = daily.map((d) => num(d.purchases));
  const trials = daily.map((d) => num(d.trials));

  return (
    <div className="space-y-5">
      {data.cp_error ? (
        <Card className="border-[var(--yellow)]/40 text-[var(--yellow)]">Control plane недоступен: {String(data.cp_error)}</Card>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Выручка сегодня" value={moneyRub(totals.revenue_rub_1d)} hint={`7 дней: ${moneyRub(totals.revenue_rub_7d)}`} />
        <Kpi label="Выручка 30 дней" value={moneyRub(totals.revenue_rub_30d)} hint={`${num(totals.count_30d)} покупок`} />
        <Kpi
          label="Активные подписки"
          value={money(data.active_subscriptions)}
          hint={`${money(data.active_devices)} устройств · ${money(data.live_connections)} онлайн`}
        />
        <Kpi
          label="Триал → оплата"
          value={percent(sales.trial_conversion_pct)}
          hint={`${num(sales.trial_converted)} из ${num(sales.trials_all)} · триалов за 30 дней: ${num(sales.trials_30d)}`}
        />
      </div>

      {num(sales.open_count) > 0 ? (
        <Card className="flex items-center justify-between gap-3 py-3">
          <span className="text-[13px]">Покупки в обработке — сверка довыдаст или вернёт деньги</span>
          <Badge tone="yellow">{num(sales.open_count)} · {moneyRub(sales.open_rub)}</Badge>
        </Card>
      ) : null}

      <Card>
        <div className="mb-1 text-[13.5px] font-semibold">Продажи за 30 дней</div>
        <div className="mb-4 text-[11px] text-[var(--text-muted)]">Выручка по дню оплаты (UTC), покупки и выданные триалы</div>
        <LineAreaChart
          points={daily.map((d) => ({ key: String(d.date), label: dateShort(d.date) }))}
          series={[
            { key: "revenue", label: "Выручка", color: "var(--green)", values: revenue },
            { key: "purchases", label: "Покупки", color: "var(--blue)", values: purchases, fill: false, axis: "right" },
            { key: "trials", label: "Триалы", color: "var(--purple)", values: trials, fill: false, dashed: true, axis: "right" },
          ]}
          height={220}
          hover={hover}
          onHover={setHover}
          formatTick={(v) => money(v)}
          formatTickRight={(v) => String(Math.round(v))}
          summary={`${moneyRub(sum(revenue))} · ${sum(purchases)} покупок · ${sum(trials)} триалов`}
          tooltip={(i) => (
            <div className="flex flex-col gap-0.5">
              <span>{dateShort(daily[i]?.date)}</span>
              <span className="font-mono text-[var(--green)]">{moneyRub(revenue[i])}</span>
              <span className="font-mono text-[var(--blue)]">{purchases[i]} покупок</span>
              <span className="font-mono text-[var(--purple)]">{trials[i]} триалов</span>
            </div>
          )}
          emptyHint="Продаж ещё не было"
        />
      </Card>

      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">Серверы</div>
          {nodes.length === 0 ? (
            <p className="text-[13px] text-[var(--text-muted)]">Нет данных от control plane</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {nodes.map((node) => <NodeCard key={String(node.node_id)} node={node} />)}
            </div>
          )}
          {asList(data.pauses).length > 0 ? (
            <div className="mt-3 space-y-1 text-[12px] text-[var(--yellow)]">
              {asList(data.pauses).map((p) => (
                <div key={String(p.allocation_id)}>{String(p.node_name || "Нода")}: {String(p.reason)}</div>
              ))}
            </div>
          ) : null}
        </Card>
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">По тарифам</div>
          <Table columns={PLAN_COLUMNS} rows={byPlan} empty="Оплат за 30 дней нет" />
        </Card>
      </div>
    </div>
  );
}

function NodeCard({ node }: { node: Dict }) {
  const load = Math.min(1, Math.max(0, num(node.load)));
  const state = NODE_STATE[String(node.state)] || { label: String(node.state), tone: "default" as const };
  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-semibold">{String(node.name)}</span>
        <Badge tone={state.tone}>{state.label}</Badge>
      </div>
      <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">{String(node.country || "—")}</div>
      <div className="mt-3 flex items-baseline justify-between text-[12px]">
        <span className="text-[var(--text-secondary)]">{num(node.online)} / {num(node.capacity)} онлайн</span>
        <span className="font-mono tabular-nums">{Math.round(load * 100)}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
        <div className="h-full rounded-full transition-all" style={{ width: `${load * 100}%`, background: loadTone(load) }} />
      </div>
      <div className="mt-2 text-[11px] text-[var(--text-muted)]">
        Трафик сегодня: {bytes(num(node.rx_today) + num(node.tx_today))}
      </div>
      {node.status_reason ? (
        <div className="mt-1.5 text-[11px] text-[var(--yellow)]">{String(node.status_reason)}</div>
      ) : null}
    </div>
  );
}
