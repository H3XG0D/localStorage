// Package nodeagent implements the Control Plane side of the node-agent
// protocol (ADR-004). It exposes three endpoints on a dedicated mTLS listener:
//
//	POST /v1/agent/register   — one-time token + CSR → signed certificate
//	GET  /v1/agent/state      — long-poll desired peer state
//	POST /v1/agent/telemetry  — heartbeat + peer-applied confirmation
//
// Authorization: register uses a one-time node_token; state and telemetry use
// mTLS client certificate (CN = node ID).
package nodeagent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"sync"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/ca"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

const (
	certTTL     = 90 * 24 * time.Hour
	pollTimeout = 30 * time.Second
)

// Handler handles node-agent CP endpoints.
type Handler struct {
	ca        *ca.CA
	tokens    store.NodeTokenStore
	certs     store.NodeCertStore
	state     store.NodeStateStore
	allocs    store.AllocationStore
	endpoints store.EndpointStore
	reports   store.ReportStore
	now       func() time.Time
	// notify is closed/replaced when state changes for a node.
	// We use a simple broadcast channel per node-id.
	notify *notifyBus

	trafficMu sync.Mutex
	traffic   map[string]trafficMark // node id -> last accepted delta
}

// trafficMark is the last (boot, seq) traffic delta counted for a node. A
// retried heartbeat repeats seq with a delta that only grew, so the CP adds the
// difference instead of the whole value.
type trafficMark struct {
	boot   string
	seq    int64
	rx, tx int64
}

// New creates a Handler.
func New(authority *ca.CA, st store.Store) *Handler {
	return &Handler{
		ca:        authority,
		tokens:    st.NodeTokens(),
		certs:     st.NodeCerts(),
		state:     st.NodeState(),
		allocs:    st.Allocations(),
		endpoints: st.Endpoints(),
		reports:   st.Reports(),
		now:       time.Now,
		notify:    newNotifyBus(),
		traffic:   map[string]trafficMark{},
	}
}

// Routes registers agent endpoints on the given mux. The mux is expected to
// be served on a TLS listener; mTLS enforcement happens at the TLS layer for
// state/telemetry, while register only requires a valid one-time token.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/agent/register", h.register)
	mux.HandleFunc("GET /v1/agent/state", h.state_)
	mux.HandleFunc("POST /v1/agent/telemetry", h.telemetry)
}

// --- register ------------------------------------------------------------------

type registerRequest struct {
	NodeToken string `json:"node_token"` // raw one-time token
	CSRPEM    string `json:"csr_pem"`    // PEM-encoded CERTIFICATE REQUEST
}

type registerResponse struct {
	CertPEM string `json:"cert_pem"` // signed node certificate
	CAPEM   string `json:"ca_pem"`   // CA cert for server verification
}

func (h *Handler) register(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid JSON")
		return
	}
	if req.NodeToken == "" || req.CSRPEM == "" {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "node_token and csr_pem required")
		return
	}

	hash := tokenHash(req.NodeToken)
	tok, err := h.tokens.ConsumeNodeToken(r.Context(), hash, time.Now().UTC())
	if errors.Is(err, store.ErrNotFound) {
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "node token invalid, expired or already used")
		return
	}
	if err != nil {
		log.Printf("nodeagent register: consume token: %v", err)
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal error")
		return
	}

	certPEM, serial, err := h.ca.SignCSR([]byte(req.CSRPEM), tok.NodeID, certTTL)
	if err != nil {
		log.Printf("nodeagent register: sign CSR for node %s: %v", tok.NodeID, err)
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_csr", "CSR invalid or could not be signed")
		return
	}

	now := time.Now().UTC()
	nc := store.NodeCertificate{
		ID:        id.NewUUID(),
		NodeID:    tok.NodeID,
		Serial:    serial,
		CertPEM:   string(certPEM),
		IssuedAt:  now,
		ExpiresAt: now.Add(certTTL),
	}
	if err := h.certs.CreateNodeCert(r.Context(), nc); err != nil {
		log.Printf("nodeagent register: store cert for node %s: %v", tok.NodeID, err)
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal error")
		return
	}

	httpx.WriteJSON(w, http.StatusOK, registerResponse{
		CertPEM: string(certPEM),
		CAPEM:   string(h.ca.CertPEM()),
	})
}

// --- state (long-poll) --------------------------------------------------------

