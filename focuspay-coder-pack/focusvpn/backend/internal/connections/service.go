// Package connections implements POST/DELETE /v1/connections (API.md §6, plans/M3).
package connections

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"focusvpn.example/focusvpn/backend/internal/nodehealth"
	"focusvpn.example/focusvpn/backend/internal/nodeselector"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/entitlement"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/ipam"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

var (
	ErrValidation          = errors.New("validation_error")
	ErrDeviceNotFound      = errors.New("device_not_found")
	ErrForbidden           = errors.New("forbidden")
	ErrNodeUnavailable     = errors.New("node_unavailable")
	ErrTooManyAllocations  = errors.New("too_many_allocations")
	ErrTooManyDevices      = errors.New("too_many_devices")
	ErrSubscriptionExpired = store.ErrSubscriptionExpired
	ErrNotFound            = errors.New("not_found")
)

// StateNotifier is called when desired state changes so agents can be woken from
// long-poll immediately (ADR-004). It is optional; nil = no-op.
type StateNotifier interface {
	Notify(nodeID string)
}

// Service orchestrates allocations + config issuance.
type Service struct {
	devices    store.DeviceStore
	endpoints  store.EndpointStore
	allocs     store.AllocationStore
	configs    store.ConfigurationStore
	subs       store.SubscriptionStore
	nodeState  store.NodeStateStore
	kek        mycrypto.KEK
	signer     *mycrypto.ConfigSigner
	autoActive bool
	notifier   StateNotifier
	now        func() time.Time

	mu           sync.Mutex
	vlessSetHash string
}

// NewService constructs the connections service.
func NewService(
	devices store.DeviceStore,
	endpoints store.EndpointStore,
	allocs store.AllocationStore,
	configs store.ConfigurationStore,
	subs store.SubscriptionStore,
	nodeState store.NodeStateStore,
	kek mycrypto.KEK,
	signer *mycrypto.ConfigSigner,
	autoActive bool,
	notifier StateNotifier,
) *Service {
	return &Service{
		devices: devices, endpoints: endpoints, allocs: allocs, configs: configs, subs: subs,
		nodeState: nodeState,
		kek:       kek, signer: signer, autoActive: autoActive, notifier: notifier, now: time.Now,
	}
}

// CreateResult is returned to the HTTP layer.
type CreateResult struct {
	Allocation    store.Allocation
	Configuration store.Configuration
	Endpoint      store.Endpoint
	Candidates    []nodeselector.Scored
	APIStatus     string // provisioning | active
	Created       bool   // false if idempotent reuse
}

