package nodeagent_test

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/nodeagent"
	"focusvpn.example/focusvpn/backend/internal/platform/ca"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func newTestHandler(t *testing.T) (*nodeagent.Handler, *memory.Store) {
	t.Helper()
	authority, err := ca.LoadOrEphemeral("", "")
	if err != nil {
		t.Fatalf("ca: %v", err)
	}
	st := memory.New()
	h := nodeagent.New(authority, st)
	return h, st
}

func newMux(h *nodeagent.Handler) *http.ServeMux {
	mux := http.NewServeMux()
	h.Routes(mux)
	return mux
}

func makeCSR(t *testing.T) ([]byte, *ecdsa.PrivateKey) {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	tmpl := &x509.CertificateRequest{
		Subject:            pkix.Name{CommonName: "test-node"},
		SignatureAlgorithm: x509.ECDSAWithSHA256,
	}
	raw, err := x509.CreateCertificateRequest(rand.Reader, tmpl, priv)
	if err != nil {
		t.Fatalf("csr: %v", err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: raw}), priv
}

func tokenHash(raw string) string {
	h := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(h[:])
}

func seedToken(t *testing.T, st *memory.Store, nodeID, raw string) {
	t.Helper()
	tok := store.NodeToken{
		ID:        id.NewUUID(),
		NodeID:    nodeID,
		TokenHash: tokenHash(raw),
		ExpiresAt: time.Now().Add(time.Hour),
		CreatedAt: time.Now(),
	}
	if err := st.NodeTokens().CreateNodeToken(context.Background(), tok); err != nil {
		t.Fatalf("seed token: %v", err)
	}
}

