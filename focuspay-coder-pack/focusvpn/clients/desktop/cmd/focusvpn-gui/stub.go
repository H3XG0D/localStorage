//go:build !wails

// Stub so `go build ./clients/desktop/cmd/focusvpn-gui` documents the real GUI build.
package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Fprintln(os.Stderr, `focusvpn-gui: build with WebKit + GTK:

  go build -tags wails -o bin/focusvpn-gui ./clients/desktop/cmd/focusvpn-gui

Requires: libgtk-3-dev libwebkit2gtk-4.1-dev (Linux).
UI: clients/desktop/frontend/ (same screens as Android). Tunnel: xray subprocess.
Headless bindings smoke: make smoke-desktop`)
	os.Exit(0)
}