// Create provisions (or reuses) a connection for the caller's device.
func (s *Service) Create(ctx context.Context, userID, deviceID, protocol, country, region, preferredNode string) (CreateResult, error) {
	if deviceID == "" {
		return CreateResult{}, ErrValidation
	}
	if protocol == "" {
		protocol = store.ProtocolVLESS
	}
	protocol = store.CanonicalProtocol(protocol)
	if err := entitlement.Check(ctx, s.subs, userID); err != nil {
		if errors.Is(err, store.ErrSubscriptionExpired) {
			return CreateResult{}, ErrSubscriptionExpired
		}
		return CreateResult{}, err
	}
	dev, err := s.devices.GetDeviceByID(ctx, deviceID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return CreateResult{}, ErrDeviceNotFound
		}
		return CreateResult{}, err
	}
	if dev.UserID != userID || dev.Status != "active" {
		return CreateResult{}, ErrForbidden
	}
	allowed, err := deviceWithinSeats(ctx, s.subs, s.devices, userID, deviceID, s.now())
	if err != nil {
		return CreateResult{}, err
	}
	if !allowed {
		if err := s.RevokeByDevice(ctx, deviceID); err != nil {
			return CreateResult{}, err
		}
		return CreateResult{}, ErrTooManyDevices
	}

	// Idempotent reuse of live allocation for this device. A VLESS allocation whose
	// node went down, or that is not the node the user just picked, is replaced.
	preferred := strings.TrimSpace(preferredNode)
	if live, err := s.allocs.GetLiveByDevice(ctx, deviceID); err == nil {
		ep, eerr := s.endpoints.GetEndpointByID(ctx, live.EndpointID)
		if eerr != nil {
			return CreateResult{}, eerr
		}
		// An allocation without a UUID predates 000008 (plaintext column dropped):
		// it can never be served again, so replace it like a dead-node allocation.
		move := preferred != "" && !strings.EqualFold(ep.NodeName, preferred)
		replace := store.IsVLESS(ep.Protocol) && (!selectable(ep) || live.VLESSUUID == "" || move)
		if replace {
			if move {
				list, lerr := s.listForProtocol(ctx, protocol, country)
				if lerr != nil {
					return CreateResult{}, lerr
				}
				if _, ok := preferredEndpoint(list, preferred); !ok {
					return CreateResult{}, ErrNodeUnavailable
				}
			}
			if err := s.revokeAllocation(ctx, live); err != nil {
				return CreateResult{}, err
			}
		} else {
			cfg, cerr := s.configs.GetActiveByAllocation(ctx, live.ID)
			if cerr != nil {
				return CreateResult{}, cerr
			}
			if store.IsVLESS(ep.Protocol) {
				// Same UUID, fresh fail-over list: nodes may have come and gone.
				if cfg, cerr = s.reissue(ctx, cfg, false); cerr != nil {
					return CreateResult{}, cerr
				}
			}
			cands := nodeselector.Rank([]store.Endpoint{ep}, nodeselector.Query{PreferredNode: preferredNode, Limit: 1})
			return CreateResult{
				Allocation: live, Configuration: cfg, Endpoint: ep, Candidates: cands,
				APIStatus: apiStatus(live.Status), Created: false,
			}, nil
		}
	} else if !errors.Is(err, store.ErrNotFound) {
		return CreateResult{}, err
	}

	n, err := s.allocs.CountLiveByDevice(ctx, deviceID)
	if err != nil {
		return CreateResult{}, err
	}
	if n >= 1 {
		return CreateResult{}, ErrTooManyAllocations
	}

	list, err := s.listForProtocol(ctx, protocol, country)
	if err != nil {
		return CreateResult{}, err
	}
	ranked := nodeselector.Rank(list, nodeselector.Query{
		Protocol: protocol, Country: country, Region: region,
		PreferredNode: preferredNode, Limit: nodeselector.DefaultLimit,
	})
	if len(ranked) == 0 {
		return CreateResult{}, ErrNodeUnavailable
	}
	ep := ranked[0].Endpoint
	if preferred != "" {
		match, ok := preferredEndpoint(list, preferred)
		if !ok {
			return CreateResult{}, ErrNodeUnavailable
		}
		ep = match
	}

	used, err := s.allocs.ListLiveIPs(ctx, ep.ID)
	if err != nil {
		return CreateResult{}, err
	}
	ip, err := ipam.NextHost(ep.Subnet, used)
	if err != nil {
		return CreateResult{}, ErrNodeUnavailable
	}

	now := s.now()
	status := "pending"
	apiSt := "provisioning"
	if s.autoActive {
		status = "active"
		apiSt = "active"
	}
	alloc := store.Allocation{
		ID: id.NewUUID(), UserID: userID, DeviceID: deviceID, EndpointID: ep.ID,
		IP: ip, PeerPublicKey: append([]byte(nil), dev.PublicKey...), Status: status,
		CreatedAt: now, UpdatedAt: now,
	}
	if store.IsVLESS(ep.Protocol) {
		alloc.VLESSUUID = id.NewUUID()
	}
	if err := s.allocs.CreateAllocation(ctx, alloc); err != nil {
		if errors.Is(err, store.ErrConflict) {
			return CreateResult{}, ErrTooManyAllocations
		}
		return CreateResult{}, err
	}

	parts, err := buildParts(alloc, ep, endpointsOf(ranked))
	if err != nil {
		_ = s.allocs.SetAllocationStatus(ctx, alloc.ID, "failed", s.now())
		return CreateResult{}, err
	}
	partsBytes, err := mycrypto.CanonicalJSON(parts)
	if err != nil {
		_ = s.allocs.SetAllocationStatus(ctx, alloc.ID, "failed", s.now())
		return CreateResult{}, err
	}
	blob, hash, err := mycrypto.Envelope(s.kek, partsBytes)
	if err != nil {
		_ = s.allocs.SetAllocationStatus(ctx, alloc.ID, "failed", s.now())
		return CreateResult{}, err
	}
	sig, _, err := s.signer.SignParts(1, parts)
	if err != nil {
		_ = s.allocs.SetAllocationStatus(ctx, alloc.ID, "failed", s.now())
		return CreateResult{}, err
	}
	cfg := store.Configuration{
		ID: id.NewUUID(), AllocationID: alloc.ID, DeviceID: deviceID, Version: 1,
		ContentEncrypted: blob, ContentHash: hash, Signature: sig, Status: "active",
		CreatedAt: now, UpdatedAt: now,
	}
	if err := s.configs.CreateConfiguration(ctx, cfg); err != nil {
		_ = s.allocs.SetAllocationStatus(ctx, alloc.ID, "failed", s.now())
		return CreateResult{}, err
	}
	// Bump desired-state version so the node-agent poll returns immediately.
	s.notifyEndpoint(ctx, ep)
	return CreateResult{
		Allocation: alloc, Configuration: cfg, Endpoint: ep, Candidates: ranked,
		APIStatus: apiSt, Created: true,
	}, nil
}

