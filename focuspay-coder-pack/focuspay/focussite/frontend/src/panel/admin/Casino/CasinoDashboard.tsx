import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, CalendarDays, RefreshCw } from "lucide-react";
import { getCasinoStats, disbandCasinoClan, type AdminCasinoStats } from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import { Button, Card, Field, Input, PageHeader, cx } from "@/panel/ui/primitives";
import { CasinoStatsView } from "@/panel/admin/Casino/CasinoStatsView";
import { isYmd, localRange, PERIOD_PRESETS, type PeriodPreset } from "@/panel/lib/analyticsPeriod";

type CasinoPeriod = PeriodPreset | "all";

const PAGE_PRESETS: { key: CasinoPeriod; label: string }[] = [
  { key: "all", label: "За всё время" },
  ...PERIOD_PRESETS,
];

function parsePeriod(raw: string | null): CasinoPeriod {
  if (raw === "all") return "all";
  return PERIOD_PRESETS.some((item) => item.key === raw) ? (raw as PeriodPreset) : "week";
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

export function CasinoDashboard() {
  const [params, setParams] = useSearchParams();
  const preset = parsePeriod(params.get("period"));
  const fallback = useMemo(() => localRange("week"), []);
  const [customFrom, setCustomFrom] = useState(() => params.get("from") || fallback.from);
  const [customTo, setCustomTo] = useState(() => params.get("to") || fallback.to);
  const range = preset === "all" ? null : preset === "custom" ? { from: customFrom, to: customTo } : localRange(preset);

  const [data, setData] = useState<AdminCasinoStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (range && (!isYmd(range.from) || !isYmd(range.to) || range.from > range.to)) {
      setError("Проверьте даты периода");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setData(range ? await getCasinoStats(range.from, range.to) : await getCasinoStats());
    } catch (err) {
      setData(null);
      setError(getErrorMessage(err, "Не удалось загрузить статистику казино"));
    } finally {
      setLoading(false);
    }
  }, [range?.from, range?.to, preset]);

  useEffect(() => {
    void load();
  }, [load]);

  function setPreset(next: CasinoPeriod) {
    const nextParams = new URLSearchParams(params);
    if (next === "week") nextParams.delete("period");
    else nextParams.set("period", next);
    if (next === "custom") {
      const from = isYmd(customFrom) ? customFrom : fallback.from;
      const to = isYmd(customTo) ? customTo : fallback.to;
      setCustomFrom(from);
      setCustomTo(to);
      nextParams.set("from", from);
      nextParams.set("to", to);
    } else {
      nextParams.delete("from");
      nextParams.delete("to");
    }
    setParams(nextParams, { replace: true });
  }

  function setCustomDate(kind: "from" | "to", value: string) {
    const nextFrom = kind === "from" ? value : customFrom;
    const nextTo = kind === "to" ? value : customTo;
    if (kind === "from") setCustomFrom(value);
    else setCustomTo(value);
    const nextParams = new URLSearchParams(params);
    nextParams.set("period", "custom");
    if (isYmd(nextFrom)) nextParams.set("from", nextFrom);
    if (isYmd(nextTo)) nextParams.set("to", nextTo);
    setParams(nextParams, { replace: true });
  }

  const periodLabel = range ? `${range.from} — ${range.to}` : "всё время";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Казино — Дашборд"
        subtitle={`Оборот игроков, GGR и чистая прибыль · ${periodLabel} · Москва`}
        actions={
          <Button type="button" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
            Обновить
          </Button>
        }
      />

      <Card className="grid gap-3 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-end">
        <div className="flex items-center gap-2 text-[12px] text-[var(--text-secondary)] md:pb-1">
          <CalendarDays className="size-4" /> Период
        </div>
        <div className="flex min-w-0 flex-wrap gap-1 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-1">
          {PAGE_PRESETS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setPreset(item.key)}
              className={cx(
                "rounded-[var(--radius-sm)] px-3 py-1.5 text-[12px] font-medium transition-colors",
                preset === item.key ? "bg-[var(--accent)] text-[var(--text-inverse)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        {preset === "custom" ? (
          <div className="grid grid-cols-2 gap-2">
            <Field label="С">
              <Input type="date" value={customFrom} onChange={(event) => setCustomDate("from", event.target.value)} />
            </Field>
            <Field label="По">
              <Input type="date" value={customTo} onChange={(event) => setCustomDate("to", event.target.value)} />
            </Field>
          </div>
        ) : (
          <span className="rounded-full border border-[var(--border)] px-2.5 py-1.5 text-[11px] tabular-nums text-[var(--text-muted)]">
            {periodLabel}
          </span>
        )}
      </Card>

      <Card className="flex flex-wrap items-center justify-between gap-3 border-[var(--border-strong)]">
        <div className="flex items-start gap-3">
          <Bot className="mt-0.5 h-5 w-5 text-[var(--text-secondary)]" aria-hidden />
          <div>
            <div className="text-[13px] font-semibold">Настройка PvP-ботов</div>
            <p className="mt-1 text-[12px] text-[var(--text-muted)]">
              Банк казино, включение ботов, лимит проигрыша и проверка готовности.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/x8/casino/risk"
            className="rounded-[var(--radius)] border border-[var(--border-strong)] px-3 py-2 text-[12px] text-[var(--text-primary)] hover:border-[var(--accent)]"
          >
            Риск →
          </Link>
          <Link
            to="/x8/casino/house"
            className="rounded-[var(--radius)] border border-[var(--border-strong)] px-3 py-2 text-[12px] text-[var(--green)] hover:border-[var(--accent)]"
          >
            Роботы PvP →
          </Link>
        </div>
      </Card>

      {loading ? (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
          Считаем статистику казино…
        </Card>
      ) : error ? (
        <Card className="space-y-3">
          <div role="alert" className="text-[13px] text-[var(--red)]">
            {error}
          </div>
          <Button type="button" size="sm" onClick={() => void load()}>
            Повторить
          </Button>
        </Card>
      ) : data ? (
        <>
          <CasinoStatsView data={data} />
          <Card className="space-y-4">
            <h2 className="text-[14px] font-semibold">Топ кланов за неделю</h2>
            {(data.top_clans ?? []).length === 0 ? (
              <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">Кланов с оборотом пока нет</div>
            ) : (
              <div className="divide-y divide-[var(--border)]">
                {(data.top_clans ?? []).map((clan, index) => (
                  <div key={clan.tag} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="w-6 shrink-0 text-[12px] text-[var(--text-muted)]">{index + 1}</span>
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium">
                          [{clan.tag}] {clan.name}
                        </div>
                        <div className="text-[12px] text-[var(--text-muted)]">{clan.member_count} игроков</div>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="font-mono text-[13px] font-semibold tabular-nums">
                        {clan.wager_rub.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => {
                          if (!window.confirm(`Распустить [${clan.tag}]?`)) return;
                          void disbandCasinoClan(clan.id).then(() => void load());
                        }}
                      >
                        Распустить
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      ) : (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]">Показатели не получены</Card>
      )}
    </div>
  );
}
