# AGENTS.md — FocusVPN

Коммерческий VPN-продукт (**FocusVPN**). Рабочий каталог `focusvpn`. Перенесено из `CLAUDE.md`.

В Obsidian-vault проект проходит под старым именем **MYVPN** — это один и тот же проект.

## Project Brain (Obsidian)

Документация живёт в [`docs/`](docs/) и входит в **мозг экосистемы**: vault `~/Documents/brain` (симлинк `Projects/MYVPN` → эта папка `docs/`). Открыть: `./scripts/open-brain.sh`. Мозг также ведёт FocusPay (`tg_bot_btc`), задачи команды со сроками и межпроектные планы в `brain/Ecosystem/` (например, единая БД юзеров + пополнение баланса VPN из бота).

Схема: [`docs/_system/BRAIN.md`](docs/_system/BRAIN.md). Вход: [`docs/Home.md`](docs/Home.md). Каталог: [`docs/INDEX.md`](docs/INDEX.md). Канбан: [`docs/FocusVPN Board.md`](docs/FocusVPN%20Board.md) (формат Tasks: `- [ ] задача 📅 YYYY-MM-DD [[Team/Имя]] #focusvpn`). Статус-карточка экосистемы: [`docs/STATUS.md`](docs/STATUS.md) — держать frontmatter (`status`, `milestone`) актуальным.

Ты — библиотекарь этого мозга. Держи его связным и актуальным, не оставляй orphan-заметок. Obsidian установлен как Flatpak `md.obsidian.Obsidian`; UI-конфиг vault — в `brain/.obsidian/`, локальный `docs/.obsidian/` оставлен для standalone-использования.

**Автоматическое обновление:** после существенной работы, породившей знание, обновлять Project Brain даже без просьбы «сохрани в Obsidian». Таблица «Всегда записывать» обязательна без явного запроса.

Планы майлстоунов и дизайна — в [`docs/plans/`](docs/plans/) (type `plan`). Логи чатов **вне скоупа** — зоны `docs/sessions/` нет; долговечное знание идёт в CURRENT_TASK / DECISIONS / ADR / research / TODO / plans.

### Перед любой работой

1. Прочитать [`docs/Home.md`](docs/Home.md) — статус и навигация.
2. Прочитать [`docs/CURRENT_TASK.md`](docs/CURRENT_TASK.md) — что в работе.
3. Прочитать [`docs/ROADMAP.md`](docs/ROADMAP.md) — фазы и DoD.
4. Читать [`docs/PROJECT.md`](docs/PROJECT.md), когда нужны цели/правила.
5. Для архитектурных изменений: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), затем ADR в [`docs/adr/`](docs/adr/).
6. Решения фиксировать в [`docs/DECISIONS.md`](docs/DECISIONS.md); открытые вопросы — в [`docs/TODO.md`](docs/TODO.md).

### Всегда записывать (после существенной работы — обязательно)

| Триггер | Куда писать |
|---|---|
| Смена фокуса / майлстоуна | [`CURRENT_TASK.md`](docs/CURRENT_TASK.md); при смене статуса фазы — блок статуса в [`Home.md`](docs/Home.md) + frontmatter [`STATUS.md`](docs/STATUS.md) |
| Дизайн майлстоуна (до реализации) | Заметка в [`docs/plans/`](docs/plans/) (напр. `M3.md`) + [`MOC/Execution`](docs/MOC/Execution.md) + [`INDEX`](docs/INDEX.md) |
| Любое решение | Строка в [`DECISIONS.md`](docs/DECISIONS.md) (чеклист — [`_templates/decision-log.md`](docs/_templates/decision-log.md)) |
| Архитектурное решение | ADR из [`_templates/adr.md`](docs/_templates/adr.md) → `docs/adr/00N-slug.md` + [`MOC/Decisions`](docs/MOC/Decisions.md) + [`INDEX`](docs/INDEX.md) |
| Внешний research / лицензии | Заметка из [`_templates/research.md`](docs/_templates/research.md) + [`MOC/Research`](docs/MOC/Research.md) + [`research/README`](docs/research/README.md) + [`INDEX`](docs/INDEX.md); лицензии также в [`OPEN_SOURCE.md`](docs/OPEN_SOURCE.md) |
| Риск / долг | [`TODO.md`](docs/TODO.md) |
| Любая новая заметка | Frontmatter (`type`, `tags`, `status`, `updated`) + ≥1 `[[wikilink]]` + [`INDEX`](docs/INDEX.md) + нужный [`MOC/`](docs/MOC/) |