// notifyStateChange increments the node state version and wakes pollers.
func (s *Service) notifyStateChange(ctx context.Context, nodeID string) error {
	var err error
	if s.nodeState != nil {
		_, err = s.nodeState.IncrementStateVersion(ctx, nodeID)
	}
	if s.notifier != nil {
		s.notifier.Notify(nodeID)
	}
	return err
}

// Revoke deletes (revokes) a connection owned by the user.
func (s *Service) Revoke(ctx context.Context, userID, connectionID string) error {
	a, err := s.allocs.GetAllocationByID(ctx, connectionID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return ErrNotFound
		}
		return err
	}
	if a.UserID != userID {
		return ErrForbidden
	}
	if a.Status == "revoked" {
		return nil
	}
	return s.revokeAllocation(ctx, a)
}

// TrimExcessDevices drops live tunnels of devices past the seat limit.
// The device row stays so the user can unbind it. Oldest devices keep their tunnel.
func (s *Service) TrimExcessDevices(ctx context.Context, now time.Time) (int, error) {
	ids, err := s.devices.ListOverLimitDeviceIDs(ctx, now)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, id := range ids {
		if _, err := s.allocs.GetLiveByDevice(ctx, id); errors.Is(err, store.ErrNotFound) {
			continue
		} else if err != nil {
			return n, err
		}
		if err := s.RevokeByDevice(ctx, id); err != nil {
			return n, err
		}
		n++
	}
	return n, nil
}

// deviceWithinSeats reports whether deviceID is among the oldest active devices
// that fit the live subscription's seat limit.
func deviceWithinSeats(ctx context.Context, subs store.SubscriptionStore, devices store.DeviceStore, userID, deviceID string, now time.Time) (bool, error) {
	_, plan, err := subs.GetActiveByUser(ctx, userID)
	if err != nil {
		return false, err
	}
	slots, err := subs.ListLiveDeviceSlots(ctx, userID, now)
	if err != nil {
		return false, err
	}
	limit := plan.MaxDevices + len(slots)
	list, err := devices.ListDevicesByUser(ctx, userID)
	if err != nil {
		return false, err
	}
	rank := 0
	for _, d := range list {
		if d.Status != "active" {
			continue
		}
		rank++
		if d.ID == deviceID {
			return rank <= limit, nil
		}
	}
	return false, nil
}

// RevokeByDevice revokes every live connection of a device (device unlinked), so
// its credentials disappear from node desired state.
func (s *Service) RevokeByDevice(ctx context.Context, deviceID string) error {
	for {
		a, err := s.allocs.GetLiveByDevice(ctx, deviceID)
		if errors.Is(err, store.ErrNotFound) {
			return nil
		}
		if err != nil {
			return err
		}
		if err := s.revokeAllocation(ctx, a); err != nil {
			return err
		}
	}
}

func (s *Service) revokeAllocation(ctx context.Context, a store.Allocation) error {
	now := s.now()
	if err := s.configs.RevokeByAllocation(ctx, a.ID, now); err != nil {
		return err
	}
	if err := s.allocs.SetAllocationStatus(ctx, a.ID, "revoked", now); err != nil {
		return err
	}
	if ep, err := s.endpoints.GetEndpointByID(ctx, a.EndpointID); err == nil {
		s.notifyEndpoint(ctx, ep)
	}
	return nil
}

