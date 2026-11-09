// Package engine implements the Windows AmneziaWG path (P3-M5b bridge).
//
// Dataplane: embedded amneziawg-go (MIT, pin v0.2.19) over prebuilt wintun.dll
// (WireGuard LLC Prebuilt Binaries License). Prepare probes the DLL with
// LoadLibraryEx on Windows; Start/Stop delegate to AppCore GoEngine (CreateTUN).
// Never statically link GPL wintun sources into the product binary.
package engine

import (
	"context"
	"os"
	"strings"
	"sync"

	coreengine "focusvpn.example/focusvpn/clients/appcore/engine"
)

// WintunEngine probes wintun.dll then drives AmneziaWG via amneziawg-go.
type WintunEngine struct {
	mu     sync.Mutex
	dryRun bool
	// DLLName is the side-by-side library name (default wintun.dll).
	DLLName string
	// LastProbe records the result of the last LoadLibraryEx attempt (Windows only).
	LastProbe string
	goEng     *coreengine.GoEngine
}

// New selects the Windows product engine (default: amneziawg-go + wintun probe).
// Honors FOCUSVPN_ENGINE like AppCore NewDefault for wireguard/xray/awg overrides.
func New(dryRun bool) coreengine.VPNEngine {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FOCUSVPN_ENGINE"))) {
	case "wireguard", "wg", "xray", "reality", "vless", "awg", "awg-quick", "subprocess":
		return coreengine.NewNamed(os.Getenv("FOCUSVPN_ENGINE"), dryRun)
	default:
		return NewWintun(dryRun)
	}
}

// NewWintun constructs the Windows AmneziaWG engine (go + wintun).
func NewWintun(dryRun bool) *WintunEngine {
	return &WintunEngine{
		dryRun:  dryRun,
		DLLName: "wintun.dll",
		goEng:   coreengine.NewGo(dryRun),
	}
}

// Name is the engine label for status/CLI JSON.
func Name() string {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FOCUSVPN_ENGINE"))) {
	case "wireguard", "wg":
		return "wireguard-go"
	case "xray", "reality", "vless":
		return "xray"
	case "awg", "awg-quick", "subprocess":
		return "awg-quick"
	default:
		return "amneziawg-go"
	}
}

// Prepare probes wintun.dll on Windows when not dry-run; always OK in dry-run.
func (e *WintunEngine) Prepare(ctx context.Context) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.dryRun {
		e.LastProbe = "dry-run"
		return e.goEng.Prepare(ctx)
	}
	msg, err := probeWintun(e.DLLName)
	e.LastProbe = msg
	if err != nil {
		return err
	}
	return e.goEng.Prepare(ctx)
}

// Start applies ConfigParts via amneziawg-go (ChannelTUN in dry-run; CreateTUN+wintun otherwise).
func (e *WintunEngine) Start(ctx context.Context, cfg coreengine.AssembledConfig) error {
	if !e.dryRun {
		msg, err := probeWintun(e.DLLName)
		e.mu.Lock()
		e.LastProbe = msg
		e.mu.Unlock()
		if err != nil {
			return err
		}
	} else {
		e.mu.Lock()
		e.LastProbe = "dry-run"
		e.mu.Unlock()
	}
	return e.goEng.Start(ctx, cfg)
}

// Stop closes the userspace AmneziaWG device.
func (e *WintunEngine) Stop(ctx context.Context) error {
	return e.goEng.Stop(ctx)
}

// State returns the lifecycle state from the go engine.
func (e *WintunEngine) State() coreengine.State {
	return e.goEng.State()
}

// Stats delegates to the go engine.
func (e *WintunEngine) Stats() (coreengine.Stats, error) {
	return e.goEng.Stats()
}

var _ coreengine.VPNEngine = (*WintunEngine)(nil)
