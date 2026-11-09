import { moscowYmd, parseOrderInstant } from "@/panel/lib/analyticsPeriod";

export const REVIEW_TODAY_LABEL = "Клиент уже оставлял отзыв сегодня";

/** True when the review timestamp falls on the current Europe/Moscow calendar day. */
export function isReviewFromCalendarToday(createdAt: unknown, now: Date = new Date()): boolean {
  if (createdAt == null) return false;
  const instant = parseOrderInstant(String(createdAt));
  if (!instant) return false;
  return moscowYmd(instant) === moscowYmd(now);
}
