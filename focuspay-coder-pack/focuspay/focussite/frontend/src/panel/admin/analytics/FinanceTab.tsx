import { useEffect, useMemo, useState } from "react";
import { Info, TrendingDown, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { getPricing, getTriangleOverview, patchPricing, type Dict } from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import type { AnalyticsBundle } from "@/panel/lib/useAnalyticsData";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Badge, Button, Card, Field, Input, Kpi, Table, cx, type Column } from "@/panel/ui/primitives";
import { DataIssues } from "@/panel/admin/analytics/DataIssues";
import { asDict, asList, dateShort, financeKpi, money, num, percent, signedMoney, sum } from "@/panel/admin/analytics/format";

function findWaterfall(pnl: Dict, key: string) {
  return num(asList(pnl.waterfall).find((step) => String(step.key) === key)?.amount);
}

function directionLabel(type: string) {
  if (type === "auto_buy") return "Авто-покупка";
  if (type === "manual_buy") return "Ручная покупка";
  if (type === "sell") return "Продажа";
  if (type === "casino") return "Казино";
  if (type === "vpn") return "VPN";
  return type;
}

/**
 * A daily series must add up to the KPI above it. Tolerate rounding and payroll
 * date attribution, but surface anything bigger — silence is how the two numbers
 * drifted apart unnoticed.
 */
function reconcile(chartSum: number, kpi: number): string | null {
  const diff = chartSum - kpi;
  const scale = Math.max(Math.abs(kpi), 1);
  if (Math.abs(diff) < 100 || Math.abs(diff) / scale < 0.01) return null;
  return `ряд ${money(chartSum)} ≠ KPI ${money(kpi)} (${diff > 0 ? "+" : ""}${money(diff)} ₽)`;
}

function WaterfallChart({ steps }: { steps: Dict[] }) {
  const visible = steps.filter((step) => {
    const key = String(step.key);
    if (key === "fiat_volume") return false;
    if (key === "casino_profit") return true;
    return Math.abs(num(step.amount)) > 0.009;
  });
  const max = Math.max(...visible.map((step) => Math.abs(num(step.amount))), 1);
  if (!visible.length) return <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">Нет движений за период</div>;
  return (
    <div className="flex flex-col gap-3">
      {visible.map((step, index) => {
        const amount = num(step.amount);
        return (
          <div key={`${String(step.key)}-${index}`} className="grid grid-cols-[minmax(130px,1fr)_minmax(120px,1.5fr)_auto] items-center gap-3 text-[12px]">
            <span className={cx("truncate", step.kind === "total" && "font-semibold")}>{String(step.label ?? "—")}</span>
            <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
              <div className={cx("h-full rounded-full", amount >= 0 ? "bg-[var(--green)]" : "bg-[var(--red)]")} style={{ width: `${Math.max((Math.abs(amount) / max) * 100, 2)}%` }} />
            </div>
            <span className={cx("font-mono", amount >= 0 ? "text-[var(--green)]" : "text-[var(--red)]")}>{signedMoney(amount)}</span>
          </div>
        );
      })}
    </div>
  );
}

function ExpenseBreakdown({ pnl }: { pnl: Dict }) {
  const costs = asDict(pnl.costs);
  const payroll = asDict(pnl.payroll);
  const manual = asDict(pnl.manual_expenses);
  const recurring = asDict(pnl.recurring_expenses);
  const rows = [
    ["Кешбэк", costs.cashback],
    ["Реферальные", costs.referral],
    ["Партнёрские", costs.partner],
    ["Бонусы за отзывы", costs.review_bonus],
    ["Выплаты на кошельки", costs.wallet_payout],
    ["FocusLucky", costs.focus_lucky],
    ["Комиссии swap", costs.swap_commission],
    ["Реквизитный пул", costs.payout_requisites],
    ["Зарплата операторов", payroll.operators_total],
    ["Зарплата админов", payroll.admin_salary],
    ["USDT операторам", costs.usdt_issued_rub],
    ["Подписки (recurring)", recurring.total],
    ["Ручные расходы", manual.total],
  ]
    .map(([label, amount]) => ({ label: String(label), amount: num(amount) }))
    .filter((row) => row.amount > 0.009);
  const max = Math.max(...rows.map((row) => row.amount), 1);
  return (
    <div className="flex flex-col gap-3">
      {rows.length ? (
        rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[150px_1fr_auto] items-center gap-3 text-[12px]">
            <span className="truncate text-[var(--text-secondary)]">{row.label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
              <div className="h-full rounded-full bg-[var(--orange)]" style={{ width: `${Math.max((row.amount / max) * 100, 2)}%` }} />
            </div>
            <span className="font-mono">{money(row.amount, true)} ₽</span>
          </div>
        ))
      ) : (
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">Расходов за период нет — в снимке затраты не разложены.</div>
      )}
    </div>
  );
}

