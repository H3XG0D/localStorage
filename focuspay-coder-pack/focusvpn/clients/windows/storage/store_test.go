package storage

import (
	"os"
	"path/filepath"
	"testing"
)

func TestProtectRoundTrip(t *testing.T) {
	dir := t.TempDir()
	s, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	plain := []byte("session-secret-42")
	if err := s.Set("tok", plain); err != nil {
		t.Fatal(err)
	}
	got, err := s.Get("tok")
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(plain) {
		t.Fatalf("got %q", got)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "tok"))
	if err != nil {
		t.Fatal(err)
	}
	if len(raw) < len(blobPrefix) || string(raw[:len(blobPrefix)]) != blobPrefix {
		t.Fatalf("missing envelope prefix in %q", raw)
	}
}
