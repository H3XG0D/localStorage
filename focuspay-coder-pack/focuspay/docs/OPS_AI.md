# Ops AI — очередь задач и UI-регрессия

## Назначение

Ops AI принимает запросы операторов/админов, готовит `cursor_prompt` для ручного
применения в Cursor и держит очередь review на `/x8/ai-tasks`.

**Freeze:** нет автокоммита, автодеплоя, subprocess/git и автоисполнения Cursor-промптов.
Approve только отдаёт промпт человеку. См. `docs/FROZEN.md`.

## Экраны

| Path | Hint | Роль |
|---|---|---|
| `/x8/ai-tasks` | Очередь AI-задач | Админ: review / approve / reject / done |
| `/ops/dev-requests` | Задачи AI | Оператор: создать задачу |
| FAB `/x8/*`, `/ops/*` | UI CONTEXT | Чат + escalate в очередь |

`/grill-me` в чате панели (и команда Cursor) — прожарка: сначала уточняет одну цель,
не кладёт задачу в очередь. Слова человека важнее findings. Несколько просьб не сливаются.

LIVE RATES / BUY-SELL — справочник сайта. Не подменять цель задачи на публичный `/exchange`.

**Inbox ≠ баг:** `/ops/dev-requests` и `/x8/ai-tasks` — очередь подачи, не поверхность бага.
«Ошибка в боте / телеграм» → `bot/tg_bot_btc` (`handlers`, `services`). Курсы бота ≠ LIVE RATES сайта.

## UI-регрессия (read-only агент)

После обновлений на `/x8/ai-tasks` доступен отдельный агент:

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/admin/ai-tasks/regression/start` | Старт + отчёт (Idempotency-Key) |
| GET | `/api/admin/ai-tasks/regression/latest` | Последний run текущего admin |
| GET | `/api/admin/ai-tasks/regression/{id}` | Статус |
| GET | `/api/admin/ai-tasks/regression/{id}/report` | Полный отчёт |
| POST | `/api/admin/ai-tasks/regression/{id}/observations` | Дополнить console/network |

Сценарий жёстко: `path=/x8/ai-tasks`, hint «Очередь AI-задач».

**Разрешено:** открыть экран, фильтр статуса, выбрать строку, смотреть деталь,
копировать промпт, собрать console/network, screenshot-meta.

**Запрещено агенту:** Approve, Reject, Done, финансы, deploy, git, subprocess,
исполнение Cursor-промпта.

Отчёт: steps (expected/actual), severity, screenshot ref, console/network errors,
version/deployment, `bugfix_proposal` (только предложение).

Реализация: `ops_ai_regression.py` + кнопка «UI-регрессия» в `AdminAiTasks.tsx`.

## Nightly SAST self-check (bandit + pip-audit)

Прод: `focuspay-selfcheck.service` — демон origin-smoke (~15 мин, UA
`FocusPay-SelfCheck/1.0`). Nightly SAST раньше вызывал `bandit`/`pip-audit` из
PATH и при отсутствии писал `not installed` в Telegram (fail-open). Теперь SAST
вынесен в **`focuspay-sast-selfcheck.timer`** (04:15, User=focuspay, абсолютные
бины). У демона `SELFCHECK_SAST=0` (если 1 — тот же fail-closed модуль
`ops_ai_selfcheck`, не PATH).

Fail-closed:

- Абсолютные пути: `BANDIT_BIN`, `PIP_AUDIT_BIN`, `EXCHANGE_ROOT`, `BOT_ROOT`.
- Pinned venv `/opt/focuspay-security-tools` (не API venv, не системный PATH).
- Preflight: executable + `--version` + маркеры каталогов. Нет инструмента /
  битый root → check `unavailable`, **job exit 2**, alarm на `/x8/ai-tasks`.
- Ненулевой exit инструмента → `failed` (реальные findings), не «успех с текстом».
- `bandit.yaml` в корне дерева (если есть) передаётся как `-c`. Skip только **B608**
  (asyncpg `$N`; heuristic FP на f-string SQL). `exclude_dirs`: tests/scripts/deploy/tmp.
- pip-audit JSON: пакет с `"vulns": []` — чисто; finding только при непустом `vulns`
  или обрезанной строке без ключа (тогда «запроси полный отчёт», без выдуманного CVE).
- Результат в таблице `ops_ai_selfcheck_runs` и `GET /api/admin/ai-tasks/selfcheck/latest`.
- Telegram — опциональный alert. Источник истины — API.
- `agents_json.selfcheck` — статусы проверок. `agents.merged` — только уязвимости.
  Строка `bandit[exchange]: not installed` **не** finding.
- Cursor-промпт SAST: отдельные секции Bandit exchange / Bandit bot / pip-audit exchange.
  Findings в `<<<UNTRUSTED_DATA … UNTRUSTED_DATA>>>` (данные, не инструкции).
  Неполные поля → запросить полный отчёт, не выдумывать CVE/rule_id/CWE.
  Задача остаётся в `review`; Cursor/git/subprocess/deploy не запускаются.
- `_PRIV_IDEMP` ключ = kind + admin + task (+ operator) + action + client key.
  Cross-user replay запрещён. `_RATE` — process-local, не замена auth.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/admin/ai-tasks/selfcheck/latest` | Последний run (карточка экрана) |
