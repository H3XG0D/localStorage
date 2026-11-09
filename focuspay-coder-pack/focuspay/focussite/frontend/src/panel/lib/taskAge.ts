/** Relative age for Ops AI queue rows (`created_at` is timestamptz). */

export function formatTaskAge(value: unknown, now = Date.now()): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "—";
  const iso = /Z$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw.replace(" ", "T")}Z`;
  const time = new Date(iso).getTime();
  if (!Number.isFinite(time)) return "—";
  const minutes = Math.max(0, Math.floor((now - time) / 60000));
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  return `${Math.floor(hours / 24)} д назад`;
}
