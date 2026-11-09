/**
 * V2 baccarat streets: first card around, then second, then thirds.
 * Run: npx tsx scripts/check-baccarat-streets.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BACCARA_CARD_MS,
  BACCARA_RESULT_BEAT_MS,
  BACCARA_STREET_GAP_MS,
  baccaratElapsedMs,
  baccaratHandScore,
  baccaratHandsFromSeats,
  baccaratRevealedAfter,
  baccaratRoundKey,
  baccaratShownCount,
  baccaratStreetAttr,
  baccaratStreetRevealMs,
  baccaratStreetSteps,
  baccaratStreetWaitMs,
  baccaratVisibleCards,
  blackjackHandScore,
  blackjackHolesOpen,
  blackjackRoundKey,
  blackjackStreetHands,
  blackjackVisibleCards,
  faceCardCodes,
} from "../src/casino/baccaratStreets.ts";
import { mergeV2LobbyTables } from "../src/casino/v2LobbyMerge.ts";

assert.equal(BACCARA_CARD_MS, 420);
assert.equal(BACCARA_STREET_GAP_MS, 650);
assert.equal(BACCARA_RESULT_BEAT_MS, 450);

assert.equal(blackjackHolesOpen("running", "scoring"), false);
assert.equal(blackjackHolesOpen("running", "hitting"), false);
assert.equal(blackjackHolesOpen("running", "draw_choice"), true);
assert.equal(blackjackHolesOpen("finished", "hitting"), true);

assert.equal(baccaratHandScore(["2♠", "7♥"]), 9);
assert.equal(baccaratHandScore(["10♥", "5♣"]), 5);
assert.equal(baccaratHandScore(["10♥", "5♣", "8♦"]), 3);
assert.equal(baccaratHandScore(["A♠"]), 1);
assert.equal(baccaratHandScore(["K♦", "Q♣"]), 0);

const screenshotHands = baccaratHandsFromSeats([
  { seat_no: 1, cards: ["2♠", "7♥"] },
  { seat_no: 2, cards: ["10♥", "5♣", "8♦"] },
  { seat_no: 3, cards: [] },
]);
assert.deepEqual(screenshotHands, {
  1: ["2♠", "7♥"],
  2: ["10♥", "5♣", "8♦"],
});
assert.deepEqual(
  baccaratHandsFromSeats([{ seat_no: 1, cards: ["back", "back"] }]),
  {},
  "baccarat still drops hole backs",
);
assert.deepEqual(
  baccaratHandsFromSeats([{ seat_no: 1, cards: ["back", "back"] }, { seat_no: 2, cards: ["K♠", "9♦"] }], {
    keepBacks: true,
  }),
  { 1: ["back", "back"], 2: ["K♠", "9♦"] },
  "blackjack streets keep two backs so the table shows two hole cards",
);

const screenshotSteps = baccaratStreetSteps(screenshotHands);
assert.deepEqual(
  screenshotSteps,
  [
    { seat: 1, index: 0 },
    { seat: 2, index: 0 },
    { seat: 1, index: 1 },
    { seat: 2, index: 1 },
    { seat: 2, index: 2 },
  ],
  "firsts around the table, then seconds, then only seat 2 third",
);

assert.equal(baccaratStreetWaitMs(screenshotSteps, 0), BACCARA_CARD_MS);
assert.equal(baccaratStreetWaitMs(screenshotSteps, 1), BACCARA_CARD_MS);
assert.equal(baccaratStreetWaitMs(screenshotSteps, 2), BACCARA_STREET_GAP_MS, "gap before street 2");
assert.equal(baccaratStreetWaitMs(screenshotSteps, 3), BACCARA_CARD_MS);
assert.equal(baccaratStreetWaitMs(screenshotSteps, 4), BACCARA_STREET_GAP_MS, "gap before third");

const screenshotMs = baccaratStreetRevealMs({ steps: screenshotSteps });
assert.equal(screenshotMs, 3 * BACCARA_CARD_MS + 2 * BACCARA_STREET_GAP_MS + BACCARA_RESULT_BEAT_MS);
assert.equal(screenshotMs, 3010);
assert.ok(screenshotMs > 1000, "must be slower than dumping the whole hand");

assert.equal(baccaratStreetRevealMs({ steps: screenshotSteps, skipMotion: true }), 0);
assert.equal(
  baccaratStreetRevealMs({ steps: screenshotSteps, includeOutcomeBeat: false }),
  3 * BACCARA_CARD_MS + 2 * BACCARA_STREET_GAP_MS,
);

const threeSeat = baccaratStreetSteps({
  1: ["A♣", "8♦"],
  2: ["A♠", "8♥"],
  3: ["8♣", "8♥", "9♥"],
});
assert.deepEqual(
  threeSeat.map((step) => `${step.seat}:${step.index}`),
  ["1:0", "2:0", "3:0", "1:1", "2:1", "3:1", "3:2"],
);
assert.equal(
  baccaratStreetRevealMs({ steps: threeSeat }),
  5 * BACCARA_CARD_MS + 2 * BACCARA_STREET_GAP_MS + BACCARA_RESULT_BEAT_MS,
);
assert.equal(baccaratStreetRevealMs({ steps: threeSeat }), 3850);

assert.equal(baccaratShownCount(screenshotSteps, 2, 1), 1);
assert.equal(baccaratShownCount(screenshotSteps, 2, 2), 1);
assert.deepEqual(baccaratVisibleCards(["10♥", "5♣", "8♦"], 2), ["10♥", "5♣"]);
assert.equal(baccaratHandScore(baccaratVisibleCards(["10♥", "5♣", "8♦"], 2)), 5);
assert.equal(baccaratHandScore(baccaratVisibleCards(["10♥", "5♣", "8♦"], 3)), 3);

assert.equal(baccaratStreetAttr(screenshotSteps, 0, false), "1");
assert.equal(baccaratStreetAttr(screenshotSteps, 2, false), "1");
assert.equal(baccaratStreetAttr(screenshotSteps, 4, false), "2");
assert.equal(baccaratStreetAttr(screenshotSteps, 5, false), "3");
assert.equal(baccaratStreetAttr(screenshotSteps, 5, true), "outcome");
assert.equal(baccaratStreetAttr([], 0, false), "");

const keyA = baccaratRoundKey("web-1", "aaa", screenshotHands);
const keyB = baccaratRoundKey("web-1", "aaa", { ...screenshotHands, 2: ["10♥", "5♣", "9♦"] });
assert.notEqual(keyA, keyB, "redeal must change the round key");
assert.equal(
  baccaratRoundKey("web-1", "aaa", screenshotHands),
  baccaratRoundKey("web-1", "aaa", screenshotHands),
  "same hands and commit stay the same key",
);
assert.notEqual(
  baccaratRoundKey("web-1", "aaa", screenshotHands, "t1"),
  baccaratRoundKey("web-1", "aaa", screenshotHands, "t2"),
  "new deal timestamp must restart streets",
);
assert.equal(keyA.includes("seed"), false, "seed must not live in the round key");

const bjHands = {
  1: ["K♠", "9♦"],
  2: ["A♠", "8♥"],
  3: ["2♣", "4♦"],
};
const bjStreetHands = blackjackStreetHands(bjHands);
assert.deepEqual(Object.values(bjStreetHands).map((cards) => cards.length), [2, 2, 2]);
const bjSteps = baccaratStreetSteps(bjStreetHands);
assert.deepEqual(
  bjSteps.map((step) => `${step.seat}:${step.index}`),
  ["1:0", "2:0", "3:0", "1:1", "2:1", "3:1"],
  "blackjack uses two streets around the table, no thirds",
);
assert.equal(baccaratStreetRevealMs({ steps: bjSteps, includeOutcomeBeat: false }), 5 * BACCARA_CARD_MS + BACCARA_STREET_GAP_MS);
assert.equal(baccaratStreetRevealMs({ steps: bjSteps, includeOutcomeBeat: false }), 2750);
assert.deepEqual(blackjackVisibleCards(["back", "back", "5♣"], 2, false), ["back", "back"]);
assert.deepEqual(blackjackVisibleCards(["back", "back", "5♣"], 2, true), ["back", "back", "5♣"]);
assert.deepEqual(faceCardCodes(["back", "back", "5♣"]), ["5♣"]);
assert.equal(blackjackHandScore(faceCardCodes(["back", "back"])), 0);
assert.equal(blackjackHandScore(["A♠", "K♥"]), 21);
const bjKeyA = blackjackRoundKey("web-bj", "aaa", bjHands);
const bjKeyB = blackjackRoundKey("web-bj", "aaa", { ...bjHands, 2: ["A♠", "8♥", "5♣"] });
assert.equal(bjKeyA, bjKeyB, "third card after street must not reset blackjack round key");

assert.equal(baccaratElapsedMs(undefined, 1000), 0);
assert.equal(baccaratElapsedMs("not-a-date", 1000), 0);
assert.equal(baccaratElapsedMs("2026-08-31T12:00:00.000Z", Date.parse("2026-08-31T12:00:00.500Z")), 500);

const catchStart = baccaratRevealedAfter(screenshotSteps, 0);
assert.equal(catchStart.revealed, 0);
assert.equal(catchStart.resultReady, false);
assert.equal(catchStart.nextWaitMs, BACCARA_CARD_MS);

const afterFirst = baccaratRevealedAfter(screenshotSteps, BACCARA_CARD_MS);
assert.equal(afterFirst.revealed, 1);
assert.equal(afterFirst.resultReady, false);

const streetMs = baccaratStreetRevealMs({ steps: screenshotSteps, includeOutcomeBeat: false });
const afterCards = baccaratRevealedAfter(screenshotSteps, streetMs);
assert.equal(afterCards.revealed, screenshotSteps.length);
assert.equal(afterCards.resultReady, false);
assert.equal(afterCards.nextWaitMs, BACCARA_RESULT_BEAT_MS);

const afterBeat = baccaratRevealedAfter(screenshotSteps, streetMs + BACCARA_RESULT_BEAT_MS);
assert.equal(afterBeat.revealed, screenshotSteps.length);
assert.equal(afterBeat.resultReady, true);
assert.equal(afterBeat.nextWaitMs, 0);

const midFirst = baccaratRevealedAfter(screenshotSteps, 200);
assert.equal(midFirst.revealed, 0);
assert.equal(midFirst.nextWaitMs, BACCARA_CARD_MS - 200);

const seatedFinished = {
  table_id: "web-keep",
  is_seated: true,
  status: "finished" as const,
  game_state: { phase: "scoring" },
  roster: [{ cards: ["2♠", "7♥"] }],
};
const otherOpen = {
  table_id: "web-open",
  is_seated: false,
  status: "open" as const,
  game_state: {},
  roster: [],
};
const mergedKeep = mergeV2LobbyTables([otherOpen], [seatedFinished, otherOpen]);
assert.equal(mergedKeep[0].table_id, "web-keep", "keep seated finished table missing from list");
assert.equal(mergedKeep.some((row) => row.table_id === "web-open"), true);

const strangerFinished = {
  table_id: "web-other",
  is_seated: false,
  status: "finished" as const,
  game_state: {},
  roster: [{ cards: ["A♠"] }],
};
const droppedStranger = mergeV2LobbyTables([otherOpen], [strangerFinished]);
assert.equal(
  droppedStranger.some((row) => row.table_id === "web-other"),
  false,
  "do not keep others' finished tables",
);

const otherGame = mergeV2LobbyTables(
  [{ ...otherOpen, game_type: "blackjack" }],
  [{ ...seatedFinished, game_type: "baccara" }],
  "blackjack",
);
assert.equal(
  otherGame.some((row) => row.table_id === "web-keep"),
  false,
  "do not keep a seated table from another game",
);

const seatedWithCards = {
  table_id: "web-race",
  is_seated: true,
  status: "running" as const,
  game_state: { phase: "scoring" },
  roster: [{ cards: ["2♠", "7♥"] }],
};
const staleEmpty = {
  table_id: "web-race",
  is_seated: true,
  status: "running" as const,
  game_state: { phase: "scoring" },
  roster: [{ cards: [] }],
};
const preferCards = mergeV2LobbyTables([staleEmpty], [seatedWithCards]);
assert.deepEqual(preferCards[0].roster[0].cards, ["2♠", "7♥"], "stale list must not wipe seated hands");

const table = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/casino/CasinoV2Table.tsx"), "utf8");
assert.match(table, /from "\.\/useBaccaratStreets"/);
assert.match(table, /data-casino-baccara-street/);
assert.match(table, /useBaccaratStreets/);
assert.doesNotMatch(
  table,
  /isBlackjack && baccara/,
  "blackjack must not share the street timer",
);
assert.match(table, /hitCasinoV2Table/);
assert.match(table, /standCasinoV2Table/);
assert.match(table, /data-casino-v2-hit-actions/);

const compact = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/casino/CasinoV2CompactPlay.tsx"),
  "utf8",
);
assert.match(compact, /from "\.\/useBaccaratStreets"/);
assert.match(compact, /data-casino-baccara-street/);
assert.match(compact, /visibleForSeat/);
assert.match(compact, /blackjackHandScore/);

const hook = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/casino/useBaccaratStreets.ts"), "utf8");
assert.match(hook, /baccaratStreetSteps/);
assert.match(hook, /baccaraResultReady|resultReady/);
assert.match(hook, /baccaratRevealedAfter/);
assert.match(hook, /cards_dealt_at/);
assert.match(hook, /blackjackRoundKey/);
assert.match(hook, /blackjackVisibleCards/);
assert.match(hook, /keepBacks/);
assert.doesNotMatch(hook, /game_state\.seed/);

const lobby = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/casino/CasinoPlayersLobby.tsx"),
  "utf8",
);
assert.match(lobby, /mergeV2LobbyTables/);
assert.match(lobby, /hitCasinoV2Table/);
assert.match(lobby, /standCasinoV2Table/);
assert.doesNotMatch(lobby, /setTables\(payload\.tables \|\| \[\]\)/);
assert.doesNotMatch(lobby, /Руки до 17/);
assert.doesNotMatch(lobby, /улицами/);
assert.match(lobby, /Чужие карты закрыты до итога/);

console.log("check-baccarat-streets: ok");
