# FocusVPN — agent / contributor context

Commercial VPN product (**FocusVPN**). Repo directory `focusvpn`.

## Project Brain (Obsidian)

FocusVPN docs live in [`docs/`](docs/) and are part of the **ecosystem brain**: Obsidian vault `~/Documents/brain` (symlink `Projects/FocusVPN` → this `docs/`). Open with `./scripts/open-brain.sh`. The brain also tracks FocusPay (`tg_bot_btc`), team tasks with due dates, and cross-project plans in `brain/Ecosystem/` (e.g. unified users DB + VPN balance top-up from the bot — future task).

Schema: [`docs/_system/BRAIN.md`](docs/_system/BRAIN.md). Entry: [`docs/Home.md`](docs/Home.md). Catalog: [`docs/INDEX.md`](docs/INDEX.md). Kanban: [`docs/FocusVPN Board.md`](docs/FocusVPN%20Board.md) (Tasks format: `- [ ] task 📅 YYYY-MM-DD [[Team/Имя]] #focusvpn`). Ecosystem status card: [`docs/STATUS.md`](docs/STATUS.md) — keep its frontmatter (`status`, `milestone`) current.

You are the librarian of this brain. Keep it linked and current; do not leave orphan notes. Obsidian is installed as Flatpak `md.obsidian.Obsidian`; vault UI config lives in `brain/.obsidian/` (Home dashboard on open, Dataview/Tasks/Kanban plugins, local config `docs/.obsidian/` kept for standalone use).

**Automatic update:** After substantial work that creates meaningful knowledge, update the Project Brain even if the user did not say “save to Obsidian” (or equivalent). The Always-record table below is mandatory without an explicit save request.

Milestone / design plans live under [`docs/plans/`](docs/plans/) (type `plan`). Session chat logs are **out of scope** — there is no `docs/sessions/` zone; durable knowledge goes into CURRENT_TASK / DECISIONS / ADR / research / TODO / plans instead.

Milestone status → keep [`docs/STATUS.md`](docs/STATUS.md) frontmatter (`status`, `milestone`) current. User-visible tasks → cards on [`docs/FocusVPN Board.md`](docs/FocusVPN%20Board.md) when appropriate.

### Before any work

1. Read [`docs/Home.md`](docs/Home.md) (status + navigation).
2. Read [`docs/CURRENT_TASK.md`](docs/CURRENT_TASK.md) (what is in progress).
3. Read [`docs/ROADMAP.md`](docs/ROADMAP.md) (phases and DoD).
4. Read [`docs/PROJECT.md`](docs/PROJECT.md) when you need goals/rules.
5. For architecture changes: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), then ADRs in [`docs/adr/`](docs/adr/).
6. Log decisions in [`docs/DECISIONS.md`](docs/DECISIONS.md); open issues in [`docs/TODO.md`](docs/TODO.md).

### Always record (after substantial work — mandatory)

| Trigger | Write to |
|---|---|
| Focus / milestone change | [`CURRENT_TASK.md`](docs/CURRENT_TASK.md); if phase/milestone status changed → status block in [`Home.md`](docs/Home.md) + [`STATUS.md`](docs/STATUS.md) frontmatter |
| Milestone design (pre-implementation) | [`docs/plans/`](docs/plans/) note (e.g. `M3.md`) + [`MOC/Execution`](docs/MOC/Execution.md) + [`INDEX`](docs/INDEX.md) |
| Any decision | Row in [`DECISIONS.md`](docs/DECISIONS.md) ([checklist](docs/_templates/decision-log.md)) |
| Architectural decision | ADR from [`_templates/adr.md`](docs/_templates/adr.md) → `docs/adr/00N-slug.md` + [`MOC/Decisions`](docs/MOC/Decisions.md) + [`INDEX`](docs/INDEX.md) |
| External research / licenses | Note from [`_templates/research.md`](docs/_templates/research.md) + [`MOC/Research`](docs/MOC/Research.md) + [`research/README`](docs/research/README.md) + [`INDEX`](docs/INDEX.md); licenses also [`OPEN_SOURCE.md`](docs/OPEN_SOURCE.md) |
| Risk / debt | [`TODO.md`](docs/TODO.md) |
| Any new note | Frontmatter (`type`, `tags`, `status`, `updated`) + ≥1 `[[wikilink]]` + [`INDEX`](docs/INDEX.md) + relevant [`MOC/`](docs/MOC/) |

Do not end a session with undocumented decisions, orphan notes, or a stale `CURRENT_TASK`.

### Linking rules

- Prefer Obsidian `[[wikilinks]]` inside the vault; keep existing markdown links for non-Obsidian readers when useful.
- Do not duplicate canonical facts — link to the source doc (e.g. JWT → SECURITY / ADR-006).
- No orphan notes. Follow [`docs/_system/BRAIN.md`](docs/_system/BRAIN.md).

## Phase gates

- **Phase 1** (architecture docs) is complete.
- **Phase 2** (Go control plane + node-agent + CLI harness) is **in progress**. Milestones 1–2 are done; next is Milestone 3 (see CURRENT_TASK / ROADMAP).
- Do **not** implement a new Phase 2 milestone (or start Phase 3+ UI clients) unless the user explicitly requests or approves that milestone.
- Phase 2 scope = Go CP + node-agent + **CLI harness** (not full UI clients). See ROADMAP §2–§3.
- External research notes go in [`docs/research/`](docs/research/); licenses live in [`docs/OPEN_SOURCE.md`](docs/OPEN_SOURCE.md).

## Non-negotiables

- No GPL/AGPL in the product binary; node GPL tools only as separate processes.
- Client private keys never leave the device; CP signs ConfigParts (Ed25519).
- Access JWT = EdDSA (Ed25519); refresh rotation + reuse detection.
- MVP AmneziaWG uses Jc/Jmin/Jmax, unique per node; pin `amneziawg-go` `v0.2.19` until upgraded by decision.

## Agent skills

Installed under `.agents/skills/` (Cursor: `.cursor/skills` → symlink). Prefer invoking explicitly (`/grill-with-docs`, `/tdd`, …).

Suggested chain for a new feature: **`/grill-with-docs` → `/to-spec` → `/to-tickets` → `/tdd`**. Bugs: `/diagnose`. Large ambiguous efforts: `/wayfinder`.

### Issue tracker

Local markdown under `.scratch/` (+ cards on `docs/FocusVPN Board.md` when user-visible). See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

Defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context: root [`CONTEXT.md`](CONTEXT.md) (glossary) + [`docs/adr/`](docs/adr/) (FocusVPN ADR template/numbering) + Project Brain. See [`docs/agents/domain.md`](docs/agents/domain.md).
