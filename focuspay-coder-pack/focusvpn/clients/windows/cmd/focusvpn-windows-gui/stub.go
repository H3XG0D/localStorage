//go:build !wails

// Stub so `go build ./clients/windows/cmd/focusvpn-windows-gui` documents the GUI build.
package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Fprintln(os.Stderr, `focusvpn-windows-gui: same screens as Linux (clients/desktop/frontend)

  go build -tags wails -o bin/focusvpn-windows-gui ./clients/windows/cmd/focusvpn-windows-gui

Headless / CI: make smoke-windows
GUI tunnel: xray. Place wintun.dll next to the exe (Prebuilt Binaries License).
CLI smoke stays on amneziawg-go.`)
	os.Exit(0)
}
