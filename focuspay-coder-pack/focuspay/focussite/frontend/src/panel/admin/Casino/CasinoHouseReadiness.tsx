import { useEffect } from "react";
import { CheckCircle2, Circle } from "lucide-react";
import { Link, useLocation } from "react-router";
import type { AdminCasinoHouseReadiness, AdminCasinoHouseReadinessCheck } from "@/panel/lib/adminApi";
import { Badge, Card } from "@/panel/ui/primitives";

export function useHashSectionScroll(ready = true) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!ready) return;
    const id = hash.replace(/^#/, "");
    if (!id) return;
    const timer = window.setTimeout(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [hash, ready]);
}

function rub(value: number): string {
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function ProgressRing({ ok, total }: { ok: number; total: number }) {
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  const ratio = total > 0 ? Math.min(1, ok / total) : 0;
  const done = ok === total && total > 0;
  return (
    <svg viewBox="0 0 56 56" className="h-14 w-14 shrink-0" role="img" aria-label={`${ok} из ${total}`}>
      <circle cx="28" cy="28" r={radius} fill="none" stroke="var(--border-strong)" strokeWidth="6" />
      <circle
        cx="28"
        cy="28"
        r={radius}
        fill="none"
        stroke={done ? "var(--green)" : "var(--text-primary)"}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - ratio)}
        transform="rotate(-90 28 28)"
      />
      <text
        x="28"
        y="32"
        textAnchor="middle"
        className="fill-[var(--text-primary)] font-mono text-[11px] font-semibold"
      >
        {ok}/{total}
      </text>
    </svg>
  );
}

function CheckRow({ check }: { check: AdminCasinoHouseReadinessCheck }) {
  return (
    <li
      data-readiness-item={check.id}
      data-readiness-ok={check.ok ? "1" : "0"}
      className="flex flex-wrap items-start justify-between gap-2 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-2"
    >
      <div className="flex min-w-0 items-start gap-2">
        {check.ok ? (
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--green)]" aria-hidden />
        ) : (
          <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--yellow)]" aria-hidden />
        )}
        <div>
          <div className="text-[13px] font-medium text-[var(--text-primary)]">{check.title}</div>
          <div className="mt-0.5 text-[12px] text-[var(--text-muted)]">{check.detail}</div>
        </div>
      </div>
      {check.href ? (
        <Link
          to={check.href}
          className="inline-flex h-8 shrink-0 items-center rounded-[var(--radius)] border border-[var(--border-strong)] px-3 text-[12.5px] text-[var(--text-primary)] hover:border-[var(--accent)]"
        >
          {check.ok ? "Открыть" : "Исправить"}
        </Link>
      ) : null}
    </li>
  );
}

export function CasinoHouseReadiness({
  readiness,
}: {
  readiness: AdminCasinoHouseReadiness | null;
  onFixStep?: (step: string) => void;
}) {
  if (!readiness) return null;

  const required = readiness.required ?? [];
  const secondary = readiness.secondary ?? readiness.checks ?? [];
  const requiredOk = readiness.required_ok ?? required.filter((item) => item.ok).length;
  const requiredTotal = readiness.required_total ?? 5;
  const requiredReady = readiness.required_ready ?? requiredOk === requiredTotal;

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3" data-readiness-required={`${requiredOk}/${requiredTotal}`}>
        <div className="flex items-start gap-3">
          <ProgressRing ok={requiredOk} total={requiredTotal} />
          <div>
            <div className="text-[14px] font-semibold">Чек-лист готовности</div>
            <p className="mt-1 text-[12px] text-[var(--text-muted)]">
              Состояние с сервера, не из браузера. Банк {rub(readiness.available_rub)}
              {readiness.bankroll_floor_rub != null ? ` · порог ${rub(readiness.bankroll_floor_rub)}` : ""}.
            </p>
          </div>
        </div>
        <Badge tone={requiredReady ? "green" : "yellow"}>
          {requiredReady ? "Обязательные 5 готовы" : `${requiredOk} из ${requiredTotal}`}
        </Badge>
      </div>

      <ul className="space-y-2" data-readiness-required-list="">
        {required.map((check) => (
          <CheckRow key={check.id} check={check} />
        ))}
      </ul>

      {requiredReady ? (
        <details className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2" data-readiness-secondary="">
          <summary className="cursor-pointer text-[13px] font-medium text-[var(--text-secondary)]">
            Дополнительно для PvP-столов
            {readiness.ready ? " — можно создавать столы" : ` — ${secondary.filter((item) => !item.ok).length} уточнений`}
          </summary>
          <ul className="mt-3 space-y-2">
            {secondary.map((check) => (
              <CheckRow key={check.id} check={check} />
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}
