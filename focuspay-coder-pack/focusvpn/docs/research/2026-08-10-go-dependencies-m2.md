---
type: research
tags: [research, go, licenses, database]
status: active
updated: 2026-08-10
---

# Go dependencies — Phase 2 Milestone 2 (persistence + migrations)

Date: 2026-08-10

M2 introduces PostgreSQL persistence and versioned migrations. License review of
the newly added modules (non-negotiable: no GPL/AGPL in the product binary;
MIT/Apache/BSD/MPL are acceptable):

| Module | Version | Purpose | License |
|---|---|---|---|
| `github.com/jackc/pgx/v5` | v5.7.6 | PostgreSQL driver + pool (no ORM) | MIT |
| `github.com/jackc/puddle/v2` | v2.2.2 | pgxpool connection pool (transitive) | MIT |
| `github.com/jackc/pgpassfile` | v1.0.0 | pgx transitive | MIT |
| `github.com/jackc/pgservicefile` | (pseudo) | pgx transitive | MIT |
| `github.com/jackc/pgerrcode` | (pseudo) | SQLSTATE constants for constraint mapping | MIT |
| `github.com/golang-migrate/migrate/v4` | v4.19.0 | versioned SQL migrations (iofs + pgx/v5) | MIT |
| `github.com/hashicorp/go-multierror` | v1.1.1 | migrate transitive | MPL-2.0 |
| `github.com/hashicorp/errwrap` | v1.1.0 | migrate transitive | MPL-2.0 |
| `golang.org/x/text` | v0.40.0 | transitive | BSD-3-Clause |
| `golang.org/x/sync` | v0.22.0 | transitive | BSD-3-Clause |

All permissive. MPL-2.0 (file-level copyleft) is acceptable for linking into the
product binary; only GPL/AGPL are excluded. See docs/OPEN_SOURCE.md.

## Tooling decision: pgx directly, sqlc deferred

ARCHITECTURE.md §4.3 / DATABASE.md name "pgx + sqlc (no ORM)". For the MVP we use
**pgx with hand-written, reviewable SQL** and defer the `sqlc` codegen toolchain.
This preserves the architectural decisions that matter — PostgreSQL as the single
source of truth, **no ORM**, pgx as the driver — and only postpones a codegen
convenience. Recorded in DECISIONS.md; revisit if query volume makes codegen
worthwhile.

## Migration runner without the migrate CLI

The environment has no `migrate` binary. We embed the SQL files
(`backend/migrations/*.sql` via `embed.FS`) and drive them through the
golang-migrate **library** (`source/iofs` + `database/pgx/v5`), exposed as
`backend/cmd/migrate`. This keeps the setup reproducible from a clean checkout
with only the Go toolchain — no extra system tooling.

## Dev stack (Podman)

`infra/compose/docker-compose.yml` (compose spec, fully-qualified
`docker.io/library/...` images) runs PostgreSQL 16 + Redis 7. Driven by
`podman compose`; the rootless API socket must be active
(`systemctl --user enable --now podman.socket`) because the compose provider
speaks the Docker API. Verified: `up -d`, migrate up/down/up, and a no-change up
against PostgreSQL 16.

## Связано

- [[OPEN_SOURCE]] · [[DATABASE]] · [[DECISIONS]] · [[MOC/Research]]
