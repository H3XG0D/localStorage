package storage_test

import (
	"testing"

	"focusvpn.example/focusvpn/clients/appcore/storage"
)

func TestMemoryRoundTrip(t *testing.T) {
	m := storage.NewMemory()
	if err := m.Set("k", []byte("v")); err != nil {
		t.Fatal(err)
	}
	got, err := m.Get("k")
	if err != nil || string(got) != "v" {
		t.Fatalf("got %q %v", got, err)
	}
	if err := m.Delete("k"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.Get("k"); err != storage.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}
