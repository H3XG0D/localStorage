import type { Dict } from "@/panel/lib/adminApi";

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const preciseFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

export function num(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function money(value: unknown, precise = false) {
  if (value === null || value === undefined || value === "") return "—";
  return (precise ? preciseFormat : numberFormat).format(num(value));
}

export function moneyRub(value: unknown, precise = false) {
  if (value === null || value === undefined || value === "") return "—";
  return `${money(value, precise)} ₽`;
}

export function percent(value: unknown) {
  return `${num(value).toFixed(1).replace(".0", "")}%`;
}

export function dateShort(value: unknown) {
  const raw = String(value ?? "");
  const parsed = new Date(`${raw}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return raw.slice(8) || "—";
  return parsed.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

export function dateFull(value: unknown) {
  const raw = String(value ?? "");
  const parsed = new Date(`${raw}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return raw || "—";
  return parsed.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" });
}

export function signedMoney(value: unknown) {
  const amount = num(value);
  return `${amount > 0 ? "+" : ""}${money(amount, true)} ₽`;
}

export function asDict(v: unknown): Dict {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Dict) : {};
}

export function asList(v: unknown): Dict[] {
  return Array.isArray(v) ? (v as Dict[]) : [];
}

export function ordersTotalLabel(count: number, fiat?: unknown) {
  if (fiat === null || fiat === undefined || fiat === "") return `${count} заявок`;
  return `${count} заявок · ${money(fiat)} ₽`;
}

export function sum(values: number[]) {
  return values.reduce((acc, v) => acc + v, 0);
}

export type FinanceKpiKey =
  | "turnover"
  | "deals"
  | "service_profit"
  | "service_profit_total"
  | "after_costs"
  | "owner_residual";

// Backend /finance-overview returns kpi as a positional list and some waterfall
// steps are conditional, so match on the label and keep the index as fallback.
const KPI_MATCH: { key: FinanceKpiKey; test: (label: string) => boolean; index: number }[] = [
  { key: "turnover", test: (l) => l.startsWith("оборот"), index: 0 },
  { key: "deals", test: (l) => l.includes("сдел") && l.includes("количеств"), index: 1 },
  { key: "service_profit", test: (l) => l.includes("до начислений"), index: 2 },
  { key: "service_profit_total", test: (l) => l.includes("внештат") || l.includes("казино"), index: 3 },
  { key: "after_costs", test: (l) => l.includes("после начислений"), index: 4 },
  { key: "owner_residual", test: (l) => l.includes("остаток"), index: 5 },
];

/** Value + delta for one finance KPI, matched by label with positional fallback. */
export function financeKpi(finance: unknown, key: FinanceKpiKey): { value: number | null; deltaPct?: number } {
  const rows = asList(asDict(finance).kpi);
  const rule = KPI_MATCH.find((item) => item.key === key);
  if (!rule) return { value: null };
  const byLabel = rows.find((row) => rule.test(String(row.label ?? "").toLowerCase()));
  const row = byLabel ?? rows[rule.index];
  if (!row) return { value: null };
  return {
    value: row.value === null || row.value === undefined ? null : num(row.value),
    deltaPct: typeof row.deltaPct === "number" ? row.deltaPct : undefined,
  };
}