| GET | `/api/admin/ai-tasks/selfcheck/{id}` | Деталь run |

Файлы: `ops_ai_selfcheck.py`, `scripts/security_selfcheck.py`,
`deploy/security/focuspay-sast-selfcheck.{service,timer}`.

WorkingDirectory unit: `/var/lib/focuspay/selfcheck` (не `/opt/exchange-backend`).

## Привилегированные POST

- Повторная проверка `get_current_admin` + обязательный `admin_id`.
- `source_session_id` / `source_message_id` / `task_id` / `client_id` **не** дают право:
  нужна ownership-проверка сессии и JWT admin.
- `Idempotency-Key` на approve / reject / done / regression/start (replay-защита).
- Rate limit: Ops AI `OPS_AI_RATE_PER_MIN`; regression — отдельный bucket.
- Cookies панели: HttpOnly + Secure (https) + SameSite=Lax (`panel_cookies.py`).
  Привилегированные действия также принимают Bearer → сниженный CSRF-риск vs cookie-only.

## Telegram bind (`opsbind_` / `/ops_bind`)

Привязка оператора к боту задаётся в `/ops/profile` (кнопка «Получить ссылку»).

| Канал | Формат | Обработчик |
|---|---|---|
| Deep-link | `https://t.me/<bot>?start=opsbind_<TOKEN>` | `start_handler` → `maybe_handle_ops_bind` |
| Команда | `/ops_bind <TOKEN>` | `CommandHandler("ops_bind")` |
| API выдачи ссылки | `POST /api/operator/ai/telegram/bind-link` | `get_current_operator` (сессия панели) |

Токен живёт 2 часа. Просроченный/чужой код — явное сообщение и ссылка на `/ops/profile`, не молчаливый отказ. Страница `/ops/profile` — SPA-маршрут панели (нужна ops-сессия); бэкенд отдаёт JSON bind API, не HTML.

Кнопка «Профиль» в боте — reply-клавиатура (`MENU_PROFILE`), не inline `callback_data`. Карточка покупателя: `profile_hub_handler` + `hub:*`. Операторский URL: `ops:profile` / `/ops/profile`.

## UI context allowlist

`ops_ai_ui_context.validate_ui_context`: path только `/ops/*` и `/x8/*`, search —
whitelist keys (`id`, `status`, `action`, `order`…), hint/title редактируются.

## LLM / ESCALATE_JSON

Системная инструкция в `ops_ai_llm.CHAT_SYSTEM`. Парсер `split_escalate`:
редактирует секреты, блокирует injection-фразы в `cursor_prompt`.
Escalate создаёт задачу в review — **не** approve и **не** execute.

## Smoke-план

1. Открыть `/x8/ai-tasks` под admin.
2. Нажать «UI-регрессия» → статус passed/failed + шаги.
3. Убедиться, что агент не вызвал approve/reject/done (network).
4. Вручную Approve одной review-задачи → промпт копируется, без автодеплоя.
5. `python -m unittest tests.test_ops_ai_regression tests.test_ops_ai_ui_anchor tests.test_ops_ai_selfcheck`.
6. Frontend smoke: `node scripts/smoke-ai-tasks-regression.mjs` (из `focussite/frontend`).
7. `/x8/ai-tasks`: карточка SAST — `unavailable`/`skipped`/`failed` красные, не yellow-finding.
