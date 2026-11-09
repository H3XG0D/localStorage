/**
 * Senior operators: /ops/history archive of all orders (read-only).
 * Run: npx tsx scripts/check-ops-order-history.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(root, rel), "utf8");
}

const routes = read("src/panel/operator/OperatorRoutes.tsx");
assert.match(routes, /\/ops\/history/);
assert.match(routes, /label: "История"/);
assert.match(routes, /orders\.history/);
assert.match(routes, /OperatorOrderHistory/);

const page = read("src/panel/operator/OperatorOrderHistory.tsx");
assert.match(page, /data-ops-order-history/);
assert.match(page, /getOrderHistory/);
assert.match(page, /OpsClientLink/);
assert.match(page, /Открыть в очереди/);
assert.match(page, /\/ops\/orders\?order=/);
assert.doesNotMatch(page, /service_profit/);
assert.doesNotMatch(page, /setOrderStatus/);
assert.doesNotMatch(page, /cancelAdminOrder/);
assert.doesNotMatch(page, /confirmAdminPayout/);

const api = read("src/panel/lib/operatorApi.ts");
assert.match(api, /\/orders\/history/);
assert.match(api, /fetchOperatorOrderReceiptBlob/);
