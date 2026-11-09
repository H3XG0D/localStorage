---
type: system
tags: [agents, system]
status: active
updated: 2026-08-10
---

# Issue tracker: Local Markdown (+ brain board)

Agent skills (`to-spec`, `to-tickets`, `wayfinder`, `triage`) use **local markdown** under `.scratch/`. There is no GitHub/GitLab remote yet.

Human-visible FocusVPN work stays on the Obsidian board: [[FocusVPN Board]]. Risks/debt: [[TODO]]. Current focus: [[CURRENT_TASK]].

## Conventions (agent scratch)

- One feature per directory: `.scratch/<feature-slug>/`
- Spec: `.scratch/<feature-slug>/spec.md`
- Implementation tickets: `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state: a `Status:` line near the top (see [[agents/triage-labels|triage-labels]])
- Comments append under `## Comments`

## When a skill says "publish to the issue tracker"

1. Create the file under `.scratch/<feature-slug>/` (create dirs as needed).
2. If the work is user-visible / milestone-scoped, also add a card on [[FocusVPN Board]] (`- [ ] … 📅 YYYY-MM-DD #focusvpn`) and, when focus changes, update [[CURRENT_TASK]].

## When a skill says "fetch the relevant ticket"

Read the path the user passed (usually under `.scratch/`). Board cards are not a substitute for the scratch ticket file.

## Wayfinding (`/wayfinder`)

- **Map**: `.scratch/<effort>/map.md`
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md` with `Type:` (`research`/`prototype`/`grilling`/`task`) and `Status:` (`claimed`/`resolved`)
- **Blocking**: `Blocked by: NN, NN` near the top
- **Frontier / claim / resolve**: as in mattpocock local-markdown conventions

## Related

- [[Home]] · [[CURRENT_TASK]] · [[FocusVPN Board]] · [[TODO]] · [[_system/BRAIN]]
