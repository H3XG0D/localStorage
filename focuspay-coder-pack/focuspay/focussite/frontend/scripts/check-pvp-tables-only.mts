/**
 * Dice / baccarat / blackjack are player tables only.
 * Run: npx tsx scripts/check-pvp-tables-only.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(root, rel), "utf8");
}

const catalog = read("src/casino/gameCatalog.ts");
assert.match(catalog, /house: "Общий стол"/);
assert.doesNotMatch(catalog, /Против FocusBet/);
assert.match(catalog, /id: "pvp_dice"[\s\S]*href: "\/casino\/play\/pvp_dice\?mode=players"/);
assert.match(catalog, /id: "baccara"[\s\S]*href: "\/casino\/play\/baccara\?mode=players"/);
assert.match(catalog, /id: "blackjack"[\s\S]*href: "\/casino\/play\/blackjack\?mode=players"/);

const play = read("src/casino/CasinoPlay.tsx");
assert.match(play, /isHeadToHead\(gameId\)\s*\n\s*\? "players"/);
assert.doesNotMatch(play, /navigate\(casinoTo\("\/casino\/play\/pvp_dice\?mode=house"\)/);
assert.match(play, /isRoulette \|\| isHeadToHead\(gameId\) \? null/);

const lobby = read("src/casino/CasinoLobby.tsx");
assert.doesNotMatch(lobby, /mode=house/);

const players = read("src/casino/CasinoPlayersLobby.tsx");
assert.match(players, /data-casino-create-menu/);
assert.match(players, /createCasinoV2Table/);
assert.match(players, /baccara/);
assert.match(players, /casino-room-list/);
assert.match(players, /casino-room-row/);
assert.match(players, /Сесть/);
assert.match(players, /CasinoV2CompactPlay/);
assert.match(players, /facesOnly/);
assert.match(players, /casino-v2-strip-play/);
assert.match(players, /data-casino-v2-lobby/);
assert.match(players, /addCasinoV2Bot/);
assert.match(players, /rollCasinoV2Table/);
assert.doesNotMatch(players, /navigate\(casinoTo\(`\/casino\/tables\/\$\{/);
assert.doesNotMatch(players, /CasinoTableTile/);
assert.doesNotMatch(players, /createCasinoDuel/);

const table = read("src/casino/CasinoV2Table.tsx");
assert.match(table, /game_type === "baccara"/);
assert.match(table, /data-casino-v2-add-bot/);
assert.match(table, /data-casino-baccara-street/);

console.log("check-pvp-tables-only: ok");