// notifyEndpoint wakes the agents that serve this endpoint's allocations: every
// Xray node for VLESS (shared user set), otherwise only the endpoint's node.
func (s *Service) notifyEndpoint(ctx context.Context, ep store.Endpoint) {
	// Errors are non-fatal here: SyncVLESS and the agent's periodic poll converge.
	if !store.IsVLESS(ep.Protocol) {
		_ = s.notifyStateChange(ctx, ep.NodeID)
		return
	}
	_ = s.notifyVLESSNodes(ctx)
}

// notifyVLESSNodes bumps every Xray node's state version. An error means at least
// one node was not bumped, so the caller should retry on the next tick.
func (s *Service) notifyVLESSNodes(ctx context.Context) error {
	all, err := s.endpoints.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	seen := map[string]bool{}
	var firstErr error
	for _, e := range all {
		if store.IsVLESS(e.Protocol) && !seen[e.NodeID] {
			seen[e.NodeID] = true
			if err := s.notifyStateChange(ctx, e.NodeID); err != nil && firstErr == nil {
				firstErr = err
			}
		}
	}
	return firstErr
}

// ProbeEdges dials the public TLS port of every node whose agent is still
// calling home. Two failures in a row take the node out of the pool.
func (s *Service) ProbeEdges(ctx context.Context, freshFor time.Duration) error {
	if freshFor <= 0 {
		freshFor = 90 * time.Second
	}
	hosts, err := s.endpoints.ListEdgeHosts(ctx, s.now().Add(-freshFor))
	if err != nil {
		return err
	}
	var first error
	for _, h := range hosts {
		ok, reason := nodehealth.DialTLS(ctx, h.Hostname)
		if err := s.endpoints.ApplyEdgeProbe(ctx, h.NodeID, ok, reason); err != nil && first == nil {
			first = err
		}
	}
	return first
}

// SyncVLESS marks nodes OFFLINE after missed heartbeats and re-pushes the Xray
// user set when it changed for reasons other than connect/revoke (subscription
// expiry). Called by the scheduler.
func (s *Service) SyncVLESS(ctx context.Context, staleAfter time.Duration) error {
	now := s.now()
	if _, err := s.endpoints.MarkStaleOffline(ctx, now.Add(-staleAfter)); err != nil {
		return err
	}
	live, err := s.allocs.ListLiveEntitledVLESS(ctx, now)
	if err != nil {
		return err
	}
	h := sha256.New()
	for _, a := range live {
		h.Write([]byte(a.VLESSUUID))
	}
	sum := hex.EncodeToString(h.Sum(nil))
	s.mu.Lock()
	changed := sum != s.vlessSetHash
	s.mu.Unlock()
	if !changed {
		return nil
	}
	if err := s.notifyVLESSNodes(ctx); err != nil {
		return err
	}
	s.mu.Lock()
	s.vlessSetHash = sum
	s.mu.Unlock()
	return nil
}

func (s *Service) listForProtocol(ctx context.Context, protocol, country string) ([]store.Endpoint, error) {
	if !store.IsVLESS(protocol) {
		return s.endpoints.ListSelectable(ctx, protocol, country)
	}
	all, err := s.endpoints.ListSelectable(ctx, "", country)
	if err != nil {
		return nil, err
	}
	var out []store.Endpoint
	for _, e := range all {
		if store.IsVLESS(e.Protocol) {
			out = append(out, e)
		}
	}
	return out, nil
}

func selectable(ep store.Endpoint) bool {
	return ep.State == "HEALTHY" || ep.State == "DEGRADED"
}

// preferredEndpoint is the node the user picked, if it is still selectable.
// Load does not matter: an explicit choice beats a freer server.
func preferredEndpoint(list []store.Endpoint, name string) (store.Endpoint, bool) {
	for _, e := range list {
		if selectable(e) && strings.EqualFold(e.NodeName, name) {
			return e, true
		}
	}
	return store.Endpoint{}, false
}

