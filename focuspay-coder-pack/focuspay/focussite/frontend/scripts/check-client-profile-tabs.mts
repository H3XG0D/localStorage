/**
 * Operator + admin client profile: exchange/casino tabs, permission gate, no operator profit.
 * Run: npx tsx scripts/check-client-profile-tabs.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(root, rel), "utf8");
}

const ops = read("src/panel/operator/ClientProfile.tsx");
assert.match(ops, /data-client-profile-tabs/);
assert.match(ops, /id: "exchange", label: "Обменник"/);
assert.match(ops, /searchParams.get\("tab"\)/);
assert.match(ops, /replace: true/);
assert.match(ops, /id: "casino", label: "Казино"/);
assert.match(ops, /includes\("casino\.payout"\)/);
assert.match(ops, /canCasino/);
assert.match(ops, /<ClientCasinoTab/);
assert.match(ops, /scope="operator"/);
assert.match(ops, /getUserCasinoProfile/);
assert.match(ops, /data-client-exchange-referral/);
assert.match(ops, /data-client-exchange-balances/);
assert.match(ops, /data-client-exchange-reviews/);
assert.doesNotMatch(ops, /gross_profit/);
assert.doesNotMatch(ops, /house_net_rub/);
assert.doesNotMatch(ops, /finance\.net_profit/);

const admin = read("src/panel/admin/AdminUsers.tsx");
assert.match(admin, /data-client-profile-tabs/);
assert.match(admin, /id: "exchange", label: "Обменник"/);
assert.match(admin, /id: "casino", label: "Казино"/);
assert.match(admin, /<ClientCasinoTab/);
assert.match(admin, /scope="admin"/);
assert.match(admin, /getCasinoPlayerProfile/);
assert.match(admin, /\/x8\/casino\/games\?player_id=/);

const tab = read("src/panel/ui/ClientCasinoTab.tsx");
assert.match(tab, /data-client-casino-tab/);
assert.match(tab, /scope === "admin"/);
assert.match(tab, /data-client-casino-risk/);
assert.match(tab, /house_net_rub/);
assert.match(tab, /FocusLucky/);

const primitives = read("src/panel/ui/primitives.tsx");
assert.match(primitives, /export function Tabs/);

const opApi = read("src/panel/lib/operatorApi.ts");
assert.match(opApi, /getUserCasinoProfile/);
assert.match(opApi, /getUserCasinoHistory/);
assert.match(opApi, /\/users\/\$\{id\}\/casino/);

const admApi = read("src/panel/lib/adminApi.ts");
assert.match(admApi, /getCasinoPlayerProfile/);
assert.match(admApi, /getCasinoPlayerHistory/);
assert.match(admApi, /\/casino\/players\/\$\{playerId\}\/profile/);

const games = read("src/panel/admin/Casino/CasinoGames.tsx");
assert.match(games, /searchParams.get\("player_id"\)/);

console.log("check-client-profile-tabs: ok");
