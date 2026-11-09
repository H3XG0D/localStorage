// Package storage provides Windows session persistence (DPAPI on Windows, file 0600 else).
package storage

import (
	"fmt"
	"os"
	"path/filepath"

	corestore "focusvpn.example/focusvpn/clients/appcore/storage"
)

const blobPrefix = "FocusVPN1\n"

// Store wraps FileStore and protects values with DPAPI on Windows.
type Store struct {
	inner *corestore.FileStore
}

// New opens (or creates) the Windows data directory.
// Default: %LOCALAPPDATA%/FocusVPN on Windows, ~/.config/focusvpn-windows elsewhere.
func New(dir string) (*Store, error) {
	if dir == "" {
		var err error
		dir, err = defaultDir()
		if err != nil {
			return nil, err
		}
	}
	inner, err := corestore.NewFileStore(dir)
	if err != nil {
		return nil, err
	}
	return &Store{inner: inner}, nil
}

func defaultDir() (string, error) {
	if d := os.Getenv("LOCALAPPDATA"); d != "" {
		return filepath.Join(d, "FocusVPN"), nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".config", "focusvpn-windows"), nil
}

// Get reads and unprotects a secret.
func (s *Store) Get(key string) ([]byte, error) {
	b, err := s.inner.Get(key)
	if err != nil {
		return nil, err
	}
	return unprotect(b)
}

// Set protects and writes a secret.
func (s *Store) Set(key string, value []byte) error {
	enc, err := protect(value)
	if err != nil {
		return err
	}
	return s.inner.Set(key, enc)
}

// Delete removes a secret.
func (s *Store) Delete(key string) error {
	return s.inner.Delete(key)
}

// Dir returns the on-disk directory.
func (s *Store) Dir() string { return s.inner.Dir() }

var _ corestore.SecureStorage = (*Store)(nil)

// Ensure protect round-trip prefix is documented for debugging.
func formatProtectError(op string, err error) error {
	return fmt.Errorf("windows/storage: %s: %w", op, err)
}
