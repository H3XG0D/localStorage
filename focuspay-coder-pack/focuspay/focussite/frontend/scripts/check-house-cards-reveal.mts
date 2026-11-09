/**
 * House baccarat/blackjack reveal: cards first, outcome after.
 * Run: npx tsx scripts/check-house-cards-reveal.mts
 */
import assert from "node:assert/strict";
import {
  HOUSE_CARD_DEAL_MS,
  HOUSE_CARD_RESULT_BEAT_MS,
  cardsFromPlayResult,
  houseCardsRevealMs,
} from "../src/casino/houseCards.ts";

assert.equal(HOUSE_CARD_DEAL_MS, 280);
assert.equal(HOUSE_CARD_RESULT_BEAT_MS, 450);

assert.deepEqual(
  cardsFromPlayResult({ player_cards: ["Q♦", "K♣", "J♠"], house_cards: ["6♦", "K♣"] }, "player"),
  ["Q♦", "K♣", "J♠"],
);
assert.deepEqual(
  cardsFromPlayResult({ rng: { house_cards: ["A♠", "9♥"] } }, "house"),
  ["A♠", "9♥"],
);
assert.deepEqual(cardsFromPlayResult(null, "player"), []);

const baccaraLoss = houseCardsRevealMs({ playerCount: 3, houseCount: 2 });
assert.equal(baccaraLoss, 3 * 280 + 2 * 280 + 450, "toast/banner only after 5 cards + beat");
assert.ok(baccaraLoss > 1000, "must be slower than the old dice 1s rolling wait");

assert.equal(houseCardsRevealMs({ playerCount: 2, houseCount: 2, liveHouse: true }), 2 * 280);
assert.equal(
  houseCardsRevealMs({ playerCount: 3, houseCount: 2, skipMotion: true }),
  0,
  "reduced motion still skips delay math",
);
assert.equal(
  houseCardsRevealMs({ playerCount: 3, houseCount: 3, fromPlayer: 2, fromHouse: 2 }),
  280 + 280 + 450,
  "blackjack stand only waits for the new cards",
);
assert.equal(
  houseCardsRevealMs({ playerCount: 3, houseCount: 1, fromPlayer: 2, liveHouse: true }),
  280,
  "hit during player_turn: one card, no outcome beat",
);

console.log("check-house-cards-reveal: ok");
