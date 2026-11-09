import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getOperatorSla, getOperatorStats, getOperators, postOperatorPenalty, type Dict } from "@/panel/lib/adminApi";
import { isoDate, shiftIso } from "@/panel/lib/analyticsPeriod";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, cx } from "@/panel/ui/primitives";
import { OperatorEditModal } from "@/panel/admin/AdminOperators";

type PeriodKey = "month" | 7 | 30 | 90;

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: "month", label: "Месяц" },
  { key: 7, label: "7 дней" },
  { key: 30, label: "30 дней" },
  { key: 90, label: "90 дней" },
];

function money(v: unknown, digits = 0) {
  if (v == null || v === "") return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(v));
}
function hours(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(Number(v ?? 0));
}
function cryptoAmt(v: unknown) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 8 });
}
function dt(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
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
function deltaCls(n: number | null | undefined) {
  if (n == null || n === 0) return "text-[var(--text-muted)]";
  return n > 0 ? "text-[var(--green)]" : "text-[var(--orange)]";
}
function fmtDelta(n: number | null | undefined) {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${cryptoAmt(n)}`;
}
function asList(v: unknown): Dict[] {
  return Array.isArray(v) ? (v as Dict[]) : [];
}
function ledgerTypeLabel(t: unknown) {
  const key = String(t || "");
  if (key === "accrual") return "Начисление";
  if (key === "hold") return "Холд";
  if (key === "payout") return "Выплата";
  if (key === "release") return "Возврат";
  if (key === "penalty") return "Штраф";
  if (key === "hourly") return "Часы";
  return key || "—";
}
function parseOperatorId(param: string | undefined, pathname: string): number | null {
  const fromParam = Number(param);
  if (Number.isInteger(fromParam) && fromParam > 0) return fromParam;
  const m = pathname.match(/\/operators\/(\d+)\/?$/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isInteger(n) && n > 0 ? n : null;
}
function operatorFromState(state: unknown, oid: number | null): Dict | null {
  if (oid == null || !state || typeof state !== "object") return null;
  const op = (state as { operator?: Dict }).operator;
  if (!op || typeof op !== "object") return null;
  return Number(op.id) === oid ? op : null;
}
function rolesOf(r: Dict) {
  return Array.isArray(r.operator_roles) ? r.operator_roles.map(String) : [String(r.operator_role ?? "client")];
}
function gradeLabel(g: unknown) {
  const v = String(g || "");
  if (v === "trainee") return "Стажёр";
  if (v === "senior") return "Старший";
  if (v === "junior") return "Новичок";
  return v || "Новичок";
}

export function AdminOperatorDetail() {
  const { id: idParam } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const oid = parseOperatorId(idParam, location.pathname);
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [payload, setPayload] = useState<Dict | null>(null);
  const [sla, setSla] = useState<Dict | null>(null);
  const [listRow, setListRow] = useState<Dict | null>(() => operatorFromState(location.state, oid));
  const [loading, setLoading] = useState(oid != null);
  const [editOpen, setEditOpen] = useState(false);
  const [penaltyOpen, setPenaltyOpen] = useState(false);
  const [hover, setHover] = useState<number | null>(null);

  const load = useCallback(() => {
    if (oid == null) {
      setLoading(false);
      setPayload(null);
      return;
    }
    const { from, to } = periodRange(period);
    setLoading(true);
    getOperatorStats(oid, { date_from: from, date_to: to })
      .then((stats) => setPayload(stats))
      .catch((e) => {
        setPayload(null);
        toast.error(e instanceof PanelApiError ? e.message : "Оператор не найден");
      })
      .finally(() => setLoading(false));
    getOperatorSla(oid, period === "month" ? Math.max(1, new Date().getDate()) : period)
      .then((slaStats) => setSla(slaStats))
      .catch(() => setSla(null));
    getOperators({ status: "all" })
      .then((listed) => {
        const ops = Array.isArray(listed) ? listed : ((listed as Dict).operators as Dict[]) || [];
        const found = ops.find((r) => Number(r.id) === oid) ?? null;
        if (found) setListRow(found);
      })
      .catch(() => {});
  }, [oid, period]);

  useEffect(() => load(), [load]);
  useEffect(() => {
    const seeded = operatorFromState(location.state, oid);
    if (seeded) setListRow((prev) => prev ?? seeded);
  }, [location.state, oid]);

  const operator = { ...(listRow || {}), ...((payload?.operator ?? {}) as Dict) } as Dict;
  const summary = (payload?.summary ?? {}) as Dict;
  const totals = (payload?.totals ?? {}) as Dict;
  const daily = asList(payload?.daily);
  const dailyBalances = asList(payload?.daily_balances);
  const shifts = asList(payload?.shifts);
  const viewFinance = payload ? payload.can_view_finance !== false : false;
  const payroll = (payload?.payroll ?? {}) as Dict;
  const payrollLedger = asList(payload?.payroll_ledger);
  const slaClaim = (sla?.time_to_claim ?? {}) as Dict;
  const slaComplete = (sla?.time_to_complete ?? {}) as Dict;
  const slaBreaches = (sla?.sla_breaches ?? {}) as Dict;
  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "период";
  const name = String(operator.display_name || operator.username || (oid != null ? `Оператор ${oid}` : "Оператор"));
  const editSource = listRow ?? (Number.isFinite(Number(operator.id)) ? operator : null);
  const roleList = operator.username || operator.operator_roles || operator.operator_role ? rolesOf(operator) : [];
  const grades = (operator.role_grades ?? {}) as Dict;

  const dailyChrono = useMemo(
    () => [...daily].sort((a, b) => String(a.date).localeCompare(String(b.date))),
    [daily],
  );
  const chartPoints = dailyChrono.map((d) => ({ key: String(d.date), label: dayLabel(d.date) }));
  const usdtTotals = useMemo(() => {
    if (!dailyBalances.length) return null;
    const sorted = [...dailyBalances].sort((a, b) => String(a.date).localeCompare(String(b.date)));
    let recv = 0;
    let sent = 0;
    let gapIn = 0;
    let gapOut = 0;
    for (const row of sorted) {
      const usdt = asList(row.summary).find((s) => String(s.crypto).toLowerCase() === "usdt");
      if (!usdt) continue;
      recv += Number(usdt.recv_in_sell ?? 0);
      sent += Number(usdt.sent_in_buy ?? 0);
      gapIn += Number(usdt.gap_in ?? 0);
      gapOut += Number(usdt.gap_out ?? 0);
    }
    const first = asList(sorted[0].summary).find((s) => String(s.crypto).toLowerCase() === "usdt");
    const last = asList(sorted[sorted.length - 1].summary).find((s) => String(s.crypto).toLowerCase() === "usdt");
    const start = first?.balance_start == null ? null : Number(first.balance_start);
    const end = last?.balance_end == null ? null : Number(last.balance_end);
    return { start, end, recv, sent, gapIn, gapOut, monthDelta: start != null && end != null ? end - start : null };
  }, [dailyBalances]);

  return (
    <>
      <PageHeader
        title={oid == null ? "Оператор не найден" : name}
        subtitle={operator.username ? `@${String(operator.username)}` : undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => navigate("/x8/operators")}>
              <ArrowLeft className="size-4" /> К списку
            </Button>
            {editSource && (
              <Button variant="secondary" onClick={() => setEditOpen(true)}>
                Изменить
              </Button>
            )}
            {viewFinance && oid != null && (
              <Button variant="danger" onClick={() => setPenaltyOpen(true)}>
                Штраф
              </Button>
            )}
          </div>
        }
      />

      {oid == null ? (
        <Card>Нет такого оператора. Вернитесь к списку и откройте строку ещё раз.</Card>
      ) : (
        <>
      <div className="flex flex-wrap items-center gap-2">
        {PERIODS.map((p) => (
          <Button key={String(p.key)} size="sm" variant={period === p.key ? "primary" : "secondary"} onClick={() => setPeriod(p.key)}>
            {p.label}
          </Button>
        ))}
        <span className="text-[12px] text-[var(--text-muted)]">
          {payload ? `${payload.date_from} — ${payload.date_to}` : ""}
        </span>
        {operator.is_active != null && (
          <Badge tone={operator.is_active ? "green" : "red"}>{operator.is_active ? "активен" : "выключен"}</Badge>
        )}
      </div>

      {roleList.length > 0 && (
        <Card>
          <div className="mb-2 text-[13.5px] font-semibold">Роли</div>
          <div className="flex flex-wrap gap-2">
            {roleList.map((role) => (
              <Badge key={role} tone={role === "finance" ? "blue" : "green"}>
                {role === "finance" ? "Финансы" : "Клиент"}
                {grades[role] ? ` · ${gradeLabel(grades[role])}` : ""}
              </Badge>
            ))}
          </div>
        </Card>
      )}

      {loading || !payload ? (
        <Card>{loading ? "Загрузка статистики…" : "Нет данных по сменам"}</Card>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
            <Kpi label="Дней работал" value={String(summary.days_worked ?? 0)} hint={`${summary.work_frequency_pct ?? 0}% от ${summary.days_in_period ?? 0} дн.`} />
            <Kpi label="Часов всего" value={`${hours(summary.total_hours)} ч`} hint={`Ø ${hours(summary.avg_hours_per_work_day)} ч в рабочий день`} />
            <Kpi label="Смен" value={String(summary.shifts_count ?? shifts.length)} hint={`${summary.orders ?? totals.orders ?? 0} заявок · ${money(summary.fiat ?? totals.fiat)} ₽`} />
            {viewFinance && (summary.earnings_rub != null || totals.earnings_rub != null) && (
              <Kpi label="Заработок, ₽" value={money(summary.earnings_rub ?? totals.earnings_rub, 2)} hint={`за ${periodLabel.toLowerCase()}`} />
            )}
          </div>

          {sla && (
            <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
              <Kpi label="SLA: взятие" value={`${money(slaClaim.avg_minutes, 1)} мин`} hint={`p95 ${money(slaClaim.p95_minutes, 1)} · порог ${money(slaClaim.sla_threshold_minutes)} мин`} />
              <Kpi label="SLA: завершение" value={`${money(slaComplete.avg_minutes, 1)} мин`} hint={`p95 ${money(slaComplete.p95_minutes, 1)} · порог ${money(slaComplete.sla_threshold_minutes)} мин`} />
              <Kpi label="Нарушений SLA" value={String(slaBreaches.total ?? 0)} hint={`взятие ${slaBreaches.claim ?? 0} · завершение ${slaBreaches.complete ?? 0}`} />
              <Kpi label="Заявок в SLA" value={String(sla.total_orders ?? 0)} hint={`за ${sla.period_days ?? "—"} дн.`} />
            </div>
          )}

          {viewFinance && (
            <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
              <Kpi label="Начислено, ₽" value={money(payroll.accrued_rub, 2)} hint="всего на личный баланс" />
              <Kpi label="Доступно, ₽" value={money(payroll.available_rub, 2)} hint="к выводу" />
              <Kpi label="Штрафы, ₽" value={money(payroll.penalty_rub, 2)} hint={`выплачено ${money(payroll.paid_rub, 2)} ₽`} />
            </div>
          )}

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">График активности</div>
            {chartPoints.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Нет данных за период</p>
            ) : (
              <LineAreaChart
                points={chartPoints}
                series={[
                  { key: "hours", label: "Часы", color: "var(--blue)", values: dailyChrono.map((d) => Number(d.hours ?? 0)) },
                ]}
                hover={hover}
                onHover={setHover}
                summary={`${daily.reduce((s, d) => s + Number(d.orders ?? 0), 0)} заявок · ${money(daily.reduce((s, d) => s + Number(d.fiat ?? 0), 0))} ₽`}
                tooltip={(i) => {
                  const d = dailyChrono[i];
                  if (!d) return null;
                  return (
                    <div className="text-[12px]">
                      <div className="font-medium">{dayLabel(d.date)}</div>
                      <div>{hours(d.hours)} ч · {Number(d.orders ?? 0)} заявок · {money(d.fiat)} ₽</div>
                      {viewFinance && d.earnings_rub != null && <div>заработок {money(d.earnings_rub, 2)} ₽</div>}
                    </div>
                  );
                }}
              />
            )}
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">По дням</div>
            {daily.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Смен за период нет</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)]">
                      <th className="px-3 py-2 font-medium">Дата</th>
                      <th className="px-3 py-2 font-medium">Смен</th>
                      <th className="px-3 py-2 font-medium">Часы</th>
                      <th className="px-3 py-2 font-medium">Время</th>
                      <th className="px-3 py-2 text-right font-medium">Заявок</th>
                      <th className="px-3 py-2 text-right font-medium">Оборот</th>
                      {viewFinance && <th className="px-3 py-2 text-right font-medium">Заработок</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {daily.map((d) => (
                      <tr key={String(d.date)} className="border-b border-[var(--border)] last:border-0">
                        <td className="px-3 py-2">{dayLabel(d.date)}</td>
                        <td className="px-3 py-2">{String(d.shifts_count ?? 0)}</td>
                        <td className="px-3 py-2 font-mono">{hours(d.hours)} ч</td>
                        <td className="px-3 py-2 text-[12px] text-[var(--text-secondary)]">
                          {asList(d.shift_times).map((t, i) => (
                            <span key={i}>{i > 0 ? ", " : ""}{String(t.start ?? "")}–{String(t.end ?? "")}</span>
                          ))}
                        </td>
                        <td className="px-3 py-2 text-right">{String(d.orders ?? 0)}</td>
                        <td className="px-3 py-2 text-right font-mono">{money(d.fiat)} ₽</td>
                        {viewFinance && <td className="px-3 py-2 text-right font-mono">{d.earnings_rub == null ? "—" : `${money(d.earnings_rub, 2)} ₽`}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card>
            <div className="mb-1 text-[13.5px] font-semibold">Балансы по дням</div>
            <p className="mb-3 text-[12px] text-[var(--text-muted)]">
              USDT: приход от клиентов (sell), выдача (buy), пополнения/выводы между сменами.
            </p>
            {dailyBalances.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Балансы за период не записаны</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] border-collapse text-[13px]">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)]">
                      {["Дата", "Смен", "Баланс нач→кон", "Получено", "Отправлено", "Пополн.", "Вывод", "Δ за день", "vs вчера"].map((h) => (
                        <th key={h} className="px-3 py-2 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dailyBalances.map((row) => (
                      <DailyBalanceDay key={String(row.date)} row={row} />
                    ))}
                    {usdtTotals && (
                      <tr className="border-t border-[var(--border-strong)] font-semibold">
                        <td className="px-3 py-2">Итого за период</td>
                        <td className="px-3 py-2" />
                        <td className="px-3 py-2 font-mono text-[12px]">{cryptoAmt(usdtTotals.start)} → {cryptoAmt(usdtTotals.end)}</td>
                        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(usdtTotals.recv))}>{usdtTotals.recv ? fmtDelta(usdtTotals.recv) : "—"}</td>
                        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(-usdtTotals.sent))}>{usdtTotals.sent ? fmtDelta(-usdtTotals.sent) : "—"}</td>
                        <td className="px-3 py-2 font-mono text-[12px] text-[var(--green)]">{usdtTotals.gapIn ? fmtDelta(usdtTotals.gapIn) : "—"}</td>
                        <td className="px-3 py-2 font-mono text-[12px] text-[var(--orange)]">{usdtTotals.gapOut ? fmtDelta(-usdtTotals.gapOut) : "—"}</td>
                        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(usdtTotals.monthDelta))}>{fmtDelta(usdtTotals.monthDelta)}</td>
                        <td className="px-3 py-2" />
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">История смен</div>
            {shifts.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Смен за период нет</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)]">
                      <th className="px-3 py-2 font-medium">Начало</th>
                      <th className="px-3 py-2 font-medium">Конец</th>
                      <th className="px-3 py-2 text-right font-medium">Заявок</th>
                      <th className="px-3 py-2 text-right font-medium">Оборот</th>
                      {viewFinance && <th className="px-3 py-2 text-right font-medium">База</th>}
                      {viewFinance && <th className="px-3 py-2 text-right font-medium">Заработок</th>}
                      <th className="px-3 py-2 font-medium">Примечание</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shifts.map((s) => (
                      <ShiftHistoryRow key={Number(s.id)} s={s} viewFinance={viewFinance} colCount={viewFinance ? 7 : 5} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {viewFinance && (
            <Card>
              <div className="mb-3 text-[13.5px] font-semibold">Зарплата · история</div>
              {payrollLedger.length === 0 ? (
                <p className="text-[12.5px] text-[var(--text-muted)]">Движений по балансу нет</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[13px]">
                    <thead>
                      <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)]">
                        <th className="px-3 py-2 font-medium">Дата</th>
                        <th className="px-3 py-2 font-medium">Тип</th>
                        <th className="px-3 py-2 text-right font-medium">Сумма</th>
                        <th className="px-3 py-2 font-medium">Комментарий</th>
                      </tr>
                    </thead>
                    <tbody>
                      {payrollLedger.map((row) => {
                        const amt = Number(row.amount_rub ?? 0);
                        return (
                          <tr key={String(row.id)} className="border-b border-[var(--border)] last:border-0">
                            <td className="px-3 py-2 whitespace-nowrap">{dt(row.created_at)}</td>
                            <td className="px-3 py-2">{ledgerTypeLabel(row.type)}</td>
                            <td className={cx("px-3 py-2 text-right font-mono", amt < 0 ? "text-[var(--orange)]" : amt > 0 ? "text-[var(--green)]" : "")}>
                              {amt > 0 ? "+" : ""}{money(amt, 2)} ₽
                            </td>
                            <td className="max-w-[360px] truncate px-3 py-2 text-[12px] text-[var(--text-secondary)]">{String(row.note || "—")}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </>
      )}
        </>
      )}

      {editOpen && editSource && (
        <OperatorEditModal
          operator={editSource}
          onClose={() => setEditOpen(false)}
          onDone={() => {
            setEditOpen(false);
            load();
          }}
        />
      )}
      {penaltyOpen && oid != null && (
        <OperatorPenaltyModal
          name={name}
          available={Number(payroll.available_rub ?? 0)}
          operatorId={oid}
          onClose={() => setPenaltyOpen(false)}
          onDone={() => {
            setPenaltyOpen(false);
            load();
          }}
        />
      )}
    </>
  );
}

function OperatorPenaltyModal({
  name,
  available,
  operatorId,
  onClose,
  onDone,
}: {
  name: string;
  available: number;
  operatorId: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    const n = Number(amount.replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) return toast.error("Укажите сумму больше нуля");
    if (reason.trim().length < 2) return toast.error("Укажите причину штрафа");
    setBusy(true);
    try {
      await postOperatorPenalty(operatorId, { amount_rub: n, reason: reason.trim() });
      toast.success("Штраф списан");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      title={`Штраф · ${name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="danger" disabled={busy} onClick={submit}>Списать</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[12.5px] text-[var(--text-muted)]">Спишется с личного баланса. Доступно {money(available, 2)} ₽.</p>
        <Field label="Сумма, ₽">
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0" />
        </Field>
        <Field label="Причина">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            maxLength={500}
            placeholder="За что штраф"
            className="w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--text-muted)]"
          />
        </Field>
      </div>
    </Modal>
  );
}

function DailyBalanceDay({ row }: { row: Dict }) {
  const [open, setOpen] = useState(false);
  const shifts = asList(row.shifts);
  const usdt = asList(row.summary).find((s) => String(s.crypto).toLowerCase() === "usdt");
  return (
    <>
      <tr className={shifts.length ? "cursor-pointer hover:bg-[var(--bg-elevated)]" : ""} onClick={() => shifts.length && setOpen((v) => !v)}>
        <td className="px-3 py-2">{dayLabel(row.date)}{shifts.length > 0 ? <span className="ml-1 text-[var(--text-muted)]">{open ? "▾" : "▸"}</span> : null}</td>
        <td className="px-3 py-2">{String(row.shifts_count ?? shifts.length)}</td>
        <td className="px-3 py-2 font-mono text-[12px]">{cryptoAmt(usdt?.balance_start)} → {cryptoAmt(usdt?.balance_end)}</td>
        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(Number(usdt?.recv_in_sell ?? 0)))}>{usdt?.recv_in_sell ? fmtDelta(Number(usdt.recv_in_sell)) : "—"}</td>
        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(usdt?.sent_in_buy ? -Number(usdt.sent_in_buy) : 0))}>{usdt?.sent_in_buy ? fmtDelta(-Number(usdt.sent_in_buy)) : "—"}</td>
        <td className="px-3 py-2 font-mono text-[12px] text-[var(--green)]">{usdt?.gap_in ? fmtDelta(Number(usdt.gap_in)) : "—"}</td>
        <td className="px-3 py-2 font-mono text-[12px] text-[var(--orange)]">{usdt?.gap_out ? fmtDelta(-Number(usdt.gap_out)) : "—"}</td>
        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(usdt?.day_delta == null ? null : Number(usdt.day_delta)))}>{fmtDelta(usdt?.day_delta == null ? null : Number(usdt.day_delta))}</td>
        <td className={cx("px-3 py-2 font-mono text-[12px]", deltaCls(usdt?.vs_prev_day_end == null ? null : Number(usdt.vs_prev_day_end)))}>{fmtDelta(usdt?.vs_prev_day_end == null ? null : Number(usdt.vs_prev_day_end))}</td>
      </tr>
      {open && shifts.map((sh) => (
        <tr key={Number(sh.shift_id ?? sh.id)} className="bg-[var(--bg-elevated)]">
          <td colSpan={9} className="px-3 py-3">
            <p className="mb-2 text-[12px] text-[var(--text-muted)]">
              Смена #{String(sh.shift_id ?? sh.id)}: {String(sh.start_time ?? "")}–{String(sh.end_time ?? "")}
            </p>
            <BalanceMini rows={asList(sh.balances)} />
          </td>
        </tr>
      ))}
    </>
  );
}

