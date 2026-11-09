#!/usr/bin/env node
/**
 * Frontend smoke for /x8/ai-tasks regression helpers (no vitest).
 * Run: node scripts/smoke-ai-tasks-regression.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const lib = readFileSync(join(root, "src/panel/lib/aiTasksRegression.ts"), "utf8");
const selfcheck = readFileSync(join(root, "src/panel/lib/aiTasksSelfcheck.ts"), "utf8");
const page = readFileSync(join(root, "src/panel/admin/AdminAiTasks.tsx"), "utf8");
const api = readFileSync(join(root, "src/panel/lib/adminApi.ts"), "utf8");

assert.match(lib, /AI_TASKS_PATH = "\/x8\/ai-tasks"/);
assert.match(lib, /AI_TASKS_HINT = "Очередь AI-задач"/);
assert.match(lib, /"approve"/);
assert.match(lib, /FORBIDDEN_UI_ACTIONS/);
assert.match(lib, /startConsoleNetworkCapture/);
assert.match(page, /aiRegressionStart/);
assert.match(page, /UI-регрессия/);
assert.match(page, /runRegression/);
assert.ok(!/runRegression[\s\S]*aiApproveTask/.test(page), "regression must not call approve");
assert.match(api, /\/ai-tasks\/regression\/start/);
assert.match(api, /Idempotency-Key/);

assert.match(selfcheck, /isSelfcheckAlarm/);
assert.match(selfcheck, /unavailable/);
assert.match(selfcheck, /isCheckStatusFinding/);
assert.match(selfcheck, /selfcheckBadgeTone/);
assert.match(page, /SAST self-check/);
assert.match(page, /aiSelfcheckLatest/);
assert.match(page, /isCheckStatusFinding/);
assert.match(page, /selfcheckBadgeTone/);
assert.match(page, /unavailable/);
assert.match(api, /\/ai-tasks\/selfcheck\/latest/);
assert.match(page, /авария/);
assert.match(page, /formatTaskAge/);
assert.match(page, /created_at/);
assert.match(api, /created_at\?: string/);

const age = readFileSync(join(root, "src/panel/lib/taskAge.ts"), "utf8");
assert.match(age, /мин назад/);
assert.match(age, /ч назад/);
assert.match(age, /только что/);

function formatTaskAge(value, now) {
  const raw = String(value ?? "").trim();
  if (!raw) return "—";
  const iso = /Z$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw.replace(" ", "T")}Z`;
  const time = new Date(iso).getTime();
  if (!Number.isFinite(time)) return "—";
  const minutes = Math.max(0, Math.floor((now - time) / 60000));
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  return `${Math.floor(hours / 24)} д назад`;
}
const t0 = Date.parse("2026-08-20T12:00:00Z");
assert.equal(formatTaskAge("2026-08-20T11:59:30Z", t0), "только что");
assert.equal(formatTaskAge("2026-08-20T11:47:00Z", t0), "13 мин назад");
assert.equal(formatTaskAge("2026-08-20T09:00:00Z", t0), "3 ч назад");
assert.equal(formatTaskAge("2026-08-18T12:00:00Z", t0), "2 д назад");
assert.equal(formatTaskAge("", t0), "—");

console.log("smoke-ai-tasks-regression: ok");
