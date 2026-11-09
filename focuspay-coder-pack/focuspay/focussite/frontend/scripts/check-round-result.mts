/**
 * V2 round-end copy: finished beats stale hitting phase, personal payout, rematch body.
 * Run: npx tsx scripts/check-round-result.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { CasinoV2TableView } from "../src/lib/public.ts";
import {
  formatCasinoRub,
  v2MyRoundResult,
  v2ReplayBody,
  v2SeatPayout,
  v2StatusLabel,
} from "../src/casino/v2RoundResult.ts";

const liveLoss = {
  table_id: "web-efd94be6e241433c",
  game_type: "blackjack",
  stake_rub: "50.00",
  max_seats: 3,
  status: "finished",
  state_version: 9,
  bot_count: 2,
  free_seats: [],
  roster: [
    {
      seat_no: 1,
      participant_kind: "player",
      actor: { user_id: 940002, display_name: "ауебратва", initial: "А" },
      is_you: true,
      pips: null,
      total: null,
      rolled: 0,
      cards: ["10♣", "8♠"],
      score: 18,
      is_winner: false,
      payout_rub: null,
    },
    {
      seat_no: 2,
      participant_kind: "bot",
      actor: { user_id: 0, display_name: "PvP Robot 1", initial: "P" },
      is_you: false,
      pips: null,
      total: null,
      rolled: 0,
      cards: ["7♠", "4♥", "J♣"],
      score: 21,
      is_winner: true,
      payout_rub: "142.50",
    },
    {
      seat_no: 3,
      participant_kind: "bot",
      actor: { user_id: 0, display_name: "PvP Robot 1", initial: "P" },
      is_you: false,
      pips: null,
      total: null,
      rolled: 0,
      cards: ["7♦", "A♥"],
      score: 18,
      is_winner: false,
      payout_rub: null,
    },
  ],
  rolls_needed: 0,
  my_seat_no: 1,
  can_roll: false,
  can_start: false,
  can_leave: false,
  can_cancel: false,
  is_seated: true,
  is_creator: true,
  roll_deadline_at: null,
  house_will_roll: false,
  pot_rub: "150.00",
  commission_rub: "7.50",
  net_payout_rub: "142.50",
  game_state: { phase: "hitting" },
  outcome: { kind: "winner", winner_seat_nos: [2] },
  settlement: {
    outcome_kind: "winner",
    winner_seat_nos: [2],
    pot_rub: "150.00",
    commission_rub: "7.50",
    payouts: [{ seat_no: 2, amount_rub: "142.50" }],
  },
} as CasinoV2TableView;

assert.equal(v2StatusLabel(liveLoss), "готово", "finished beats leftover hitting phase");
assert.equal(v2StatusLabel({ ...liveLoss, status: "running", game_state: { phase: "hitting" } }), "добор");
assert.equal(v2SeatPayout(liveLoss, 2), "142.50");
assert.equal(v2SeatPayout(liveLoss, 1), null);

const mine = v2MyRoundResult(liveLoss);
assert.ok(mine);
assert.equal(mine.kind, "loss");
assert.equal(mine.title, "Проигрыш");
assert.equal(mine.signedLabel, `−${formatCasinoRub(50)}`);
assert.match(mine.detail, /142/);

const win = v2MyRoundResult({
  ...liveLoss,
  roster: liveLoss.roster.map((seat) =>
    seat.seat_no === 1
      ? { ...seat, is_winner: true, payout_rub: "142.50" }
      : { ...seat, is_you: false, is_winner: false, payout_rub: null },
  ),
  settlement: {
    ...liveLoss.settlement,
    winner_seat_nos: [1],
    payouts: [{ seat_no: 1, amount_rub: "142.50" }],
  },
});
assert.ok(win);
assert.equal(win.kind, "win");
assert.equal(win.signedLabel, `+${formatCasinoRub("142.50")}`);

const split = v2MyRoundResult({
  ...liveLoss,
  roster: liveLoss.roster.map((seat) =>
    seat.seat_no === 1 || seat.seat_no === 2
      ? { ...seat, is_winner: true, payout_rub: "71.25" }
      : seat,
  ),
  settlement: {
    outcome_kind: "tie_split",
    winner_seat_nos: [1, 2],
    payouts: [
      { seat_no: 1, amount_rub: "71.25" },
      { seat_no: 2, amount_rub: "71.25" },
    ],
  },
});
assert.ok(split);
assert.equal(split.kind, "tie");
assert.match(split.detail, /разделили/);

const replay = v2ReplayBody(liveLoss);
assert.equal(replay.game_type, "blackjack");
assert.equal(replay.stake_rub, 50);
assert.equal(replay.max_seats, 3);
assert.equal(replay.bot_count, 0);
assert.equal(replay.autojoin, false);

const root = dirname(fileURLToPath(import.meta.url));
const lobby = readFileSync(join(root, "../src/casino/CasinoPlayersLobby.tsx"), "utf8");
assert.match(lobby, /data-casino-v2-replay/);
assert.match(lobby, /Перераздача/);
assert.match(lobby, /К столам/);
assert.doesNotMatch(lobby, /Ещё раунд/);
assert.match(lobby, /useV2RoundNotice/);

const table = readFileSync(join(root, "../src/casino/CasinoV2Table.tsx"), "utf8");
assert.match(table, /data-casino-v2-replay/);
assert.match(table, /В лобби/);
assert.doesNotMatch(table, /Ещё раунд/);
assert.match(table, /CasinoRoundResult/);
assert.match(table, /Ничья — лидеры кидают ещё раз/);

const compact = readFileSync(join(root, "../src/casino/CasinoV2CompactPlay.tsx"), "utf8");
assert.match(compact, /formatCasinoRub\(payout\)/);
assert.match(compact, /finished && seat/);

console.log("check-round-result: ok");
