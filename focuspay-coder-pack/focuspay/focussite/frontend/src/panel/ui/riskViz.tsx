function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function gaugeTone(value: number, warnAt?: number, dangerAt?: number): "ok" | "warn" | "danger" {
  if (dangerAt == null && warnAt == null) return "ok";
  if (dangerAt != null && warnAt != null && dangerAt < warnAt) {
    if (value <= dangerAt) return "danger";
    if (value <= warnAt) return "warn";
    return "ok";
  }
  if (dangerAt != null && value >= dangerAt) return "danger";
  if (warnAt != null && value >= warnAt) return "warn";
  return "ok";
}

const TONE_FILL: Record<"ok" | "warn" | "danger", string> = {
  ok: "var(--text-primary)",
  warn: "var(--yellow)",
  danger: "var(--red)",
};

const TONE_BADGE: Record<"ok" | "warn" | "danger", "default" | "yellow" | "red"> = {
  ok: "default",
  warn: "yellow",
  danger: "red",
};

function gaugeStatus(value: number, warnAt?: number, dangerAt?: number): string {
  const tone = gaugeTone(value, warnAt, dangerAt);
  if (tone === "danger") return "критично мало";
  if (tone === "warn") return "ниже порога";
  if (warnAt != null && warnAt > 0 && value < warnAt * 2) return "ниже цели";
  return "запас есть";
}

