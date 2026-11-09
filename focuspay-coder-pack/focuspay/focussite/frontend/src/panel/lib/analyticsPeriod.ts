export type PeriodPreset = "today" | "yesterday" | "week" | "month" | "year" | "custom";
export type AnalyticsTab = "overview" | "finance" | "traffic" | "clients" | "channels" | "casino";
export type MskClock = { ymd: string; hour: number; month: string };

export const ANALYTICS_TZ = "Europe/Moscow";

export const PERIOD_PRESETS: { key: PeriodPreset; label: string }[] = [
  { key: "today", label: "Сегодня" },
  { key: "yesterday", label: "Вчера" },
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
  { key: "year", label: "Год" },
  { key: "custom", label: "Свой" },
];

export const ANALYTICS_TABS: { key: AnalyticsTab; label: string }[] = [
  { key: "overview", label: "Обзор" },
  { key: "finance", label: "Финансы" },
  { key: "casino", label: "Казино" },
  { key: "traffic", label: "Трафик" },
  { key: "clients", label: "Клиенты" },
  { key: "channels", label: "Каналы" },
];

export function isoDate(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function moscowYmd(date = new Date()): string {
  const map = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: ANALYTICS_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(date)
      .map((p) => [p.type, p.value]),
  );
  return `${map.year}-${map.month}-${map.day}`;
}

function hasExplicitOffset(iso: string): boolean {
  return /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso.trim());
}

/** orders.created_at is TIMESTAMP WITHOUT TIME ZONE stored as naive UTC. */
export function parseOrderInstant(iso: string): Date | null {
  const raw = String(iso || "").trim();
  if (!raw) return null;
  const normalized = (raw.includes("T") ? raw : raw.replace(" ", "T")).replace(/(\.\d{3})\d+/, "$1");
  const parsed = hasExplicitOffset(normalized) ? new Date(normalized) : new Date(`${normalized}Z`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

export function mskClock(iso: string): MskClock | null {
  const instant = parseOrderInstant(iso);
  if (!instant) return null;
  const map = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: ANALYTICS_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hour12: false,
    })
      .formatToParts(instant)
      .map((p) => [p.type, p.value]),
  );
  const y = map.year;
  const mo = String(map.month || "").padStart(2, "0");
  const da = String(map.day || "").padStart(2, "0");
  let hour = Number(map.hour);
  if (hour === 24) hour = 0;
  if (!y || !/^\d{2}$/.test(mo) || !/^\d{2}$/.test(da) || !Number.isFinite(hour)) return null;
  hour = Math.min(23, Math.max(0, hour));
  return { ymd: `${y}-${mo}-${da}`, hour, month: `${y}-${mo}` };
}

export function shiftIso(ymd: string, delta: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10);
}

export function localRange(preset: PeriodPreset): { from: string; to: string } {
  const today = moscowYmd();
  if (preset === "yesterday") {
    const y = shiftIso(today, -1);
    return { from: y, to: y };
  }
  if (preset === "week") return { from: shiftIso(today, -6), to: today };
  if (preset === "month") return { from: shiftIso(today, -29), to: today };
  if (preset === "year") return { from: `${today.slice(0, 4)}-01-01`, to: today };
  return { from: today, to: today };
}

export function ownerPeriodOf(preset: PeriodPreset): "today" | "yesterday" | "week" | "month" | "year" {
  if (preset === "custom" || preset === "week") return "week";
  return preset;
}

export function isYmd(v: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(v);
}

export function daysInclusive(from: string, to: string): number {
  if (!isYmd(from) || !isYmd(to) || from > to) return 1;
  const a = Date.UTC(Number(from.slice(0, 4)), Number(from.slice(5, 7)) - 1, Number(from.slice(8, 10)));
  const b = Date.UTC(Number(to.slice(0, 4)), Number(to.slice(5, 7)) - 1, Number(to.slice(8, 10)));
  return Math.round((b - a) / 86_400_000) + 1;
}

export function previousRange(from: string, to: string): { from: string; to: string } {
  const days = daysInclusive(from, to);
  const prevTo = shiftIso(from, -1);
  return { from: shiftIso(prevTo, -(days - 1)), to: prevTo };
}
