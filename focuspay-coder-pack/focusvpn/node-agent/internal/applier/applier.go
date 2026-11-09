// Package applier applies desired peer state to the AmneziaWG interface via
// subprocess `awg` and `awg-quick` (GPL tools — not linked, ADR-002 / ADR-004).
// License safety: awg/awg-quick are called as external processes; this binary
// does not link or include any GPL code.
package applier

import (
	"context"
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"
	"sync"

	"focusvpn.example/focusvpn/node-agent/internal/poller"
)

// AppliedPeer tracks applied allocations so we can diff on the next state update.
type AppliedPeer struct {
	AllocationID string
	PublicKey    string // base64
	AllowedIP    string
}

// Applier manages the AmneziaWG interface peer table.
type Applier struct {
	iface   string
	mu      sync.Mutex
	applied map[string]AppliedPeer // allocation_id -> peer
}

// New creates an Applier for the given interface.
func New(iface string) *Applier {
	return &Applier{
		iface:   iface,
		applied: make(map[string]AppliedPeer),
	}
}

// Apply diffs the desired state against the current applied set and calls `awg`
// to add new peers and remove stale ones.
// Returns the set of allocation IDs that were successfully applied (for telemetry).
func (a *Applier) Apply(ctx context.Context, state poller.StateResponse) ([]string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()

	desired := make(map[string]poller.PeerState, len(state.Peers))
	for _, p := range state.Peers {
		desired[p.AllocationID] = p
	}

	var applied []string
	// Add/update new peers.
	for id, p := range desired {
		pubB64 := base64.StdEncoding.EncodeToString(p.PublicKey)
		if ex, ok := a.applied[id]; ok && ex.PublicKey == pubB64 && ex.AllowedIP == p.AllowedIP {
			applied = append(applied, id)
			continue // already applied
		}
		if err := a.addPeer(ctx, pubB64, p.AllowedIP); err != nil {
			log.Printf("applier: add peer %s (alloc %s): %v", pubB64, id, err)
			continue
		}
		a.applied[id] = AppliedPeer{AllocationID: id, PublicKey: pubB64, AllowedIP: p.AllowedIP}
		applied = append(applied, id)
		log.Printf("applier: peer applied for alloc %s (%s)", id, p.AllowedIP)
	}

	// Remove stale peers not in desired state.
	for id, ex := range a.applied {
		if _, ok := desired[id]; !ok {
			if err := a.removePeer(ctx, ex.PublicKey); err != nil {
				log.Printf("applier: remove peer %s (alloc %s): %v", ex.PublicKey, id, err)
			} else {
				delete(a.applied, id)
				log.Printf("applier: peer removed for alloc %s", id)
			}
		}
	}
	return applied, nil
}

// addPeer calls: awg set <iface> peer <pubkey> allowed-ips <ip>
func (a *Applier) addPeer(ctx context.Context, pubKeyB64, allowedIP string) error {
	// awg set uses base64-encoded WireGuard keys directly.
	return runAWG(ctx, "set", a.iface, "peer", pubKeyB64, "allowed-ips", allowedIP)
}

// removePeer calls: awg set <iface> peer <pubkey> remove
func (a *Applier) removePeer(ctx context.Context, pubKeyB64 string) error {
	return runAWG(ctx, "set", a.iface, "peer", pubKeyB64, "remove")
}

func runAWG(ctx context.Context, args ...string) error {
	cmd := exec.CommandContext(ctx, "awg", args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("awg %s: %w", strings.Join(args, " "), err)
	}
	return nil
}
