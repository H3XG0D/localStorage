/**
 * Frontend roulette model check: wheel order, colours and the landing angle.
 * Run: npx tsx scripts/check-roulette-model.mts
 *
 * The backend owns the drawn pocket; this only proves the client renders and
 * parks the wheel on the pocket the server sent.
 */
import assert from "node:assert/strict";
import {
  ROULETTE_BETS,
  ROULETTE_MAX_COVER,
  ROULETTE_POCKET_COUNT,
  ROULETTE_SECTOR_DEG,
  ROULETTE_STRAIGHT_RETURN,
  ROULETTE_WHEEL_ORDER,
  canonicalRouletteBetKey,
  DEFAULT_ROULETTE_BET,
  mergeRouletteHistory,
  rouletteHistoryWithoutRound,
  rouletteVisiblePocket,
  rouletteBetWins,
  rouletteOddsLabel,
  roulettePocketColor,
  rouletteRotationFor,
  rouletteSelectedPockets,
  rouletteUiPhase,
  rouletteWheelIndex,
  makeRouletteSpinPlan,
  readRouletteFastPlay,
  ROULETTE_FAST_PLAY_KEY,
  rouletteBetSpec,
  visibleCasinoWallet,
  writeRouletteFastPlay,
  rouletteTableRevealReady,
  rouletteTableAcceptsBets,
  rouletteTableShouldSpinFromSnapshot,
  ROULETTE_FELT_ORDER,
  toggleRoulettePocket,
  ROULETTE_TABLE_CHIPS,
  ROULETTE_TABLE_DRAFT_MAX,
  ROULETTE_LAST_TABLE_BETS_KEY,
  rouletteStraightKey,
  pushRouletteDraftChip,
  undoRouletteDraftChip,
  clearRouletteDraftSpot,
  mergeRouletteDraftBySpot,
  rouletteDraftConfirmPayload,
  rouletteDraftTotal,
  rouletteUndoLastPlace,
  rouletteTableSpotMax,
  casinoViewerId,
  lastTableBetsToDraft,
  readRouletteLastTableBets,
  writeRouletteLastTableBets,
} from "../src/casino/roulette.ts";

const CANON_RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36];
const CANON_BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35];
const CANON_ORDER = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
  24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];

assert.equal(ROULETTE_POCKET_COUNT, 37);
assert.deepEqual([...ROULETTE_WHEEL_ORDER], CANON_ORDER, "wheel order must be the physical single-zero order");
assert.equal(new Set(ROULETTE_WHEEL_ORDER).size, 37, "every pocket appears once");

assert.equal(roulettePocketColor(0), "green");
for (const pocket of CANON_RED) assert.equal(roulettePocketColor(pocket), "red", `pocket ${pocket} must be red`);
for (const pocket of CANON_BLACK) assert.equal(roulettePocketColor(pocket), "black", `pocket ${pocket} must be black`);
assert.equal(
  ROULETTE_WHEEL_ORDER.filter((pocket) => roulettePocketColor(pocket) === "green").length,
  1,
  "single zero only",
);

assert.equal(ROULETTE_BETS.red.payoutMultiplier, 2);
assert.equal(ROULETTE_BETS.black.payoutMultiplier, 2);
assert.equal(ROULETTE_BETS.zero.payoutMultiplier, 36);
assert.equal(ROULETTE_BETS.even.payoutMultiplier, 2);
assert.equal(ROULETTE_BETS.dozen1.payoutMultiplier, 3);
assert.equal(ROULETTE_BETS.col1.payoutMultiplier, 3);
assert.equal(ROULETTE_BETS.red.profitRatio, 1);
assert.equal(ROULETTE_BETS.zero.profitRatio, 35);
assert.equal(rouletteBetSpec("1rd").key, "dozen1");
assert.equal(rouletteBetSpec("чёт").key, "even");
assert.equal(rouletteBetSpec("1-12").key, "dozen1");
assert.equal(rouletteBetSpec("1,2,3,4,5,6,7,8,9,10,11,12").key, "dozen1");