/**
 * Пул чужих карт под выплаты: своя стоимость против того же объёма,
 * прогнанного через провайдера карт. Отрицательная стоимость — заработали.
 */
function RequisitePool({ pool }: { pool: Dict }) {
  const turnover = num(pool.turnover_rub);
  if (turnover <= 0) {
    return (
      <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">
        За период реквизиты не закрывались.
      </div>
    );
  }
  const cost = num(pool.cost_rub);
  const saving = num(pool.saving_rub);
  const feePct = num(pool.card_fee_pct);
  return (
    <>
      <div className="grid grid-cols-3 gap-3 max-[520px]:grid-cols-1">
        <Kpi label="Оборот пула" value={`${money(turnover)} ₽`} hint={`${num(pool.requisites)} реквизит(ов)`} />
        <Kpi
          label="Стоимость"
          value={`${signedMoney(cost)} ₽`}
          hint={`в среднем ${num(pool.avg_cost_pct).toFixed(2)}%`}
        />
        <Kpi
          label={`Экономия против ${feePct.toFixed(0)}%`}
          value={`${signedMoney(saving)} ₽`}
          hint={`провайдер взял бы ${money(pool.card_fee_cost_rub)} ₽`}
        />
      </div>
      <div className="mt-3 text-[11px] text-[var(--text-muted)]">
        Стоимость с плюсом — доплатили реквизитчику, с минусом — реквизит принёс доход.
      </div>
    </>
  );
}