function ShiftHistoryRow({ s, viewFinance, colCount }: { s: Dict; viewFinance: boolean; colCount: number }) {
  const [open, setOpen] = useState(false);
  const bals = asList(s.balance_summary);
  const has = bals.length > 0;
  return (
    <>
      <tr className={has ? "cursor-pointer hover:bg-[var(--bg-elevated)]" : ""} onClick={() => has && setOpen((v) => !v)}>
        <td className="px-3 py-2 whitespace-nowrap">{dt(s.started_at)}{has ? <span className="ml-1 text-[var(--text-muted)]">{open ? "▾" : "▸"}</span> : null}</td>
        <td className="px-3 py-2">{s.ended_at ? dt(s.ended_at) : <Badge tone="green">на смене</Badge>}</td>
        <td className="px-3 py-2 text-right">{String(s.orders_count ?? 0)}</td>
        <td className="px-3 py-2 text-right font-mono">{money(s.fiat_total)} ₽</td>
        {viewFinance && <td className="px-3 py-2 text-right font-mono text-[var(--text-secondary)]">{s.profit_rub == null ? "—" : `${money(s.profit_rub, 2)} ₽`}</td>}
        {viewFinance && <td className="px-3 py-2 text-right font-mono">{s.earnings_rub == null ? "—" : `${money(s.earnings_rub, 2)} ₽`}</td>}
        <td className="max-w-[200px] truncate px-3 py-2 text-[12px] text-[var(--text-muted)]">{String(s.note || "—")}</td>
      </tr>
      {open && has && (
        <tr className="bg-[var(--bg-elevated)]">
          <td colSpan={colCount} className="px-3 py-3">
            <BalanceMini rows={bals} />
          </td>
        </tr>
      )}
    </>
  );
}

