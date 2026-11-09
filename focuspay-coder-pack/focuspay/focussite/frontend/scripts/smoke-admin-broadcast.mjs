#!/usr/bin/env node
/**
 * Frontend smoke for /x8 and /ops broadcast stickers + AI draft (no vitest).
 * Run: node scripts/smoke-admin-broadcast.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const lib = readFileSync(join(root, "src/panel/lib/adminBroadcast.ts"), "utf8");
const page = readFileSync(join(root, "src/panel/ui/BroadcastPanel.tsx"), "utf8");

assert.match(lib, /BROADCAST_AI_DEFAULT_ENABLED = false/);
assert.match(lib, /BROADCAST_STICKER_MODE_DEFAULT[^=]*= "none"/);
assert.match(lib, /buildCreateJobBody/);
assert.match(lib, /normalizeDestination/);
assert.match(lib, /destination: normalizeDestination/);
assert.match(lib, /buildPatchJobBody/);
assert.match(lib, /stickerDraftFromRow/);
assert.match(lib, /moscowDateTimeLocalToIso/);
assert.match(lib, /scheduled_at/);
assert.match(lib, /time_local/);
assert.match(lib, /days_of_week/);
assert.match(lib, /applyAiDraft/);
assert.match(lib, /pickFallbackStickerId/);
assert.match(lib, /stickerPreviewUrl/);
assert.doesNotMatch(lib, /LIVE RATES|\/exchange/);
assert.doesNotMatch(lib, /brand-stickers/);

assert.match(page, /scope === "operator"/);
assert.doesNotMatch(page, /Подобрать автоматически/);
assert.doesNotMatch(page, /Стикеры проекта/);
assert.doesNotMatch(page, /Каталог пуст/);
assert.doesNotMatch(page, /brand-stickers/);
assert.match(page, /Улучшить текст/);
assert.doesNotMatch(page, /Включить AI/);
assert.doesNotMatch(page, /"\/broadcast\/stickers"/);
assert.match(page, /\/broadcast\/ai-draft/);
assert.match(page, /buildCreateJobBody/);
assert.match(page, /\/broadcast\/ai-draft[\s\S]*ai_enabled: true/);
assert.match(page, /confirmAiDraft/);
assert.doesNotMatch(page, /sticker=\{previewSticker\}/);
assert.doesNotMatch(page, /sticker=\{jobPreviewSticker/);
assert.match(page, /Запланировать/);
assert.match(page, /В бота/);
assert.match(page, /В новости/);
assert.match(page, /1 пост в новости FocusPay/);
assert.match(page, /destination === "bot" \? \(/);
assert.match(page, /Сохранить повтор/);
assert.match(page, /\/broadcast\/schedules/);
assert.match(page, /reuseJob/);
assert.match(page, /openJobViewer/);
assert.match(page, /saveJobViewer/);
assert.match(page, /previewEdit/);
assert.match(page, /Повторить/);
assert.match(page, /Изменить/);
assert.match(page, /Сохранить/);
assert.match(page, /История рассылок/);
assert.match(page, /previewJob/);
assert.match(page, /onRowClick/);
assert.match(page, /editingJobId/);
assert.match(page, /editingScheduleId/);
assert.match(page, /buildPatchJobBody/);
assert.doesNotMatch(page.slice(page.indexOf("function reuseJob"), page.indexOf("function reuseSchedule")), /method: "POST"/);

const sendBlock = page.slice(page.indexOf("async function send()"), page.indexOf("async function cancel"));
assert.match(sendBlock, /buildCreateJobBody/);
assert.match(sendBlock, /scheduledAt/);
assert.doesNotMatch(sendBlock, /ai_enabled/);
assert.doesNotMatch(sendBlock, /isAdmin/);

console.log("smoke-admin-broadcast: ok");