Не заканчивать сессию с недокументированными решениями, orphan-заметками или устаревшим `CURRENT_TASK`.

### Правила связывания

- Внутри vault предпочитать Obsidian `[[wikilinks]]`; markdown-ссылки оставлять там, где полезны для не-Obsidian читателей.
- Не дублировать канонические факты — ссылаться на источник (напр. JWT → SECURITY / ADR-006).
- Никаких orphan-заметок. Следовать [`docs/_system/BRAIN.md`](docs/_system/BRAIN.md).

## Фазовые гейты

- **Фаза 1** (архитектурные документы) завершена.
- **Фаза 2** (Go control plane + node-agent + CLI harness) — в работе. Майлстоуны 1–2 сделаны, дальше Milestone 3 (см. CURRENT_TASK / ROADMAP).
- **Не реализовывать** новый майлстоун Фазы 2 (и не начинать UI-клиенты Фазы 3+) без явного запроса или одобрения этого майлстоуна.
- Скоуп Фазы 2 = Go CP + node-agent + **CLI harness** (не полноценные UI-клиенты). См. ROADMAP §2–§3.
- Внешний research — в [`docs/research/`](docs/research/); лицензии — в [`docs/OPEN_SOURCE.md`](docs/OPEN_SOURCE.md).

## Незыблемое

- Никакого GPL/AGPL в бинаре продукта; GPL-инструменты на нодах — только отдельными процессами.
- Приватные ключи клиента никогда не покидают устройство; CP подписывает ConfigParts (Ed25519).
- Access JWT = EdDSA (Ed25519); ротация refresh + детект переиспользования.
- MVP AmneziaWG использует Jc/Jmin/Jmax, уникальные на ноду; пин `amneziawg-go` `v0.2.19` до решения об апгрейде.

## Стек и команды

Go 1.25, модуль `focusvpn.example/focusvpn`. Ключевое: `amneziawg-go v0.2.19`, `wireguard`, `golang-jwt/jwt/v5`, `golang-migrate/migrate/v4`, `pgx/v5`, `wails/v2` (десктоп). Python-бот-компаньон — `bots/focusvpn-tg`.

Makefile работает через **podman compose** (`infra/compose/docker-compose.yml`):

```bash
make build test vet tidy            # сборка, тесты, vet
make run                            # FOCUSVPN_STORE=memory go run ./backend/cmd/server
make dev-up dev-down dev-logs       # окружение; dev-reset уничтожает volumes
make migrate migrate-down migrate-version
make seed seed-agent-token          # seed-agent-token печатает одноразовый AGENT_NODE_TOKEN для ноды DE-01
make build-agent                    # bin/node-agent
make db-test-create && make test-integration
make smoke smoke-e2e smoke-linux smoke-desktop smoke-windows smoke-xray smoke-e1-billing smoke-e1-full
make android-check apple-check windows-check native-libs-check license-check launch-check
make release-linux release-windows release-android release-all
```

`make dev-reset` делает `down -v` и уничтожает volumes — не запускать без подтверждения.
`make smoke-e2e` с `FOCUSVPN_E2E_REAL_TUNNEL=1` требует `awg`/`awg-quick` и CAP_NET_ADMIN.

## Навыки агента

Установлены в `.agents/skills/` (Cursor: `.cursor/skills` — симлинк). Копия на уровне пользователя — `~/.agents/skills/`, доступна во всех проектах. Предпочитать явный вызов (`/grill-with-docs`, `/tdd`, …).

Цепочка для новой фичи: **`/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement`** (внутри `/tdd`, затем `/code-review`).
Баги: **`/diagnosing-bugs`**. Большие туманные задачи: **`/wayfinder`**. Не помнишь нужный навык: **`/ask-matt`**.

### Issue tracker

Локальный markdown в `.scratch/` (+ карточки на `docs/FocusVPN Board.md`, когда задача видна пользователю). См. [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Метки triage

По умолчанию: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. См. [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Доменные документы

Единый контекст: корневой [`CONTEXT.md`](CONTEXT.md) (глоссарий) + [`docs/adr/`](docs/adr/) (шаблон и нумерация ADR FocusVPN) + Project Brain. См. [`docs/agents/domain.md`](docs/agents/domain.md).

## Общение

Язык общения с заказчиком — **русский**. Английский — только в коде, командах, путях и идентификаторах.

Не коммитить, не пушить, не деплоить без явной просьбы. Не печатать значения секретов.
