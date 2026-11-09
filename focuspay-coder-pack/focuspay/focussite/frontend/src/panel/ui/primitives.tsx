// Panel UI primitives — dark admin design system (ported from focus-panel).
// Kept dependency-light: plain elements + theme tokens via panel.css variables.
import { forwardRef, useEffect, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { Link } from "react-router-dom";

type Cls = string | false | null | undefined;
export function cx(...parts: Cls[]): string {
  return parts.filter(Boolean).join(" ");
}

/* ---------- Button ---------- */
type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
type BtnSize = "sm" | "md";
const btnBase =
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius)] font-medium whitespace-nowrap transition-colors disabled:opacity-50 disabled:pointer-events-none";
const btnVariant: Record<BtnVariant, string> = {
  primary: "bg-[var(--accent)] text-[var(--text-inverse)] hover:bg-[var(--accent-hover)]",
  secondary: "bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--border-strong)] hover:bg-[var(--bg-overlay)]",
  ghost: "text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]",
  danger: "bg-[var(--red-bg)] text-[var(--red)] border border-[var(--red)]/30 hover:bg-[var(--red)]/20",
};
const btnSize: Record<BtnSize, string> = { sm: "h-8 px-3 text-[12.5px]", md: "h-9 px-4 text-[13px]" };

export function Button({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: BtnSize }) {
  return (
    <button className={cx(btnBase, btnVariant[variant], btnSize[size], "active:scale-[0.98]", className)} {...props}>
      {children}
    </button>
  );
}

/* ---------- Badge ---------- */
export type BadgeTone = "default" | "green" | "yellow" | "red" | "blue" | "purple" | "orange";
const badgeTone: Record<BadgeTone, string> = {
  default: "bg-[var(--bg-overlay)] text-[var(--text-secondary)] border-[var(--border-strong)]",
  green: "bg-[var(--green-bg)] text-[var(--green)] border-[var(--green)]/30",
  yellow: "bg-[var(--yellow-bg)] text-[var(--yellow)] border-[var(--yellow)]/30",
  red: "bg-[var(--red-bg)] text-[var(--red)] border-[var(--red)]/30",
  blue: "bg-[var(--blue-bg)] text-[var(--blue)] border-[var(--blue)]/30",
  purple: "bg-[var(--purple-bg)] text-[var(--purple)] border-[var(--purple)]/30",
  orange: "bg-[var(--orange-bg)] text-[var(--orange)] border-[var(--orange)]/30",
};
export function Badge({ tone = "default", children, className }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold", badgeTone[tone], className)}>
      {children}
    </span>
  );
}

/* ---------- Card ---------- */
export function Card({ children, className, id }: { children: ReactNode; className?: string; id?: string }) {
  return (
    <div id={id} className={cx("rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-5", className)}>
      {children}
    </div>
  );
}

/* ---------- Input / Select ---------- */
const fieldBase =
  "h-9 w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--text-muted)]";
export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(fieldBase, className)} {...props} />;
}
export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(fieldBase, "cursor-pointer", className)} {...props}>
      {children}
    </select>
  );
}
export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-snug text-[var(--text-muted)]">{hint}</span>}
    </label>
  );
}

/* ---------- KPI ---------- */
export function Kpi({
  label,
  value,
  hint,
  trend,
  onClick,
  active,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  trend?: number;
  onClick?: () => void;
  active?: boolean;
}) {
  const roundedTrend = typeof trend === "number" ? Math.round(trend) : undefined;
  const className = cx(
    "flex flex-col gap-2 rounded-[var(--radius-lg)] border bg-[var(--bg-surface)] p-5 text-left transition-colors",
    active ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/40" : "border-[var(--border)] hover:border-[var(--border-strong)]",
    onClick && "w-full cursor-pointer",
  );
  const body = (
    <>
      <div className="flex min-w-0 items-start justify-between gap-2">
        <span className="min-w-0 text-[12px] text-[var(--text-muted)]">{label}</span>
        {typeof roundedTrend === "number" && roundedTrend !== 0 && (
          <Badge tone={roundedTrend > 0 ? "green" : "red"} className="shrink-0">
            {roundedTrend > 0 ? "+" : ""}
            {roundedTrend}%
          </Badge>
        )}
      </div>
      <div className="font-mono text-2xl font-extrabold tracking-tight tabular-nums">{value}</div>
      {hint && <div className="text-[11px] text-[var(--text-muted)]">{hint}</div>}
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={className}>
        {body}
      </button>
    );
  }
  return <div className={className}>{body}</div>;
}

