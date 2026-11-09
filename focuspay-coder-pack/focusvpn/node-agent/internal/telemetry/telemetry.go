// Package telemetry sends periodic heartbeats to POST /v1/agent/telemetry
// (ADR-004). It also carries peer-applied confirmations that trigger the
// allocation pending→active transition on the Control Plane.
package telemetry

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"focusvpn.example/focusvpn/node-agent/internal/mtls"
)

type peerTelemetry struct {
	AllocationID string     `json:"allocation_id"`
	Applied      bool       `json:"applied"`
	HandshakeAt  *time.Time `json:"handshake_at,omitempty"`
}

type telemetryPayload struct {
	NodeID      string          `json:"node_id"`
	LoadPercent float64         `json:"load_percent"`
	RxBytes     int64           `json:"rx_bytes"`
	TxBytes     int64           `json:"tx_bytes"`
	PeerCount   int             `json:"peer_count"`
	OnlineUsers *int            `json:"online_users,omitempty"`
	Peers       []peerTelemetry `json:"peers,omitempty"`
	// Boot+Seq let the CP apply a retried traffic delta only once: the same seq
	// is resent (with a grown delta) until a POST succeeds.
	Boot string `json:"boot,omitempty"`
	Seq  int64  `json:"seq,omitempty"`
	// Health is the local probe. Shares lists UUIDs seen from too many addresses.
	Health *Health `json:"health,omitempty"`
	Shares []Share `json:"shares,omitempty"`
}

// Health is one local probe result.
type Health struct {
	OK       bool   `json:"ok"`
	Degraded bool   `json:"degraded,omitempty"`
	Reason   string `json:"reason,omitempty"`
}

// Share is one UUID over the address cap. The address list stays on the node.
type Share struct {
	AllocationID string `json:"allocation_id"`
	IPCount      int    `json:"ip_count"`
}

// Sample is one Xray stats reading: cumulative counters since Xray start.
// Downlink is bytes delivered to users.
type Sample struct {
	Online   int
	Downlink int64
	Uplink   int64
	Health   *Health
	Shares   []Share
}

// Collector reads node stats for a heartbeat. Nil collector keeps WG behavior.
type Collector func(ctx context.Context) (Sample, error)

// Sender sends telemetry to the CP and tracks pending peer confirmations.
type Sender struct {
	client   *mtls.Client
	nodeID   string
	interval time.Duration

	mu      sync.Mutex
	pending []string // allocation IDs applied since last telemetry send
	collect Collector

	boot             string
	seq              int64
	baseDown, baseUp int64 // counters already accepted by the CP
}

// New creates a Sender.
func New(client *mtls.Client, nodeID string, interval time.Duration) *Sender {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return &Sender{client: client, nodeID: nodeID, interval: interval, boot: hex.EncodeToString(b), seq: 1}
}

// SetCollector attaches an Xray stats source. WG agents leave it unset.
func (s *Sender) SetCollector(c Collector) { s.collect = c }

// MarkApplied records allocation IDs that have been applied and should be
// confirmed to the CP on the next telemetry send.
func (s *Sender) MarkApplied(ids []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.pending = append(s.pending, ids...)
}

// Run sends heartbeats on the configured interval until ctx is cancelled.
func (s *Sender) Run(ctx context.Context) {
	ticker := time.NewTicker(s.interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := s.send(ctx); err != nil {
				log.Printf("telemetry: send error: %v", err)
			}
		}
	}
}

func (s *Sender) send(ctx context.Context) error {
	s.mu.Lock()
	pending := s.pending
	s.pending = nil
	s.mu.Unlock()

	var peers []peerTelemetry
	for _, id := range pending {
		peers = append(peers, peerTelemetry{AllocationID: id, Applied: true})
	}

	payload := telemetryPayload{
		NodeID:    s.nodeID,
		PeerCount: len(peers),
		Peers:     peers,
	}
	var sample *Sample
	if s.collect != nil {
		got, err := s.collect(ctx)
		payload.Health = got.Health
		payload.Shares = got.Shares
		if err != nil {
			log.Printf("telemetry: stats: %v", err)
		} else {
			sample = &got
			if got.Downlink < s.baseDown || got.Uplink < s.baseUp {
				// Xray restarted and its counters began from zero.
				s.baseDown, s.baseUp = 0, 0
			}
			online := got.Online
			payload.OnlineUsers = &online
			payload.RxBytes = got.Downlink - s.baseDown
			payload.TxBytes = got.Uplink - s.baseUp
			payload.PeerCount = got.Online
			payload.Boot, payload.Seq = s.boot, s.seq
		}
	}
	if err := s.post(ctx, payload); err != nil {
		s.requeue(pending)
		return err
	}
	if sample != nil {
		s.baseDown, s.baseUp = sample.Downlink, sample.Uplink
		s.seq++
	}
	return nil
}

func (s *Sender) requeue(ids []string) {
	if len(ids) == 0 {
		return
	}
	s.mu.Lock()
	s.pending = append(append([]string(nil), ids...), s.pending...)
	s.mu.Unlock()
}

func (s *Sender) post(ctx context.Context, payload telemetryPayload) error {
	body, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.client.CPURL()+"/v1/agent/telemetry", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.client.Do(req)
	if err != nil {
		return fmt.Errorf("telemetry POST: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		return fmt.Errorf("telemetry: unexpected status %d", resp.StatusCode)
	}
	return nil
}
