import { useMemo } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, CircleDollarSign } from "lucide-react";
import type { Dict } from "@/panel/lib/adminApi";
import type { AnalyticsBundle } from "@/panel/lib/useAnalyticsData";
import { Badge, Card, Kpi } from "@/panel/ui/primitives";
import { DataIssues } from "@/panel/admin/analytics/DataIssues";
import { asDict, asList, financeKpi, money, moneyRub, num } from "@/panel/admin/analytics/format";
import type { PeriodPreset } from "@/panel/lib/analyticsPeriod";

function ageSince(value: unknown) {
  const time = new Date(String(value ?? "")).getTime();
  if (!Number.isFinite(time)) return "давно";
  const hours = Math.floor((Date.now() - time) / 3_600_000);
  if (hours < 1) return "меньше часа";
  if (hours < 24) return `${hours} ч`;
  return `${Math.floor(hours / 24)} д ${hours % 24} ч`;
}

/** Hint for owner-sourced metrics: they follow the preset window, not our dates. */
function ownerHint(m: Dict | undefined, window: string) {
  const parts = [window];
  if (m && typeof m.abs_change === "number") parts.push(`к пред. ${m.abs_change > 0 ? "+" : ""}${money(m.abs_change)}`);
  return parts.join(" · ");
}

export function OverviewTab({
  data,
  period,
  loading,
}: {
  data: AnalyticsBundle;
  period: PeriodPreset;
  loading: boolean;
}) {
  const metrics = asDict(data.owner?.metrics);
  const requested = `${data.from} — ${data.to}`;
  const ownerWindow = data.ownerWindow;
  const ownerRange = ownerWindow ? `${ownerWindow.from} — ${ownerWindow.to}` : requested;
  const ownerDiffers = Boolean(ownerWindow && !ownerWindow.matchesRequest);
  const netIncome = financeKpi(data.finance, "owner_residual");
  const grossMargin = financeKpi(data.finance, "service_profit_total");
  const paidDeals = financeKpi(data.finance, "deals");
  const casinoPnl = asDict(asDict(data.finance).pnl).casino;
  const casinoProfit = casinoPnl && typeof casinoPnl === "object" ? num(asDict(casinoPnl).owner_profit_rub) : null;
  const vpnPnl = asDict(asDict(data.finance).pnl).vpn;
  const vpnProfit = vpnPnl && typeof vpnPnl === "object" && "owner_profit_rub" in asDict(vpnPnl)
    ? num(asDict(vpnPnl).owner_profit_rub)
    : null;
  const wallet = asDict(data.live?.wallet);
  const hot = asDict(data.live?.hot_wallet);
  const hotCoins = asList(hot.coins);
  const savings = asDict(data.live?.autopilot_savings);
  const operators = asList(data.live?.operators);
  const sections = asList(data.liab?.sections);
  const shifts = asList(wallet.active_shifts);
  const discrepancies = asList(wallet.discrepancies);
  const onShift = operators.filter((o) => Boolean(o.on_shift));

  const attention = useMemo(() => {
    const items: { tone: "red" | "yellow"; title: string; detail: string; to: string }[] = [];
    discrepancies.forEach((item) =>
      items.push({
        tone: "red",
        title: "Проверить кошелёк",
        detail: String(item.message ?? "Есть расхождение в балансе"),
        to: "/x8/balances",
      }),
    );
    shifts.forEach((shift) => {
      const snapshot = asDict(shift.wallet_snapshot);
      const started = new Date(String(shift.started_at ?? "")).getTime();
      const old = Number.isFinite(started) && Date.now() - started > 24 * 3_600_000;
      if (old || (snapshot.on_shift === true && snapshot.phase === "shift_start")) {
        items.push({
          tone: "yellow",
          title: `${String(shift.operator_name ?? "Оператор")}: смена требует проверки`,
          detail: `Открыта ${ageSince(shift.started_at)} · финальный баланс не введён`,
          to: "/x8/shifts",
        });
      }
    });
    return items;
  }, [discrepancies, shifts]);

  return (
    <>
      <DataIssues data={data} slices={["owner", "finance", "live", "liab"]} />

      {ownerDiffers ? (
        <div className="text-[11px] text-[var(--text-muted)]">
          «Новые пользователи» и «Новые партнёры» приходят из /dashboard/owner, который считает по своему пресету
          ({ownerRange}{period === "custom" ? ", свои даты он не принимает" : ""}). Деньги и сделки — ровно за {requested}.
        </div>
      ) : null}

      <div className="grid grid-cols-7 gap-4 max-xl:grid-cols-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Kpi
          label="Чистый доход"
          value={loading && netIncome.value === null ? "…" : moneyRub(netIncome.value)}
          hint={`Остаток владельца · ${requested}`}
          trend={netIncome.deltaPct}
        />
        <Kpi
          label="Валовая маржа"
          value={loading && grossMargin.value === null ? "…" : moneyRub(grossMargin.value)}
          hint={`Прибыль сервиса с внештатом · ${requested}`}
          trend={grossMargin.deltaPct}
        />
        <Kpi
          label="Казино"
          value={loading && casinoProfit === null ? "…" : moneyRub(casinoProfit, true)}
          hint={`GGR владельца · ${requested}`}
        />
        <Kpi
          label="VPN"
          value={loading && vpnProfit === null ? "…" : vpnProfit === null ? "—" : moneyRub(vpnProfit, true)}
          hint={`После рефералки и кешбэка · ${requested}`}
        />
        <Kpi
          label="Оплаченные сделки"
          value={loading && paidDeals.value === null ? "…" : paidDeals.value === null ? "—" : String(Math.round(paidDeals.value))}
          hint={`Заявки и внештат · ${requested}`}
          trend={paidDeals.deltaPct}
        />
        <Kpi
          label="Новые пользователи"
          value={loading && !metrics.new_users ? "…" : String(asDict(metrics.new_users).current ?? "—")}
          hint={ownerHint(asDict(metrics.new_users), ownerRange)}
          trend={typeof asDict(metrics.new_users).pct_change === "number" ? num(asDict(metrics.new_users).pct_change) : undefined}
        />
        <Kpi
          label="Новые партнёры"
          value={loading && !metrics.new_partners ? "…" : String(asDict(metrics.new_partners).current ?? "—")}
          hint={ownerHint(asDict(metrics.new_partners), ownerRange)}
          trend={typeof asDict(metrics.new_partners).pct_change === "number" ? num(asDict(metrics.new_partners).pct_change) : undefined}
        />
      </div>

      {attention.length > 0 ? (
        <Card className="border-[var(--yellow)]/30">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="size-4 text-[var(--yellow)]" />
            <span className="text-[13.5px] font-semibold">Требует внимания</span>
            <Badge tone="yellow">{attention.length}</Badge>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {attention.map((item, index) => (
              <Link
                key={`${item.title}-${index}`}
                to={item.to}
                className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 hover:border-[var(--border-strong)]"
              >
                <div className="text-[13px] font-semibold">{item.title}</div>
                <div className="mt-0.5 text-[12px] text-[var(--text-secondary)]">{item.detail}</div>
              </Link>
            ))}
          </div>
        </Card>
      ) : (
        <Card className="border-[var(--green)]/20">
          <div className="flex items-center gap-2 text-[13px]">
            <CheckCircle2 className="size-4 text-[var(--green)]" />
            Операционно спокойно. Нет срочных расхождений кошелька
          </div>
        </Card>
      )}

      <div className="grid grid-cols-[1fr_340px] gap-4 max-[1100px]:grid-cols-1">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[13.5px] font-semibold">Операторы онлайн</span>
            <span className="text-[12px] text-[var(--text-muted)]">{onShift.length} на смене</span>
          </div>
          {operators.length === 0 ? (
            <p className="py-6 text-center text-[13px] text-[var(--text-muted)]">Нет данных об операторах.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {operators.map((o, i) => (
                <div key={String(o.id ?? i)} className="flex items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[13px]">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className={`size-2 shrink-0 rounded-full ${o.on_shift ? "bg-[var(--green)]" : "bg-[var(--text-muted)]"}`} />
                    <span className="truncate font-medium">{String(o.name ?? o.username ?? `Оператор ${o.id ?? ""}`)}</span>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-x-4 text-[12px] text-[var(--text-muted)]">
                    <span>в работе: {String(o.orders_in_work ?? 0)}</span>
                    <span>оборот: <span className="font-mono text-[var(--text-primary)]">{moneyRub(o.turnover ?? o.fiat_total)}</span></span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <div className="flex flex-col gap-4">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[13.5px] font-semibold">Горячий кошелёк</span>
              <CircleDollarSign className="size-4 text-[var(--green)]" />
            </div>
            {hot.available !== true ? (
              <p className="text-[13px] text-[var(--text-muted)]">
                {String(hot.floor_phrase || "Нет данных")}
              </p>
            ) : (
              <>
                <div className="font-mono text-2xl font-bold">{money(hot.total_rub)} ₽</div>
                <div className="mt-2 flex flex-col gap-1.5 text-[13px]">
                  {hotCoins.map((c) => (
                    <div key={String(c.coin)} className="flex items-baseline justify-between gap-3">
                      <span className="font-medium">{String(c.coin ?? "").toUpperCase()}</span>
                      <span className="text-right text-[12px] text-[var(--text-secondary)]">
                        <span className="font-mono text-[var(--text-primary)]">{money(c.value_rub)} ₽</span>
                        {" · "}
                        {String(c.phrase ?? "темпа нет")}
                      </span>
                    </div>
                  ))}
                </div>
                {hot.floor_phrase ? (
                  <p className="mt-2 text-[12px] text-[var(--text-muted)]">{String(hot.floor_phrase)}</p>
                ) : null}
              </>
            )}
          </Card>
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[13.5px] font-semibold">Плюс автопилота</span>
              <span className="text-[11px] text-[var(--text-muted)]">7 дней · ставки не меняем</span>
            </div>
            {savings.net_rub == null ? (
              <p className="text-[13px] text-[var(--text-muted)]">{String(savings.line || "Нет данных")}</p>
            ) : (
              <>
                <div className="font-mono text-2xl font-bold">{money(savings.net_rub)} ₽</div>
                <div className="mt-2 flex flex-col gap-1.5 text-[12.5px] text-[var(--text-secondary)]">
                  <div className="flex justify-between gap-3">
                    <span>Операторы</span>
                    <span className="font-mono text-[var(--text-primary)]">{money(savings.operator_save_rub)} ₽</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span>Рефералы до 20%</span>
                    <span className="font-mono text-[var(--text-primary)]">
                      −{money(num(savings.user_referral_extra_rub) + num(savings.partner_extra_rub))} ₽
                    </span>
                  </div>
                  <div className="text-[var(--text-muted)]">Кешбэк не поднимаем</div>
                </div>
              </>
            )}
          </Card>
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[13.5px] font-semibold">Кошельки смен</span>
              <CircleDollarSign className="size-4 text-[var(--green)]" />
            </div>
            <div className="font-mono text-2xl font-bold">{money(wallet.total_rub)} ₽</div>
            <div className="mt-1 text-[12px] text-[var(--text-muted)]">
              {money(wallet.total_usd)} USD · {shifts.length} открытых смен
            </div>
          </Card>
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[13.5px] font-semibold">Обязательства</span>
              <span className="font-mono text-[13px]">{money(data.liab?.total_rub)} ₽</span>
            </div>
            <div className="flex flex-col gap-2 text-[13px]">
              {sections.length === 0 ? (
                <p className="text-[12.5px] text-[var(--text-muted)]">Нет данных.</p>
              ) : (
                sections.map((s, i) => (
                  <div key={i} className="flex items-center justify-between border-b border-[var(--border)] pb-2 last:border-0">
                    <span className="text-[var(--text-secondary)]">{String(s.label ?? s.id ?? "—")}</span>
                    <span className="font-mono">{money(s.amount_rub)} ₽</span>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