/* ---------- Tabs ---------- */
export type TabItem = { id: string; label: string };
export function Tabs({
  value,
  onChange,
  items,
  className,
}: {
  value: string;
  onChange: (id: string) => void;
  items: TabItem[];
  className?: string;
}) {
  return (
    <div role="tablist" className={cx("flex flex-wrap gap-1 border-b border-[var(--border)]", className)}>
      {items.map((item) => {
        const active = value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            data-tab={item.id}
            className={cx(
              "-mb-px h-9 px-3 text-[13px] font-medium",
              active
                ? "border-b-2 border-[var(--text-primary)] text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
            )}
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Table ---------- */
export interface Column<Row> {
  key: string;
  label: string;
  width?: string;
  align?: "left" | "right" | "center";
  render?: (row: Row) => ReactNode;
}
export function Table<Row extends Record<string, unknown>>({
  columns,
  rows,
  empty = "Нет данных",
  onRowClick,
  rowHref,
  rowState,
}: {
  columns: Column<Row>[];
  rows: Row[];
  empty?: string;
  onRowClick?: (row: Row) => void;
  rowHref?: (row: Row) => string | null | undefined;
  rowState?: (row: Row) => unknown;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {columns.map((c) => (
              <th
                key={c.key}
                style={{ width: c.width, textAlign: c.align ?? "left" }}
                className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]"
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-3 py-10 text-center text-[var(--text-muted)]">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => {
              const href = rowHref?.(row) || undefined;
              const clickable = Boolean(href || onRowClick);
              return (
                <tr
                  key={(row.id as string | number) ?? i}
                  onClick={!href && onRowClick ? () => onRowClick(row) : undefined}
                  className={cx(
                    "border-b border-[var(--border)] last:border-0",
                    clickable && "cursor-pointer hover:bg-[var(--bg-elevated)]",
                  )}
                >
                  {columns.map((c) => {
                    const content = c.render ? c.render(row) : String(row[c.key] ?? "—");
                    return (
                      <td
                        key={c.key}
                        style={{ textAlign: c.align ?? "left" }}
                        className={cx("text-[var(--text-primary)]", href ? "p-0" : "px-3 py-2.5")}
                      >
                        {href ? (
                          <Link
                            to={href}
                            state={rowState?.(row)}
                            className="block px-3 py-2.5 text-inherit no-underline hover:text-inherit"
                          >
                            {content}
                          </Link>
                        ) : (
                          content
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Modal ---------- */
export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg" | "xl";
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Autofocus only when the dialog opens. Do not depend on `onClose` identity —
  // parents often pass inline lambdas, and re-running focus after each keystroke
  // steals focus from inputs onto the header close button.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKeyDown);

    const root = dialogRef.current;
    if (root) {
      const active = document.activeElement;
      const alreadyInside = active instanceof HTMLElement && root.contains(active);
      if (!alreadyInside) {
        const field = root.querySelector<HTMLElement>("input:not([disabled]), select:not([disabled]), textarea:not([disabled])");
        const fallback = root.querySelector<HTMLElement>("button:not([disabled]), input, select, textarea, a[href]");
        (field ?? fallback)?.focus();
      }
    }

    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!open) return null;
  const width = size === "xl" ? "max-w-5xl" : size === "lg" ? "max-w-3xl" : "max-w-lg";
  const bodyMax = size === "xl" ? "max-h-[min(86vh,920px)]" : "max-h-[min(70vh,720px)]";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal aria-label={title}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div ref={dialogRef} className={cx("relative z-10 w-full rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-surface)] shadow-[var(--shadow-lg)] motion-safe:animate-[panel-modal-in_180ms_ease-out]", width)}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3.5">
          <h3 className="text-[14px] font-semibold">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Закрыть" className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]">✕</button>
        </div>
        <div className={cx("overflow-y-auto p-5", bodyMax)}>{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border)] px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------- Page header ---------- */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[12.5px] text-[var(--text-muted)]">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export {
  DangerZone,
  DiffRow,
  SAVE_BAR_H,
  SaveBar,
  SettingsSection,
  ValidationSummary,
  diffSegments,
  useDirtyForm,
  type FieldError,
} from "./settingsPrimitives";
export { TierGridEditor, type TierColumn, type TierGridEditorProps } from "./TierGridEditor";
export { CorridorChart, Gauge } from "./riskViz";
