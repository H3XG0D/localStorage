# FROZEN — зоны, которые Ops AI / агенты не меняют автоматически

Этот файл фиксирует **запреты автоприменения** для FocusPay (Ops AI, UI-регрессия,
Cursor-промпты, sticker sandbox).

## Абсолютные запреты без явного human OK

1. **Автокоммит / push / amend** в git.
2. **Автодеплой** на прод (nginx, systemd, `deploy_all.py` без запроса).
3. **Subprocess** для применения патчей / Cursor CLI / shell от LLM.
4. **Исполнение `cursor_prompt`** сервером — только копирование человеку после Approve.
5. **Финансы / Payfast / HMAC / payroll formulas** — не трогать без явной фразы заказчика
   и отдельного approve.
6. **Секреты** (`.env`, токены, SSH-пароли) — не писать в код, логи, отчёты, escalate JSON.

## Ops AI очередь (`/x8/ai-tasks`)

- Approve = статус `approved` + текст промпта. Не запускает Cursor.
- Reject / Done — только аутентифицированный admin (`admin_id` обязателен).
- UI-регрессионный агент: **read-only**; Approve/Reject/Done ему недоступны.
- Багфиксы из отчёта регрессии — **proposals**; применение только после подтверждения.

## UI context

Для регрессии AI-задач фиксировать:

- `path=/x8/ai-tasks`
- `hint=Очередь AI-задач`

Не подменять цель на `/exchange` из-за LIVE RATES.

## Связанные документы

- `docs/OPS_AI.md` — API и smoke.
- `docs/PRIVACY_AI_NEWS.md` — privacy / audit TTL.
- `docs/PERMISSION_MATRIX.md` — RBAC.
