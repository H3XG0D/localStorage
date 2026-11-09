package engine

import "context"

// DryRun is a no-op VPNEngine for tests and --dry-run paths that only need conf files.
type DryRun struct {
	state State
}

// NewDryRun returns a disconnected dry-run engine.
func NewDryRun() *DryRun { return &DryRun{state: StateDisconnected} }

func (d *DryRun) Prepare(context.Context) error { return nil }

func (d *DryRun) Start(_ context.Context, _ AssembledConfig) error {
	d.state = StateConnected
	return nil
}

func (d *DryRun) Stop(context.Context) error {
	d.state = StateDisconnected
	return nil
}

func (d *DryRun) State() State { return d.state }

func (d *DryRun) Stats() (Stats, error) { return Stats{}, nil }

var _ VPNEngine = (*DryRun)(nil)
