/**
 * Rooms: visible catalog tile, no "Все дуэли", dice-like create, jackpot reel, +bot.
 * Run: npx tsx scripts/check-casino-rooms.mts
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
assert.match(catalog, /id: "fixed_room"[\s\S]*name: "Комнаты"/);
assert.match(catalog, /id: "fixed_room"[\s\S]*href: "\/casino\/play\/fixed_room\?mode=players"/);
const roomBlock = catalog.match(/\{\s*id: "fixed_room",[\s\S]*?\n  \},/);
assert.ok(roomBlock, "fixed_room catalog block");
assert.doesNotMatch(roomBlock[0], /hidden:/);
assert.doesNotMatch(catalog, /title: "Комната N"/);

const shell = read("src/casino/CasinoShell.tsx");
assert.doesNotMatch(shell, /Все дуэли/);
assert.doesNotMatch(shell, /duelsTo/);
assert.doesNotMatch(shell, /CasinoLiveDock/);
assert.match(shell, /if \(id === "fixed_room"\) return <Target/);

const routes = read("src/casino/casinoRoutes.tsx");
assert.match(routes, /path="duels" element=\{<RedirectToCasinoPlay gameId="fixed_room"/);
assert.match(routes, /path="duels\/:duelId" element=\{<CasinoDuelRoom/);

const rooms = read("src/casino/CasinoFixedRooms.tsx");
assert.match(rooms, /data-casino-create-menu/);
assert.match(rooms, /data-casino-room-add-bot/);
assert.match(rooms, /postCasinoRoomBot/);
assert.match(rooms, /buildWeightedReel/);
assert.match(rooms, /rooms\/events/);
assert.match(rooms, /casino-room-list/);
assert.match(rooms, /casino-room-row/);
assert.match(rooms, /Сесть/);
assert.doesNotMatch(rooms, /CasinoTableTile/);
assert.match(rooms, /CasinoRoomLiveCanvas/);
assert.match(rooms, /layout="row"/);
assert.match(rooms, /SEAT_CHOICES/);
assert.match(rooms, /250/);

const canvas = read("src/casino/CasinoRoomLiveCanvas.tsx");
assert.match(canvas, /casino-room-join/);
assert.match(canvas, /layout === "row"/);
assert.match(canvas, /Array.from\(\{ length: Math.max\(2, room.seat_count\)/);
assert.match(canvas, /CasinoPlayerChip/);
assert.match(canvas, /player\.user_id !== 0/);

const css = read("src/casino/casino.css");
assert.match(css, /casino-room-list/);
assert.match(css, /casino-room-join/);
assert.match(css, /casino-room-row \.casino-player-nick/);
assert.match(canvas, /WEIGHTED_REEL_SPIN_MS/);
assert.match(css, /casino-jackpot-reel\.is-drama/);
assert.match(css, /casino-jackpot-reel\.is-drama \.casino-jackpot-slot\.is-winner/);
assert.match(css, /10\.5s/);

const lobby = read("src/casino/CasinoLobby.tsx");
assert.match(lobby, /Живые комнаты/);
assert.doesNotMatch(lobby, /Живые дуэли/);
assert.doesNotMatch(lobby, /Открыть лобби дуэлей/);
assert.doesNotMatch(lobby, /🎯/);
assert.match(lobby, /<Target size=\{20\} \/>/);

console.log("check-casino-rooms: ok");
