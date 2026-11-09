// Package poller implements the long-poll GET /v1/agent/state loop (ADR-004).
package poller

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"focusvpn.example/focusvpn/node-agent/internal/mtls"
)

// PeerState is one peer in the desired state from the CP.
type PeerState struct {
	AllocationID string `json:"allocation_id"`
	PublicKey    []byte `json:"public_key"`
	AllowedIP    string `json:"allowed_ip"`
	Status       string `json:"status"`
	// VLESSUUID is set for Xray users. The node email is AllocationID.
	VLESSUUID string `json:"vless_uuid,omitempty"`
}

// StateResponse is the CP /v1/agent/state response body.
type StateResponse struct {
	NodeID  string      `json:"node_id"`
	Version int64       `json:"version"`
	Peers   []PeerState `json:"peers"`
}

// ApplyFunc is called with the new desired state when it changes.
type ApplyFunc func(ctx context.Context, state StateResponse) error

// Poller runs the long-poll loop until ctx is cancelled.
type Poller struct {
	client       *mtls.Client
	nodeID       string
	pollInterval time.Duration
	onState      ApplyFunc
}

// New creates a Poller.
func New(client *mtls.Client, nodeID string, pollInterval time.Duration, onState ApplyFunc) *Poller {
	return &Poller{client: client, nodeID: nodeID, pollInterval: pollInterval, onState: onState}
}

// Run starts the poll loop and blocks until ctx is cancelled.
func (p *Poller) Run(ctx context.Context) {
	var since int64
	for {
		state, err := p.poll(ctx, since)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			log.Printf("poller: poll error: %v; retrying in %s", err, p.pollInterval)
			select {
			case <-ctx.Done():
				return
			case <-time.After(p.pollInterval):
				continue
			}
		}
		if state.Version > since {
			since = state.Version
			// Apply even when the peer list is empty: that is how a revoked
			// user is removed from the node.
			if err := p.onState(ctx, state); err != nil {
				log.Printf("poller: apply error: %v", err)
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(p.pollInterval):
		}
	}
}

func (p *Poller) poll(ctx context.Context, since int64) (StateResponse, error) {
	url := fmt.Sprintf("%s/v1/agent/state?since=%d", p.client.CPURL(), since)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return StateResponse{}, err
	}
	resp, err := p.client.Do(req)
	if err != nil {
		return StateResponse{}, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode == http.StatusConflict {
		// 409 stale_version — reset to 0.
		log.Println("poller: stale version; re-syncing from 0")
		return StateResponse{NodeID: p.nodeID, Version: 0}, nil
	}
	if resp.StatusCode != http.StatusOK {
		return StateResponse{}, fmt.Errorf("state poll: %d %s", resp.StatusCode, bytes.TrimSpace(data))
	}
	var s StateResponse
	if err := json.Unmarshal(data, &s); err != nil {
		return StateResponse{}, fmt.Errorf("state poll: decode: %w", err)
	}
	return s, nil
}
