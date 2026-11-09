/**
 * Casino login goes to /login/telegram (bot Start), not the phone widget.
 * Run: npx tsx scripts/check-casino-bot-login.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { authPathWithNext } from "../src/lib/postLoginPath.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function src(rel: string): string {
  return readFileSync(join(root, rel), "utf8");
}

assert.equal(authPathWithNext("/login/telegram", "/casino"), "/login/telegram?next=%2Fcasino");
assert.equal(
  authPathWithNext("/login/telegram", "/casino/play/roulette?mode=house"),
  "/login/telegram?next=%2Fcasino%2Fplay%2Froulette%3Fmode%3Dhouse",
);

const paths = src("src/casino/casinoPaths.tsx");
assert.match(paths, /authPathWithNext\("\/login\/telegram"/);
assert.doesNotMatch(paths, /authPathWithNext\("\/login"/);

const app = src("src/App.tsx");
assert.match(app, /path="\/login\/telegram"/);
assert.match(app, /TelegramBotLogin/);

const page = src("src/pages/TelegramBotLogin.tsx");
assert.match(page, /telegramBotStart/);
assert.match(page, /telegramBotWait/);
assert.match(page, /telegramBotComplete/);
assert.match(page, /data-casino-tg-bot-login/);
assert.match(page, /authPathWithNext\("\/login"/);
assert.match(page, /игровой бот FocusBet/);

const auth = src("src/lib/auth.ts");
assert.match(auth, /\/auth\/telegram\/bot-start/);
assert.match(auth, /\/auth\/telegram\/bot-wait/);
assert.match(auth, /\/auth\/telegram\/bot-complete/);

console.log("check-casino-bot-login: ok");
