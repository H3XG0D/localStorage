package engine

import (
	"context"
	"testing"

	"focusvpn.example/focusvpn/clients/shared/xray"
)

func TestXrayEngineDryRun(t *testing.T) {
	c, err := xray.SyntheticForDryRun("203.0.113.10:443", "33333333-3333-3333-3333-333333333333")
	if err != nil {
		t.Fatal(err)
	}
	e := NewXray(true)
	if err := e.Prepare(context.Background()); err != nil {
		t.Fatal(err)
	}
	cfg := AssembledConfig{Xray: &c, ConfDir: t.TempDir()}
	if err := e.Start(context.Background(), cfg); err != nil {
		t.Fatal(err)
	}
	if e.State() != StateConnected {
		t.Fatalf("state=%s", e.State())
	}
	if err := e.Stop(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func TestNewNamedXray(t *testing.T) {
	e := NewNamed("xray", true)
	if _, ok := e.(*XrayEngine); !ok {
		t.Fatalf("%T", e)
	}
	e2 := NewNamed("reality", true)
	if _, ok := e2.(*XrayEngine); !ok {
		t.Fatalf("%T", e2)
	}
}