for (let pocket = 0; pocket < 37; pocket += 1) {
  const color = roulettePocketColor(pocket);
  assert.equal(rouletteBetWins("red", pocket), color === "red");
  assert.equal(rouletteBetWins("black", pocket), color === "black");
  assert.equal(rouletteBetWins("zero", pocket), pocket === 0);
}
assert.equal(rouletteBetWins("zero", 0), true);
for (let pocket = 1; pocket < 37; pocket += 1) {
  const spec = rouletteBetSpec(String(pocket));
  assert.equal(spec.payoutMultiplier, 36, `straight ${pocket} pays ×36`);
  assert.equal(spec.profitRatio, 35);
  assert.equal(rouletteBetWins(String(pocket), pocket), true);
  assert.equal(rouletteBetWins(String(pocket), (pocket + 1) % 37), false);
}
assert.equal(rouletteBetSpec("0").key, "zero");

const ten = rouletteBetSpec("1,2,3,4,5,6,7,8,9,10");
assert.equal(ten.key, "1,2,3,4,5,6,7,8,9,10");
assert.equal(ten.payoutMultiplier, 3.6);
assert.equal(ten.payoutMultiplier, ROULETTE_STRAIGHT_RETURN / 10);
assert.equal(ten.profitRatio, 2.6);
assert.equal(ten.odds, "2.6:1");
assert.equal(rouletteOddsLabel(10), "2.6:1");
assert.equal(rouletteOddsLabel(1), "35:1");
assert.equal(rouletteOddsLabel(2), "17:1");
assert.equal(rouletteBetWins("1,2,3,4,5,6,7,8,9,10", 7), true);
assert.equal(rouletteBetWins("1,2,3,4,5,6,7,8,9,10", 36), false);
assert.equal(rouletteBetSpec("10, 1,1, 2").key, "1,2,10");
assert.equal(rouletteBetSpec("10, 1,1, 2").payoutMultiplier, 12);
assert.equal(canonicalRouletteBetKey([10, 1, 2]), "1,2,10");
assert.equal(rouletteBetSpec("0,1").key, "0,1");
assert.equal(rouletteBetSpec("0,1").payoutMultiplier, 18);
assert.equal(ROULETTE_MAX_COVER, 36);

assert.equal(toggleRoulettePocket("red", 17), "17");
assert.equal(toggleRoulettePocket("17", 18), "17,18");
assert.equal(toggleRoulettePocket("17,18", 18), "17");
assert.equal(toggleRoulettePocket("17", 17), "17");
assert.equal(toggleRoulettePocket("zero", 1), "0,1");
assert.equal(rouletteStraightKey(0), "zero");
assert.equal(rouletteStraightKey(22), "22");
assert.deepEqual([...ROULETTE_TABLE_CHIPS], [10, 25, 50, 100, 500, 1000]);
assert.ok(ROULETTE_TABLE_CHIPS.includes(25), "table chips include 25");
assert.ok(ROULETTE_TABLE_CHIPS.includes(50), "table chips include 50");
assert.deepEqual(rouletteSelectedPockets("1,7,17"), [1, 7, 17]);
assert.deepEqual(rouletteSelectedPockets("red"), []);
assert.deepEqual(rouletteSelectedPockets("zero"), [0]);
assert.equal(DEFAULT_ROULETTE_BET, "red");
assert.equal(makeRouletteSpinPlan(true).durationMs, 0);
assert.equal(makeRouletteSpinPlan(true).turns, 0);

const fastStore: Record<string, string> = {};
const fastStorage = {
  getItem: (key: string) => fastStore[key] ?? null,
  setItem: (key: string, value: string) => {
    fastStore[key] = value;
  },
};
assert.equal(readRouletteFastPlay(fastStorage), false);
writeRouletteFastPlay(true, fastStorage);
assert.equal(fastStore[ROULETTE_FAST_PLAY_KEY], "1");
assert.equal(readRouletteFastPlay(fastStorage), true);
writeRouletteFastPlay(false, fastStorage);
assert.equal(readRouletteFastPlay(fastStorage), false);
assert.equal(readRouletteFastPlay(null), false);

