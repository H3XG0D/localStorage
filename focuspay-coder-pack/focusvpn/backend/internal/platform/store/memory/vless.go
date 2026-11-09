package memory

import (
	"context"
	"sort"
	"time"

	"focusvpn.example/focusvpn/backend/internal/nodehealth"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

type nodeMeta struct {
	Reason      string
	HealthFails int
	ProbeFails  int
}

// Reports returns the operator report sub-store.
func (s *Store) Reports() store.ReportStore { return s }

func (s *Store) UpsertVLESSNode(_ context.Context, n store.VLESSNode) (string, string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if n.Capacity <= 0 {
		n.Capacity = 500
	}
	if n.Region == "" {
		n.Region = "unspecified"
	}
	var used []string
	for _, e := range s.endpoints {
		used = append(used, e.Subnet)
	}
	for id, e := range s.endpoints {
		if e.NodeName != n.Name || !store.IsVLESS(e.Protocol) {
			continue
		}
		e.Country = n.Country
		e.Region = n.Region
		e.Hostname = n.Hostname
		e.Capacity = n.Capacity
		e.Xray = append([]byte(nil), n.Xray...)
		s.endpoints[id] = e
		return e.NodeID, e.ID, nil
	}
	nodeID, epID := id.NewUUID(), id.NewUUID()
	s.endpoints[epID] = store.Endpoint{
		ID: epID, NodeID: nodeID, NodeName: n.Name, Country: n.Country, Region: n.Region,
		Hostname: n.Hostname, Protocol: store.ProtocolVLESS, Port: 443, State: "OFFLINE",
		Subnet: store.AssignSubnet(used, n.Subnet), Capacity: n.Capacity,
		Xray: append([]byte(nil), n.Xray...),
	}
	if _, ok := s.nodeVers[nodeID]; !ok {
		s.nodeVers[nodeID] = 0
	}
	return nodeID, epID, nil
}

func (s *Store) ListEndpoints(_ context.Context) ([]store.Endpoint, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]store.Endpoint, 0, len(s.endpoints))
	for _, e := range s.endpoints {
		out = append(out, e)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

func (s *Store) RecordNodeHeartbeat(ctx context.Context, nodeID string, online int, at time.Time) error {
	return s.RecordNodePulse(ctx, nodeID, online, at, nil)
}

func (s *Store) RecordNodePulse(_ context.Context, nodeID string, online int, at time.Time, health *store.NodeHealth) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.touchNodeLocked(nodeID, online, at) {
		return store.ErrNotFound
	}
	st := s.nodeStatusLocked(nodeID)
	if health == nil {
		st = nodehealth.ApplyLegacyHeartbeat(st)
	} else {
		st = nodehealth.ApplyAgent(st, nodehealth.Report{OK: health.OK, Degraded: health.Degraded, Reason: health.Reason})
	}
	s.saveNodeStatusLocked(nodeID, st)
	return nil
}

func (s *Store) ApplyEdgeProbe(_ context.Context, nodeID string, ok bool, reason string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, known := s.nodeIDsLocked()[nodeID]; !known {
		return store.ErrNotFound
	}
	st := nodehealth.ApplyProbe(s.nodeStatusLocked(nodeID), ok, reason)
	s.saveNodeStatusLocked(nodeID, st)
	return nil
}

func (s *Store) ListEdgeHosts(_ context.Context, since time.Time) ([]store.EdgeHost, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	seen := map[string]bool{}
	var out []store.EdgeHost
	for _, e := range s.endpoints {
		if seen[e.NodeID] || e.Hostname == "" || e.LastHeartbeatAt == nil || e.LastHeartbeatAt.Before(since) {
			continue
		}
		if s.nodeStatusLocked(e.NodeID).State == "DRAINING" {
			continue
		}
		seen[e.NodeID] = true
		out = append(out, store.EdgeHost{NodeID: e.NodeID, Hostname: e.Hostname})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].NodeID < out[j].NodeID })
	return out, nil
}

func (s *Store) MarkStaleOffline(_ context.Context, before time.Time) ([]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []string
	for nodeID := range s.nodeIDsLocked() {
		var hb *time.Time
		for _, e := range s.endpoints {
			if e.NodeID == nodeID && e.LastHeartbeatAt != nil {
				hb = e.LastHeartbeatAt
			}
		}
		if hb == nil || !hb.Before(before) {
			continue
		}
		prev := s.nodeStatusLocked(nodeID)
		next := nodehealth.ApplyStale(prev)
		if !nodehealth.Changed(prev, next) {
			continue
		}
		s.saveNodeStatusLocked(nodeID, next)
		out = append(out, nodeID)
	}
	sort.Strings(out)
	return out, nil
}

func (s *Store) touchNodeLocked(nodeID string, online int, at time.Time) bool {
	found := false
	t := at
	for id, e := range s.endpoints {
		if e.NodeID != nodeID {
			continue
		}
		found = true
		e.LastHeartbeatAt = &t
		e.PeerCount = online
		e.Load = 0
		if e.Capacity > 0 {
			e.Load = float64(online) / float64(e.Capacity)
		}
		s.endpoints[id] = e
	}
	return found
}

func (s *Store) nodeIDsLocked() map[string]bool {
	out := map[string]bool{}
	for _, e := range s.endpoints {
		out[e.NodeID] = true
	}
	return out
}

func (s *Store) nodeStatusLocked(nodeID string) nodehealth.Status {
	st := nodehealth.Status{State: "OFFLINE"}
	for _, e := range s.endpoints {
		if e.NodeID == nodeID && e.State != "" {
			st.State = e.State
			break
		}
	}
	if s.nodeMeta != nil {
		if m, ok := s.nodeMeta[nodeID]; ok {
			st.Reason = m.Reason
			st.HealthFails = m.HealthFails
			st.ProbeFails = m.ProbeFails
		}
	}
	return st
}