// TestRegisterOK registers with a valid token and CSR.
func TestRegisterOK(t *testing.T) {
	h, st := newTestHandler(t)
	mux := newMux(h)

	nodeID := id.NewUUID()
	rawToken := "test-token-1234"
	seedToken(t, st, nodeID, rawToken)

	csrPEM, _ := makeCSR(t)
	body, _ := json.Marshal(map[string]string{
		"node_token": rawToken,
		"csr_pem":    string(csrPEM),
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/agent/register", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp["cert_pem"] == "" {
		t.Fatal("expected cert_pem in response")
	}
	if resp["ca_pem"] == "" {
		t.Fatal("expected ca_pem in response")
	}
}

// TestRegisterInvalidToken returns 401 for an unknown or used token.
func TestRegisterInvalidToken(t *testing.T) {
	h, _ := newTestHandler(t)
	mux := newMux(h)

	csrPEM, _ := makeCSR(t)
	body, _ := json.Marshal(map[string]string{
		"node_token": "bad-token",
		"csr_pem":    string(csrPEM),
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/agent/register", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

// TestRegisterTokenConsumedOnce ensures a token cannot be reused.
func TestRegisterTokenConsumedOnce(t *testing.T) {
	h, st := newTestHandler(t)
	mux := newMux(h)

	nodeID := id.NewUUID()
	rawToken := "once-token"
	seedToken(t, st, nodeID, rawToken)

	csrPEM, _ := makeCSR(t)
	do := func() int {
		body, _ := json.Marshal(map[string]string{
			"node_token": rawToken,
			"csr_pem":    string(csrPEM),
		})
		req := httptest.NewRequest(http.MethodPost, "/v1/agent/register", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		return w.Code
	}

	if code := do(); code != http.StatusOK {
		t.Fatalf("first: expected 200, got %d", code)
	}
	if code := do(); code != http.StatusUnauthorized {
		t.Fatalf("second: expected 401 (token reuse), got %d", code)
	}
}

// TestStateNoMTLS returns 401 when no TLS client cert is presented.
func TestStateNoMTLS(t *testing.T) {
	h, _ := newTestHandler(t)
	mux := newMux(h)

	req := httptest.NewRequest(http.MethodGet, "/v1/agent/state?since=0", nil)
	// No TLS — r.TLS will be nil.
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

// TestTelemetryActivatesAllocation checks that posting applied=true transitions
// a pending allocation to active.
func TestTelemetryActivatesAllocation(t *testing.T) {
	h, st := newTestHandler(t)
	mux := newMux(h)

	// Seed a pending allocation.
	allocID := id.NewUUID()
	alloc := store.Allocation{
		ID:         allocID,
		UserID:     id.NewUUID(),
		DeviceID:   id.NewUUID(),
		EndpointID: id.NewUUID(),
		IP:         "10.200.0.2",
		Status:     "pending",
		CreatedAt:  time.Now(),
		UpdatedAt:  time.Now(),
	}
	if err := st.Allocations().CreateAllocation(context.Background(), alloc); err != nil {
		t.Fatalf("seed alloc: %v", err)
	}

	payload, _ := json.Marshal(map[string]any{
		"node_id":    "test-node-cn",
		"peer_count": 1,
		"peers": []map[string]any{
			{"allocation_id": allocID, "applied": true},
		},
	})

	// Simulate mTLS by injecting a fake TLS state with the node CN.
	req := httptest.NewRequest(http.MethodPost, "/v1/agent/telemetry", bytes.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")
	req = withFakeTLSCN(req, "test-node-cn")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusNoContent {
		t.Fatalf("expected 204, got %d: %s", w.Code, w.Body.String())
	}

	updated, err := st.Allocations().GetAllocationByID(context.Background(), allocID)
	if err != nil {
		t.Fatalf("get alloc: %v", err)
	}
	if updated.Status != "active" {
		t.Fatalf("expected active, got %s", updated.Status)
	}
}

func TestVLESSStateSharedAndHeartbeat(t *testing.T) {
	h, st := newTestHandler(t)
	mux := newMux(h)
	ctx := context.Background()
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	st.UseKEK(mycrypto.KEK{ID: "kek-v1", Key: key})
	const nodeA, nodeB = "node-a", "node-b"
	st.SeedEndpoint(store.Endpoint{
		ID: "ep-a", NodeID: nodeA, NodeName: "DE1", Protocol: "vless-ws", State: "OFFLINE",
		Hostname: "de1.example", Port: 443, Subnet: "10.210.0.0/24", Capacity: 100,
	})
	st.SeedEndpoint(store.Endpoint{
		ID: "ep-b", NodeID: nodeB, NodeName: "DE2", Protocol: "vless-ws", State: "OFFLINE",
		Hostname: "de2.example", Port: 443, Subnet: "10.211.0.0/24", Capacity: 50,
	})
	for _, n := range []string{nodeA, nodeB} {
		if err := st.EnsureStateVersion(ctx, n); err != nil {
			t.Fatal(err)
		}
		if _, err := st.IncrementStateVersion(ctx, n); err != nil {
			t.Fatal(err)
		}
	}
	userID := id.NewUUID()
	now := time.Now().UTC()
	st.SeedSubscription(store.Subscription{
		ID: id.NewUUID(), UserID: userID, PlanID: "week", Status: "active", EndsAt: now.Add(24 * time.Hour),
	})
	allocID := id.NewUUID()
	vlessID := id.NewUUID()
	if err := st.CreateAllocation(ctx, store.Allocation{
		ID: allocID, UserID: userID, DeviceID: id.NewUUID(), EndpointID: "ep-a",
		IP: "10.210.0.2", Status: "active", VLESSUUID: vlessID, CreatedAt: now, UpdatedAt: now,
	}); err != nil {
		t.Fatal(err)
	}

	for _, node := range []string{nodeA, nodeB} {
		req := withFakeTLSCN(httptest.NewRequest(http.MethodGet, "/v1/agent/state?since=0", nil), node)
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("%s state: %d %s", node, w.Code, w.Body.String())
		}
		var body struct {
			Peers []struct {
				AllocationID string `json:"allocation_id"`
				VLESSUUID    string `json:"vless_uuid"`
			} `json:"peers"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		if len(body.Peers) != 1 || body.Peers[0].VLESSUUID != vlessID {
			t.Fatalf("%s peers: %+v", node, body.Peers)
		}
	}

	online := 4
	payload, _ := json.Marshal(map[string]any{
		"online_users": online, "rx_bytes": 1000, "tx_bytes": 250,
	})
	req := withFakeTLSCN(httptest.NewRequest(http.MethodPost, "/v1/agent/telemetry", bytes.NewReader(payload)), nodeA)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent {
		t.Fatalf("telemetry: %d %s", w.Code, w.Body.String())
	}
	eps, err := st.ListEndpoints(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range eps {
		if e.NodeID != nodeA {
			continue
		}
		if e.State != "HEALTHY" || e.PeerCount != 4 || e.Load != 0.04 {
			t.Fatalf("heartbeat: %+v", e)
		}
	}
	sum, err := st.Summary(ctx, time.Now().UTC())
	if err != nil {
		t.Fatal(err)
	}
	var found bool
	for _, n := range sum.Nodes {
		if n.NodeID == nodeA {
			found = true
			if n.RxToday != 1000 || n.TxToday != 250 || n.Online != 4 {
				t.Fatalf("report node: %+v", n)
			}
		}
	}
	if !found {
		t.Fatalf("node missing from report: %+v", sum.Nodes)
	}
}

func TestTelemetryRetriedSeqCountsOnlyGrowth(t *testing.T) {
	h, st := newTestHandler(t)
	mux := newMux(h)
	ctx := context.Background()
	const node = "node-t"
	st.SeedEndpoint(store.Endpoint{ID: "ep-t", NodeID: node, NodeName: "T1", Protocol: "vless", State: "OFFLINE",
		Hostname: "t1.example", Port: 443, Subnet: "10.220.0.0/24", Capacity: 10})
	send := func(boot string, seq, rx int64) {
		t.Helper()
		payload, _ := json.Marshal(map[string]any{"online_users": 1, "rx_bytes": rx, "tx_bytes": 0, "boot": boot, "seq": seq})
		req := withFakeTLSCN(httptest.NewRequest(http.MethodPost, "/v1/agent/telemetry", bytes.NewReader(payload)), node)
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		if w.Code != http.StatusNoContent {
			t.Fatalf("telemetry: %d %s", w.Code, w.Body.String())
		}
	}
	send("b1", 1, 100) // accepted, but the agent saw a timeout
	send("b1", 1, 150) // retry with the grown delta: +50
	send("b1", 2, 30)  // next interval: +30
	send("b1", 1, 999) // stale replay: ignored
	send("b2", 1, 7)   // agent restarted: +7
	sum, err := st.Summary(ctx, time.Now().UTC())
	if err != nil {
		t.Fatal(err)
	}
	for _, n := range sum.Nodes {
		if n.NodeID == node && n.RxToday != 187 {
			t.Fatalf("rx today = %d, want 187", n.RxToday)
		}
	}
}
