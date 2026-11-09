---
type: system
tags: [agents, system]
status: active
updated: 2026-08-10
---

# Domain Docs (FocusVPN)

How engineering skills consume domain documentation in this repo. **Single-context** layout, wired into the existing Project Brain — do not invent a parallel docs tree.

## Before exploring, read these

1. [[Home]] · [[CURRENT_TASK]] · [[ROADMAP]] (always, per `CLAUDE.md`)
2. **`CONTEXT.md`** at the repo root — ubiquitous language / glossary only
3. Specs that touch the area: [[ARCHITECTURE]], [[API]], [[DATABASE]], [[SECURITY]], …
4. **`docs/adr/`** — ADRs for the area (existing: `001`…`006`; next free number is **007**)
5. Decision log: [[DECISIONS]]

If `CONTEXT.md` is missing a term, proceed; `/grill-with-docs` / `/domain-modeling` fill the glossary lazily. Do **not** treat absence of a term as a blocker.

## File structure (this repo)

```
/
├── CONTEXT.md                 ← glossary only (no implementation)
├── CLAUDE.md                  ← agent protocol + brain rules
├── docs/
│   ├── Home.md, CURRENT_TASK.md, DECISIONS.md, …
│   ├── adr/00N-slug.md        ← FocusVPN ADR numbering (3 digits)
│   ├── _templates/adr.md      ← required ADR template
│   └── agents/                ← this folder (skill config)
├── backend/
├── clients/
└── .scratch/                  ← agent specs / tickets (see issue-tracker.md)
```

## Glossary rules

When naming a domain concept (issue title, test name, refactor proposal), use the term as defined in `CONTEXT.md`. Do not drift to synonyms listed under `_Avoid_`.

`CONTEXT.md` stays free of implementation detail. Specs stay in `docs/*.md`; decisions stay in ADR / [[DECISIONS]].

## ADR rules (override skill defaults)

When creating an ADR:

1. Use template [`docs/_templates/adr.md`](../_templates/adr.md) — **not** the one-paragraph mattpocock default.
2. Filename: `docs/adr/00N-slug.md` (3-digit, zero-padded). Scan existing files; next after `006` is `007`.
3. Add Obsidian frontmatter (`type: adr`, `tags`, `status`, `updated`).
4. After write: row in [[DECISIONS]], link in [[MOC/Decisions]], entry in [[INDEX]]. No orphan notes ([[_system/BRAIN]]).

Offer an ADR only when hard-to-reverse **and** surprising without context **and** a real trade-off (same bar as `/domain-modeling`).

## Flag ADR / brain conflicts

If output contradicts an existing ADR or non-negotiable in `CLAUDE.md`, surface it explicitly — do not silently override.

## Related

- [[Home]] · [[DECISIONS]] · [[MOC/Decisions]] · [[_system/BRAIN]] · [[agents/issue-tracker]]
