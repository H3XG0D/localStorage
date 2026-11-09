// NOTE: The operator payout pool (requests: pay / reject) lives in a separate
// screen — AdminOperatorPayroll.tsx. This screen only handles employee salaries.
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  getPayrollSettings,
  patchPayrollSettings,
  getOperatorPayrollSettings,
  patchOperatorPayrollSettings,
  getOperatorPayrollGrades,
  patchOperatorPayrollGrades,
  getOperatorPayrollDistribution,
  getAutopilot,
  patchSalaryRecipient,
  accrueSalary,
  type Dict,
} from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Table, type Column } from "@/panel/ui/primitives";

const GRADE_NAMES = ["trainee", "junior", "senior"] as const;
type GradeWeights = Record<"client" | "finance", Record<(typeof GRADE_NAMES)[number], number>>;
const DEFAULT_GRADE_WEIGHTS: GradeWeights = {
  client: { trainee: 0.75, junior: 1, senior: 1.25 },
  finance: { trainee: 0.75, junior: 1, senior: 1.25 },
};

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

export function AdminPayroll() {
  const [data, setData] = useState<Dict | null>(null);
  const [distribution, setDistribution] = useState<Dict | null>(null);
  const [weekly, setWeekly] = useState("");
  const [pool, setPool] = useState("30");
  const [clientShare, setClientShare] = useState("30");
  const [financeShare, setFinanceShare] = useState("70");
  const [grades, setGrades] = useState<GradeWeights>(DEFAULT_GRADE_WEIGHTS);
  const [presence, setPresence] = useState("5");
  const [manualPct, setManualPct] = useState("10");
  const [hourlyOn, setHourlyOn] = useState(false);
  const [hourlyRate, setHourlyRate] = useState("0");
  const [autoEnabled, setAutoEnabled] = useState<boolean | null>(null);
  const [savingWeekly, setSavingWeekly] = useState(false);
  const [savingPool, setSavingPool] = useState(false);
  const [savingGrades, setSavingGrades] = useState(false);
  const [savingAutopilotPay, setSavingAutopilotPay] = useState(false);
  const [accruing, setAccruing] = useState(false);
  const [editRow, setEditRow] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([getPayrollSettings(), getOperatorPayrollSettings(), getOperatorPayrollGrades(), getAutopilot().catch(() => null)])
      .then(([salary, operator, gradeData, autopilot]) => {
        setData(salary);
        setWeekly(String(salary.admin_weekly_salary_rub ?? ""));
        setPool(String(operator.operator_pool_percent ?? 30));
        setClientShare(String(operator.client_operator_share_percent ?? 30));
        setFinanceShare(String(operator.finance_operator_share_percent ?? 70));
        const asNumber = (value: unknown, fallback: number) => {
          const parsed = Number(value);
          return Number.isFinite(parsed) ? String(parsed) : String(fallback);
        };
        setPresence(asNumber(operator.autopilot_presence_percent, 5));
        setManualPct(asNumber(operator.autopilot_manual_percent, 10));
        setHourlyOn(operator.autopilot_hourly_enabled === true);
        setHourlyRate(asNumber(operator.autopilot_hourly_rate_rub, 0));
        const autoSettings = (autopilot?.settings ?? {}) as Dict;
        setAutoEnabled(typeof autoSettings.auto_mode_enabled === "boolean" ? autoSettings.auto_mode_enabled : null);
        const raw = (gradeData.role_grade_weights ?? {}) as Dict;
        const client = (raw.client ?? {}) as Dict;
        const finance = (raw.finance ?? {}) as Dict;
        setGrades({
          client: { ...DEFAULT_GRADE_WEIGHTS.client, trainee: Number(client.trainee ?? DEFAULT_GRADE_WEIGHTS.client.trainee), junior: Number(client.junior ?? DEFAULT_GRADE_WEIGHTS.client.junior), senior: Number(client.senior ?? DEFAULT_GRADE_WEIGHTS.client.senior) },
          finance: { ...DEFAULT_GRADE_WEIGHTS.finance, trainee: Number(finance.trainee ?? DEFAULT_GRADE_WEIGHTS.finance.trainee), junior: Number(finance.junior ?? DEFAULT_GRADE_WEIGHTS.finance.junior), senior: Number(finance.senior ?? DEFAULT_GRADE_WEIGHTS.finance.senior) },
        });
        return getOperatorPayrollDistribution()
          .then(setDistribution)
          .catch(() => setDistribution(null));
      })
      .catch((e) => {
        const message = e instanceof PanelApiError ? e.message : "Не удалось загрузить зарплаты";
        setError(message);
        toast.error(message);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const recipients = (data?.salary_recipients ?? []) as Dict[];
  const accruals = (data?.recent_accruals ?? []) as Dict[];

  async function saveWeekly() {
    const val = Number(weekly);
    if (Number.isNaN(val) || val < 0) {
      toast.error("Укажите сумму");
      return;
    }
    setSavingWeekly(true);
    try {
      await patchPayrollSettings(val);
      toast.success("Сохранено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setSavingWeekly(false);
    }
  }

  async function savePool() {
    const values = [Number(pool), Number(clientShare), Number(financeShare)];
    if (values.some((v) => !Number.isFinite(v) || v < 0 || v > 100) || Math.abs(values[1] + values[2] - 100) > 0.001) {
      toast.error("Фонд и доли должны быть от 0 до 100%, а доли — в сумме 100%");
      return;
    }
    setSavingPool(true);
    try {
      await patchOperatorPayrollSettings({
        operator_pool_percent: values[0],
        client_operator_share_percent: values[1],
        finance_operator_share_percent: values[2],
      });
      toast.success("Настройки фонда сохранены");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setSavingPool(false);
    }
  }

  async function accrue() {
    setAccruing(true);
    try {
      await accrueSalary();
      toast.success("Начислено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setAccruing(false);
    }
  }

  async function saveAutopilotPay() {
    const presenceValue = Number(presence);
    const manualValue = Number(manualPct);
    const rateValue = Number(hourlyRate);
    if ([presenceValue, manualValue].some((v) => !Number.isFinite(v) || v < 0 || v > 100) || !Number.isFinite(rateValue) || rateValue < 0) {
      toast.error("Проценты — от 0 до 100, ставка часа — от 0");
      return;
    }
    setSavingAutopilotPay(true);
    try {
      await patchOperatorPayrollSettings({
        autopilot_presence_percent: presenceValue,
        autopilot_manual_percent: manualValue,
        autopilot_hourly_enabled: hourlyOn,
        autopilot_hourly_rate_rub: rateValue,
      });
      toast.success("Ставки автопилота сохранены");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setSavingAutopilotPay(false);
    }
  }

  async function saveGrades() {
    const values = [...GRADE_NAMES.flatMap((grade) => [grades.client[grade], grades.finance[grade]])];
    if (values.some((value) => !Number.isFinite(value) || value <= 0 || value > 1000)) {
      toast.error("Коэффициенты должны быть больше 0 и не больше 1000");
      return;
    }
    setSavingGrades(true);
    try {
      await patchOperatorPayrollGrades({ role_grade_weights: grades });
      toast.success("Коэффициенты уровней сохранены");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setSavingGrades(false);
    }
  }

  const recipientCols: Column<Dict>[] = [
    { key: "name", label: "Сотрудник", render: (r) => String(r.label ?? r.display_name ?? r.name ?? r.username ?? "—") },
    { key: "daily_salary_rub", label: "Оклад/день ₽", align: "right", render: (r) => <span className="font-mono tabular-nums">{money(r.daily_salary_rub)}</span> },
    { key: "is_active", label: "Статус", width: "110px", render: (r) => <Badge tone={r.is_active ? "green" : "default"}>{r.is_active ? "активен" : "выключен"}</Badge> },
    {
      key: "edit",
      label: "",
      width: "100px",
      render: (r) => (
        <Button size="sm" variant="secondary" onClick={(e) => { e.stopPropagation(); setEditRow(r); }}>
          Изменить
        </Button>
      ),
    },
  ];

  const accrualCols: Column<Dict>[] = [
    { key: "accrued_at", label: "Дата", width: "160px", render: (r) => String(r.accrued_at ?? r.created_at ?? r.date ?? "—") },
    { key: "name", label: "Кому", render: (r) => String(r.label ?? r.display_name ?? r.name ?? r.username ?? r.recipient_name ?? "—") },
    { key: "amount_rub", label: "Сумма ₽", align: "right", render: (r) => <span className="font-mono tabular-nums">{money(r.amount_rub)}</span> },
  ];

  const poolValue = Number(pool) || 0;
  const clientValue = Number(clientShare) || 0;
  const financeValue = Number(financeShare) || 0;
  const shareSum = clientValue + financeValue;
  const shareSumValid = Math.abs(shareSum - 100) < 0.01;
  const previewClientValue = Number(distribution?.client_operator_share_percent ?? clientValue);
  const previewFinanceValue = Number(distribution?.finance_operator_share_percent ?? financeValue);

  // Пример расчёта для чистой прибыли 1000₽
  const exampleProfit = 1000;
  const examplePool = (exampleProfit * poolValue) / 100;
  const exampleClient = (examplePool * previewClientValue) / 100;
  const exampleFinance = (examplePool * previewFinanceValue) / 100;

  return (
    <>
      <PageHeader
        title="Зарплаты"
        subtitle="Настройка оплаты операторов и сотрудников"
        actions={
          <Button variant="primary" disabled={accruing} onClick={accrue}>
            Начислить сейчас
          </Button>
        }
      />

      {error && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--red)]/30 bg-[var(--red-bg)] p-4 text-[13px] text-[var(--red)]">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
        <div className="flex flex-col gap-6">
          {/* Операторский фонд */}
          <Card>
            <div className="mb-1 flex flex-wrap items-center gap-2 text-[15px] font-semibold">
              Операторский фонд
              {autoEnabled === false && <Badge tone="green">Активная схема</Badge>}
            </div>
            <div className="mb-4 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
              Процент чистой прибыли, пока автопилот выключен. Фонд делится между операторами по ролям и грейдам.
            </div>

            <div className="mb-4 grid gap-4 sm:grid-cols-3">
              <Field label="Фонд от прибыли, %">
                <Input
                  inputMode="decimal"
                  value={pool}
                  onChange={(e) => setPool(e.target.value)}
                  className="font-mono"
                  placeholder="30"
                />
              </Field>
              <Field label="Резервная доля клиентских операций, %">
                <Input
                  inputMode="decimal"
                  value={clientShare}
                  onChange={(e) => {
                    const value = e.target.value;
                    setClientShare(value);
                    const numeric = Number(value);
                    if (Number.isFinite(numeric) && numeric >= 0 && numeric <= 100) {
                      setFinanceShare(String(100 - numeric));
                    }
                  }}
                  className="font-mono"
                  aria-label="Резервная доля клиентских операторов"
                  placeholder="30"
                />
              </Field>
              <Field label="Финансовые операции, % фонда">
                <Input
                  readOnly
                  value={financeShare}
                  className="font-mono"
                  aria-label="Доля финансовых операторов"
                />
              </Field>
            </div>

            <div className="mb-4 flex items-center gap-3">
              <Button variant="primary" disabled={savingPool || !shareSumValid} onClick={savePool}>
                Сохранить настройки
              </Button>
              <span className={`text-[12px] ${shareSumValid ? "text-[var(--text-muted)]" : "text-[var(--red)]"}`}>
                {clientValue}% + {financeValue}% = {shareSum.toFixed(1)}%
                {!shareSumValid && " (должно быть 100%)"}
              </span>
            </div>

            <ActiveRoleDistribution distribution={distribution} />

            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12px] text-[var(--text-muted)]">
              <strong className="text-[var(--text-primary)]">Важно:</strong> Для смены с обеими ролями доля считается автоматически по грейдам.
              Резервная доля применяется, если одна из ролей не открыта. Изменения действуют только на новые завершённые заявки, история не пересчитывается.
            </div>

            <div className="mt-4 border-t border-[var(--border)] pt-4">
              <div className="mb-1 text-[14px] font-semibold">Коэффициенты уровней</div>
              <div className="mb-3 text-[12px] text-[var(--text-muted)]">
                Грейд задаёт роль в формуле фонда. Коэффициент — это не процент фонда: он делит уже выделенную долю роли между несколькими операторами этой роли.
                Например, при коэффициентах 0.75 и 1.25 первый получит 37.5%, а второй 62.5% своей роли. При одном операторе в роли коэффициент на итоговую долю не влияет.
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {(["client", "finance"] as const).map((role) => (
                  <div key={role} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3">
                    <div className="mb-2 text-[12px] font-medium">{role === "client" ? "Клиентские операции" : "Финансовые операции"}</div>
                    <div className="grid grid-cols-3 gap-2">
                      {GRADE_NAMES.map((grade) => (
                        <Field key={grade} label={grade === "trainee" ? "Стажёр" : grade === "junior" ? "Новичок" : "Старший"}>
                          <Input
                            type="number"
                            min="0.01"
                            max="1000"
                            step="0.01"
                            value={grades[role][grade]}
                            onChange={(e) => setGrades((current) => ({ ...current, [role]: { ...current[role], [grade]: Number(e.target.value) } }))}
                            className="font-mono"
                          />
                        </Field>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <Button className="mt-3" variant="secondary" disabled={savingGrades} onClick={saveGrades}>Сохранить коэффициенты</Button>
            </div>
          </Card>

          <Card>
            <div className="mb-1 flex flex-wrap items-center gap-2 text-[15px] font-semibold">
              Когда автопилот включён
              {autoEnabled === true && <Badge tone="green">Активная схема</Badge>}
              {autoEnabled === false && <Badge>Включится вместе с автопилотом</Badge>}
            </div>
            <div className="mb-4 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
              От чистой прибыли заявки. Процент за смену делится между всеми, кто был на смене в момент выплаты, по грейдам.
              Ручной процент получают только участники этой заявки. Один оператор забирает его целиком. Если на заявке есть и клиентская, и финансовая роль, тот же процент делится между ними по грейдам. Почасовая — один фонд на всех, кто в эту минуту на смене: ставка делится поминутно по тем же грейдам.
            </div>
            <div className="mb-4 grid gap-4 sm:grid-cols-2">
              <Field label="За смену, % прибыли" hint="Автозаявка, операторы на смене">
                <Input inputMode="decimal" value={presence} onChange={(e) => setPresence(e.target.value)} className="font-mono" placeholder="5" />
              </Field>
              <Field label="Ручная заявка, % прибыли" hint="Тому, кто её провёл">
                <Input inputMode="decimal" value={manualPct} onChange={(e) => setManualPct(e.target.value)} className="font-mono" placeholder="10" />
              </Field>
            </div>
            <div className="mb-4 flex flex-wrap items-end gap-4">
              <div className="flex items-center gap-3 pb-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={hourlyOn}
                  onClick={() => setHourlyOn((on) => !on)}
                  className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors ${hourlyOn ? "border-[var(--green)] bg-[var(--green-bg)]" : "border-[var(--border)] bg-[var(--bg-elevated)]"}`}
                >
                  <span className={`absolute top-0.5 size-4 rounded-full transition-all ${hourlyOn ? "left-[22px] bg-[var(--green)]" : "left-0.5 bg-[var(--text-muted)]"}`} />
                </button>
                <span className="text-[13px]">Почасовая оплата</span>
              </div>
              <Field label="Ставка, ₽/час">
                <Input inputMode="decimal" value={hourlyRate} onChange={(e) => setHourlyRate(e.target.value)} className="font-mono" placeholder="0" disabled={!hourlyOn} />
              </Field>
            </div>
            <Button variant="primary" disabled={savingAutopilotPay} onClick={saveAutopilotPay}>
              Сохранить ставки автопилота
            </Button>
            <div className="mt-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12px] text-[var(--text-muted)]">
              Пример при чистой прибыли 1 000 ₽: за смену {money((1000 * (Number(presence) || 0)) / 100)} ₽ на всех, кто на смене;
              ручная заявка {money((1000 * (Number(manualPct) || 0)) / 100)} ₽ исполнителю
              {hourlyOn ? `; плюс ${money(hourlyRate)} ₽/час на всех, кто в эту минуту на смене` : ""}.
              Уже закрытые заявки не пересчитываются.
            </div>
          </Card>

          {/* Зарплата сотрудников */}
          <Card>
            <div className="mb-1 text-[15px] font-semibold">Фиксированные оклады</div>
            <div className="mb-4 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
              Фиксированная оплата для сотрудников, не привязанная к заявкам (админ, менеджеры, техподдержка).
            </div>

            <div className="mb-4 flex max-w-md items-end gap-3">
              <Field label="Недельный оклад админа, ₽">
                <Input
                  inputMode="decimal"
                  value={weekly}
                  onChange={(e) => setWeekly(e.target.value)}
                  className="font-mono"
                  placeholder="50000"
                />
              </Field>
              <Button variant="primary" disabled={savingWeekly} onClick={saveWeekly}>
                Сохранить
              </Button>
            </div>

            <div className="mb-4 flex flex-wrap gap-4 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[13px]">
              <div>
                <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Итого в день</div>
                <div className="mt-0.5 font-mono text-[15px] font-medium">
                  {money(data?.daily_salary_total_rub ?? data?.daily_total_rub)} ₽
                </div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Итого в неделю</div>
                <div className="mt-0.5 font-mono text-[15px] font-medium">
                  {money(data?.weekly_salary_total_rub ?? data?.weekly_total_rub)} ₽
                </div>
              </div>
            </div>

            <Table columns={recipientCols} rows={recipients} empty={loading ? "Загрузка…" : "Нет получателей"} />
          </Card>

          {/* История начислений */}
          <Card>
            <div className="mb-3 text-[15px] font-semibold">Последние начисления</div>
            <Table columns={accrualCols} rows={accruals} empty={loading ? "Загрузка…" : "Нет начислений"} />
          </Card>
        </div>

        {/* Справка-калькулятор */}
        <div className="flex flex-col gap-6">
          <Card className="sticky top-4">
            <div className="mb-3 text-[14px] font-semibold">Пример расчёта</div>
            <div className="mb-3 text-[12px] text-[var(--text-muted)]">
              Как делится прибыль по текущим настройкам фонда:
            </div>

            <div className="space-y-3">
              <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3">
                <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Чистая прибыль заявки</div>
                <div className="mt-1 font-mono text-[18px] font-semibold">{money(exampleProfit)} ₽</div>
              </div>

              <div className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
                <div className="h-px flex-1 bg-[var(--border)]" />
                <span>× {poolValue}% в фонд</span>
                <div className="h-px flex-1 bg-[var(--border)]" />
              </div>

              <div className="rounded-[var(--radius)] border border-[var(--blue)]/30 bg-[var(--blue-bg)] p-3">
                <div className="text-[11px] uppercase tracking-wide text-[var(--blue)]">Операторский фонд</div>
                <div className="mt-1 font-mono text-[18px] font-semibold text-[var(--blue)]">{money(examplePool)} ₽</div>
              </div>

              <div className="space-y-2 pl-4">
                <div className="flex items-center justify-between rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
                  <span className="text-[12px] text-[var(--text-muted)]">Клиентские ({previewClientValue}%)</span>
                  <span className="font-mono text-[14px] font-medium">{money(exampleClient)} ₽</span>
                </div>
                <div className="flex items-center justify-between rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
                  <span className="text-[12px] text-[var(--text-muted)]">Финансовые ({previewFinanceValue}%)</span>
                  <span className="font-mono text-[14px] font-medium">{money(exampleFinance)} ₽</span>
                </div>
              </div>
            </div>

            <div className="mt-4 space-y-2 border-t border-[var(--border)] pt-4 text-[11.5px] leading-relaxed text-[var(--text-muted)]">
              <p>
                <strong className="text-[var(--text-primary)]">Ручная заявка:</strong> клиентскую долю получает оператор,
                работавший с клиентом. Другие клиентские операторы её не делят.
              </p>
              <p>
                <strong className="text-[var(--text-primary)]">Автоматическая заявка:</strong> каждая доля делится поровну
                между назначенными участниками соответствующей роли.
              </p>
            </div>
          </Card>
        </div>
      </div>

      {editRow && <EditRecipientModal row={editRow} onClose={() => setEditRow(null)} onDone={() => { setEditRow(null); load(); }} />}
    </>
  );
}

function gradeLabel(value: unknown) {
  return value === "trainee" ? "Стажёр" : value === "senior" ? "Старший" : "Новичок";
}

function roleLabel(value: unknown) {
  if (value === "both") return "Клиент + финансы";
  return value === "finance" ? "Финансы" : "Клиент";
}

function ActiveRoleDistribution({ distribution }: { distribution: Dict | null }) {
  if (!distribution) return null;
  const client = Number(distribution.client_operator_share_percent ?? 0);
  const finance = Number(distribution.finance_operator_share_percent ?? 0);
  const participants = (Array.isArray(distribution.participants) ? distribution.participants : []) as Dict[];
  const complete = distribution.role_pair_complete === true;
  const mode = String(distribution.role_share_mode ?? "fallback");

  return (
    <div className="mb-4 rounded-[var(--radius)] border border-[var(--blue)]/30 bg-[var(--blue-bg)] p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] font-semibold">Распределение на активной смене</div>
        <Badge tone={complete ? "green" : "yellow"}>{complete ? "По грейдам" : "Ожидается пара ролей"}</Badge>
      </div>
      <div className="mb-3 text-[12px] text-[var(--text-muted)]">
        {complete
          ? "Эти доли будут зафиксированы в новых начислениях заявок этой смены."
          : "Пока не открыты обе роли, используется резервная доля из настроек фонда."}
      </div>
      <RoleShareBar client={client} finance={finance} />
      {participants.length > 0 && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {participants.map((participant, index) => (
            <div key={`${String(participant.operator_id ?? index)}-${String(participant.role ?? "role")}`} className="rounded-[var(--radius)] bg-[var(--bg-surface)]/60 px-3 py-2 text-[12px]">
              <div className="truncate font-medium">{String(participant.display_name ?? participant.username ?? `Оператор ${index + 1}`)}</div>
              <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-[var(--text-muted)]">
                <span>{roleLabel(participant.role)} · {gradeLabel(participant.grade)}</span>
                <span className="font-mono tabular-nums">{Number(participant.fund_share_percent ?? 0)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {mode === "fallback" && <div className="mt-2 text-[11px] text-[var(--yellow)]">Фактическая пара ролей ещё не определена.</div>}
    </div>
  );
}

function RoleShareBar({ client, finance }: { client: number; finance: number }) {
  const clientValue = Math.min(100, Math.max(0, Number.isFinite(client) ? client : 0));
  const financeValue = Math.min(100, Math.max(0, Number.isFinite(finance) ? finance : 0));
  const total = clientValue + financeValue;
  const clientWidth = total > 0 ? (clientValue / total) * 100 : 0;

  return (
    <div className="flex flex-col gap-1.5" role="img" aria-label={`Клиентские ${clientValue}%, финансовые ${financeValue}%`}>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--bg-overlay)]">
        <div className="bg-[var(--blue)] transition-[width] duration-150" style={{ width: `${clientWidth}%` }} />
        <div className="bg-[var(--green)] transition-[width] duration-150" style={{ width: `${Math.max(0, 100 - clientWidth)}%` }} />
      </div>
      <div className="flex justify-between text-[10px] text-[var(--text-muted)]">
        <span>Клиентские · {clientValue}%</span>
        <span>Финансовые · {financeValue}%</span>
      </div>
    </div>
  );
}

function EditRecipientModal({ row, onClose, onDone }: { row: Dict; onClose: () => void; onDone: () => void }) {
  const [daily, setDaily] = useState(String(row.daily_salary_rub ?? ""));
  const [active, setActive] = useState(Boolean(row.is_active));
  const [busy, setBusy] = useState(false);

  async function submit() {
    const val = Number(daily);
    if (Number.isNaN(val) || val < 0) {
      toast.error("Укажите сумму");
      return;
    }
    setBusy(true);
    try {
      await patchSalaryRecipient(Number(row.id ?? row.recipient_id), { daily_salary_rub: val, is_active: active });
      toast.success("Сохранено");
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
      title={`Оклад · ${String(row.label ?? row.display_name ?? row.name ?? row.username ?? "")}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>Сохранить</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Оклад в день, ₽">
          <Input inputMode="decimal" value={daily} onChange={(e) => setDaily(e.target.value)} className="font-mono" />
        </Field>
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-[var(--text-primary)]">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Активен
        </label>
      </div>
    </Modal>
  );
}
