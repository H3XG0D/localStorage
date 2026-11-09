/**
 * Round-robin weighted reel (jackpot / FocusLucky).
 * Run: npx tsx scripts/check-weighted-reel.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  WEIGHTED_REEL_SLOT_COUNT,
  WEIGHTED_REEL_SPIN_MS,
  WEIGHTED_REEL_WINNER_INDEX,
  buildWeightedReel,
} from "../src/casino/weightedReel.ts";

const a = { user_id: 1, amount_rub: 80 };
const b = { user_id: 2, amount_rub: 20 };
const weight = (row: { amount_rub: number }) => row.amount_rub;

const two = buildWeightedReel([a, b], weight, 2);
assert.equal(two.length, WEIGHTED_REEL_SLOT_COUNT);
assert.equal(two[WEIGHTED_REEL_WINNER_INDEX].user_id, 2);
const counts = { 1: 0, 2: 0 };
for (const slot of two) counts[slot.user_id as 1 | 2] += 1;
assert.equal(counts[1] + counts[2], WEIGHTED_REEL_SLOT_COUNT);
assert.ok(counts[1] >= 79 && counts[1] <= 80);
assert.ok(counts[2] >= 20 && counts[2] <= 21);
for (let i = 0; i < 40; i += 1) {
  if (i === WEIGHTED_REEL_WINNER_INDEX) continue;
  assert.equal(two[i].user_id, i % 2 === 0 ? 1 : 2, `slot ${i} should alternate`);
}

const solo = buildWeightedReel([a], weight, 1);
assert.equal(solo.length, WEIGHTED_REEL_SLOT_COUNT);
assert.ok(solo.every((row) => row.user_id === 1));
assert.equal(solo[WEIGHTED_REEL_WINNER_INDEX].user_id, 1);

const tickets = buildWeightedReel(
  [
    { user_id: 10, tickets: 1 },
    { user_id: 11, tickets: 1 },
    { user_id: 12, tickets: 1 },
  ],
  (row) => row.tickets,
  11,
);
assert.equal(tickets[WEIGHTED_REEL_WINNER_INDEX].user_id, 11);
assert.equal(tickets.filter((row) => row.user_id === 10).length + tickets.filter((row) => row.user_id === 11).length + tickets.filter((row) => row.user_id === 12).length, WEIGHTED_REEL_SLOT_COUNT);
assert.ok(tickets.filter((row) => row.user_id === 10).length >= 32);
assert.ok(tickets.filter((row) => row.user_id === 11).length >= 32);
assert.ok(tickets.filter((row) => row.user_id === 12).length >= 32);
assert.equal(tickets[0].user_id, 10);
assert.equal(tickets[1].user_id, 11);
assert.equal(tickets[2].user_id, 12);
assert.equal(tickets[3].user_id, 10);

assert.deepEqual(buildWeightedReel([], weight, null), []);
assert.equal(WEIGHTED_REEL_WINNER_INDEX, 80);
assert.equal(WEIGHTED_REEL_SPIN_MS, 10500);

const raffle = readFileSync(new URL("../src/casino/CasinoRaffle.tsx", import.meta.url), "utf8");
assert.match(raffle, /const SPIN_MS = WEIGHTED_REEL_SPIN_MS;/);
assert.match(raffle, /data\?\.draw_at/);
assert.match(raffle, /casino-raffle-chance/);
assert.doesNotMatch(raffle, /is-drama/);

console.log("check-weighted-reel: ok");