func endpointsOf(ranked []nodeselector.Scored) []store.Endpoint {
	out := make([]store.Endpoint, 0, len(ranked))
	for _, r := range ranked {
		out = append(out, r.Endpoint)
	}
	return out
}

// ReissueConfig replaces the active config for an allocation with version+1
// (same peer/IP; re-envelope + re-sign). Used by the config-TTL scheduler (P4-M5).
func (s *Service) ReissueConfig(ctx context.Context, old store.Configuration) (store.Configuration, error) {
	return s.reissue(ctx, old, true)
}

func (s *Service) reissue(ctx context.Context, old store.Configuration, notify bool) (store.Configuration, error) {
	if old.Status != "active" {
		return store.Configuration{}, ErrNotFound
	}
	alloc, err := s.allocs.GetAllocationByID(ctx, old.AllocationID)
	if err != nil {
		return store.Configuration{}, err
	}
	if alloc.Status != "pending" && alloc.Status != "active" {
		return store.Configuration{}, ErrNotFound
	}
	ep, err := s.endpoints.GetEndpointByID(ctx, alloc.EndpointID)
	if err != nil {
		return store.Configuration{}, err
	}
	now := s.now()
	parts, err := buildParts(alloc, ep, s.failoverServers(ctx, ep))
	if err != nil {
		return store.Configuration{}, err
	}
	partsBytes, err := mycrypto.CanonicalJSON(parts)
	if err != nil {
		return store.Configuration{}, err
	}
	blob, hash, err := mycrypto.Envelope(s.kek, partsBytes)
	if err != nil {
		return store.Configuration{}, err
	}
	nextVer := old.Version + 1
	sig, _, err := s.signer.SignParts(nextVer, parts)
	if err != nil {
		return store.Configuration{}, err
	}
	rotated := now
	cfg := store.Configuration{
		ID: id.NewUUID(), AllocationID: alloc.ID, DeviceID: old.DeviceID, Version: nextVer,
		ContentEncrypted: blob, ContentHash: hash, Signature: sig, Status: "active",
		RotatedAt: &rotated, CreatedAt: now, UpdatedAt: now,
	}
	if err := s.configs.ReplaceActiveConfiguration(ctx, cfg, now); err != nil {
		return store.Configuration{}, err
	}
	if notify {
		s.notifyEndpoint(ctx, ep)
	}
	return cfg, nil
}

// failoverServers lists ep first, then the best other VLESS endpoints, so a
// client can walk to a live node without asking the CP again.
func (s *Service) failoverServers(ctx context.Context, ep store.Endpoint) []store.Endpoint {
	servers := []store.Endpoint{ep}
	if !store.IsVLESS(ep.Protocol) {
		return servers
	}
	list, err := s.listForProtocol(ctx, ep.Protocol, "")
	if err != nil {
		return servers
	}
	for _, r := range nodeselector.Rank(list, nodeselector.Query{Limit: nodeselector.DefaultLimit + 1}) {
		if r.Endpoint.ID != ep.ID && len(servers) < nodeselector.DefaultLimit {
			servers = append(servers, r.Endpoint)
		}
	}
	return servers
}

// RotateAgedConfigs re-issues every active config older than cutoff. Returns count rotated.
func (s *Service) RotateAgedConfigs(ctx context.Context, cutoff time.Time) (int, error) {
	aged, err := s.configs.ListActiveOlderThan(ctx, cutoff)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, c := range aged {
		if _, err := s.ReissueConfig(ctx, c); err != nil {
			if errors.Is(err, ErrNotFound) {
				continue
			}
			return n, err
		}
		n++
	}
	return n, nil
}

// xraySettings mirrors vpn_endpoints.xray (migration 000007).
type xraySettings struct {
	Transport string        `json:"transport"`
	Path      string        `json:"path"`
	Host      string        `json:"host"`
	SNI       string        `json:"sni"`
	Port      int           `json:"port"`
	Mode      string        `json:"mode"`
	Alt       *xraySettings `json:"alt,omitempty"`
}

