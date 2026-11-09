---
type: system
tags: [template, decisions]
status: active
updated: 2026-08-10
---

# Template — строка в DECISIONS.md

Не отдельная заметка: вставить строку в таблицу дня в [[DECISIONS]], затем при необходимости ADR.

## Чеклист

1. Краткая суть решения (1 предложение).
2. Ссылка на канон: ADR / спека / ROADMAP.
3. Если архитектурное — ADR из `_templates/adr.md` → `adr/00N-slug.md`.
4. Обновить [[MOC/Decisions]] (если новый ADR) и [[INDEX]].
5. Риски → [[TODO]].

## Строка таблицы

```md
| Краткое имя | Суть в одном предложении | [[ADR-00N]] или [[SECURITY]] §N |
```

## Related

- [[DECISIONS]] · [[MOC/Decisions]] · [[_system/BRAIN]]
