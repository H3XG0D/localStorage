import { useCallback, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import { getPayrollBalance, requestPayroll } from "@/panel/lib/operatorApi";
import { Badge, Button, Card, Field, Input, Kpi, PageHeader } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v ?? 0));
}

type Dict = Record<string, unknown>;

function asDict(value: unknown): Dict | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Dict : null;
}

function numberOrNull(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function gradeLabel(value: unknown) {
  return value === "trainee" ? "Стажёр" : value === "senior" ? "Старший" : "Новичок";
}

function roleLabel(value: unknown) {
  if (value === "both") return "Клиент + финансы";
  return value === "finance" ? "Финансы" : "Клиент";
}

function accrualKindLabel(kind: unknown) {
  if (kind === "presence") return "За смену";
  if (kind === "manual") return "Ручная";
  if (kind === "hourly") return "Часы";
  if (kind === "penalty") return "Штраф";
  return "Начисление";
}

function getPayMode(data: Dict | null) {
  const nested = asDict(data?.payroll_distribution ?? data?.distribution ?? data?.shift_payroll);
  if (!nested) return null;
  const participants = Array.isArray(nested.presence_participants) ? nested.presence_participants : [];
  return {
    mode: nested.pay_mode === "autopilot" ? "autopilot" : "role_split",
    pool: numberOrNull(nested.operator_pool_percent) ?? 30,
    presence: numberOrNull(nested.autopilot_presence_percent) ?? 0,
    manual: numberOrNull(nested.autopilot_manual_percent) ?? 0,
    hourlyEnabled: nested.autopilot_hourly_enabled === true,
    hourlyRate: numberOrNull(nested.autopilot_hourly_rate_rub) ?? 0,
    presenceParticipants: participants.filter((item): item is Dict => Boolean(asDict(item))).map((item) => asDict(item) as Dict),
  };
}

function getDistribution(data: Dict | null) {
  const nested = asDict(data?.payroll_distribution ?? data?.distribution ?? data?.shift_payroll);
  const source = nested ?? data;
  if (!source) return null;

  const client = numberOrNull(source.client_operator_share_percent ?? source.client_share_percent ?? source.client_percent);
  const finance = numberOrNull(source.finance_operator_share_percent ?? source.finance_share_percent ?? source.finance_percent);
  if (client === null || finance === null || client < 0 || finance < 0 || client > 100 || finance > 100 || Math.abs(client + finance - 100) > 0.01) return null;

  const participants = (
    Array.isArray(source.participants) && source.participants.length > 0
      ? source.participants
      : [
          ...(Array.isArray(source.client_participants) ? source.client_participants : []),
          ...(Array.isArray(source.finance_participants) ? source.finance_participants : []),
        ]
  ).filter((item): item is Dict => Boolean(asDict(item))).map((item) => asDict(item) as Dict);
  const complete = source.role_pair_complete === true
    || (Array.isArray(source.client_participants) && source.client_participants.length > 0
      && Array.isArray(source.finance_participants) && source.finance_participants.length > 0);

  return {
    client,
    finance,
    participants,
    complete,
    mode: String(source.role_share_mode ?? "fallback"),
    formula: String(source.role_share_formula ?? ""),
  };
}

export function OperatorPayroll() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [amount, setAmount] = useState("");
  const [requisites, setRequisites] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getPayrollBalance()
      .then(setData)
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"));
  }, []);

  useAuthedPoll("operator", load, 15000, [load]);

  const pending = data?.my_pending_request as Record<string, unknown> | null | undefined;
  const distribution = getDistribution(data);
  const pay = getPayMode(data);
  const preview = asDict(data?.hourly_preview);
  const recent = Array.isArray(data?.recent_accruals) ? data.recent_accruals.filter((item): item is Dict => Boolean(asDict(item))) : [];
  const autopilotPay = pay?.mode === "autopilot";

  async function submit() {
    if (Number(amount) <= 0 || requisites.trim().length < 5) {
      toast.error("Укажите сумму и реквизиты");
      return;
    }
    setBusy(true);
    try {
      await requestPayroll(Number(amount), requisites.trim());
      toast.success("Заявка на выплату создана");
      setAmount("");
      setRequisites("");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Зарплата" subtitle="Баланс пула и заявка на выплату" />
      <div className="grid grid-cols-3 gap-4 max-[520px]:grid-cols-1">
        <Kpi label="Всего начислено, ₽" value={money(data?.total_rub)} />
        <Kpi label="Доступно к выводу, ₽" value={money(data?.available_rub)} />
        <Kpi label="В холде, ₽" value={money(data?.pending_holds_rub)} />
      </div>

      {pay && (
        <Card>
          <div className="mb-1 text-[13.5px] font-semibold">
            {autopilotPay ? "Автопилот включён" : "Автопилот выключен"}
          </div>
          <p className="m-0 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
            {autopilotPay
              ? `${pay.presence}% чистой прибыли с автозаявки делится между теми, кто на смене. ${pay.manual}% — за заявку, которую оператор провёл сам. Почасовая ${pay.hourlyEnabled ? `${money(pay.hourlyRate)} ₽/час на всех, кто в эту минуту на смене` : "выключена"}.`
              : `Фонд ${pay.pool}% чистой прибыли делится по ролям и грейдам.`}
          </p>
          {preview?.open === true && preview.applies === true && (
            <p className="mb-0 mt-3 text-[12.5px]">
              Открытая смена: прогноз <span className="font-mono">{money(preview.forecast_rub)} ₽</span> — доля фонда {money(preview.rate_rub)} ₽/час. В баланс попадёт при закрытии смены.
            </p>
          )}
          {preview?.open === true && preview.applies !== true && pay.hourlyEnabled && (
            <p className="mb-0 mt-3 text-[12.5px] text-[var(--text-muted)]">
              Эта смена открыта без почасовой. Ставка {money(pay.hourlyRate)} ₽/час начнётся со следующей смены.
            </p>
          )}
        </Card>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
        <Card>
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[13.5px] font-semibold">{autopilotPay ? "Доля процента за смену" : "Распределение фонда на смене"}</div>
            <Badge tone={autopilotPay ? "green" : distribution?.complete ? "green" : "yellow"}>
              {autopilotPay ? "По грейдам" : distribution ? (distribution.complete ? "По грейдам" : "Резервная доля") : "Детализация недоступна"}
            </Badge>
          </div>
          {autopilotPay ? (
            <>
              <div className="mb-4 text-[12.5px] text-[var(--text-muted)]">
                Один фонд {pay.presence}% делится между операторами, которые сейчас на смене. Один человек забирает его целиком.
              </div>
              {pay.presenceParticipants.length > 0 ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {pay.presenceParticipants.map((participant, index) => (
                    <div key={`${String(participant.operator_id ?? index)}-presence`} className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">
                      <div className="truncate font-medium">{String(participant.display_name ?? participant.username ?? `Оператор ${index + 1}`)}</div>
                      <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-[var(--text-muted)]">
                        <span>{roleLabel(participant.role)} · {gradeLabel(participant.grade)}</span>
                        <span className="font-mono tabular-nums">{numberOrNull(participant.fund_share_percent) ?? 0}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="m-0 text-[12.5px] text-[var(--text-muted)]">На смене никого нет — автозаявки операторам не начисляются.</p>
              )}
            </>
          ) : distribution ? (
            <>
              <div className="mb-4 text-[12.5px] text-[var(--text-muted)]">
                Доля рассчитывается автоматически по ролям и грейдам операторов, которые сейчас находятся на смене.
                {distribution.formula && ` ${distribution.formula}.`}
              </div>
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(220px,0.8fr)]">
                <div className="flex min-w-0 flex-col justify-center gap-2 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3">
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">Доля фонда по ролям</div>
                  <div className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-[11px] text-[var(--text-muted)]">Клиентские</span>
                    <div
                      className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--bg-overlay)]"
                      role="img"
                      aria-label={`Клиентские операции ${distribution.client}%`}
                    >
                      <div className="h-full rounded-full bg-[var(--blue)]" style={{ width: `${distribution.client}%` }} />
                    </div>
                    <span className="w-12 text-right font-mono text-[12px] tabular-nums">{distribution.client}%</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-[11px] text-[var(--text-muted)]">Финансовые</span>
                    <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
                      <div className="h-full rounded-full bg-[var(--green)]" style={{ width: `${distribution.finance}%` }} />
                    </div>
                    <span className="w-12 text-right font-mono text-[12px] tabular-nums">{distribution.finance}%</span>
                  </div>
                </div>
                {distribution.participants.length > 0 && (
                  <div className="min-w-0">
                    <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">Операторы на смене</div>
                    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                      {distribution.participants.map((participant, index) => (
                        <div key={`${String(participant.operator_id ?? participant.id ?? index)}-${String(participant.role ?? "role")}-${index}`} className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">
                          <div className="truncate font-medium">{String(participant.display_name ?? participant.operator_name ?? participant.username ?? `Оператор ${index + 1}`)}</div>
                          <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-[var(--text-muted)]">
                            <span>{roleLabel(participant.role)} · {gradeLabel(participant.grade)}</span>
                            <span className="font-mono tabular-nums">{numberOrNull(participant.fund_share_percent ?? participant.share_percent ?? participant.weight_percent) ?? 0}%</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              {!distribution.complete && (
                <div className="mt-3 border-t border-[var(--border)] pt-3 text-[11.5px] text-[var(--yellow)]">
                  Для grade-based расчёта нужен активный оператор обеих ролей: «Клиент» и «Финансы».
                </div>
              )}
            </>
          ) : (
            <p className="m-0 text-[12.5px] text-[var(--text-muted)]">
              Сервер пока не передал состав участников и доли по заявкам. Баланс выше доступен, но детализация смены появится после подключения нового payroll-расчёта.
            </p>
          )}
        </Card>

        <Card className="h-fit">
          <div className="mb-1 flex items-center justify-between gap-2">
            <div className="text-[13.5px] font-semibold">Запросить выплату</div>
            <Badge tone={pending ? "yellow" : "default"}>{pending ? "В обработке" : "Готово"}</Badge>
          </div>
          <div className="mb-4 text-[12px] text-[var(--text-muted)]">Вывод доступного баланса оператора.</div>
          {pending ? (
            <div className="rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] p-3 text-[13px] text-[var(--yellow)]">
              Заявка на выплату в обработке: <span className="font-mono font-semibold">{money(pending.amount_rub)} ₽</span>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <Field label="Сумма, ₽">
                <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="font-mono" />
              </Field>
              <Field label="Реквизиты">
                <Input value={requisites} onChange={(e) => setRequisites(e.target.value)} placeholder="Карта / кошелёк" />
              </Field>
              <Button variant="primary" disabled={busy} onClick={submit}>
                Создать заявку
              </Button>
            </div>
          )}
        </Card>
      </div>

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Последние начисления</div>
        {recent.length === 0 ? (
          <p className="m-0 text-[12.5px] text-[var(--text-muted)]">Начислений пока нет</p>
        ) : (
          <div className="flex flex-col gap-2">
            {recent.map((row, index) => (
              <div key={String(row.id ?? index)} className="flex items-center justify-between gap-3 text-[12.5px]">
                <div className="min-w-0">
                  <Badge>{accrualKindLabel(row.kind)}</Badge>
                  <span className="ml-2 text-[var(--text-muted)]">{String(row.note ?? "")}</span>
                </div>
                <span className="shrink-0 font-mono tabular-nums">{money(row.amount_rub)} ₽</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