// PeerState is one peer entry in the desired state response.
type PeerState struct {
	AllocationID string `json:"allocation_id"`
	PublicKey    []byte `json:"public_key"` // client's x25519 key
	AllowedIP    string `json:"allowed_ip"` // /32 host route
	Status       string `json:"status"`     // "pending" or "active"
	// VLESSUUID is set for Xray users; the agent adds it to every VLESS inbound
	// with email = AllocationID.
	VLESSUUID string `json:"vless_uuid,omitempty"`
}

type stateResponse struct {
	NodeID  string      `json:"node_id"`
	Version int64       `json:"version"`
	Peers   []PeerState `json:"peers"`
}

func (h *Handler) state_(w http.ResponseWriter, r *http.Request) {
	nodeID := nodeIDFromTLS(r)
	if nodeID == "" {
		httpx.WriteError(w, r, http.StatusUnauthorized, "unauthorized", "mTLS client cert required")
		return
	}

	sinceStr := r.URL.Query().Get("since")
	var since int64
	if sinceStr != "" {
		var err error
		since, err = strconv.ParseInt(sinceStr, 10, 64)
		if err != nil {
			httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "since must be an integer")
			return
		}
	}

	// Wait until version > since (long-poll) or timeout.
	ctx, cancel := context.WithTimeout(r.Context(), pollTimeout)
	defer cancel()

	curVer, err := h.state.GetStateVersion(ctx, nodeID)
	if errors.Is(err, store.ErrNotFound) {
		// Node not registered in state table yet; return version 0 empty.
		httpx.WriteJSON(w, http.StatusOK, stateResponse{NodeID: nodeID, Version: 0, Peers: []PeerState{}})
		return
	}
	if err != nil {
		log.Printf("nodeagent state: get version for %s: %v", nodeID, err)
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal error")
		return
	}

	if curVer <= since {
		// Block until notified or timeout.
		h.notify.wait(ctx, nodeID)
		// Re-read after wait (may still be unchanged if it was a spurious wake).
		curVer, err = h.state.GetStateVersion(ctx, nodeID)
		if err != nil {
			if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
				// Timeout: return current (possibly unchanged) state.
				curVer = since
			} else {
				log.Printf("nodeagent state: re-read version for %s: %v", nodeID, err)
				httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal error")
				return
			}
		}
	}

	if curVer <= since {
		// Still no change after poll timeout — return empty with same version so
		// the agent can immediately re-poll with the same since value.
		httpx.WriteJSON(w, http.StatusOK, stateResponse{NodeID: nodeID, Version: since, Peers: []PeerState{}})
		return
	}

	peers, err := h.buildPeers(ctx, nodeID)
	if err != nil {
		log.Printf("nodeagent state: build peers for %s: %v", nodeID, err)
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal error")
		return
	}
	httpx.WriteJSON(w, http.StatusOK, stateResponse{NodeID: nodeID, Version: curVer, Peers: peers})
}

// buildPeers returns the desired peers for a node: live allocations of its
// WireGuard-family endpoints plus, when the node serves VLESS, every entitled
// VLESS user (shared across Xray nodes so clients can fail over).
func (h *Handler) buildPeers(ctx context.Context, nodeID string) ([]PeerState, error) {
	eps, err := h.endpoints.ListEndpoints(ctx)
	if err != nil {
		return nil, err
	}

	peers := []PeerState{}
	vless := false
	for _, ep := range eps {
		if ep.NodeID != nodeID {
			continue
		}
		if store.IsVLESS(ep.Protocol) {
			vless = true
			continue
		}
		epAllocs, err := h.allocs.ListLiveByEndpoint(ctx, ep.ID)
		if err != nil {
			return nil, err
		}
		for _, a := range epAllocs {
			peers = append(peers, PeerState{
				AllocationID: a.ID,
				PublicKey:    a.PeerPublicKey,
				AllowedIP:    a.IP + "/32",
				Status:       a.Status,
			})
		}
	}
	if vless {
		users, err := h.allocs.ListLiveEntitledVLESS(ctx, h.now())
		if err != nil {
			return nil, err
		}
		for _, a := range users {
			peers = append(peers, PeerState{AllocationID: a.ID, Status: a.Status, VLESSUUID: a.VLESSUUID})
		}
	}
	return peers, nil
}

// --- telemetry ----------------------------------------------------------------