// Landing angle: the winning sector must sit under the 12 o'clock pointer, and
// the wheel must always keep turning forward across a run of spins.
let rotation = 0;
for (const pocket of ROULETTE_WHEEL_ORDER) {
  const next = rouletteRotationFor(pocket, rotation, 3);
  assert.ok(next >= rotation + 3 * 360, `spin must move forward at least 3 turns for pocket ${pocket}`);
  const under = (rouletteWheelIndex(pocket) * ROULETTE_SECTOR_DEG + next) % 360;
  const offset = Math.min(under, 360 - under);
  assert.ok(offset < 1e-6, `pocket ${pocket} lands ${offset.toFixed(6)}° off the pointer`);
  rotation = next;
}

const history = mergeRouletteHistory(
  [{ id: "b", pocket: 0, color: "green" }],
  [{ id: "a", pocket: 23, color: "red" }],
);
assert.deepEqual(history.map((row) => row.id), ["a", "b"], "newest first");
assert.equal(mergeRouletteHistory(history, [{ id: "a", pocket: 23, color: "red" }]).length, 2, "dedupe by round id");
assert.equal(
  mergeRouletteHistory(
    [],
    Array.from({ length: 40 }, (_, i) => ({ id: `x${i}`, pocket: i % 37, color: roulettePocketColor(i % 37) })),
  ).length,
  10,
  "history is capped",
);

assert.deepEqual(
  [...ROULETTE_FELT_ORDER].sort((a, b) => a - b),
  Array.from({ length: 37 }, (_, i) => i),
  "felt shows every pocket once",
);
assert.equal(ROULETTE_FELT_ORDER[0], 0);
assert.deepEqual([...ROULETTE_FELT_ORDER.slice(1, 4)], [3, 2, 1]);

assert.equal(
  rouletteUiPhase({ spinning: true, stake: 10, wallet: 100, result: { won: true }, authed: true }),
  "spinning",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 0, wallet: 100, result: null, authed: true }),
  "invalid",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 50, wallet: 10, result: null, authed: true }),
  "insufficient",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 10, wallet: 100, boundError: "over", result: null, authed: true }),
  "invalid",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 10, wallet: 100, result: { won: true }, authed: true }),
  "win",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 10, wallet: 100, result: { won: false }, authed: true }),
  "loss",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 10, wallet: 100, result: null, authed: true }),
  "ready",
);
assert.equal(
  rouletteUiPhase({ spinning: false, stake: 10, wallet: 100, result: null, authed: false }),
  "idle",
);

assert.equal(visibleCasinoWallet(800, 1000, true), 1000, "spin must not show the settled live wallet");
assert.equal(visibleCasinoWallet(800, 1000, false), 800, "after the wheel parks, show live");
assert.equal(visibleCasinoWallet(800, null, true), 800, "no snapshot yet — fall back to live");
assert.equal(visibleCasinoWallet(null, 1000, true), 1000);

assert.equal(rouletteTableRevealReady(true, false), false, "settled SSE must not stop a table spin before the wheel parks");
assert.equal(rouletteTableRevealReady(true, true), true, "after park, table may reveal");
assert.equal(rouletteTableRevealReady(false, false), true, "house 1×1 does not wait on the table gate");
assert.equal(rouletteTableAcceptsBets("open"), true);
assert.equal(rouletteTableAcceptsBets("settled"), true, "last spin must not lock the next collecting round");
assert.equal(rouletteTableAcceptsBets("spinning"), false);
assert.equal(rouletteTableAcceptsBets("locked"), false);
assert.equal(rouletteTableAcceptsBets(null), true);
assert.equal(
  rouletteTableShouldSpinFromSnapshot({ round_id: "rt-1", status: "settled", pocket: 17 }, null),
  true,
  "poll of a just-settled round must still spin",
);
assert.equal(
  rouletteTableShouldSpinFromSnapshot({ round_id: "rt-1", status: "settled", pocket: 17 }, "rt-1"),
  false,
  "do not replay a round the wheel already spun",
);
assert.equal(
  rouletteTableShouldSpinFromSnapshot({ round_id: "rt-2", status: "open", pocket: null }, null),
  false,
  "open betting window does not spin",
);

