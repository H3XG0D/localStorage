export const BROADCAST_AI_DEFAULT_ENABLED = false;
export const BROADCAST_STICKER_MODE_DEFAULT: "auto" | "none" = "none";
export const BROADCAST_MAX_STICKERS = 1;
export const BROADCAST_AI_PROFILE_DEFAULT = "default";

export type StickerMode = "none" | "selected" | "auto";
export type BroadcastSendMode = "now" | "once" | "repeat";
export type BroadcastDestination = "bot" | "news";

export function normalizeDestination(value: unknown): BroadcastDestination {
  return value === "news" ? "news" : "bot";
}

export function destinationTitle(value: unknown): string {
  return normalizeDestination(value) === "news" ? "Новости" : "Бот";
}

export const WEEKDAY_OPTIONS = [
  { id: 1, label: "Пн" },
  { id: 2, label: "Вт" },
  { id: 3, label: "Ср" },
  { id: 4, label: "Чт" },
  { id: 5, label: "Пт" },
  { id: 6, label: "Сб" },
  { id: 7, label: "Вс" },
] as const;

export const ALL_WEEKDAYS = WEEKDAY_OPTIONS.map((item) => item.id);

export type BroadcastSticker = {
  id: string;
  label?: string;
  emoji?: string;
  preview_url?: string;
  available?: boolean;
};

export type AiDraftResult = {
  original_text: string;
  improved_text: string | null;
  suggested_sticker_ids: string[];
  error?: string | null;
};

export function parseStickerCatalog(raw: unknown): BroadcastSticker[] {
  const root = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const list = Array.isArray(raw) ? raw : Array.isArray(root.stickers) ? root.stickers : [];
  const out: BroadcastSticker[] = [];
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const id = String(row.id || "").trim();
    if (!id) continue;
    out.push({
      id,
      label: row.label != null ? String(row.label) : id,
      emoji: row.emoji != null ? String(row.emoji) : "",
      preview_url: row.preview_url != null ? String(row.preview_url) : "",
      available: row.available !== false,
    });
  }
  return out;
}

export function catalogIsEmpty(raw: unknown, parsed: BroadcastSticker[]): boolean {
  if (raw && typeof raw === "object" && (raw as Record<string, unknown>).catalog_empty === true) return true;
  return parsed.length === 0;
}

export function toggleStickerId(current: string[], id: string, max = BROADCAST_MAX_STICKERS): string[] {
  const sid = id.trim();
  if (!sid) return current;
  if (current.includes(sid)) return current.filter((item) => item !== sid);
  if (current.length >= max) return current;
  return [...current, sid];
}

export function resolveStickerMode(autoPick: boolean, selected: string[]): StickerMode {
  if (autoPick) return "auto";
  return selected.length ? "selected" : "none";
}

const FALLBACK_EMOJI: Array<{ needles: string[]; emoji: string }> = [
  { needles: ["промо", "скидк", "бонус", "подарок", "розыгрыш", "кэшбэк", "кешбэк", "выгод", "promo", "gift"], emoji: "✨" },
  { needles: ["курс", "pulse", "rate", "котир"], emoji: "🪐" },
  { needles: ["оплат", "paid", "карт", "сбп"], emoji: "🔑" },
  { needles: ["готов", "done", "успеш"], emoji: "✔️" },
  { needles: ["спасиб", "thank"], emoji: "💌" },
  { needles: ["помог", "help", "support"], emoji: "🩹" },
  { needles: ["привет", "hello", "hi "], emoji: "🪽" },
  { needles: ["новост", "news", "обновл"], emoji: "📝" },
];
const DEFAULT_EMOJIS = ["⭐", "✨", "✔️", "🪐"];

export function stickerPreviewUrl(scope: "admin" | "operator", id: string, previewUrl?: string): string {
  const sid = id.trim();
  const raw = (previewUrl || "").trim();
  if (raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("/api/")) return raw;
  if (raw.startsWith("/broadcast/")) return `/api/${scope}${raw}`;
  if (!sid) return "";
  return `/api/${scope}/broadcast/stickers/${encodeURIComponent(sid)}/preview`;
}

export function pickFallbackSticker(catalog: BroadcastSticker[], text: string): BroadcastSticker | undefined {
  const available = catalog.filter((item) => item.available !== false);
  if (!available.length) return undefined;
  const byEmoji = new Map<string, BroadcastSticker>();
  for (const item of available) {
    const emoji = (item.emoji || "").trim();
    if (emoji && !byEmoji.has(emoji)) byEmoji.set(emoji, item);
  }
  const blob = text.trim().toLowerCase();
  for (const rule of FALLBACK_EMOJI) {
    if (rule.needles.some((n) => blob.includes(n))) {
      const hit = byEmoji.get(rule.emoji);
      if (hit) return hit;
    }
  }
  for (const emoji of DEFAULT_EMOJIS) {
    const hit = byEmoji.get(emoji);
    if (hit) return hit;
  }
  return available[0];
}

export function pickFallbackStickerId(text: string, catalog: BroadcastSticker[] = []): string {
  return pickFallbackSticker(catalog, text)?.id || "";
}

export function plannedPreviewStickers(input: {
  catalog: BroadcastSticker[];
  autoPick: boolean;
  selectedIds: string[];
  text: string;
  catalogEmpty: boolean;
}): BroadcastSticker[] {
  if (input.catalogEmpty) return [];
  if (input.autoPick) {
    const picked = pickFallbackSticker(input.catalog, input.text);
    return picked ? [picked] : [];
  }
  return input.catalog.filter((item) => input.selectedIds.includes(item.id));
}