// xrayServers renders the node's primary transport and, when configured, the
// alternate one (WS and XHTTP on the same host). Missing settings fall back to
// the node hostname, TLS on 443 and WebSocket.
func xrayServers(ep store.Endpoint) ([]map[string]any, error) {
	var x xraySettings
	if len(ep.Xray) > 0 {
		if err := json.Unmarshal(ep.Xray, &x); err != nil {
			return nil, fmt.Errorf("endpoint %s xray json: %w", ep.ID, err)
		}
	}
	first, err := renderServer(ep, x)
	if err != nil {
		return nil, err
	}
	out := []map[string]any{first}
	if x.Alt != nil && x.Alt.Path != "" {
		alt := *x.Alt
		if alt.Host == "" {
			alt.Host = x.Host
		}
		if alt.SNI == "" {
			alt.SNI = x.SNI
		}
		if alt.Port == 0 {
			alt.Port = x.Port
		}
		second, err := renderServer(ep, alt)
		if err != nil {
			return nil, err
		}
		out = append(out, second)
	}
	return out, nil
}

func renderServer(ep store.Endpoint, x xraySettings) (map[string]any, error) {
	if x.Transport == "" {
		x.Transport = "ws"
	}
	if x.Host == "" {
		x.Host = ep.Hostname
	}
	if x.Host == "" {
		x.Host = "127.0.0.1"
	}
	if x.SNI == "" {
		x.SNI = x.Host
	}
	if x.Port == 0 {
		x.Port = 443
	}
	if x.Path == "" {
		return nil, fmt.Errorf("endpoint %s: xray.path not configured", ep.ID)
	}
	srv := map[string]any{
		"node":      ep.NodeName,
		"country":   ep.Country,
		"address":   x.Host,
		"port":      x.Port,
		"sni":       x.SNI,
		"host":      x.Host,
		"path":      x.Path,
		"network":   x.Transport,
		"security":  "tls",
		"transport": x.Transport,
	}
	if x.Mode != "" {
		srv["mode"] = x.Mode
	}
	return srv, nil
}

// xrayPart builds ConfigParts["xray"]: the allocation's VLESS credential and the
// ordered server list (primary first, then fail-over candidates). The primary's
// fields are also flattened at the top level for single-server clients.
func xrayPart(a store.Allocation, primary store.Endpoint, servers []store.Endpoint) (any, error) {
	if !store.IsVLESS(primary.Protocol) {
		return nil, nil
	}
	if a.VLESSUUID == "" {
		return nil, fmt.Errorf("allocation %s: vless uuid missing", a.ID)
	}
	entries, err := xrayServers(primary)
	if err != nil {
		return nil, err
	}
	first := entries[0]
	var list []any
	for _, srv := range entries {
		list = append(list, srv)
	}
	for _, ep := range servers {
		if ep.ID == primary.ID || !store.IsVLESS(ep.Protocol) {
			continue
		}
		more, err := xrayServers(ep)
		if err != nil {
			continue
		}
		for _, srv := range more {
			list = append(list, srv)
		}
	}
	out := map[string]any{"uuid": a.VLESSUUID, "servers": list}
	for k, v := range first {
		out[k] = v
	}
	return out, nil
}

func apiStatus(db string) string {
	switch db {
	case "pending":
		return "provisioning"
	default:
		return db
	}
}

func buildParts(a store.Allocation, ep store.Endpoint, servers []store.Endpoint) (map[string]any, error) {
	xp, err := xrayPart(a, ep, servers)
	if err != nil {
		return nil, err
	}
	var obf any
	if len(ep.Obfuscation) > 0 {
		if err := json.Unmarshal(ep.Obfuscation, &obf); err != nil {
			return nil, fmt.Errorf("obfuscation json: %w", err)
		}
	}
	host := ep.Hostname
	if host == "" {
		host = "127.0.0.1"
	}
	return map[string]any{
		"interface": map[string]any{
			"address": a.IP + "/32",
			"dns":     []any{"10.200.0.1"},
			"mtu":     1420,
		},
		"peer": map[string]any{
			"server_public_key": base64.StdEncoding.EncodeToString(ep.PublicKey),
			"endpoint":          fmt.Sprintf("%s:%d", host, ep.Port),
			"allowed_ips":       []any{"0.0.0.0/0", "::/0"},
		},
		"protocol": map[string]any{
			"name":        ep.Protocol,
			"obfuscation": obf,
		},
		"xray": xp,
	}, nil
}