type telemetryRequest struct {
	NodeID      string  `json:"node_id"`
	LoadPercent float64 `json:"load_percent"`
	RxBytes     int64   `json:"rx_bytes"`
	TxBytes     int64   `json:"tx_bytes"`
	PeerCount   int     `json:"peer_count"`
	// OnlineUsers is the number of Xray users with a live session (nil for WG nodes).
	OnlineUsers *int            `json:"online_users,omitempty"`
	Peers       []peerTelemetry `json:"peers,omitempty"`
	Boot        string          `json:"boot,omitempty"`
	Seq         int64           `json:"seq,omitempty"`
	Health      *healthReport   `json:"health,omitempty"`
	Shares      []shareReport   `json:"shares,omitempty"`
}

type healthReport struct {
	OK       bool   `json:"ok"`
	Degraded bool   `json:"degraded"`
	Reason   string `json:"reason"`
}

type shareReport struct {
	AllocationID string `json:"allocation_id"`
	IPCount      int    `json:"ip_count"`
}

type peerTelemetry struct {
	AllocationID string     `json:"allocation_id"`
	Applied      bool       `json:"applied"`
	HandshakeAt  *time.Time `json:"handshake_at,omitempty"`
}

// trafficDelta returns the bytes not yet counted for this heartbeat.
func (h *Handler) trafficDelta(nodeID string, req telemetryRequest) (rx, tx int64) {
	if req.Boot == "" || req.Seq == 0 {
		return max(req.RxBytes, 0), max(req.TxBytes, 0)
	}
	h.trafficMu.Lock()
	defer h.trafficMu.Unlock()
	m, ok := h.traffic[nodeID]
	switch {
	case ok && m.boot == req.Boot && req.Seq < m.seq:
		return 0, 0
	case ok && m.boot == req.Boot && req.Seq == m.seq:
		rx, tx = max(req.RxBytes-m.rx, 0), max(req.TxBytes-m.tx, 0)
		m.rx, m.tx = max(m.rx, req.RxBytes), max(m.tx, req.TxBytes)
		h.traffic[nodeID] = m
		return rx, tx
	}
	h.traffic[nodeID] = trafficMark{boot: req.Boot, seq: req.Seq, rx: req.RxBytes, tx: req.TxBytes}
	return max(req.RxBytes, 0), max(req.TxBytes, 0)
}

func (h *Handler) telemetry(w http.ResponseWriter, r *http.Request) {
	nodeID := nodeIDFromTLS(r)
	if nodeID == "" {
		httpx.WriteError(w, r, http.StatusUnauthorized, "unauthorized", "mTLS client cert required")
		return
	}

	var req telemetryRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid JSON")
		return
	}

	now := h.now().UTC()
	online := req.PeerCount
	if req.OnlineUsers != nil {
		online = *req.OnlineUsers
	}
	var health *store.NodeHealth
	if req.Health != nil {
		health = &store.NodeHealth{OK: req.Health.OK, Degraded: req.Health.Degraded, Reason: req.Health.Reason}
	}
	if err := h.endpoints.RecordNodePulse(r.Context(), nodeID, online, now, health); err != nil && !errors.Is(err, store.ErrNotFound) {
		log.Printf("nodeagent telemetry: heartbeat %s: %v", nodeID, err)
	}
	if h.pauseShares(r.Context(), nodeID, now, req.Shares) {
		h.wakeVLESS(r.Context())
	}
	if rx, tx := h.trafficDelta(nodeID, req); rx > 0 || tx > 0 {
		if err := h.reports.AddNodeTraffic(r.Context(), nodeID, now, rx, tx); err != nil {
			log.Printf("nodeagent telemetry: traffic %s: %v", nodeID, err)
		}
	}
	for _, p := range req.Peers {
		if !p.Applied || p.AllocationID == "" {
			continue
		}
		alloc, err := h.allocs.GetAllocationByID(r.Context(), p.AllocationID)
		if errors.Is(err, store.ErrNotFound) {
			continue
		}
		if err != nil {
			log.Printf("nodeagent telemetry: get alloc %s: %v", p.AllocationID, err)
			continue
		}
		if alloc.Status == "pending" {
			if err := h.allocs.SetAllocationStatus(r.Context(), alloc.ID, "active", now); err != nil {
				log.Printf("nodeagent telemetry: activate alloc %s: %v", alloc.ID, err)
			} else {
				log.Printf("nodeagent telemetry: allocation %s activated (peer applied on node %s)", alloc.ID, nodeID)
			}
		}
	}

	w.WriteHeader(http.StatusNoContent)
}

