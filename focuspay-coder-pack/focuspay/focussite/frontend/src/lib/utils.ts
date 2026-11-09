import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMoney(value: number | string | null | undefined) {
  const amount = Number(value ?? 0);
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(amount);
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

/** Format a crypto amount with sensible precision (up to 8 dp, trimmed). */
export function formatCrypto(value: number | string | null | undefined, maxDigits = 8) {
  const amount = Number(value ?? 0);
  if (!isFinite(amount)) return "0";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: maxDigits }).format(amount);
}