export function buildCreateJobBody(input: {
  segment: string;
  destination?: BroadcastDestination;
  text: string;
  selectedStickerIds: string[];
  autoPick: boolean;
  scheduledAt?: string;
}): { segment: string; destination: BroadcastDestination; text: string; selected_sticker_ids: string[]; sticker_mode: StickerMode; scheduled_at?: string } {
  const sticker_mode = resolveStickerMode(input.autoPick, input.selectedStickerIds);
  const body: { segment: string; destination: BroadcastDestination; text: string; selected_sticker_ids: string[]; sticker_mode: StickerMode; scheduled_at?: string } = {
    segment: input.segment,
    destination: normalizeDestination(input.destination),
    text: input.text,
    selected_sticker_ids: sticker_mode === "selected" ? input.selectedStickerIds : [],
    sticker_mode,
  };
  if (input.scheduledAt) body.scheduled_at = input.scheduledAt;
  return body;
}

export function buildCreateScheduleBody(input: {
  segment: string;
  destination?: BroadcastDestination;
  text: string;
  selectedStickerIds: string[];
  autoPick: boolean;
  timeLocal: string;
  daysOfWeek: number[];
}): {
  segment: string;
  destination: BroadcastDestination;
  text: string;
  selected_sticker_ids: string[];
  sticker_mode: StickerMode;
  time_local: string;
  days_of_week: number[];
} {
  const sticker_mode = resolveStickerMode(input.autoPick, input.selectedStickerIds);
  return {
    segment: input.segment,
    destination: normalizeDestination(input.destination),
    text: input.text,
    selected_sticker_ids: sticker_mode === "selected" ? input.selectedStickerIds : [],
    sticker_mode,
    time_local: input.timeLocal,
    days_of_week: input.daysOfWeek.length ? input.daysOfWeek : ALL_WEEKDAYS,
  };
}

export function stickerDraftFromRow(row: { sticker_ids?: unknown; sticker_mode?: unknown }): {
  selectedStickerIds: string[];
  autoPick: boolean;
} {
  const mode = String(row.sticker_mode || "none");
  const raw = row.sticker_ids;
  const ids = Array.isArray(raw) ? raw.map((item) => String(item).trim()).filter(Boolean).slice(0, BROADCAST_MAX_STICKERS) : [];
  if (mode === "auto") return { selectedStickerIds: [], autoPick: true };
  if (ids.length) return { selectedStickerIds: ids, autoPick: false };
  return { selectedStickerIds: [], autoPick: false };
}

export function buildPatchJobBody(input: {
  segment: string;
  destination?: BroadcastDestination;
  text: string;
  selectedStickerIds: string[];
  autoPick: boolean;
  scheduledAt?: string | null;
}): {
  segment: string;
  destination: BroadcastDestination;
  text: string;
  selected_sticker_ids: string[];
  sticker_mode: StickerMode;
  scheduled_at?: string | null;
} {
  const sticker_mode = resolveStickerMode(input.autoPick, input.selectedStickerIds);
  const body: {
    segment: string;
    destination: BroadcastDestination;
    text: string;
    selected_sticker_ids: string[];
    sticker_mode: StickerMode;
    scheduled_at?: string | null;
  } = {
    segment: input.segment,
    destination: normalizeDestination(input.destination),
    text: input.text,
    selected_sticker_ids: sticker_mode === "selected" ? input.selectedStickerIds : [],
    sticker_mode,
  };
  if (input.scheduledAt !== undefined) body.scheduled_at = input.scheduledAt;
  return body;
}

export function toggleWeekday(current: number[], day: number): number[] {
  const id = Number(day);
  if (id < 1 || id > 7) return current;
  if (current.includes(id)) {
    const next = current.filter((item) => item !== id);
    return next.length ? next : current;
  }
  return [...current, id].sort((a, b) => a - b);
}

export function moscowDateTimeLocalToIso(local: string): string {
  const trimmed = local.trim();
  if (!trimmed) return "";
  const withSeconds = trimmed.length === 16 ? `${trimmed}:00` : trimmed;
  return `${withSeconds}+03:00`;
}

export function isoToMoscowDateTimeLocal(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

export function defaultMoscowSlotLocal(minutesAhead = 60): string {
  return isoToMoscowDateTimeLocal(new Date(Date.now() + minutesAhead * 60_000).toISOString());
}

export function weekdayLabels(days: number[]): string {
  const set = new Set(days);
  return WEEKDAY_OPTIONS.filter((item) => set.has(item.id)).map((item) => item.label).join(" ") || "—";
}

export function applyAiDraft(
  draft: AiDraftResult,
  current: { text: string; selectedStickerIds: string[]; autoPick: boolean },
): { text: string; selectedStickerIds: string[]; autoPick: boolean } | null {
  const improved = (draft.improved_text || "").trim();
  if (!improved || draft.error) return null;
  const suggested = (draft.suggested_sticker_ids || []).map((id) => String(id).trim()).filter(Boolean).slice(0, BROADCAST_MAX_STICKERS);
  return {
    text: improved,
    selectedStickerIds: suggested.length ? suggested : current.selectedStickerIds,
    autoPick: suggested.length ? false : current.autoPick,
  };
}