export function FinanceTab({ data }: { data: AnalyticsBundle }) {
  const [hover, setHover] = useState<number | null>(null);
  const stats = asDict(data.stats);
  const fin = asDict(data.finance);
  const pnl = asDict(fin.pnl);
  const total = asDict(pnl.total);
  const payroll = asDict(pnl.payroll);
  const capitalTurnover = asDict(pnl.capital_turnover);
  const statsChart = asList(stats.chart);
  const chart = asList(fin.chart).length ? asList(fin.chart) : statsChart;
  const byType = asList(pnl.by_type);
  const ledger = asDict(data.owner?.ledger);
  const serviceProfit = findWaterfall(pnl, "service_profit");
  const netProfit = num(total.net_profit);
  const finalResidual = num(payroll.owner_residual);
  const downstreamCosts = netProfit - finalResidual;
  const internalTurnover = num(total.fiat_volume);
  const externalTurnover = Math.max(num(total.fiat_volume_with_external) - internalTurnover, 0);
  const turnoverKpi = internalTurnover + externalTurnover;
  const kpiTurnover = financeKpi(fin, "turnover");
  const kpiDeals = financeKpi(fin, "deals");
  const kpiServiceProfit = financeKpi(fin, "service_profit");
  const kpiAfterCosts = financeKpi(fin, "after_costs");
  const kpiResidual = financeKpi(fin, "owner_residual");
  const dealsCount =
    kpiDeals.value ?? (byType.reduce((acc, row) => acc + num(row.orders), 0) || num(asDict(stats.summary).total_orders_paid));

  const points = useMemo(() => {
    // /finance-overview daily rows carry no external turnover; /stats has it, so
    // merge by date — otherwise the series can never add up to the KPI above it.
    const externalByDate = new Map<string, number>();
    for (const row of statsChart) externalByDate.set(String(row.date ?? ""), num(row.external_turnover_rub));
    return chart.map((row) => {
      const date = String(row.date ?? "");
      return {
        date,
        turnover: num(row.buy_fiat) + num(row.sell_fiat) + (externalByDate.get(date) ?? 0),
        net: num(row.profit_net_total ?? row.profit_net ?? row.profit),
      };
    });
  }, [chart, statsChart]);

  const hasFinance = Object.keys(pnl).length > 0;
  const chartTurnover = sum(points.map((p) => p.turnover));
  const chartNet = sum(points.map((p) => p.net));
  const turnoverGap = hasFinance ? reconcile(chartTurnover, turnoverKpi) : null;
  const netGap = hasFinance ? reconcile(chartNet, finalResidual) : null;

  const cryptoCols: Column<Dict>[] = [
    { key: "crypto", label: "Актив", render: (row) => String(row.crypto ?? "—").toUpperCase() },
    { key: "count", label: "Заявок", align: "right", render: (row) => String(row.count ?? "—") },
    { key: "fiat", label: "Оборот ₽", align: "right", render: (row) => <span className="font-mono">{money(row.fiat_volume, true)}</span> },
  ];

  return (
    <>
      <DataIssues data={data} slices={["finance", "stats", "owner"]} />

      {hasFinance ? (
        <div className="grid grid-cols-3 gap-4 max-xl:grid-cols-2 max-[620px]:grid-cols-1">
          <Kpi label="Оборот" value={`${money(turnoverKpi)} ₽`} hint={externalTurnover ? `Внутр. ${money(internalTurnover)} · внеш. ${money(externalTurnover)}` : "Покупки и продажи"} trend={kpiTurnover.deltaPct} />
          <Kpi label="Оплаченные сделки" value={String(Math.round(dealsCount))} hint="Заявки и внештат" trend={kpiDeals.deltaPct} />
          <Kpi label="Плюс по сделкам" value={`${money(serviceProfit)} ₽`} hint="Маржа после комиссии карты" trend={kpiServiceProfit.deltaPct} />
          <Kpi label="После начислений" value={`${money(total.profit_after_costs)} ₽`} hint="Кешбэк, рефералка, бонусы, FocusLucky" trend={kpiAfterCosts.deltaPct} />
          <Kpi label="Расходы после маржи" value={`${money(downstreamCosts)} ₽`} hint="Зарплаты, USDT, ручные" />
          <Kpi label="Результат владельца" value={`${money(finalResidual)} ₽`} hint={`Маржа ${percent(total.owner_margin_pct ?? total.margin_after_costs_pct)}`} trend={kpiResidual.deltaPct} />
          <Kpi
            label="Оборачиваемость капитала"
            value={capitalTurnover.available ? `${num(capitalTurnover.turnover).toFixed(2)}×` : "—"}
            hint={capitalTurnover.available ? `Капитал ${money(capitalTurnover.capital_rub)} ₽ · снимок ${dateShort(String(capitalTurnover.snapshot_date ?? ""))}` : "Нет снимка капитала до начала периода"}
          />
        </div>
      ) : (
        <Card className="border-[var(--yellow)]/30">
          <div className="text-[12px] text-[var(--yellow)]">
            Финансовый отчёт не загрузился — денежные показатели скрыты, чтобы не выдать нули за реальные цифры. Ниже
            остаются операционные данные из /stats.
          </div>
        </Card>
      )}

      <div className="grid grid-cols-[minmax(0,1.55fr)_minmax(300px,1fr)] gap-4 max-[1050px]:grid-cols-1">
        <Card>
          <div className="mb-1 flex items-start justify-between gap-3">
            <div>
              <div className="text-[13.5px] font-semibold">Оборот и результат по дням</div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                Оборот — левая ось, результат владельца — правая · {data.from} — {data.to}
              </div>
            </div>
            <Badge tone={finalResidual >= 0 ? "green" : "red"}>{finalResidual >= 0 ? "Период в плюсе" : "Период в минусе"}</Badge>
          </div>
          {turnoverGap || netGap ? (
            <div className="mb-2 text-[11px] text-[var(--yellow)]">
              Сумма ряда не сходится с KPI: {[turnoverGap ? `оборот — ${turnoverGap}` : null, netGap ? `результат — ${netGap}` : null].filter(Boolean).join("; ")}
            </div>
          ) : null}
          <LineAreaChart
            points={points.map((p) => ({ key: p.date, label: dateShort(p.date) }))}
            series={[
              { key: "turnover", label: "Оборот", color: "var(--blue)", values: points.map((p) => p.turnover) },
              { key: "net", label: "Результат владельца", color: "var(--green)", values: points.map((p) => p.net), fill: false, axis: "right" },
            ]}
            height={220}
            hover={hover}
            onHover={setHover}
            formatTick={(v) => money(v)}
            formatTickRight={(v) => money(v)}
            summary={`${money(chartTurnover)} ₽ оборот · ${money(chartNet)} ₽ результат`}
            tooltip={(i) => (
              <div className="flex flex-col gap-0.5">
                <span>{dateShort(points[i]?.date)}</span>
                <span className="font-mono text-[var(--blue)]">{money(points[i]?.turnover)} ₽ оборот</span>
                <span className="font-mono text-[var(--green)]">{money(points[i]?.net)} ₽ результат</span>
              </div>
            )}
            emptyHint="Нет дневного ряда за период"
          />
        </Card>
        <Card>
          <div className="mb-1 text-[13.5px] font-semibold">Состав результата</div>
          <div className="mb-4 text-[11px] text-[var(--text-muted)]">Маржа → расходы → результат владельца</div>
          <WaterfallChart steps={asList(pnl.waterfall)} />
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <Card>
          <div className="mb-1 text-[13.5px] font-semibold">Куда уходят деньги</div>
          <ExpenseBreakdown pnl={pnl} />
        </Card>
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">Результат по направлению</div>
          {byType.filter((row) => String(row.type) !== "external").map((row) => (
            <div key={String(row.type)} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-[var(--border)] py-2 text-[12px] last:border-0">
              <span>{directionLabel(String(row.type))}</span>
              <span className="text-[var(--text-muted)]">{String(row.type) === "casino" ? "—" : `${money(row.fiat_volume)} ₽`}</span>
              <span className={cx("font-mono", num(row.net_profit) >= 0 ? "text-[var(--green)]" : "text-[var(--red)]")}>{signedMoney(row.net_profit)}</span>
            </div>
          ))}
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <Card>
          <div className="mb-3 flex items-center gap-2 text-[13.5px] font-semibold"><TrendingUp className="size-4 text-[var(--green)]" /> Покупка по активам</div>
          <Table columns={cryptoCols} rows={asList(stats.by_crypto_buy)} empty="Нет данных" />
        </Card>
        <Card>
          <div className="mb-3 flex items-center gap-2 text-[13.5px] font-semibold"><TrendingDown className="size-4 text-[var(--red)]" /> Продажа по активам</div>
          <Table columns={cryptoCols} rows={asList(stats.by_crypto_sell)} empty="Нет данных" />
        </Card>
      </div>

      <TrianglePanel from={data.from} to={data.to} />

      <Card>
        <div className="mb-1 text-[13.5px] font-semibold">Реквизитный пул</div>
        <div className="mb-4 text-[11px] text-[var(--text-muted)]">Закрытые реквизиты выплат за период</div>
        <RequisitePool pool={asDict(pnl.payout_requisites)} />
      </Card>

      <Card>
        <div className="text-[13.5px] font-semibold">Журнал операций</div>
        <div className="mt-1 text-[12px] text-[var(--text-muted)]">
          {String(ledger.data_status ?? "unavailable") === "available"
            ? "Подтверждённые проводки за период"
            : "Журнал недоступен. Показатели считаются из PnL / снимка."}
        </div>
        {asList(ledger.by_type).map((row, i) => (
          <div key={i} className="mt-2 flex justify-between border-b border-[var(--border)] pb-2 text-[13px] last:border-0">
            <span>{String(row.type ?? "—")}</span>
            <span className="font-mono">{money(row.amount_rub)} ₽</span>
          </div>
        ))}
      </Card>

      <Card className="bg-[var(--bg-elevated)]">
        <div className="flex items-start gap-3 text-[12px] text-[var(--text-secondary)]">
          <Info className="mt-0.5 size-4 shrink-0 text-[var(--blue)]" />
          Дневной ряд берётся из /admin/stats и /finance-overview по выбранным датам, поэтому месяц и год не упираются в
          лимит 7 дней у /dashboard/owner. Дни бэкенд режет по серверной дате заявки, а часы в «Трафике» — по Москве,
          поэтому на границе суток возможен сдвиг.
        </div>
      </Card>
    </>
  );
}

