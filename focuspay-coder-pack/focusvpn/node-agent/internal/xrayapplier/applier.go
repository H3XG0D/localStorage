// Package xrayapplier reconciles the Xray user table with the Control Plane
// desired set. Xray stays a separate process; this package only talks to its
// localhost API (MPL-2.0, not linked).
package xrayapplier

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/google/uuid"

	"focusvpn.example/focusvpn/node-agent/internal/poller"
)

// Tag is one VLESS inbound. Port is only needed to build a valid `xray api adu`
// document; the API call itself is keyed by Name.
type Tag struct {
	Name string
	Port int
}

// User is one VLESS client on an inbound.
type User struct {
	Email string
	UUID  string
}

// API is the Xray localhost API surface the applier needs.
type API interface {
	ListUsers(ctx context.Context, tag string) ([]User, error)
	AddUser(ctx context.Context, tag Tag, email, id string) error
	RemoveUser(ctx context.Context, tag, email string) error
	OnlineCount(ctx context.Context) (int, error)
	// Traffic returns cumulative counters since Xray start (not reset).
	Traffic(ctx context.Context) (downlink, uplink int64, err error)
}

// Applier diffs desired VLESS users onto every configured inbound.
type Applier struct {
	api  API
	tags []Tag

	mu   sync.Mutex
	last *poller.StateResponse
}

// New creates an Applier. tags is the set of VLESS inbounds (WS and XHTTP).
func New(api API, tags []Tag) *Applier {
	return &Applier{api: api, tags: tags}
}

// Apply adds missing users and removes CP-managed users that are no longer
// desired. Emails that are not UUIDs (manual test logins) are left in place.
// An allocation id is returned only when the user is present on every tag.
func (a *Applier) Apply(ctx context.Context, state poller.StateResponse) ([]string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.last = &state
	return a.apply(ctx, state)
}

// Resync re-applies the last desired state every interval, so users dropped
// by an Xray restart or a failed add come back without a CP state change.
func (a *Applier) Resync(ctx context.Context, interval time.Duration, onApplied func([]string)) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
		a.mu.Lock()
		if a.last == nil {
			a.mu.Unlock()
			continue
		}
		applied, err := a.apply(ctx, *a.last)
		a.mu.Unlock()
		if err != nil && ctx.Err() == nil {
			log.Printf("xray: resync: %v", err)
		}
		if len(applied) > 0 && onApplied != nil {
			onApplied(applied)
		}
	}
}

func (a *Applier) apply(ctx context.Context, state poller.StateResponse) ([]string, error) {
	desired := map[string]string{}
	for _, p := range state.Peers {
		if p.VLESSUUID != "" && p.AllocationID != "" {
			desired[p.AllocationID] = p.VLESSUUID
		}
	}

	okTags := map[string]int{}
	for _, tag := range a.tags {
		current, err := a.api.ListUsers(ctx, tag.Name)
		if err != nil {
			return nil, err
		}
		have := map[string]string{}
		for _, u := range current {
			have[u.Email] = u.UUID
		}
		for email, id := range desired {
			if have[email] == id {
				okTags[email]++
				continue
			}
			if have[email] != "" {
				if err := a.api.RemoveUser(ctx, tag.Name, email); err != nil {
					log.Printf("xray: replace %s on %s: remove: %v", email, tag.Name, err)
					continue
				}
			}
			if err := a.api.AddUser(ctx, tag, email, id); err != nil {
				log.Printf("xray: add %s on %s: %v", email, tag.Name, err)
				continue
			}
			okTags[email]++
		}
		for email := range have {
			if _, keep := desired[email]; keep || !managedEmail(email) {
				continue
			}
			if err := a.api.RemoveUser(ctx, tag.Name, email); err != nil {
				log.Printf("xray: remove %s on %s: %v", email, tag.Name, err)
			}
		}
	}

	var applied []string
	need := len(a.tags)
	for email := range desired {
		if okTags[email] == need {
			applied = append(applied, email)
		}
	}
	return applied, nil
}

// Sample reads live sessions and cumulative traffic counters. The telemetry
// sender turns them into deltas once the CP has accepted a heartbeat.
func (a *Applier) Sample(ctx context.Context) (online int, downlink, uplink int64, err error) {
	online, err = a.api.OnlineCount(ctx)
	if err != nil {
		return 0, 0, 0, err
	}
	downlink, uplink, err = a.api.Traffic(ctx)
	return online, downlink, uplink, err
}

// managedEmail reports whether the Xray email was assigned by the Control Plane
// (allocation id). Hand-added test users use a different email and stay.
func managedEmail(email string) bool {
	_, err := uuid.Parse(email)
	return err == nil
}
