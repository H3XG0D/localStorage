---
name: ops-ai-closeout
description: Close the loop after work from FocusPay Ops AI: mark the task done through the normal admin API, notify the assigner, and report compactly. Use when work came from ops_ai_dev_tasks, /x8/ai-tasks, cursor_prompt, Operator Dev Requests, or an approved AI task.
---

# Ops AI task closeout + publishing style

## Когда применяется

Если работа пришла из Ops AI (`ops_ai_dev_tasks`, `/x8/ai-tasks`, `cursor_prompt`, Operator Dev Requests или одобренная AI-задача), **закрой цикл на сервере** до завершения ответа.

## Обязательный чеклист

1. **Отметить выполненной** — `POST /api/admin/ai-tasks/{id}/done` с коротким `note` (что выкатили / что проверить). Использовать обычную admin-авторизацию (login / существующая сессия). **Никогда** не форджить JWT и не обходить 2FA.
2. **Уведомить автора** — done-path должен уведомить оператора, создавшего задачу (Telegram, когда привязан). После backend deploy это автоматически делает `mark_task_done`. Если notify мог не пройти — сказать явно.
3. **Сообщить заказчику** — одна короткая строка: задача `#N` закрыта, автор уведомлён (или почему нет).
4. **Backfill** — если просят «разошли старые» / закрыть исторические задачи: вызвать backfill-path для строк `approved`/`done` без `done_notified_at` (при необходимости отметить done, затем уведомить один раз). Не слать дубликаты.

## Формат отчёта / уведомления

Структура done-note и Telegram notify (Telegram HTML, только допустимые теги):

- **Заголовок:** `Ops AI · готово #N` + название задачи
- **Что изменено:** 3–6 коротких пунктов
- **Проверка:** одна smoke-строка, если уместно
- **Ссылка:** URL admin-задачи, если известен `PUBLIC_SITE_URL`

Без стен текста и emoji-спама.

## News / buyer posts

Для рассылок или постов канала:

1. Жирный заголовок.
2. 1–2 коротких абзаца.
3. Пункты с выгодами.
4. Ясный CTA (ссылка или следующий шаг).

Когда есть пак, предпочитать один брендированный стикер FocusPay. Использовать `sanitize_telegram_html` и только Telegram-safe теги (`<b>`, `<i>`, `<a>`, …).

## Напоминания о границах

- Не делать auto-commit / auto-deploy без явной просьбы.
- Backend/nginx/restart = production; нужен явный OK, если текущая задача уже не одобрила этот deploy.
