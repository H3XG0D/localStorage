package engine

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"testing"

	coreengine "focusvpn.example/focusvpn/clients/appcore/engine"
	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

func TestWintunDryRunGoBridge(t *testing.T) {
	priv := make([]byte, 32)
	pub := make([]byte, 32)
	_, _ = rand.Read(priv)
	_, _ = rand.Read(pub)
	priv[0] &= 248
	priv[31] &= 127
	priv[31] |= 64

	cfg := coreengine.AssembledConfig{
		Tunnel: tunnel.Config{
			PrivateKey: base64.StdEncoding.EncodeToString(priv),
			PeerPubKey: base64.StdEncoding.EncodeToString(pub),
			Address:    "10.200.0.2/32",
			Endpoint:   "203.0.113.10:51820",
			Jc:         4,
			Jmin:       40,
			Jmax:       70,
			S1:         15,
			S2:         20,
			S3:         10,
			S4:         5,
			H1:         "100-110",
			H2:         "200-210",
			H3:         "300-310",
			H4:         "400-410",
			Interface:  "focusvpn0",
			AllowedIPs: []string{"0.0.0.0/0"},
			MTU:        1420,
		},
	}
	e := NewWintun(true)
	if err := e.Prepare(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e.LastProbe != "dry-run" {
		t.Fatalf("probe=%q", e.LastProbe)
	}
	if err := e.Start(context.Background(), cfg); err != nil {
		t.Fatal(err)
	}
	if e.State() != coreengine.StateConnected {
		t.Fatalf("state=%s", e.State())
	}
	if err := e.Stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e.State() != coreengine.StateDisconnected {
		t.Fatalf("state=%s", e.State())
	}
}

func TestNewDefaultIsWintun(t *testing.T) {
	t.Setenv("FOCUSVPN_ENGINE", "")
	e := New(true)
	if _, ok := e.(*WintunEngine); !ok {
		t.Fatalf("default type %T", e)
	}
	if Name() != "amneziawg-go" {
		t.Fatalf("name=%s", Name())
	}
}
