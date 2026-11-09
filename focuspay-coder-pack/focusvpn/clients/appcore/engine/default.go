package engine

import (
	"os"
	"strings"
)

// NewDefault selects the product VPN engine.
//
//	default / amneziawg / awg-go  → embedded amneziawg-go (MVP)
//	wireguard / wg               → embedded wireguard-go
//	xray / reality / vless       → Xray-core subprocess (JSON only; MPL binary not linked)
//	awg / awg-quick / subprocess → GPL awg-quick subprocess (ops only)
func NewDefault(dryRun bool) VPNEngine {
	return NewNamed(os.Getenv("FOCUSVPN_ENGINE"), dryRun)
}

// NewNamed constructs an engine by name (empty → AmneziaWG go).
func NewNamed(name string, dryRun bool) VPNEngine {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "wireguard", "wg":
		return NewWG(dryRun)
	case "xray", "reality", "vless":
		return NewXray(dryRun)
	case "awg", "awg-quick", "subprocess":
		return NewAWG(dryRun)
	default:
		return NewGo(dryRun)
	}
}
