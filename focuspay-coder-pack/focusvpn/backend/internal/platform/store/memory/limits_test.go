package memory

import (
	"context"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/nodehealth"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func TestPulseOfflineReasonAndPause(t *testing.T) {
	st := New()
	ctx := context.Background()
	now := time.Date(2026, 10, 8, 10, 0, 0, 0, time.UTC)
	if _, _, err := st.UpsertVLESSNode(ctx, store.VLESSNode{Name: "DE1", Country: "DE", Hostname: "de.example", Capacity: 100}); err != nil {
		t.Fatal(err)
	}
	eps, err := st.ListEndpoints(ctx)
	if err != nil || len(eps) != 1 {
		t.Fatal(err, len(eps))
	}
	nodeID := eps[0].NodeID
	if err := st.RecordNodePulse(ctx, nodeID, 1, now, &store.NodeHealth{OK: true}); err != nil {
		t.Fatal(err)
	}
	bad := &store.NodeHealth{Reason: "Xray не отвечает: connection refused"}
	if err := st.RecordNodePulse(ctx, nodeID, 1, now, bad); err != nil {
		t.Fatal(err)
	}
	eps, _ = st.ListEndpoints(ctx)
	if eps[0].State != "HEALTHY" {
		t.Fatalf("one miss stays up: %s", eps[0].State)
	}
	if err := st.RecordNodePulse(ctx, nodeID, 1, now.Add(time.Second), bad); err != nil {
		t.Fatal(err)
	}
	eps, _ = st.ListEndpoints(ctx)
	if eps[0].State != "OFFLINE" {
		t.Fatalf("state: %s", eps[0].State)
	}
	sum, err := st.Summary(ctx, now)
	if err != nil || len(sum.Nodes) != 1 || sum.Nodes[0].StatusReason == "" {
		t.Fatalf("reason: %+v %v", sum.Nodes, err)
	}
	if err := st.RecordNodeHeartbeat(ctx, nodeID, 1, now.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}
	eps, _ = st.ListEndpoints(ctx)
	if eps[0].State != "OFFLINE" {
		t.Fatal("bare heartbeat must not clear a probe failure")
	}
	if err := st.RecordNodePulse(ctx, nodeID, 1, now.Add(3*time.Second), &store.NodeHealth{OK: true}); err != nil {
		t.Fatal(err)
	}
	eps, _ = st.ListEndpoints(ctx)
	if eps[0].State != "HEALTHY" {
		t.Fatalf("green probe: %s", eps[0].State)
	}

	allocID := "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
	userID := "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
	st.SeedSubscription(store.Subscription{UserID: userID, Status: "active", EndsAt: now.Add(24 * time.Hour)})
	if err := st.CreateAllocation(ctx, store.Allocation{
		ID: allocID, UserID: userID, DeviceID: "cccccccc-cccc-cccc-cccc-cccccccccccc",
		EndpointID: eps[0].ID, Status: "active", VLESSUUID: "dddddddd-dddd-dddd-dddd-dddddddddddd",
	}); err != nil {
		t.Fatal(err)
	}
	live, err := st.ListLiveEntitledVLESS(ctx, now)
	if err != nil || len(live) != 1 {
		t.Fatalf("live before pause: %+v %v", live, err)
	}
	fresh, err := st.UpsertAllocationPause(ctx, store.AllocationPause{
		AllocationID: allocID, IPCount: 5, Reason: "5 адресов сразу, пауза до 10:15 UTC",
		Until: now.Add(15 * time.Minute), NodeID: nodeID, UpdatedAt: now,
	})
	if err != nil || !fresh {
		t.Fatalf("fresh=%v %v", fresh, err)
	}
	live, _ = st.ListLiveEntitledVLESS(ctx, now)
	if len(live) != 0 {
		t.Fatalf("paused uuid must leave the desired set: %+v", live)
	}
	sum, _ = st.Summary(ctx, now)
	if len(sum.Pauses) != 1 || sum.Pauses[0].NodeName != "DE1" {
		t.Fatalf("pauses: %+v", sum.Pauses)
	}
	again, err := st.UpsertAllocationPause(ctx, store.AllocationPause{
		AllocationID: allocID, IPCount: 6, Reason: "ещё", Until: now.Add(20 * time.Minute), UpdatedAt: now,
	})
	if err != nil || again {
		t.Fatalf("extending an active pause is not a new wake: fresh=%v %v", again, err)
	}

	ids, err := st.MarkStaleOffline(ctx, now.Add(time.Hour))
	if err != nil || len(ids) != 1 {
		t.Fatalf("stale: %v %v", ids, err)
	}
	eps, _ = st.ListEndpoints(ctx)
	if eps[0].State != "OFFLINE" {
		t.Fatalf("stale state: %s", eps[0].State)
	}
	sum, _ = st.Summary(ctx, now)
	if sum.Nodes[0].StatusReason != nodehealth.StaleReason {
		t.Fatalf("stale reason: %q", sum.Nodes[0].StatusReason)
	}
}
