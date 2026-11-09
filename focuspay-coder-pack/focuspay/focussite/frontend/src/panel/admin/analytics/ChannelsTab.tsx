import { useState, useMemo } from "react";
import { Users, TrendingUp, Building2 } from "lucide-react";
import type { Dict } from "@/panel/lib/adminApi";
import type { AnalyticsBundle } from "@/panel/lib/useAnalyticsData";
import { LineAreaChart, type ChartPoint, type ChartSeries } from "@/panel/ui/LineAreaChart";
import { Card, Kpi, Table, Badge, cx, type Column } from "@/panel/ui/primitives";
import { DataIssues } from "@/panel/admin/analytics/DataIssues";
import { asDict, asList, money, num, percent } from "@/panel/admin/analytics/format";

export function ChannelsTab({ data }: { data: AnalyticsBundle }) {
  const [hover, setHover] = useState<number | null>(null);
  
  const pack = asDict(data.partners);
  const partners = Array.isArray(data.partners) ? (data.partners as Dict[]) : asList(pack.partners);
  const summary = asDict(pack.summary);
  const promo = asList(asDict(data.promo).campaigns);
  const ownerRange = data.ownerWindow ? `${data.ownerWindow.from} — ${data.ownerWindow.to}` : `${data.from} — ${data.to}`;
  const extLifetime = asDict(data.external);
  const extPeriod = asDict(asDict(data.stats).summary).external;
  const ext = extPeriod ? asDict(extPeriod) : null;
  const newPartners = asDict(asDict(data.owner?.metrics).new_partners);

  // KPI расчёты
  const totalPartners = num(summary.count) || partners.length;
  const activePartners = num(summary.active_count);
  const partnerTurnover = num(summary.total_turnover_rub);
  const partnerProfit = num(summary.total_service_profit_net_rub);
  
  const avgPromoROI = promo.length > 0 
    ? promo.reduce((sum, p) => sum + num(p.roi_percent), 0) / promo.length 
    : 0;

  // Топ-8 партнёров по обороту
  const topPartners = useMemo(
    () => [...partners].sort((a, b) => num(b.paid_fiat_sum) - num(a.paid_fiat_sum)).slice(0, 8),
    [partners]
  );

  // Колонки для таблицы партнёров
  const partnerCols: Column<Dict>[] = [
    { 
      key: "name", 
      label: "Партнёр", 
      render: (row) => (
        <div className="flex items-center gap-2">
          <div className="flex flex-col">
            <span className="font-medium">{String(row.name ?? row.code ?? "—")}</span>
            <span className="font-mono text-[11px] text-[var(--text-muted)]">{String(row.code ?? "")}</span>
          </div>
        </div>
      )
    },
    { 
      key: "attracted", 
      label: "Привлечено", 
      align: "right", 
      width: "110px",
      render: (row) => <span className="font-mono">{String(row.attracted_users ?? "—")}</span>
    },
    { 
      key: "paid", 
      label: "Оплат", 
      align: "right", 
      width: "90px",
      render: (row) => <span className="font-mono">{String(row.paid_orders_count ?? "—")}</span>
    },
    { 
      key: "pct", 
      label: "Процент", 
      align: "right", 
      width: "100px",
      render: (row) => {
        const pct = row.effective_percent ?? row.partner_commission_percent;
        return <Badge tone="blue">{pct != null ? `${pct}%` : "—"}</Badge>;
      }
    },
    { 
      key: "tier", 
      label: "Прогресс тира", 
      width: "140px",
      render: (row) => {
        if (row.at_max_tier) {
          return <Badge tone="green">Макс. уровень</Badge>;
        }
        const current = num(row.effective_percent);
        const next = num(row.next_tier_percent);
        const progress = row.tier_progress_pct != null ? num(row.tier_progress_pct) : 0;
        return (
          <div className="flex flex-col gap-1">
            <div className="text-[11px] text-[var(--text-muted)]">{current}% → {next}%</div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
              <div 
                className="h-full rounded-full bg-[var(--blue)]" 
                style={{ width: `${Math.min(progress, 100)}%` }}
              />
            </div>
          </div>
        );
      }
    },
    { 
      key: "fiat", 
      label: "Оборот ₽", 
      align: "right", 
      width: "130px",
      render: (row) => <span className="font-mono tabular-nums">{money(row.paid_fiat_sum)}</span>
    },
    { 
      key: "profit", 
      label: "Прибыль ₽", 
      align: "right", 
      width: "130px",
      render: (row) => (
        <span className="font-mono tabular-nums text-[var(--green)]">
          {money(row.service_profit_net_rub ?? row.service_profit_gross_rub)}
        </span>
      )
    },
  ];

  // Колонки для таблицы промо
  const promoCols: Column<Dict>[] = [
    { 
      key: "code", 
      label: "Код кампании", 
      render: (row) => <span className="font-mono">{String(row.code ?? row.name ?? "—")}</span>
    },
    { 
      key: "attracted", 
      label: "Привлечено", 
      align: "right", 
      width: "110px",
      render: (row) => <span className="font-mono">{String(row.attracted_users ?? "—")}</span>
    },
    { 
      key: "paid", 
      label: "Оплат", 
      align: "right", 
      width: "90px",
      render: (row) => <span className="font-mono">{String(row.paid_orders_count ?? "—")}</span>
    },
    { 
      key: "conversion", 
      label: "Конверсия", 
      align: "right", 
      width: "110px",
      render: (row) => {
        const attracted = num(row.attracted_users);
        const paid = num(row.paid_orders_count);
        if (attracted === 0) return "—";
        const conv = (paid / attracted) * 100;
        return <span className="font-mono">{conv.toFixed(1)}%</span>;
      }
    },
    { 
      key: "fiat", 
      label: "Оборот ₽", 
      align: "right", 
      width: "130px",
      render: (row) => <span className="font-mono tabular-nums">{money(row.paid_fiat_sum)}</span>
    },
    { 
      key: "roi", 
      label: "ROI", 
      align: "right", 
      width: "100px",
      render: (row) => {
        const roi = num(row.roi_percent);
        if (roi == null) return "—";
        const tone = roi > 50 ? "green" : roi > 20 ? "yellow" : "red";
        return <Badge tone={tone}>{roi.toFixed(1)}%</Badge>;
      }
    },
  ];

  return (
    <>
      <DataIssues data={data} slices={["partners", "promo", "external", "stats", "owner"]} />

      {/* Верхние KPI */}
      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2">
        <Kpi 
          label="Партнёров" 
          value={String(totalPartners)} 
          hint={`активных ${activePartners} · всего`} 
        />
        <Kpi
          label="Новые партнёры"
          value={String(newPartners.current ?? "—")}
          hint={ownerRange}
          trend={typeof newPartners.pct_change === "number" ? num(newPartners.pct_change) : undefined}
        />
        <Kpi 
          label="Оборот рефералов" 
          value={`${money(partnerTurnover)} ₽`} 
          hint="накопленный, за всё время" 
        />
        <Kpi 
          label="ROI промо (средний)" 
          value={avgPromoROI > 0 ? `${avgPromoROI.toFixed(1)}%` : "—"} 
          hint={`${promo.length} кампаний за период`}
          trend={avgPromoROI > 20 ? avgPromoROI : undefined}
        />
      </div>

      {/* Реферальные партнёры */}
      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Users size={18} className="text-[var(--text-secondary)]" />
          <div className="flex-1">
            <div className="text-[14px] font-semibold">Реферальные партнёры</div>
            <div className="text-[11px] text-[var(--text-muted)]">
              Топ-{topPartners.length} по обороту · данные накопленные за всё время
            </div>
          </div>
        </div>
        <Table columns={partnerCols} rows={topPartners} empty="Нет партнёров" />
        {partners.length > topPartners.length && (
          <div className="mt-3 text-center text-[11px] text-[var(--text-muted)]">
            Показаны топ-{topPartners.length} из {partners.length} партнёров
          </div>
        )}
      </Card>

      {/* Промо-кампании и ROI */}
      <Card>
        <div className="mb-4 flex items-center gap-2">
          <TrendingUp size={18} className="text-[var(--text-secondary)]" />
          <div className="flex-1">
            <div className="text-[14px] font-semibold">Промо-кампании и ROI</div>
            <div className="text-[11px] text-[var(--text-muted)]">
              Период {data.from} — {data.to}
            </div>
          </div>
        </div>

        {/* KPI промо */}
        <div className="mb-4 grid grid-cols-4 gap-3 max-md:grid-cols-2">
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Всего кампаний</div>
            <div className="font-mono text-[20px]">{promo.length}</div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Средний ROI</div>
            <div className={cx("font-mono text-[20px]", avgPromoROI > 20 ? "text-[var(--green)]" : "text-[var(--yellow)]")}>
              {avgPromoROI > 0 ? `${avgPromoROI.toFixed(1)}%` : "—"}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Лучший ROI</div>
            <div className="font-mono text-[20px] text-[var(--green)]">
              {promo.length > 0 
                ? `${Math.max(...promo.map(p => num(p.roi_percent))).toFixed(1)}%` 
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Привлечено</div>
            <div className="font-mono text-[20px]">
              {promo.reduce((sum, p) => sum + num(p.attracted_users), 0)}
            </div>
          </div>
        </div>

        <Table columns={promoCols} rows={promo} empty="Нет кампаний за период" />
      </Card>

      {/* Внештатные обменники */}
      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Building2 size={18} className="text-[var(--text-secondary)]" />
          <div className="flex-1">
            <div className="text-[14px] font-semibold">Внештатные обменники</div>
            <div className="text-[11px] text-[var(--text-muted)]">
              {ext ? `Подтверждённые сделки за ${data.from} — ${data.to}` : "Данные за всё время"}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-4 gap-4 max-md:grid-cols-2">
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Активных обменников</div>
            <div className="font-mono text-[22px] font-bold">{String(extLifetime.active_count ?? "—")}</div>
            <div className="text-[11px] text-[var(--text-muted)]">за всё время</div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Сделок</div>
            <div className="font-mono text-[22px] font-bold">
              {String((ext ? ext.deal_count : extLifetime.total_deals) ?? "—")}
            </div>
            <div className="text-[11px] text-[var(--text-muted)]">{ext ? "за период" : "за всё время"}</div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Оборот ₽</div>
            <div className="font-mono text-[22px] font-bold">
              {money(ext ? ext.turnover_base_rub : extLifetime.total_turnover_base_rub ?? extLifetime.total_turnover_client_rub)}
            </div>
            <div className="text-[11px] text-[var(--text-muted)]">{ext ? "за период" : "за всё время"}</div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--text-muted)]">Прибыль дома $</div>
            <div className="font-mono text-[22px] font-bold text-[var(--green)]">
              {money(ext ? ext.house_profit_usd : extLifetime.house_profit_usd, true)}
            </div>
            <div className="text-[11px] text-[var(--text-muted)]">{ext ? "за период" : "за всё время"}</div>
          </div>
        </div>
      </Card>
    </>
  );
}
