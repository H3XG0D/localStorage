#!/usr/bin/env node
/**
 * Frontend smoke for /ops/reviews "already reviewed today" label (no vitest).
 * Run: node scripts/smoke-ops-reviews-today.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const helper = readFileSync(join(root, "src/panel/lib/reviewToday.ts"), "utf8");
const period = readFileSync(join(root, "src/panel/lib/analyticsPeriod.ts"), "utf8");
const page = readFileSync(join(root, "src/panel/ui/ReviewsPanel.tsx"), "utf8");

assert.match(helper, /REVIEW_TODAY_LABEL = "Клиент уже оставлял отзыв сегодня"/);
assert.match(helper, /isReviewFromCalendarToday/);
assert.match(helper, /moscowYmd/);
assert.match(helper, /parseOrderInstant/);
assert.doesNotMatch(helper, /toLocaleDateString/);
assert.doesNotMatch(helper, /can_claim_bonus_today/);
assert.doesNotMatch(helper, /LIVE RATES|\/exchange/);

assert.match(period, /ANALYTICS_TZ = "Europe\/Moscow"/);
assert.match(period, /timeZone: ANALYTICS_TZ/);

assert.match(page, /isReviewFromCalendarToday/);
assert.match(page, /REVIEW_TODAY_LABEL/);
assert.match(page, /@\/panel\/lib\/reviewToday/);
assert.doesNotMatch(page, /toLocaleDateString/);
assert.match(page, /bonus: "none"/);
assert.match(page, /bonus: "text"/);
assert.match(page, /bonus: "photo"/);
assert.match(page, /"reject"/);
assert.match(page, /Опубликовать/);
assert.match(page, /Отклонить/);

const TZ = "Europe/Moscow";

function hasExplicitOffset(iso) {
  return /[zZ]|[+-]\d{2}:?\d{2}$/.test(String(iso).trim());
}

function parseOrderInstant(iso) {
  const raw = String(iso || "").trim();
  if (!raw) return null;
  const normalized = (raw.includes("T") ? raw : raw.replace(" ", "T")).replace(/(\.\d{3})\d+/, "$1");
  const parsed = hasExplicitOffset(normalized) ? new Date(normalized) : new Date(`${normalized}Z`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function moscowYmd(date) {
  const map = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(date)
      .map((p) => [p.type, p.value]),
  );
  return `${map.year}-${map.month}-${map.day}`;
}

function isReviewFromCalendarToday(createdAt, now = new Date()) {
  if (createdAt == null) return false;
  const instant = parseOrderInstant(String(createdAt));
  if (!instant) return false;
  return moscowYmd(instant) === moscowYmd(now);
}

const now = new Date("2026-08-22T00:30:00+03:00");
assert.equal(moscowYmd(now), "2026-08-22");
assert.equal(isReviewFromCalendarToday("2026-08-22T00:10:00+03:00", now), true);
assert.equal(isReviewFromCalendarToday("2026-08-21T23:50:00+03:00", now), false);
assert.equal(isReviewFromCalendarToday("2026-08-21T20:50:00Z", now), false);
assert.equal(isReviewFromCalendarToday("2026-08-21T21:50:00Z", now), true);
assert.equal(isReviewFromCalendarToday("2026-08-21T21:30:00Z", now), true);
assert.equal(isReviewFromCalendarToday("2026-08-22T00:00:00Z", now), true);
assert.equal(isReviewFromCalendarToday("2026-08-21T20:59:00Z", now), false);
assert.equal(isReviewFromCalendarToday("", now), false);
assert.equal(isReviewFromCalendarToday(null, now), false);
assert.equal(isReviewFromCalendarToday(undefined, now), false);
assert.equal(isReviewFromCalendarToday("not-a-date", now), false);

console.log("smoke-ops-reviews-today: ok");