// pauseShares records UUIDs seen from more than three public addresses.
// It returns true when at least one allocation newly entered the pause, so the
// Xray user set has to be pushed again.
func (h *Handler) pauseShares(ctx context.Context, nodeID string, now time.Time, shares []shareReport) bool {
	until := now.Add(15 * time.Minute)
	wake := false
	for _, sh := range shares {
		if sh.AllocationID == "" || sh.IPCount <= 3 {
			continue
		}
		fresh, err := h.allocs.UpsertAllocationPause(ctx, store.AllocationPause{
			AllocationID: sh.AllocationID,
			IPCount:      sh.IPCount,
			Reason:       fmt.Sprintf("%d адресов сразу, пауза до %s UTC", sh.IPCount, until.UTC().Format("15:04")),
			Until:        until,
			NodeID:       nodeID,
			UpdatedAt:    now,
		})
		if errors.Is(err, store.ErrNotFound) {
			continue
		}
		if err != nil {
			log.Printf("nodeagent telemetry: pause %s: %v", sh.AllocationID, err)
			continue
		}
		if fresh {
			wake = true
		}
	}
	return wake
}

func (h *Handler) wakeVLESS(ctx context.Context) {
	eps, err := h.endpoints.ListEndpoints(ctx)
	if err != nil {
		log.Printf("nodeagent telemetry: list endpoints: %v", err)
		return
	}
	seen := map[string]bool{}
	for _, e := range eps {
		if !store.IsVLESS(e.Protocol) || seen[e.NodeID] {
			continue
		}
		seen[e.NodeID] = true
		if _, err := h.state.IncrementStateVersion(ctx, e.NodeID); err != nil && !errors.Is(err, store.ErrNotFound) {
			log.Printf("nodeagent telemetry: bump %s: %v", e.NodeID, err)
		}
		h.Notify(e.NodeID)
	}
}

// --- helpers ------------------------------------------------------------------

// nodeIDFromTLS extracts the node ID (CN) from the verified mTLS peer certificate.
// Returns "" if no valid client cert is present (unauthenticated request).
func nodeIDFromTLS(r *http.Request) string {
	if r.TLS == nil || len(r.TLS.PeerCertificates) == 0 {
		return ""
	}
	return r.TLS.PeerCertificates[0].Subject.CommonName
}

// tokenHash computes the SHA-256 hex digest of a raw token string.
func tokenHash(raw string) string {
	h := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(h[:])
}

// notifyBus is a simple pub/sub for state-change notifications keyed by node ID.
// When a state change occurs, all waiters for that node are unblocked.
type notifyBus struct {
	ch chan notifyMsg
}

type notifyMsg struct{ nodeID string }

func newNotifyBus() *notifyBus {
	b := &notifyBus{ch: make(chan notifyMsg, 64)}
	return b
}

// Notify wakes all pollers waiting for nodeID.
func (b *notifyBus) Notify(nodeID string) {
	select {
	case b.ch <- notifyMsg{nodeID: nodeID}:
	default:
	}
}

// wait blocks until a notification for nodeID arrives or ctx is done.
func (b *notifyBus) wait(ctx context.Context, nodeID string) {
	// Subscribe to the shared channel. Because multiple goroutines share one
	// channel we re-broadcast: each waiter gets its own channel fed by the bus.
	sub := make(chan struct{}, 1)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-ctx.Done():
				return
			case msg, ok := <-b.ch:
				if !ok {
					return
				}
				if msg.nodeID == nodeID {
					select {
					case sub <- struct{}{}:
					default:
					}
					// Re-enqueue for other concurrent waiters.
					select {
					case b.ch <- msg:
					default:
					}
					return
				}
				// Not our node — put it back.
				select {
				case b.ch <- msg:
				default:
				}
			}
		}
	}()
	select {
	case <-ctx.Done():
	case <-sub:
	}
	<-done
}

// Notify is exported so connections.Service can call it after state changes.
func (h *Handler) Notify(nodeID string) { h.notify.Notify(nodeID) }

// --- JSON health (no auth) ----------------------------------------------------

func Health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}
