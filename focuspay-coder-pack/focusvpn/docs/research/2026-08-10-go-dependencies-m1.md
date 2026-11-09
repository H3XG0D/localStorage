---
type: research
tags: [research, go, licenses]
status: active
updated: 2026-08-10
---

# Phase 2 Milestone 1 — dependency license check (2026-08-10)

New third-party Go dependencies introduced for the auth vertical slice, checked
against the FocusVPN license policy (only MIT/Apache/MPL/BSD in the product binary;
no GPL/AGPL — see OPEN_SOURCE.md §3).

| Module | Version | License | Role | Verdict |
|---|---|---|---|---|
| github.com/golang-jwt/jwt/v5 | v5.3.1 | MIT | EdDSA access-token sign/verify | OK (permissive) |
| golang.org/x/crypto | v0.54.0 | BSD-3-Clause | argon2id password hashing | OK (permissive) |
| golang.org/x/sys | v0.47.0 | BSD-3-Clause | indirect (via x/crypto) | OK (permissive) |

## Notes

- `golang.org/x/crypto@v0.54.0` requires Go >= 1.25; the toolchain / `go.mod`
  `go` directive was bumped to 1.25 accordingly.
- No GPL/AGPL pulled in. `go.sum` pins exact versions.
- UUID and opaque-token generation are implemented in-house
  (`backend/internal/platform/id`) to avoid an extra dependency.

## Relevance

These pins feed the future `THIRD_PARTY_LICENSES.md` / `NOTICE.md` (Phase 3 store
gate). Any bump must be re-checked here and in OPEN_SOURCE.md.

## Связано

- [[OPEN_SOURCE]] · [[DECISIONS]] · [[MOC/Research]] · [[CURRENT_TASK]]
