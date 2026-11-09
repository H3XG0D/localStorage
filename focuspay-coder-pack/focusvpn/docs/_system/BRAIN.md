---
type: system
tags: [system, brain]
status: active
updated: 2026-08-11
---

# Project Brain — схема

Каноническая knowledge base FocusVPN. Vault = `docs/`. Агенты поддерживают мозг по протоколу в корневом `CLAUDE.md`.

## Как открыть

1. Obsidian установлен через Flatpak: `md.obsidian.Obsidian`.
2. **Рекомендуемый запуск:** `./scripts/open-brain.sh` из корня репо — открывает **экосистемный** vault `~/Documents/brain` (там symlink `Projects/FocusVPN` → этот `docs/`).
3. **Standalone:** **Open folder as vault** → `…/focusvpn/docs` (не корень репозитория). Community plugins выключены; Templates = `_templates`.
4. В экосистемном vault workspace открывает корневой `Home` экосистемы; внутри FocusVPN — [[Home]].

## Что писать всегда

См. таблицу «Когда обновлять что» ниже и секцию **After substantial work** в корневом `CLAUDE.md`. Кратко: `CURRENT_TASK` · `plans/` · `DECISIONS`/ADR · `research/` · `TODO` · `INDEX`+MOC · никаких orphan notes.

**Автообновление:** после существенной работы мозг обновляется даже без фразы «save to Obsidian».

**Вне зоны:** `docs/sessions/` **не существует и не ведётся** — сессионные чаты не складываются в vault; устойчивое знание пишется в hub / plans / ADR / research / TODO.

## Зоны

| Зона | Путь | Назначение |
|---|---|---|
| Hub | корень `docs/` | PROJECT, CURRENT_TASK, ROADMAP, спеки, Home, INDEX, STATUS, Board |
| Plans | `plans/` | Design-доки milestones до реализации (напр. [[plans/M3]]) |
| ADR | `adr/` | Архитектурные решения (001–…) |
| Research | `research/` | Внешние источники, лицензии зависимостей |
| MOC | `MOC/` | Карты содержимого (индексы по доменам) |
| Agents | `agents/` | Конфиг skills / triage / domain |
| System | `_system/` | Соглашения мозга |
| Templates | `_templates/` | Шаблоны новых заметок |
| Obsidian | `.obsidian/` | Минимальный vault-конфиг (core only) |
| Attachments | `attachments/` | Вложения (пусто по умолчанию) |

## Типы заметок (`type` во frontmatter)

| type | Примеры |
|---|---|
| `hub` | Home, PROJECT, CURRENT_TASK, ROADMAP, DECISIONS, TODO |
| `spec` | ARCHITECTURE, API, DATABASE, SECURITY, CLIENT_ARCHITECTURE, DEPLOYMENT, OPEN_SOURCE |
| `plan` | `plans/M3.md` (и последующие milestone designs) |
| `adr` | `adr/00N-*.md` |
| `research` | `research/YYYY-MM-DD-*.md` |
| `moc` | `MOC/*.md` |
| `system` | `_system/BRAIN`, INDEX |
| `project-status` | STATUS (карточка для экосистемного дашборда) |

Kanban Board (`FocusVPN Board`) может использовать frontmatter плагина Kanban вместо полного набора полей — исключение.

## Frontmatter (минимум)

```yaml
---
type: spec
tags: [architecture]
status: active
updated: YYYY-MM-DD
---
```

## Правила связей

1. Внутри vault предпочитать `[[wikilinks]]`; markdown-ссылки `[text](path.md)` сохранять для читателей вне Obsidian.
2. У каждой новой заметки — frontmatter + хотя бы одна связь (Related / MOC / INDEX).
3. Не дублировать факты: ссылаться на канонический doc (например JWT → [[SECURITY]] / [[006-auth-session]]).
4. Orphan notes запрещены: после создания обновить [[INDEX]] и релевантный MOC.

## Когда обновлять что

| Событие | Обновить |
|---|---|
| Существенная работа / смена фокуса | [[CURRENT_TASK]], при смене фазы — [[Home]] + [[STATUS]] frontmatter |
| Design milestone (до кода) | `plans/*.md` + [[MOC/Execution]] + [[INDEX]] |
| Архитектурное решение | ADR из `_templates/adr`, строка в [[DECISIONS]], [[MOC/Decisions]], [[INDEX]] |
| Краткое решение без ADR | строка в [[DECISIONS]] (шаблон `_templates/decision-log`) |
| Внешний research / лицензии | заметка из `_templates/research`, [[MOC/Research]], [[INDEX]], при необходимости [[OPEN_SOURCE]] |
| Новый риск / долг | [[TODO]] |
| User-visible задача | карточка на [[FocusVPN Board]] при необходимости |
| Новый doc любого типа | [[INDEX]] + MOC домена |

## Шаблоны

- `_templates/research.md`
- `_templates/adr.md`
- `_templates/decision-log.md`

## Связано

- [[Home]] · [[INDEX]] · [[PROJECT]] · [[plans/M3]]
