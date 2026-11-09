/**
 * Post-login return path + Telegram OAuth parse.
 * Run: npx tsx scripts/check-post-login-path.mts
 */
import assert from "node:assert/strict";
import { authPathWithNext, POST_LOGIN_FALLBACK, resolvePostLoginPath } from "../src/lib/postLoginPath.ts";
import { consumeTelegramOauthResult, parseTelegramOauthResult, stripTelegramOauthParams } from "../src/lib/telegramOauth.ts";

assert.equal(resolvePostLoginPath("/casino"), "/casino");
assert.equal(resolvePostLoginPath("/casino/play/roulette?mode=house"), "/casino/play/roulette?mode=house");
assert.equal(resolvePostLoginPath("/exchange"), "/exchange");
assert.equal(resolvePostLoginPath("/cabinet/settings"), "/cabinet/settings");
assert.equal(resolvePostLoginPath("//evil"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("/login"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("/register"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("/forgot"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("https://evil.com"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("http://evil.com/casino"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath(undefined), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath(""), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("/login?next=/casino"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("/\\evil"), POST_LOGIN_FALLBACK);
assert.equal(resolvePostLoginPath("/%2f%2fevil"), POST_LOGIN_FALLBACK);

assert.equal(resolvePostLoginPath("/login/telegram"), POST_LOGIN_FALLBACK);
assert.equal(authPathWithNext("/login/telegram"), "/login/telegram?next=%2Fcasino");
assert.equal(authPathWithNext("/login/telegram", "/casino/wallet"), "/login/telegram?next=%2Fcasino%2Fwallet");
assert.equal(authPathWithNext("/login/telegram", "/cabinet"), "/login/telegram?next=%2Fcasino");
assert.equal(authPathWithNext("/login"), "/login");
assert.equal(authPathWithNext("/login", "/cabinet"), "/login");
assert.equal(authPathWithNext("/login", "/casino"), "/login?next=%2Fcasino");
assert.equal(
  authPathWithNext("/register", "/casino/play/roulette?mode=house"),
  "/register?next=%2Fcasino%2Fplay%2Froulette%3Fmode%3Dhouse",
);

const encoded = Buffer.from(
  JSON.stringify({ id: 1, first_name: "Ada", auth_date: 1700000000, hash: "abc" }),
).toString("base64");
assert.deepEqual(parseTelegramOauthResult("", `#tgAuthResult=${encoded}`), {
  id: 1,
  first_name: "Ada",
  auth_date: 1700000000,
  hash: "abc",
});
assert.deepEqual(
  parseTelegramOauthResult("?id=2&first_name=Bob&auth_date=1700000001&hash=def&next=/casino", ""),
  { id: "2", first_name: "Bob", auth_date: "1700000001", hash: "def" },
);
assert.equal(parseTelegramOauthResult("", ""), null);
assert.equal(stripTelegramOauthParams("?id=2&hash=def&auth_date=1&next=%2Fcasino"), "?next=%2Fcasino");
assert.deepEqual(consumeTelegramOauthResult("", `#tgAuthResult=${encoded}`), {
  id: 1,
  first_name: "Ada",
  auth_date: 1700000000,
  hash: "abc",
});
assert.equal(consumeTelegramOauthResult("", `#tgAuthResult=${encoded}`), null);

console.log("check-post-login-path: ok");