export function Gauge({
  value,
  min = 0,
  max,
  label,
  warnAt,
  dangerAt,
  markers,
  format = (n) => String(n),
}: {
  value: number;
  min?: number;
  max: number;
  label: string;
  warnAt?: number;
  dangerAt?: number;
  markers?: Array<{ value: number; label?: string }>;
  format?: (value: number) => string;
}) {
  const span = max - min || 1;
  const ratio = clamp((value - min) / span, 0, 1);
  const tone = gaugeTone(value, warnAt, dangerAt);
  const visibleMarkers = (markers ?? []).filter((marker) => Number.isFinite(marker.value) && marker.value > min);
  const aria = `${label}: ${format(value)}. ${gaugeStatus(value, warnAt, dangerAt)}`;

  return (
    <div className="w-full min-w-0 space-y-3" role="img" aria-label={aria}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[12px] text-[var(--text-muted)]">{label}</p>
          <p className="truncate font-mono text-[22px] font-semibold tabular-nums leading-tight">{format(value)}</p>
        </div>
        <span
          className={
            TONE_BADGE[tone] === "red"
              ? "inline-flex items-center rounded-full border border-[var(--red)]/30 bg-[var(--red-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--red)]"
              : TONE_BADGE[tone] === "yellow"
                ? "inline-flex items-center rounded-full border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--yellow)]"
                : "inline-flex items-center rounded-full border border-[var(--border-strong)] bg-[var(--bg-overlay)] px-2 py-0.5 text-[11px] font-semibold text-[var(--text-secondary)]"
          }
        >
          {gaugeStatus(value, warnAt, dangerAt)}
        </span>
      </div>
      <div className="space-y-1.5">
        <div className="relative h-3 overflow-visible rounded-full bg-[var(--bg-elevated)]">
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ width: `${ratio * 100}%`, background: TONE_FILL[tone] }}
          />
          {visibleMarkers.map((marker, index) => {
            const pct = clamp(((marker.value - min) / span) * 100, 0, 100);
            return (
              <span
                key={`${marker.value}-${index}`}
                className="absolute top-1/2 h-4 w-px -translate-x-1/2 -translate-y-1/2 bg-[var(--text-secondary)]"
                style={{ left: `${pct}%` }}
                title={marker.label ? `${marker.label}: ${format(marker.value)}` : format(marker.value)}
              />
            );
          })}
        </div>
        <div className="flex justify-between font-mono text-[10px] tabular-nums text-[var(--text-muted)]">
          <span>{compactAxis(min, format)}</span>
          <span>{compactAxis(max, format)}</span>
        </div>
      </div>
      {visibleMarkers.length ? (
        <ul className="grid gap-x-4 gap-y-1 text-[12px] sm:grid-cols-3">
          {visibleMarkers.map((marker, index) => (
            <li key={`${marker.label ?? "m"}-${index}`} className="flex min-w-0 justify-between gap-2">
              <span className="truncate text-[var(--text-muted)]">{marker.label ?? "метка"}</span>
              <span className="shrink-0 font-mono tabular-nums">{format(marker.value)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function compactAxis(value: number, format: (n: number) => string): string {
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`;
  }
  if (abs >= 10_000) {
    return `${Math.round(value / 1000).toLocaleString("ru-RU")} тыс.`;
  }
  return format(value);
}

function asSeries<T>(value: T | T[], length: number): T[] {
  return Array.isArray(value) ? value : Array.from({ length }, () => value);
}

export type CorridorKind = "empty" | "inside" | "below" | "above";

export function corridorStatus(
  actual: number | null | undefined,
  low: number,
  high: number,
  rounds: number,
): { kind: CorridorKind; label: string; hint: string } {
  if (rounds <= 0 || actual == null || !Number.isFinite(actual)) {
    return { kind: "empty", label: "нет партий", hint: "за окно нет завершённых игр" };
  }
  const sparse = rounds < 30;
  if (actual < low) {
    return {
      kind: "below",
      label: sparse ? "дом в плюсе · мало партий" : "дом в плюсе",
      hint: "игрокам вернули меньше расчёта",
    };
  }
  if (actual > high) {
    return {
      kind: "above",
      label: sparse ? "игроки в плюсе · мало партий" : "игроки в плюсе",
      hint: "игрокам вернули больше расчёта — смотреть аномалии",
    };
  }
  return {
    kind: "inside",
    label: sparse ? "в коридоре · мало партий" : "в коридоре",
    hint: "факт внутри полосы шума",
  };
}

function statusClass(kind: CorridorKind): string {
  if (kind === "above") return "border-[var(--red)]/30 bg-[var(--red-bg)] text-[var(--red)]";
  if (kind === "below") return "border-[var(--border-strong)] bg-[var(--bg-overlay)] text-[var(--text-secondary)]";
  if (kind === "inside") return "border-[var(--border-strong)] bg-[var(--bg-overlay)] text-[var(--text-secondary)]";
  return "border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--text-muted)]";
}

function niceDomain(values: number[]): { min: number; max: number } {
  const finite = values.filter((value) => Number.isFinite(value));
  if (!finite.length) return { min: 0, max: 120 };
  const rawMax = Math.max(100, ...finite);
  const step = rawMax > 200 ? 50 : 20;
  return { min: 0, max: Math.ceil(rawMax / step) * step };
}

export function CorridorChart({
  labels,
  actual,
  expected,
  corridorLow,
  corridorHigh,
  rounds,
  format = (n) => `${n.toFixed(0)}%`,
}: {
  labels: string[];
  actual: Array<number | null | undefined>;
  expected: number | Array<number | null | undefined>;
  corridorLow: number | number[];
  corridorHigh: number | number[];
  rounds?: number | number[];
  height?: number;
  format?: (value: number) => string;
}) {
  const n = labels.length;
  const low = asSeries(corridorLow, n);
  const high = asSeries(corridorHigh, n);
  const mid = asSeries(expected, n);
  const roundCounts = rounds == null ? asSeries(0, n) : asSeries(rounds, n);

  const rows = labels
    .map((label, i) => ({
      label,
      actual: actual[i] ?? null,
      expected: mid[i] ?? null,
      low: low[i],
      high: high[i],
      rounds: roundCounts[i] ?? 0,
    }))
    .filter((row) => row.rounds > 0);

  if (!rows.length) {
    return (
      <div className="flex items-center justify-center rounded-[var(--radius)] border border-dashed border-[var(--border-strong)] px-4 py-10 text-center text-[12px] text-[var(--text-muted)]">
        За окно нет завершённых партий — коридор строить не из чего
      </div>
    );
  }

  const scaleValues: number[] = [];
  for (const row of rows) {
    if (row.actual != null) scaleValues.push(row.actual);
    if (row.expected != null) scaleValues.push(row.expected);
    if (row.rounds > 0) {
      scaleValues.push(row.low, Math.min(row.high, 200));
    }
  }
  const domain = niceDomain(scaleValues);
  const span = domain.max - domain.min || 1;
  const xPct = (value: number) => clamp(((value - domain.min) / span) * 100, 0, 100);
  const ticks: number[] = [];
  const tickStep = domain.max > 200 ? 50 : 20;
  for (let tick = domain.min; tick <= domain.max; tick += tickStep) ticks.push(tick);

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
        <span>серая полоса — шум</span>
        <span>пунктир — формула</span>
        <span>● сколько вернули</span>
      </div>
      <div className="hidden sm:flex items-center gap-3 text-[10px] text-[var(--text-muted)]" aria-hidden>
        <span className="w-[7.5rem] shrink-0" />
        <div className="relative h-4 flex-1">
          {ticks.map((tick) => (
            <span
              key={tick}
              className="absolute -translate-x-1/2 font-mono tabular-nums"
              style={{ left: `${xPct(tick)}%` }}
            >
              {format(tick)}
            </span>
          ))}
        </div>
        <span className="w-[9.5rem] shrink-0" />
      </div>
      <div className="space-y-3">
        {rows.map((row) => {
          const status = corridorStatus(row.actual, row.low, row.high, row.rounds);
          const bandLeft = xPct(row.low);
          const bandRight = xPct(row.high);
          const theoryLeft = row.expected == null ? null : xPct(row.expected);
          const factLeft = row.actual == null ? null : xPct(row.actual);
          const outside = status.kind === "above" || status.kind === "below";
          return (
            <div key={row.label} className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
              <div className="w-full shrink-0 sm:w-[7.5rem]">
                <div className="truncate text-[13px]">{row.label}</div>
                <div className="text-[11px] text-[var(--text-muted)]">{row.rounds} парт.</div>
              </div>
              <div
                className="relative h-8 w-full min-w-0 flex-1 overflow-hidden rounded-[var(--radius)] bg-[var(--bg-elevated)]"
                role="img"
                aria-label={`${row.label}: факт ${row.actual == null ? "нет" : format(row.actual)}, теория ${row.expected == null ? "нет" : format(row.expected)}, ${row.rounds} партий, ${status.label}`}
              >
                <div
                  className="absolute inset-y-1 rounded-sm bg-[var(--text-muted)]/25"
                  style={{ left: `${bandLeft}%`, width: `${Math.max(bandRight - bandLeft, 1.2)}%` }}
                />
                {theoryLeft != null ? (
                  <span
                    className="absolute inset-y-0 border-l border-dashed border-[var(--text-secondary)]"
                    style={{ left: `${theoryLeft}%` }}
                  />
                ) : null}
                {factLeft != null ? (
                  <span
                    className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--bg-surface)]"
                    style={{
                      left: `${factLeft}%`,
                      background: outside ? "var(--red)" : "var(--text-primary)",
                    }}
                  />
                ) : null}
              </div>
              <div className="flex w-full shrink-0 flex-col items-start gap-0.5 sm:w-[9.5rem] sm:items-end">
                <span className={`inline-flex max-w-full rounded-full border px-2 py-0.5 text-[10px] font-semibold ${statusClass(status.kind)}`}>
                  {status.label}
                </span>
                <span className="font-mono text-[11px] tabular-nums text-[var(--text-muted)]">
                  {row.actual == null ? "—" : format(row.actual)}
                  {" / "}
                  {row.expected == null ? "—" : format(row.expected)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
