// Command focusvpn-gtk is a Phase 3 M1 GTK skeleton.
//
// Build with GTK (optional, not required for CI):
//
//	go build -tags gtk ./clients/linux/cmd/focusvpn-gtk
//
// Default build (no GTK deps) is a stub that prints wiring instructions and
// exits 0 — keeps `go build ./...` green without libgtk.
package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Fprint(os.Stdout, `focusvpn-gtk: Phase 3 M1 skeleton (stub build)

This binary is a documented placeholder so CI/dev can compile without GTK.

To enable a real GTK window (P3-M2):
  1. Install libgtk-3-dev (or gtk4) and gotk3 bindings
  2. Rebuild with: go build -tags gtk -o bin/focusvpn-gtk ./clients/linux/cmd/focusvpn-gtk
  3. Wire login + Connect buttons to clients/appcore/client.App

Product CLI (ready now):
  go run ./clients/linux/cmd/focusvpn --help
`)
}