function TrianglePanel({ from, to }: { from: string; to: string }) {
  const [enabled, setEnabled] = useState(true);
  const [bonus, setBonus] = useState("3");
  const [minCard, setMinCard] = useState("500");
  const [providerPct, setProviderPct] = useState(12);
  const [flatFee, setFlatFee] = useState(100);
  const [overview, setOverview] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getPricing()
      .then((row) => {
        if (!alive) return;
        const settings = asDict(row.settings);
        setEnabled(settings.triangle_enabled !== false);
        setBonus(String(settings.triangle_sell_bonus_pct ?? 3));
        setMinCard(String(settings.min_withdraw_card_rub ?? 20000));
        setProviderPct(num(settings.card_fee_auto_pct) || 12);
      })
      .catch(() => {
        if (alive) toast.error("Не удалось прочитать настройки треугольника");
      });
    getTriangleOverview(from, to)
      .then((row) => {
        if (!alive) return;
        setOverview(row);
        if (row.provider_fee_pct != null) setProviderPct(num(row.provider_fee_pct));
        if (row.withdraw_flat_fee_rub != null) setFlatFee(num(row.withdraw_flat_fee_rub));
      })
      .catch(() => {
        if (alive) setOverview(null);
      });
    return () => {
      alive = false;
    };
  }, [from, to]);

  async function save() {
    const bonusNum = Number(bonus);
    const minNum = Number(minCard);
    if (!Number.isFinite(bonusNum) || bonusNum < 0 || bonusNum > 20) {
      toast.error("Доплата от 0 до 20%");
      return;
    }
    if (!Number.isFinite(minNum) || minNum < 1) {
      toast.error("Минимум вывода должен быть больше нуля");
      return;
    }
    setBusy(true);
    try {
      await patchPricing({
        triangle_enabled: enabled,
        triangle_sell_bonus_pct: bonusNum,
        min_withdraw_card_rub: Math.round(minNum),
      });
      toast.success("Сохранено");
      const fresh = await getTriangleOverview(from, to);
      setOverview(fresh);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  const open = asDict(overview?.open);
  const forecast = asDict(overview?.forecast);
  const period = asDict(overview?.period);

  return (
    <Card>
      <div className="mb-1 text-[13.5px] font-semibold">Треугольник</div>
      <p className="mb-4 text-[12px] text-[var(--text-muted)]">
        Карта в пуле не платит провайдеру {providerPct}%. Продаже крипты на карту доплачиваем процент ниже. Вывод с баланса: {money(flatFee)} ₽ и 0%.
      </p>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-2 pb-2 text-[13px]">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Включён
        </label>
        <Field label="Доплата за продажу, %">
          <Input value={bonus} onChange={(e) => setBonus(e.target.value)} className="w-24 font-mono" inputMode="decimal" />
        </Field>
        <Field label="Минимум вывода на карту, ₽">
          <Input value={minCard} onChange={(e) => setMinCard(e.target.value)} className="w-28 font-mono" inputMode="numeric" />
        </Field>
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          Сохранить
        </Button>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 text-[13px] max-[700px]:grid-cols-1">
        <Mini label="Продажа крипты" value={`${open.sell_cards ?? 0} карт · ${money(open.sell_amount_rub)} ₽`} />
        <Mini label="Вывод с баланса и казино" value={`${open.withdraw_cards ?? 0} карт · ${money(open.withdraw_amount_rub)} ₽`} />
        <Mini label="Уже пришло" value={`${money(open.paid_rub)} ₽`} />
        <Mini label="Забронировано" value={`${money(open.reserved_rub)} ₽`} />
      </div>
      <div className="mb-2 text-[12px] text-[var(--text-muted)]">Если открытые карты закроются</div>
      <PlusLines row={forecast} />
      <div className="mb-2 mt-4 text-[12px] text-[var(--text-muted)]">За период</div>
      <PlusLines row={period} />
    </Card>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2">
      <div className="text-[11px] text-[var(--text-muted)]">{label}</div>
      <div className="font-mono text-[13px]">{value}</div>
    </div>
  );
}

function PlusLines({ row }: { row: Dict }) {
  const lines = [
    ["Не заплатили провайдеру", row.saved_provider_rub],
    ["Доплата за продажу крипты", row.sell_bonus_rub],
    ["Доплата коридора", row.subsidy_rub ?? 0],
    ["Комиссия вывода на карту", row.withdraw_fee_rub],
    ["Долив", row.doliv_rub],
    ["Итог", row.net_rub],
  ] as const;
  return (
    <div className="flex flex-col gap-1 text-[13px]">
      {lines.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-3">
          <span className={label === "Итог" ? "font-semibold" : "text-[var(--text-secondary)]"}>{label}</span>
          <span className="font-mono">{money(value)} ₽</span>
        </div>
      ))}
    </div>
  );
}
