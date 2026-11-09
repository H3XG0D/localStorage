// Package migrations embeds the versioned SQL migration files so the server and
// the migrate command can apply them without a separate migrate CLI binary.
package migrations

import "embed"

// FS holds the golang-migrate SQL files (NNNNNN_name.up.sql / .down.sql).
//
//go:embed *.sql
var FS embed.FS
