// Package connectivity implements client-side failover walk + exponential backoff
// (ARCHITECTURE §10.3, P4-M4).
package connectivity

import (
	"encoding/json"
	"math"
	"math/rand"
	"time"

	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

const (
	DefaultBase        = time.Second
	DefaultCap         = 30 * time.Second
	DefaultMaxPasses   = 2
	DefaultMaxAttempts = 10
)

// Plan walks candidates with backoff before asking CP for a fresh list.
type Plan struct {
	Candidates   []apitypes.CandidateEndpoint
	Attempt      int // 0-based global attempt counter
	Pass         int // completed full passes over Candidates
	MaxPasses    int
	MaxAttempts  int
	Base         time.Duration
	Cap          time.Duration
}

// NewPlan builds a failover plan from CP candidates.
func NewPlan(cands []apitypes.CandidateEndpoint) Plan {
	return Plan{
		Candidates:  append([]apitypes.CandidateEndpoint(nil), cands...),
		MaxPasses:   DefaultMaxPasses,
		MaxAttempts: DefaultMaxAttempts,
		Base:        DefaultBase,
		Cap:         DefaultCap,
	}
}

// AfterFailure seeds the plan so Next() advances past the candidate that already failed.
// If failedID is empty, treats Candidates[0] as attempted (CP ranks allocated first).
func (p *Plan) AfterFailure(failedEndpointID string) {
	if len(p.Candidates) == 0 {
		return
	}
	idx := 0
	if failedEndpointID != "" {
		for i, c := range p.Candidates {
			if c.Endpoint.ID == failedEndpointID {
				idx = i
				break
			}
		}
	}
	p.Attempt = idx + 1
	p.Pass = p.Attempt / len(p.Candidates)
}

// PreferredNode returns the node name for a candidate index (fallback: host).
func PreferredNode(c apitypes.CandidateEndpoint) string {
	if c.Node != "" {
		return c.Node
	}
	return c.Endpoint.Host
}

// Next returns the next candidate index and delay before trying it.
// exhausted=true means stop (user action required) or refresh CP list.
func (p *Plan) Next() (idx int, delay time.Duration, refreshCP, exhausted bool) {
	if len(p.Candidates) == 0 || p.Attempt >= p.MaxAttempts {
		return -1, 0, false, true
	}
	if p.Pass >= p.MaxPasses {
		return -1, 0, true, false
	}
	idx = p.Attempt % len(p.Candidates)
	delay = Backoff(p.Attempt, p.Base, p.Cap)
	p.Attempt++
	if p.Attempt%len(p.Candidates) == 0 {
		p.Pass++
	}
	return idx, delay, false, false
}

// Backoff is exponential with jitter: min(cap, base*2^n + rand[0,base]).
func Backoff(n int, base, cap time.Duration) time.Duration {
	if base <= 0 {
		base = DefaultBase
	}
	if cap <= 0 {
		cap = DefaultCap
	}
	if n < 0 {
		n = 0
	}
	exp := float64(base) * math.Pow(2, float64(n))
	if exp > float64(cap) {
		exp = float64(cap)
	}
	jitter := time.Duration(rand.Int63n(int64(base) + 1))
	d := time.Duration(exp) + jitter
	if d > cap {
		d = cap
	}
	return d
}

// SaveCandidates persists the failover list for offline reconnect.
func SaveCandidates(store storage.SecureStorage, cands []apitypes.CandidateEndpoint) error {
	if store == nil {
		return nil
	}
	if len(cands) == 0 {
		return store.Delete(storage.KeyCandidates)
	}
	b, err := json.Marshal(cands)
	if err != nil {
		return err
	}
	return store.Set(storage.KeyCandidates, b)
}

// LoadCandidates reads the last CP candidate list.
func LoadCandidates(store storage.SecureStorage) ([]apitypes.CandidateEndpoint, error) {
	if store == nil {
		return nil, storage.ErrNotFound
	}
	raw, err := store.Get(storage.KeyCandidates)
	if err != nil {
		return nil, err
	}
	var out []apitypes.CandidateEndpoint
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, err
	}
	return out, nil
}
