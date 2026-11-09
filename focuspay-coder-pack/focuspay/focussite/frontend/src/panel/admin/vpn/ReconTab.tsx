import { useEffect, useState } from "react";
import { getVpnReconciliation, type Dict } from "@/panel/lib/adminApi";
import { Badge, Card, Kpi, type BadgeTone } from "@/panel/ui/primitives";
import { asList, moneyRub, num } from "@/panel/admin/analytics/format";

const ISSUES: Record<string, { label: string; hint: string; tone: BadgeTone }> = {
  paid_without_grant: { label: "Оплачено, но дней нет", hint: "Деньги списаны, VPN не выдан — выдать дни или вернуть", tone: "red" },
  grant_without_payment: { label: "Дни выданы без оплаты", hint: "Покупка отменена в FocusPay, но в VPN дни есть", tone: "red" },
  amount_or_days_mismatch: { label: "Сумма или дни не совпадают", hint: "FocusPay и VPN записали разное", tone: "red" },
  grant_unknown_to_focuspay: { label: "Выдача неизвестна FocusPay", hint: "В VPN есть выдача без покупки в FocusPay", tone: "orange" },
  granted_not_confirmed: { label: "Дни выданы, списание не подтверждено", hint: "Фон FocusPay доведёт сам в течение минуты", tone: "yellow" },
  pending: { label: "В обработке", hint: "Обычное состояние, проходит само", tone: "default" },
};
const ORDER = Object.keys(ISSUES);

export function ReconTab({ onOpenUser }: { onOpenUser: (telegramId: string) => void }) {
  const [data, setData] = useState<Dict | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getVpnReconciliation()
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);
  if (error) return <Card className="text-[var(--red)]">{error}</Card>;
  if (!data) return <p className="text-[var(--text-muted)]">Загрузка…</p>;

  const issues = asList(data.issues);
  const groups = ORDER.map((key) => ({ key, items: issues.filter((i) => i.issue === key) })).filter((g) => g.items.length);
  const unknown = issues.filter((i) => !ISSUES[String(i.issue)]);
  if (unknown.length) groups.push({ key: "other", items: unknown });
  const diff = num(data.focuspay_paid_rub) - num(data.cp_granted_rub);
  const ok = Boolean(data.ok);
  const pending = issues.filter((i) => i.issue === "pending").length;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label={`Оплачено в FocusPay · ${num(data.window_days)} дней`} value={moneyRub(data.focuspay_paid_rub, true)} />
        <Kpi label="Выдано в VPN" value={moneyRub(data.cp_granted_rub, true)} />
        <Kpi label="Разница" value={moneyRub(diff, true)} hint="Ненулевая при покупках «в обработке» — это нормально" />
        <Kpi label="Записей FocusPay" value={num(data.focuspay_count)} />
      </div>

      {ok ? (
        <Card className="flex items-center gap-3 border-[var(--green)]/30">
          <span className="text-2xl">✓</span>
          <div>
            <div className="text-[14px] font-semibold text-[var(--green)]">Всё сходится</div>
            <div className="text-[12px] text-[var(--text-muted)]">
              Каждая оплата в FocusPay имеет выдачу дней в VPN и наоборот
              {pending ? ` · в обработке: ${pending}` : ""}
            </div>
          </div>
        </Card>
      ) : null}

      {groups
        .filter((g) => !ok || g.key !== "pending")
        .map((g) => {
          const meta = ISSUES[g.key] || { label: "Другое", hint: "", tone: "default" as const };
          return (
            <Card key={g.key} className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[13.5px] font-semibold">{meta.label}</div>
                  {meta.hint ? <div className="text-[11px] text-[var(--text-muted)]">{meta.hint}</div> : null}
                </div>
                <Badge tone={meta.tone}>{g.items.length}</Badge>
              </div>
              <div className="divide-y divide-[var(--border)]">
                {g.items.map((i) => (
                  <div key={`${String(i.purchase_id)}-${String(i.issue)}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[12.5px]">
                    <span className="font-mono text-[11.5px] text-[var(--text-secondary)]">{String(i.purchase_id)}</span>
                    {i.fp_days !== undefined ? (
                      <span className="text-[var(--text-muted)]">
                        FocusPay {num(i.fp_days)} дн · {moneyRub(num(i.fp_kopecks) / 100, true)} — VPN {num(i.cp_days)} дн · {moneyRub(num(i.cp_kopecks) / 100, true)}
                      </span>
                    ) : null}
                    {i.telegram_id ? (
                      <button type="button" className="font-mono text-[var(--blue)] hover:underline" onClick={() => onOpenUser(String(i.telegram_id))}>
                        {String(i.telegram_id)}
                      </button>
                    ) : <span className="text-[var(--text-muted)]">—</span>}
                  </div>
                ))}
              </div>
            </Card>
          );
        })}
    </div>
  );
}
