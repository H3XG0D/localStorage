// Package migrate applies the embedded golang-migrate migrations against
// PostgreSQL. It is used by cmd/migrate and by integration tests. Migrations are
// forward-only and versioned; Up/Down are idempotent through the migrate tool.
package migrate

import (
	"errors"
	"fmt"
	"strings"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/pgx/v5"
	"github.com/golang-migrate/migrate/v4/source/iofs"

	"focusvpn.example/focusvpn/backend/migrations"
)

// pgxURL converts a postgres:// URL to the pgx/v5 driver scheme (pgx5://) that
// golang-migrate expects, leaving already-correct URLs untouched.
func pgxURL(dbURL string) string {
	switch {
	case strings.HasPrefix(dbURL, "postgres://"):
		return "pgx5://" + strings.TrimPrefix(dbURL, "postgres://")
	case strings.HasPrefix(dbURL, "postgresql://"):
		return "pgx5://" + strings.TrimPrefix(dbURL, "postgresql://")
	default:
		return dbURL
	}
}

func newMigrator(dbURL string) (*migrate.Migrate, error) {
	src, err := iofs.New(migrations.FS, ".")
	if err != nil {
		return nil, fmt.Errorf("load embedded migrations: %w", err)
	}
	m, err := migrate.NewWithSourceInstance("iofs", src, pgxURL(dbURL))
	if err != nil {
		return nil, fmt.Errorf("init migrator: %w", err)
	}
	return m, nil
}

// Up applies all pending migrations. No pending change is not an error.
func Up(dbURL string) error {
	m, err := newMigrator(dbURL)
	if err != nil {
		return err
	}
	defer m.Close()
	if err := m.Up(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return fmt.Errorf("migrate up: %w", err)
	}
	return nil
}

// Down rolls back all migrations. No change is not an error.
func Down(dbURL string) error {
	m, err := newMigrator(dbURL)
	if err != nil {
		return err
	}
	defer m.Close()
	if err := m.Down(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return fmt.Errorf("migrate down: %w", err)
	}
	return nil
}

// Version returns the current migration version and dirty flag.
func Version(dbURL string) (uint, bool, error) {
	m, err := newMigrator(dbURL)
	if err != nil {
		return 0, false, err
	}
	defer m.Close()
	v, dirty, err := m.Version()
	if err != nil && !errors.Is(err, migrate.ErrNilVersion) {
		return 0, false, err
	}
	return v, dirty, nil
}