assert.equal(rouletteVisiblePocket(true, 17), null, "hub must not show the known pocket while the wheel is turning");
assert.equal(rouletteVisiblePocket(false, 17), 17, "after park the hub shows the pocket");
assert.equal(rouletteVisiblePocket(false, null), null);
assert.deepEqual(
  rouletteHistoryWithoutRound(
    [
      { id: "rt-live", pocket: 17, color: "black" },
      { id: "rt-old", pocket: 0, color: "green" },
    ],
    "rt-live",
  ).map((row) => row.id),
  ["rt-old"],
  "tape must drop the in-flight round until reveal",
);
assert.deepEqual(rouletteHistoryWithoutRound([{ id: "rt-old", pocket: 0, color: "green" }], null).map((row) => row.id), [
  "rt-old",
]);

const stacked = pushRouletteDraftChip(pushRouletteDraftChip([], "red", 50), "22", 25);
assert.equal(rouletteDraftTotal(stacked), 75);
assert.deepEqual(undoRouletteDraftChip(stacked).map((chip) => chip.bet), ["red"]);
assert.deepEqual(clearRouletteDraftSpot(stacked, "red").map((chip) => chip.bet), ["22"]);
assert.deepEqual(
  mergeRouletteDraftBySpot(pushRouletteDraftChip(stacked, "red", 50)).map((chip) => [chip.bet, chip.amount]),
  [["red", 100], ["22", 25]],
);
assert.deepEqual(rouletteDraftConfirmPayload(stacked), [
  { bet: "red", amount_rub: 50 },
  { bet: "22", amount_rub: 25 },
]);
assert.equal(pushRouletteDraftChip([], "red", 0).length, 0);
assert.equal(ROULETTE_TABLE_DRAFT_MAX, 80);

const stackedSpot = pushRouletteDraftChip(pushRouletteDraftChip([], "36", 50), "36", 50);
const undoStack = rouletteUndoLastPlace(stackedSpot);
assert.ok(undoStack);
assert.equal(undoStack.bet, "36");
assert.equal(undoStack.removed, 50);
assert.equal(undoStack.remainder, 50);
const undoSpotGone = rouletteUndoLastPlace(undoStack.next);
assert.ok(undoSpotGone);
assert.equal(undoSpotGone.remainder, 0);
assert.equal(undoSpotGone.removed, 50);
assert.equal(rouletteUndoLastPlace([]), null);
const undoOther = rouletteUndoLastPlace(stacked);
assert.ok(undoOther);
assert.equal(undoOther.bet, "22");
assert.equal(undoOther.remainder, 0);
assert.deepEqual(undoOther.next.map((chip) => chip.bet), ["red"]);
assert.deepEqual(
  lastTableBetsToDraft([
    { bet: "red", stake_rub: 50 },
    { bet: "nope", stake_rub: 10 },
    { bet: "17", stake_rub: 0 },
  ]).map((chip) => chip.bet),
  ["red"],
);
assert.equal(casinoViewerId({ id: 4, telegram_user_id: 881122 }, []), 881122);
assert.equal(casinoViewerId({ id: 4, telegram_id: 881122 }, []), 881122);
assert.equal(casinoViewerId({ id: 9 }, [{ user_id: -44001 }]), -44001);
assert.equal(casinoViewerId({ id: 9, telegram_user_id: null }, []), null);
assert.notEqual(casinoViewerId({ id: 9 }, []), 9);

const lastStore: Record<string, string> = {};
const lastStorage = {
  getItem: (key: string) => lastStore[key] ?? null,
  setItem: (key: string, value: string) => {
    lastStore[key] = value;
  },
};
assert.deepEqual(readRouletteLastTableBets(lastStorage), []);
writeRouletteLastTableBets([{ bet: "black", amount: 100 }], lastStorage);
assert.equal(lastStore[ROULETTE_LAST_TABLE_BETS_KEY]?.includes("black"), true);
assert.deepEqual(readRouletteLastTableBets(lastStorage), [{ bet: "black", amount: 100 }]);

assert.equal(rouletteTableSpotMax("red", 500, 27.78), 500);
assert.equal(rouletteTableSpotMax("black", 500, 27.78), 500);
assert.equal(rouletteTableSpotMax("zero", 500, 27.78), 27.78);
assert.equal(rouletteTableSpotMax("15", 500, 27.78), 27.78);
assert.equal(rouletteTableSpotMax("17", 1000, 28.57), 28.57);

console.log("roulette model ok: 37 pockets, canonical colours, exact landing angle, ui phases");
