import type { BadgeTone } from "@/panel/ui/primitives";

export function bytes(v: unknown): string {
  const x = Number(v);
  if (!Number.isFinite(x)) return "—";
  if (x < 1024) return `${x} Б`;
  if (x < 1024 ** 2) return `${(x / 1024).toFixed(1)} КБ`;
  if (x < 1024 ** 3) return `${(x / 1024 ** 2).toFixed(1)} МБ`;
  return `${(x / 1024 ** 3).toFixed(2)} ГБ`;
}

export function when(v: unknown): string {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function purchaseTitle(row: { kind?: unknown; plan_code?: unknown }): string {
  const code = String(row.plan_code || "");
  if (row.kind === "trial") return "триал";
  if (row.kind === "device") return code ? `устройство · ${code}` : "устройство";
  return code;
}

export const PURCHASE_STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  held: { label: "в обработке", tone: "yellow" },
  granted: { label: "дни выданы, списание ждёт", tone: "blue" },
  paid: { label: "оплачено", tone: "green" },
  released: { label: "возврат", tone: "default" },
  failed: { label: "отказ", tone: "red" },
};

export const NODE_STATE: Record<string, { label: string; tone: BadgeTone }> = {
  HEALTHY: { label: "работает", tone: "green" },
  DEGRADED: { label: "с перебоями", tone: "yellow" },
  DRAINING: { label: "выводится", tone: "orange" },
  OFFLINE: { label: "недоступна", tone: "red" },
};

export function loadTone(load: number): string {
  if (load >= 0.85) return "var(--red)";
  if (load >= 0.6) return "var(--yellow)";
  return "var(--green)";
}

export type PlanPrice = { perDay: number; discountPct: number };

/** Per-day price and discount against the most expensive per-day plan (same rule as the bot cards). */
export function planPrices(plans: { days: number; price_rub: string | number }[]): PlanPrice[] {
  const perDay = plans.map((p) => {
    const price = Number(p.price_rub);
    return p.days > 0 && Number.isFinite(price) ? price / p.days : 0;
  });
  const base = Math.max(0, ...perDay);
  return perDay.map((d) => ({
    perDay: Math.round(d * 100) / 100,
    discountPct: base > 0 && d > 0 ? Math.max(0, Math.round((1 - d / base) * 100)) : 0,
  }));
}

export function pluralDays(n: number): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} день`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return `${n} дня`;
  return `${n} дней`;
}
