package storage

import (
	"fmt"
	"os"
	"path/filepath"
)

// FileStore stores each key as a separate file with mode 0600 under a config dir
// (default ~/.config/focusvpn). libsecret integration is deferred.
type FileStore struct {
	dir string
}

// NewFileStore creates (if needed) the config directory.
func NewFileStore(dir string) (*FileStore, error) {
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		dir = filepath.Join(home, ".config", "focusvpn")
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	return &FileStore{dir: dir}, nil
}

func (f *FileStore) path(key string) string {
	return filepath.Join(f.dir, key)
}

// Get reads a secret.
func (f *FileStore) Get(key string) ([]byte, error) {
	b, err := os.ReadFile(f.path(key))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return b, nil
}

// Set writes a secret with 0600 permissions.
func (f *FileStore) Set(key string, value []byte) error {
	return os.WriteFile(f.path(key), value, 0600)
}

// Delete removes a secret file.
func (f *FileStore) Delete(key string) error {
	err := os.Remove(f.path(key))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("storage: delete %s: %w", key, err)
	}
	return nil
}

// Dir returns the storage directory.
func (f *FileStore) Dir() string { return f.dir }

var _ SecureStorage = (*FileStore)(nil)