func (s *Store) saveNodeStatusLocked(nodeID string, st nodehealth.Status) {
	if s.nodeMeta == nil {
		s.nodeMeta = map[string]nodeMeta{}
	}
	s.nodeMeta[nodeID] = nodeMeta{Reason: st.Reason, HealthFails: st.HealthFails, ProbeFails: st.ProbeFails}
	for id, e := range s.endpoints {
		if e.NodeID != nodeID {
			continue
		}
		e.State = st.State
		s.endpoints[id] = e
	}
}

func (s *Store) ListLiveEntitledVLESS(_ context.Context, now time.Time) ([]store.Allocation, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.Allocation
	for _, a := range s.allocs {
		if a.VLESSUUID == "" || (a.Status != "pending" && a.Status != "active") {
			continue
		}
		if ep, ok := s.endpoints[a.EndpointID]; !ok || !store.IsVLESS(ep.Protocol) {
			continue
		}
		sub, ok := s.subs[a.UserID]
		if !ok || (sub.Status != "active" && sub.Status != "trialing") || !sub.EndsAt.After(now) {
			continue
		}
		if p, ok := s.pauses[a.ID]; ok && p.Until.After(now) {
			continue
		}
		out = append(out, a)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

type trafficKey struct {
	node string
	day  string
}

func (s *Store) AddNodeTraffic(_ context.Context, nodeID string, day time.Time, rx, tx int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.traffic == nil {
		s.traffic = map[trafficKey][2]int64{}
	}
	k := trafficKey{nodeID, day.UTC().Format("2006-01-02")}
	v := s.traffic[k]
	s.traffic[k] = [2]int64{v[0] + rx, v[1] + tx}
	return nil
}

func (s *Store) Summary(_ context.Context, now time.Time) (store.ReportSummary, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var r store.ReportSummary
	for _, sub := range s.subs {
		if (sub.Status == "active" || sub.Status == "trialing") && sub.EndsAt.After(now) {
			r.ActiveSubscriptions++
		}
	}
	for _, d := range s.devices {
		if d.Status == "active" {
			r.ActiveDevices++
		}
	}
	for _, a := range s.allocs {
		if a.Status == "pending" || a.Status == "active" {
			r.LiveConnections++
		}
	}
	for _, ev := range s.billing {
		age := now.Sub(ev.CreatedAt)
		if ev.Kind == "trial" {
			if age <= 30*24*time.Hour {
				r.Trials30d++
			}
			continue
		}
		if age <= 24*time.Hour {
			r.Purchases1d++
		}
		if age <= 7*24*time.Hour {
			r.Purchases7d++
		}
		if age <= 30*24*time.Hour {
			r.Purchases30d++
			r.PurchasedDays30d += ev.Days
		}
	}
	nodes := map[string]*store.NodeReport{}
	for _, e := range s.endpoints {
		n, ok := nodes[e.NodeID]
		if !ok {
			n = &store.NodeReport{NodeID: e.NodeID, Name: e.NodeName, Country: e.Country, State: e.State, Capacity: e.Capacity}
			nodes[e.NodeID] = n
		}
		if stateRank(e.State) < stateRank(n.State) {
			n.State = e.State
		}
		if e.PeerCount > n.Online {
			n.Online = e.PeerCount
		}
		if e.Load > n.Load {
			n.Load = e.Load
		}
		if e.LastHeartbeatAt != nil {
			n.LastHeartbeatAt = e.LastHeartbeatAt
		}
		if s.nodeMeta != nil {
			if m, ok := s.nodeMeta[e.NodeID]; ok && m.Reason != "" {
				n.StatusReason = m.Reason
			}
		}
	}
	today := now.UTC().Format("2006-01-02")
	cutoff := now.UTC().AddDate(0, 0, -30).Format("2006-01-02")
	for k, v := range s.traffic {
		n, ok := nodes[k.node]
		if !ok {
			continue
		}
		if k.day == today {
			n.RxToday += v[0]
			n.TxToday += v[1]
		}
		if k.day > cutoff {
			n.Rx30d += v[0]
			n.Tx30d += v[1]
		}
	}
	for _, n := range nodes {
		r.Nodes = append(r.Nodes, *n)
	}
	sort.Slice(r.Nodes, func(i, j int) bool { return r.Nodes[i].Name < r.Nodes[j].Name })
	for _, p := range s.pauses {
		if !p.Until.After(now) {
			continue
		}
		r.Pauses = append(r.Pauses, p)
	}
	sort.Slice(r.Pauses, func(i, j int) bool { return r.Pauses[i].Until.Before(r.Pauses[j].Until) })
	return r, nil
}

func (s *Store) UpsertAllocationPause(_ context.Context, p store.AllocationPause) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.pauses == nil {
		s.pauses = map[string]store.AllocationPause{}
	}
	now := p.UpdatedAt
	if now.IsZero() {
		now = time.Now()
	}
	prev, exists := s.pauses[p.AllocationID]
	fresh := !exists || !prev.Until.After(now)
	if p.NodeName == "" {
		for _, e := range s.endpoints {
			if e.NodeID == p.NodeID {
				p.NodeName = e.NodeName
				break
			}
		}
	}
	s.pauses[p.AllocationID] = p
	return fresh, nil
}

func stateRank(s string) int {
	switch s {
	case "OFFLINE":
		return 0
	case "DRAINING":
		return 1
	case "DEGRADED":
		return 2
	default:
		return 3
	}
}
