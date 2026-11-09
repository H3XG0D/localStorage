package engine

import (
	"context"
	"sync"

	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

// AWGEngine drives AmneziaWG through awg-quick (GPL tools as subprocess only).
type AWGEngine struct {
	mu       sync.Mutex
	state    State
	confPath string
	dryRun   bool
}

// NewAWG constructs an engine. dryRun skips awg-quick (CI / no CAP_NET_ADMIN).
func NewAWG(dryRun bool) *AWGEngine {
	return &AWGEngine{state: StateDisconnected, dryRun: dryRun}
}

// Prepare checks that awg tools exist (unless dry-run).
func (e *AWGEngine) Prepare(_ context.Context) error {
	if e.dryRun {
		return nil
	}
	if !tunnel.Available() {
		return errAWGMissing
	}
	return nil
}

// Start brings the tunnel up.
func (e *AWGEngine) Start(ctx context.Context, cfg AssembledConfig) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.state = StateConnecting
	e.confPath = cfg.ConfPath
	if e.dryRun {
		e.state = StateConnected
		return nil
	}
	if !tunnel.Available() {
		e.state = StateError
		return errAWGMissing
	}
	if err := tunnel.Up(ctx, cfg.ConfPath); err != nil {
		e.state = StateError
		return err
	}
	e.state = StateConnected
	return nil
}

// Stop tears the tunnel down.
func (e *AWGEngine) Stop(ctx context.Context) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.confPath != "" && !e.dryRun && tunnel.Available() {
		_ = tunnel.Down(ctx, e.confPath)
	}
	e.state = StateDisconnected
	return nil
}

// State returns the current connection state.
func (e *AWGEngine) State() State {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.state
}

// Stats is a stub (no awg show parse required for DoD).
func (e *AWGEngine) Stats() (Stats, error) {
	return Stats{}, nil
}

type missingErr string

func (e missingErr) Error() string { return string(e) }

const errAWGMissing missingErr = "engine: awg/awg-quick not on PATH (install AmneziaWG tools or use dry-run)"

var _ VPNEngine = (*AWGEngine)(nil)