function BalanceMini({ rows }: { rows: Dict[] }) {
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="text-[var(--text-muted)]">
          {["Монета", "Начало", "Конец", "Получено", "Отправлено", "Δ смены", "Комис."].map((h) => (
            <th key={h} className="py-1 pr-3 text-right font-medium first:text-left">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((b) => {
          const start = b.balance_start == null ? null : Number(b.balance_start);
          const end = b.balance_end == null ? null : Number(b.balance_end);
          const delta = start != null && end != null ? end - start : null;
          return (
            <tr key={String(b.crypto)} className="border-t border-[var(--border)]">
              <td className="py-1 pr-3 font-mono uppercase">{String(b.crypto)}</td>
              <td className="py-1 pr-3 text-right font-mono">{cryptoAmt(start)}</td>
              <td className="py-1 pr-3 text-right font-mono">{cryptoAmt(end)}</td>
              <td className={cx("py-1 pr-3 text-right font-mono", deltaCls(Number(b.recv_in_sell ?? 0)))}>{b.recv_in_sell ? fmtDelta(Number(b.recv_in_sell)) : "—"}</td>
              <td className={cx("py-1 pr-3 text-right font-mono", deltaCls(b.sent_in_buy ? -Number(b.sent_in_buy) : 0))}>{b.sent_in_buy ? fmtDelta(-Number(b.sent_in_buy)) : "—"}</td>
              <td className={cx("py-1 pr-3 text-right font-mono", deltaCls(delta))}>{fmtDelta(delta)}</td>
              <td className="py-1 text-right font-mono text-[var(--orange)]">{cryptoAmt(b.network_fees)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
