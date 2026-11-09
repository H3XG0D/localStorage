package engine

import (
	"context"
	"fmt"
	"sync"
)

// FailN fails Start the first n times, then behaves like DryRun.
// Used to exercise AppCore failover without a real dataplane.
type FailN struct {
	mu       sync.Mutex
	failLeft int
	starts   int
	state    State
}

// NewFailN returns an engine that fails Start n times.
func NewFailN(n int) *FailN {
	return &FailN{failLeft: n, state: StateDisconnected}
}

func (f *FailN) Prepare(context.Context) error { return nil }

func (f *FailN) Start(_ context.Context, _ AssembledConfig) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.starts++
	if f.failLeft > 0 {
		f.failLeft--
		f.state = StateError
		return fmt.Errorf("engine: simulated start failure (%d left)", f.failLeft)
	}
	f.state = StateConnected
	return nil
}

func (f *FailN) Stop(context.Context) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.state = StateDisconnected
	return nil
}

func (f *FailN) State() State {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.state
}

func (f *FailN) Stats() (Stats, error) { return Stats{}, nil }

// Starts reports how many Start calls were made.
func (f *FailN) Starts() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.starts
}

var _ VPNEngine = (*FailN)(nil)
