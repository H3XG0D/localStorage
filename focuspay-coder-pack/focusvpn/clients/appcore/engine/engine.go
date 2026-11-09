// Package engine defines the VPNEngine abstraction (CLIENT_ARCHITECTURE §2).
package engine

import (
	"context"
	"time"

	"focusvpn.example/focusvpn/clients/shared/tunnel"
	xraycfg "focusvpn.example/focusvpn/clients/shared/xray"
)

// State is the connection lifecycle state.
type State string

const (
	StateDisconnected State = "disconnected"
	StateConnecting   State = "connecting"
	StateConnected    State = "connected"
	StateError        State = "error"
)

// Stats are lightweight tunnel counters.
type Stats struct {
	RxBytes     int64
	TxBytes     int64
	HandshakeAt *time.Time
}

// AssembledConfig is a ready-to-start tunnel config (private key / UUID already local).
type AssembledConfig struct {
	Tunnel tunnel.Config
	// ConfPath is set after the engine writes the .conf / .json (or dry-run path).
	ConfPath string
	// ConfDir is where engines may write generated files (Xray JSON).
	ConfDir string
	// Xray is set for VLESS+REALITY (nil for WG/AmneziaWG).
	Xray *xraycfg.ClientConfig
}

// VPNEngine is implemented per platform (Linux awg-quick, Android VpnService, …).
type VPNEngine interface {
	Prepare(ctx context.Context) error
	Start(ctx context.Context, cfg AssembledConfig) error
	Stop(ctx context.Context) error
	State() State
	Stats() (Stats, error)
}
