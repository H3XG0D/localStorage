// Smooth line/area chart for panel dashboards. No chart dependency: monotone
// cubic interpolation keeps the curve from overshooting between data points.
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "@/panel/ui/primitives";

export type ChartPoint = { key: string; label: string };

export type ChartAxis = "left" | "right";

export type ChartSeries = {
  key: string;
  label: string;
  color: string;
  values: number[];
  fill?: boolean;
  dashed?: boolean;
  /** Series on the right axis get their own scale — mixing millions with thousands on one scale flattens the smaller series to zero. */
  axis?: ChartAxis;
};

const PAD = { top: 22, right: 14, bottom: 24, left: 46 };
const PAD_RIGHT_AXIS = 56;

function niceTicks(min: number, max: number, count: number): number[] {
  const lo = Math.min(0, min);
  const hi = max === lo ? lo + 1 : max;
  const raw = (hi - lo) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const out: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) out.push(Number(v.toFixed(6)));
  return out.length > 1 ? out : [start, start + step];
}

/** Fritsch–Carlson tangents: smooth but never bulges past the data. */
function monotoneTangents(xs: number[], ys: number[]): number[] {
  const n = xs.length;
  if (n < 2) return [0];
  const delta: number[] = [];
  for (let i = 0; i < n - 1; i += 1) {
    const dx = xs[i + 1] - xs[i];
    delta.push(dx === 0 ? 0 : (ys[i + 1] - ys[i]) / dx);
  }
  const m: number[] = new Array(n).fill(0);
  m[0] = delta[0];
  m[n - 1] = delta[n - 2];
  for (let i = 1; i < n - 1; i += 1) {
    if (delta[i - 1] * delta[i] <= 0) m[i] = 0;
    else m[i] = (delta[i - 1] + delta[i]) / 2;
  }
  for (let i = 0; i < n - 1; i += 1) {
    if (delta[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / delta[i];
    const b = m[i + 1] / delta[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = (3 / Math.sqrt(s)) * delta[i];
      m[i] = t * a;
      m[i + 1] = t * b;
    }
  }
  return m;
}

function smoothPath(xs: number[], ys: number[]): string {
  if (!xs.length) return "";
  if (xs.length === 1) return `M ${xs[0]} ${ys[0]}`;
  const m = monotoneTangents(xs, ys);
  let d = `M ${xs[0]} ${ys[0]}`;
  for (let i = 0; i < xs.length - 1; i += 1) {
    const dx = (xs[i + 1] - xs[i]) / 3;
    d += ` C ${xs[i] + dx} ${ys[i] + m[i] * dx}, ${xs[i + 1] - dx} ${ys[i + 1] - m[i + 1] * dx}, ${xs[i + 1]} ${ys[i + 1]}`;
  }
  return d;
}

export function LineAreaChart({
  points,
  series,
  height = 208,
  hover,
  onHover,
  formatTick,
  formatTickRight,
  tooltip,
  emptyHint,
  summary,
}: {
  points: ChartPoint[];
  series: ChartSeries[];
  height?: number;
  hover: number | null;
  onHover: (i: number | null) => void;
  formatTick?: (v: number) => string;
  formatTickRight?: (v: number) => string;
  tooltip?: (i: number) => ReactNode;
  emptyHint?: string;
  summary?: ReactNode;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const hasRightAxis = series.some((s) => s.axis === "right");
  const padRight = hasRightAxis ? PAD_RIGHT_AXIS : PAD.right;
  const plotW = Math.max(80, width - PAD.left - padRight);
  const plotH = Math.max(60, height - PAD.top - PAD.bottom);

  const { ticks, rightTicks, yOf, yRightOf, xOf, paths } = useMemo(() => {
    const scaleFor = (list: ChartSeries[]) => {
      const all = list.flatMap((s) => s.values);
      const max = all.length ? Math.max(...all) : 1;
      const min = all.length ? Math.min(...all) : 0;
      const ticks = niceTicks(min, max, 4);
      const lo = ticks[0];
      const hi = ticks[ticks.length - 1];
      const span = hi - lo || 1;
      return { ticks, lo, y: (v: number) => PAD.top + plotH - ((v - lo) / span) * plotH };
    };
    const left = scaleFor(series.filter((s) => s.axis !== "right"));
    const right = hasRightAxis ? scaleFor(series.filter((s) => s.axis === "right")) : null;
    const count = points.length;
    const xOf = (i: number) => (count <= 1 ? PAD.left + plotW / 2 : PAD.left + (i / (count - 1)) * plotW);
    const xs = points.map((_, i) => xOf(i));
    const paths = series.map((s) => {
      const scale = s.axis === "right" && right ? right : left;
      const ys = s.values.map((v) => scale.y(v));
      const line = smoothPath(xs, ys);
      const base = scale.y(Math.max(scale.lo, 0));
      const area = line && xs.length > 1 ? `${line} L ${xs[xs.length - 1]} ${base} L ${xs[0]} ${base} Z` : "";
      return { line, area, ys };
    });
    return { ticks: left.ticks, rightTicks: right?.ticks ?? [], yOf: left.y, yRightOf: right?.y ?? left.y, xOf, paths };
  }, [series, points, plotW, plotH, hasRightAxis]);

  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 52))));

  const pick = useCallback(
    (clientX: number) => {
      const el = boxRef.current;
      if (!el || points.length === 0) return;
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left;
      const rel = points.length <= 1 ? 0 : ((x - PAD.left) / plotW) * (points.length - 1);
      onHover(Math.min(points.length - 1, Math.max(0, Math.round(rel))));
    },
    [onHover, plotW, points.length],
  );

  const onKey = (e: React.KeyboardEvent) => {
    if (!points.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const step = e.key === "ArrowRight" ? 1 : -1;
      const next = hover == null ? 0 : hover + step;
      onHover(Math.min(points.length - 1, Math.max(0, next)));
    } else if (e.key === "Escape") {
      onHover(null);
    }
  };

  const hoverX = hover != null ? xOf(hover) : 0;
  const tipSide = hoverX > PAD.left + plotW * 0.6 ? "right" : "left";
  const signature = `${points.length}:${points[0]?.key ?? ""}:${points[points.length - 1]?.key ?? ""}`;

  if (!points.length) {
    return (
      <div
        className="flex items-center justify-center rounded-[var(--radius)] border border-dashed border-[var(--border-strong)] text-[12px] text-[var(--text-muted)]"
        style={{ height }}
      >
        {emptyHint ?? "Нет данных"}
      </div>
    );
  }

  return (
    <div
      ref={boxRef}
      className="relative w-full select-none"
      style={{ height }}
      onPointerMove={(e) => pick(e.clientX)}
      onPointerLeave={() => onHover(null)}
      onKeyDown={onKey}
      tabIndex={0}
      role="img"
      aria-label={series.map((s) => s.label).join(", ")}
    >
      <svg width={width} height={height} className="overflow-visible">
        <defs>
          {series.map((s, si) => (
            <linearGradient key={s.key} id={`${uid}-g${si}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity="0.32" />
              <stop offset="55%" stopColor={s.color} stopOpacity="0.10" />
              <stop offset="100%" stopColor={s.color} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>

        {ticks.map((t, ti) => {
          const text = formatTick ? formatTick(t) : String(t);
          // Coarse formatters (тыс/млн) can collapse neighbouring ticks to the
          // same string — draw the gridline but skip the repeated label.
          const dup = ti > 0 && text === (formatTick ? formatTick(ticks[ti - 1]) : String(ticks[ti - 1]));
          return (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={PAD.left + plotW}
                y1={yOf(t)}
                y2={yOf(t)}
                stroke="var(--border)"
                strokeDasharray={t === ticks[0] ? undefined : "3 5"}
              />
              {dup ? null : (
                <text
                  x={PAD.left - 8}
                  y={yOf(t) + 3.5}
                  textAnchor="end"
                  className="fill-[var(--text-muted)] text-[10px] tabular-nums"
                >
                  {text}
                </text>
              )}
            </g>
          );
        })}

        {rightTicks.map((t, ti) => {
          const fmt = formatTickRight ?? formatTick;
          const text = fmt ? fmt(t) : String(t);
          const dup = ti > 0 && text === (fmt ? fmt(rightTicks[ti - 1]) : String(rightTicks[ti - 1]));
          if (dup) return null;
          return (
            <text
              key={`r${t}`}
              x={PAD.left + plotW + 8}
              y={yRightOf(t) + 3.5}
              textAnchor="start"
              className="fill-[var(--text-muted)] text-[10px] tabular-nums"
            >
              {text}
            </text>
          );
        })}

        {hover != null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={PAD.top}
            y2={PAD.top + plotH}
            stroke="var(--border-strong)"
            strokeDasharray="3 4"
          />
        ) : null}

        {series.map((s, si) => (
          <g key={s.key}>
            {s.fill !== false && paths[si].area ? (
              <path
                key={`area-${signature}`}
                d={paths[si].area}
                fill={`url(#${uid}-g${si})`}
                className="panel-chart-area"
              />
            ) : null}
            <path
              key={`line-${signature}`}
              d={paths[si].line}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray={s.dashed ? "5 4" : undefined}
              pathLength={s.dashed ? undefined : 1}
              className={s.dashed ? undefined : "panel-chart-line"}
            />
            {points.length === 1 ? <circle cx={xOf(0)} cy={paths[si].ys[0]} r={4} fill={s.color} /> : null}
            {hover != null ? (
              <g>
                <circle cx={hoverX} cy={paths[si].ys[hover]} r={7} fill={s.color} opacity={0.18} />
                <circle
                  cx={hoverX}
                  cy={paths[si].ys[hover]}
                  r={3.5}
                  fill="var(--bg-surface)"
                  stroke={s.color}
                  strokeWidth={2}
                />
              </g>
            ) : null}
          </g>
        ))}

        {points.map((p, i) =>
          i % labelEvery === 0 || i === points.length - 1 ? (
            <text
              key={p.key}
              x={xOf(i)}
              y={PAD.top + plotH + 15}
              textAnchor="middle"
              className={cx(
                "text-[10px]",
                hover === i ? "fill-[var(--text-primary)]" : "fill-[var(--text-muted)]",
              )}
            >
              {p.label}
            </text>
          ) : null,
        )}
      </svg>

      {hover != null && tooltip ? (
        <div
          className="pointer-events-none absolute z-10 min-w-[7rem] rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-overlay)] px-2.5 py-1.5 text-[11px] shadow-[var(--shadow)]"
          style={{
            left: tipSide === "left" ? hoverX + 12 : undefined,
            right: tipSide === "right" ? width - hoverX + 12 : undefined,
            top: PAD.top,
          }}
        >
          {tooltip(hover)}
        </div>
      ) : null}

      {summary ? (
        <div className="pointer-events-none absolute right-1 top-0 font-mono text-[12px] font-semibold tabular-nums text-[var(--text-primary)]">
          {summary}
        </div>
      ) : null}
    </div>
  );
}
