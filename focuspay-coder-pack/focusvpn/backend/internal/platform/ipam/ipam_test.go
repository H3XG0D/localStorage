package ipam_test

import (
	"testing"

	"focusvpn.example/focusvpn/backend/internal/platform/ipam"
)

func TestNextHostSkipsReserved(t *testing.T) {
	ip, err := ipam.NextHost("10.200.0.0/24", nil)
	if err != nil {
		t.Fatal(err)
	}
	if ip != "10.200.0.2" {
		t.Fatalf("got %s want 10.200.0.2", ip)
	}
	ip, err = ipam.NextHost("10.200.0.0/24", []string{"10.200.0.2", "10.200.0.3"})
	if err != nil {
		t.Fatal(err)
	}
	if ip != "10.200.0.4" {
		t.Fatalf("got %s", ip)
	}
}
