// Package nodereg is the operator API a setup script calls to attach a VLESS
// node and to read the report FocusPay shows. Both routes require
// X-Internal-Token (same secret as billing).
package nodereg

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net"
	"net/http"
	"strings"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Handler serves node registration and the operator report.
type Handler struct {
	nodes   store.NodeCatalog
	tokens  store.NodeTokenStore
	reports store.ReportStore
	token   string
	now     func() time.Time
}

// NewHandler wires the internal routes.
func NewHandler(nodes store.NodeCatalog, tokens store.NodeTokenStore, reports store.ReportStore, internalToken string) *Handler {
	return &Handler{nodes: nodes, tokens: tokens, reports: reports, token: internalToken, now: time.Now}
}

// Routes registers the internal endpoints.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/internal/nodes", h.require(h.register))
	mux.HandleFunc("GET /v1/internal/reports/summary", h.require(h.summary))
}

func (h *Handler) require(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if h.token == "" {
			httpx.WriteError(w, r, http.StatusServiceUnavailable, "internal_disabled", "FOCUSVPN_INTERNAL_TOKEN not configured")
			return
		}
		if r.Header.Get("X-Internal-Token") != h.token {
			httpx.WriteError(w, r, http.StatusUnauthorized, "unauthorized", "invalid internal token")
			return
		}
		next(w, r)
	}
}

type registerRequest struct {
	Name       string          `json:"name"`
	Country    string          `json:"country"`
	Region     string          `json:"region"`
	Hostname   string          `json:"hostname"`
	Capacity   int             `json:"capacity"`
	Subnet     string          `json:"subnet"`
	Xray       json.RawMessage `json:"xray"`
	IssueToken bool            `json:"issue_token"`
}

func (h *Handler) register(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid JSON")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	req.Hostname = strings.TrimSpace(req.Hostname)
	req.Country = strings.TrimSpace(req.Country)
	if req.Name == "" || req.Hostname == "" || req.Country == "" {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "name, country and hostname are required")
		return
	}
	if req.Subnet != "" {
		if _, _, err := net.ParseCIDR(req.Subnet); err != nil {
			httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "subnet must be a CIDR")
			return
		}
	}
	var xray map[string]any
	if err := json.Unmarshal(req.Xray, &xray); err != nil || strings.TrimSpace(asString(xray["path"])) == "" {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "xray.path is required")
		return
	}

	nodeID, endpointID, err := h.nodes.UpsertVLESSNode(r.Context(), store.VLESSNode{
		Name: req.Name, Country: req.Country, Region: req.Region, Hostname: req.Hostname,
		Capacity: req.Capacity, Subnet: req.Subnet, Xray: req.Xray,
	})
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "could not register node")
		return
	}
	resp := map[string]any{"node_id": nodeID, "endpoint_id": endpointID}
	if req.IssueToken {
		raw, err := h.issueToken(r.Context(), nodeID)
		if err != nil {
			httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "could not issue agent token")
			return
		}
		resp["agent_token"] = raw
	}
	httpx.WriteJSON(w, http.StatusOK, resp)
}

func (h *Handler) issueToken(ctx context.Context, nodeID string) (string, error) {
	raw := id.NewOpaqueToken(32)
	sum := sha256.Sum256([]byte(raw))
	now := h.now().UTC()
	err := h.tokens.CreateNodeToken(ctx, store.NodeToken{
		ID: id.NewUUID(), NodeID: nodeID, TokenHash: hex.EncodeToString(sum[:]),
		ExpiresAt: now.Add(24 * time.Hour), CreatedAt: now,
	})
	return raw, err
}

func (h *Handler) summary(w http.ResponseWriter, r *http.Request) {
	sum, err := h.reports.Summary(r.Context(), h.now().UTC())
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "could not build report")
		return
	}
	nodes := make([]map[string]any, 0, len(sum.Nodes))
	for _, n := range sum.Nodes {
		row := map[string]any{
			"node_id": n.NodeID, "name": n.Name, "country": n.Country, "state": n.State,
			"online": n.Online, "capacity": n.Capacity, "load": n.Load,
			"status_reason": n.StatusReason,
			"rx_today":      n.RxToday, "tx_today": n.TxToday, "rx_30d": n.Rx30d, "tx_30d": n.Tx30d,
		}
		if n.LastHeartbeatAt != nil {
			row["last_heartbeat_at"] = n.LastHeartbeatAt.UTC().Format(time.RFC3339)
		}
		nodes = append(nodes, row)
	}
	pauses := make([]map[string]any, 0, len(sum.Pauses))
	for _, p := range sum.Pauses {
		pauses = append(pauses, map[string]any{
			"allocation_id": p.AllocationID, "ip_count": p.IPCount, "reason": p.Reason,
			"until": p.Until.UTC().Format(time.RFC3339), "node_id": p.NodeID, "node_name": p.NodeName,
		})
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]any{
		"active_subscriptions": sum.ActiveSubscriptions,
		"active_devices":       sum.ActiveDevices,
		"live_connections":     sum.LiveConnections,
		"purchases_1d":         sum.Purchases1d,
		"purchases_7d":         sum.Purchases7d,
		"purchases_30d":        sum.Purchases30d,
		"purchased_days_30d":   sum.PurchasedDays30d,
		"trials_30d":           sum.Trials30d,
		"nodes":                nodes,
		"pauses":               pauses,
	})
}

func asString(v any) string {
	s, _ := v.(string)
	return s
}
