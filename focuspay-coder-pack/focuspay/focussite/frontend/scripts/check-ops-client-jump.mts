/**
 * Ops queue → client profile jump, casino payouts master-detail like orders.
 * Run: npx tsx scripts/check-ops-client-jump.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(root, rel), "utf8");
}

const path = read("src/panel/lib/opsClientPath.tsx");
assert.match(path, /\/ops\/client\/\$\{id\}/);
assert.match(path, /\?tab=casino/);
assert.match(path, /data-ops-client-link/);
assert.match(path, /stopPropagation/);

const orders = read("src/panel/operator/OperatorOrders.tsx");
assert.match(orders, /OpsClientLink/);
assert.match(orders, /Профиль →/);
assert.match(orders, /role="button"/);
assert.match(orders, /setSelId\(item\.order_id\)/);
assert.doesNotMatch(orders, /to=\{`\/ops\/client\/\$\{/);
assert.doesNotMatch(orders, /tab="casino"/);

const payouts = read("src/panel/operator/OperatorCasinoPayouts.tsx");
assert.match(payouts, /data-ops-casino-payouts/);
assert.match(payouts, /data-ops-payout-list/);
assert.match(payouts, /data-ops-payout-panel/);
assert.match(payouts, /searchParams.get\("payout"\)/);
assert.match(payouts, /getMe/);
assert.match(payouts, /Выплат нет/);
assert.match(payouts, /Выберите выплату/);
assert.match(payouts, /tab="casino"/);
assert.match(payouts, /OpsClientLink/);
assert.match(payouts, /Профиль →/);
assert.match(payouts, /setSelId\(item\.id\)/);
assert.match(payouts, /grid-cols-\[minmax\(0,1fr\)_420px\]/);
assert.match(payouts, /claimCasinoPayout/);
assert.match(payouts, /rejectCasinoPayout/);
assert.doesNotMatch(payouts, /onClick=\{\(\) => navigate\(`\/ops\/client/);

const profile = read("src/panel/operator/ClientProfile.tsx");
assert.match(profile, /searchParams.get\("tab"\)/);
assert.match(profile, /includes\("casino\.payout"\)/);
assert.match(profile, /replace: true/);

console.log("check-ops-client-jump: ok");
