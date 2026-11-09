package connections_test

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/connections"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

type vlessFixture struct {
	st     *memory.Store
	svc    *connections.Service
	kek    mycrypto.KEK
	userID string
	devID  string
	sub    store.Subscription
}

func newVLESSFixture(t *testing.T) vlessFixture {
	t.Helper()
	st := memory.New()
	for _, ep := range []store.Endpoint{
		{ID: "ep-de1", NodeID: "n-de1", NodeName: "DE1", Country: "DE", Hostname: "de1.example", Protocol: "vless-ws",
			Port: 443, State: "HEALTHY", Subnet: "10.210.0.0/24", Load: 0.7, Capacity: 100,
			Xray: json.RawMessage(`{"transport":"xhttp","path":"/cdn/de1","mode":"auto"}`)},
		{ID: "ep-de2", NodeID: "n-de2", NodeName: "DE2", Country: "DE", Hostname: "de2.example", Protocol: "vless-ws",
			Port: 443, State: "HEALTHY", Subnet: "10.211.0.0/24", Load: 0.1, Capacity: 100,
			Xray: json.RawMessage(`{"transport":"ws","path":"/api/de2","alt":{"transport":"xhttp","path":"/cdn/de2","mode":"auto"}}`)},
		{ID: "ep-nl1", NodeID: "n-nl1", NodeName: "NL1", Country: "NL", Hostname: "nl1.example", Protocol: "vless-ws",
			Port: 443, State: "HEALTHY", Subnet: "10.212.0.0/24", Load: 0.4, Capacity: 100,
			Xray: json.RawMessage(`{"transport":"ws","path":"/api/nl1"}`)},
	} {
		st.SeedEndpoint(ep)
		_ = st.EnsureStateVersion(context.Background(), ep.NodeID)
	}
	st.SeedPlan(store.Plan{ID: "p-week", Code: "week", Name: "Week", MaxDevices: 1, PeriodDays: 7})
	userID, devID := id.NewUUID(), id.NewUUID()
	now := time.Now().UTC()
	sub := store.Subscription{ID: id.NewUUID(), UserID: userID, PlanID: "p-week", Status: "active",
		StartsAt: now, EndsAt: now.Add(7 * 24 * time.Hour)}
	st.SeedSubscription(sub)
	devPub := make([]byte, 32)
	_, _ = rand.Read(devPub)
	if err := st.CreateDevice(context.Background(), store.Device{
		ID: devID, UserID: userID, Name: "phone", Platform: "android", PublicKey: devPub,
		Status: "active", CreatedAt: now, UpdatedAt: now,
	}, 1); err != nil {
		t.Fatal(err)
	}
	_, cfgPriv, _ := ed25519.GenerateKey(rand.Reader)
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	kek := mycrypto.KEK{ID: "kek-v1", Key: key}
	st.UseKEK(kek)
	svc := connections.NewService(st.Devices(), st.Endpoints(), st.Allocations(), st.Configurations(),
		st.Subscriptions(), st.NodeState(), kek, mycrypto.NewConfigSigner(cfgPriv), true, nil)
	return vlessFixture{st: st, svc: svc, kek: kek, userID: userID, devID: devID, sub: sub}
}

func (f vlessFixture) xrayPart(t *testing.T, cfg store.Configuration) map[string]any {
	t.Helper()
	plain, err := mycrypto.OpenEnvelope(map[string]mycrypto.KEK{f.kek.ID: f.kek}, cfg.ContentEncrypted)
	if err != nil {
		t.Fatal(err)
	}
	var parts map[string]any
	if err := json.Unmarshal(plain, &parts); err != nil {
		t.Fatal(err)
	}
	x, _ := parts["xray"].(map[string]any)
	if x == nil {
		t.Fatalf("xray part missing: %s", plain)
	}
	return x
}

func TestVLESSConnectIssuesDeviceUUIDAndFailoverList(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	res, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if res.Endpoint.NodeName != "DE2" {
		t.Fatalf("least loaded node should be primary, got %s", res.Endpoint.NodeName)
	}
	if res.Allocation.VLESSUUID == "" {
		t.Fatal("allocation has no vless uuid")
	}
	sealed := f.st.SealedVLESS(res.Allocation.ID)
	if len(sealed) == 0 || bytes.Contains(sealed, []byte(res.Allocation.VLESSUUID)) {
		t.Fatal("vless uuid must be stored only as ciphertext")
	}
	x := f.xrayPart(t, res.Configuration)
	if x["uuid"] != res.Allocation.VLESSUUID {
		t.Fatalf("config uuid %v != allocation uuid", x["uuid"])
	}
	if x["path"] != "/api/de2" || x["network"] != "ws" || x["address"] != "de2.example" {
		t.Fatalf("primary flattened wrong: %v", x)
	}
	servers, _ := x["servers"].([]any)
	if len(servers) != 4 {
		t.Fatalf("want 4 servers (primary + its alt transport + 2 fail-over), got %d", len(servers))
	}
	order := []string{}
	for _, s := range servers {
		order = append(order, s.(map[string]any)["node"].(string))
	}
	if order[0] != "DE2" || order[1] != "DE2" || order[2] != "NL1" || order[3] != "DE1" {
		t.Fatalf("server order by load: %v", order)
	}
	if servers[1].(map[string]any)["transport"] != "xhttp" || servers[1].(map[string]any)["path"] != "/cdn/de2" {
		t.Fatalf("alt transport lost: %v", servers[1])
	}
	if servers[3].(map[string]any)["transport"] != "xhttp" {
		t.Fatalf("per-node transport lost: %v", servers[3])
	}
}

func TestVLESSDesiredSetFollowsRevokeAndExpiry(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	res, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	live, _ := f.st.ListLiveEntitledVLESS(ctx, time.Now())
	if len(live) != 1 || live[0].VLESSUUID != res.Allocation.VLESSUUID {
		t.Fatalf("desired set after connect: %+v", live)
	}

	expired := f.sub
	expired.EndsAt = time.Now().Add(-time.Minute)
	f.st.SeedSubscription(expired)
	if live, _ := f.st.ListLiveEntitledVLESS(ctx, time.Now()); len(live) != 0 {
		t.Fatalf("expired subscription must drop the user: %+v", live)
	}
	vBefore, _ := f.st.GetStateVersion(ctx, "n-nl1")
	if err := f.svc.SyncVLESS(ctx, time.Minute); err != nil {
		t.Fatal(err)
	}
	if v, _ := f.st.GetStateVersion(ctx, "n-nl1"); v <= vBefore {
		t.Fatal("expiry must bump every VLESS node state version")
	}

	f.st.SeedSubscription(f.sub)
	if err := f.svc.RevokeByDevice(ctx, f.devID); err != nil {
		t.Fatal(err)
	}
	if live, _ := f.st.ListLiveEntitledVLESS(ctx, time.Now()); len(live) != 0 {
		t.Fatalf("revoked device must leave desired set: %+v", live)
	}
}

func TestVLESSReconnectMovesOffDeadNode(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	first, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	stale := time.Now().Add(-10 * time.Minute)
	if err := f.st.RecordNodeHeartbeat(ctx, "n-de2", 5, stale); err != nil {
		t.Fatal(err)
	}
	if err := f.svc.SyncVLESS(ctx, 90*time.Second); err != nil {
		t.Fatal(err)
	}
	second, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if second.Endpoint.NodeName == "DE2" {
		t.Fatal("reconnect must not stay on an OFFLINE node")
	}
	if second.Allocation.ID == first.Allocation.ID {
		t.Fatal("dead-node allocation should be replaced")
	}
}

func TestVLESSReconnectRefreshesServerList(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	first, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	f.st.SeedEndpoint(store.Endpoint{ID: "ep-fi1", NodeID: "n-fi1", NodeName: "FI1", Country: "FI", Hostname: "fi1.example",
		Protocol: "vless", Port: 443, State: "HEALTHY", Subnet: "10.213.0.0/24", Load: 0.05, Capacity: 100,
		Xray: json.RawMessage(`{"transport":"ws","path":"/api/fi1"}`)})
	second, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if second.Allocation.ID != first.Allocation.ID || second.Created {
		t.Fatal("healthy allocation must be reused")
	}
	if second.Configuration.Version <= first.Configuration.Version {
		t.Fatalf("reuse must reissue the config: v%d -> v%d", first.Configuration.Version, second.Configuration.Version)
	}
	x := f.xrayPart(t, second.Configuration)
	if x["uuid"] != first.Allocation.VLESSUUID {
		t.Fatal("reissue must keep the device UUID")
	}
	found := false
	for _, s := range x["servers"].([]any) {
		if s.(map[string]any)["node"] == "FI1" {
			found = true
		}
	}
	if !found {
		t.Fatalf("new node missing from refreshed list: %v", x["servers"])
	}
	if active, err := f.st.GetActiveByAllocation(ctx, first.Allocation.ID); err != nil || active.ID != second.Configuration.ID {
		t.Fatalf("exactly the new config must be active: %+v %v", active, err)
	}
}

func TestVLESSSyncRetriesUntilNotified(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	if _, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if err := f.svc.SyncVLESS(ctx, time.Hour); err != nil {
		t.Fatal(err)
	}
	v1, _ := f.st.GetStateVersion(ctx, "n-nl1")
	if err := f.svc.SyncVLESS(ctx, time.Hour); err != nil {
		t.Fatal(err)
	}
	if v2, _ := f.st.GetStateVersion(ctx, "n-nl1"); v2 != v1 {
		t.Fatal("unchanged set must not bump versions again")
	}
}

func TestVLESSReconnectReplacesAllocationWithoutUUID(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	now := time.Now().UTC()
	legacy := store.Allocation{ID: id.NewUUID(), UserID: f.userID, DeviceID: f.devID, EndpointID: "ep-de2",
		IP: "10.211.0.9", Status: "active", CreatedAt: now, UpdatedAt: now}
	if err := f.st.Allocations().CreateAllocation(ctx, legacy); err != nil {
		t.Fatal(err)
	}
	res, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if res.Allocation.ID == legacy.ID || res.Allocation.VLESSUUID == "" {
		t.Fatalf("pre-000008 allocation must be replaced by one with a UUID: %+v", res.Allocation)
	}
}

func TestPreferredNodeReplacesLiveAllocation(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	first, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if first.Endpoint.NodeName != "DE2" {
		t.Fatalf("auto should pick the freer node, got %s", first.Endpoint.NodeName)
	}
	second, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "DE1")
	if err != nil {
		t.Fatal(err)
	}
	if !second.Created || second.Endpoint.NodeName != "DE1" {
		t.Fatalf("explicit choice must win over load: %+v", second.Endpoint.NodeName)
	}
	if second.Allocation.ID == first.Allocation.ID {
		t.Fatal("moving nodes must replace the allocation")
	}
	old, err := f.st.Allocations().GetAllocationByID(ctx, first.Allocation.ID)
	if err != nil || old.Status != "revoked" {
		t.Fatalf("previous allocation must be revoked: %+v %v", old, err)
	}
	x := f.xrayPart(t, second.Configuration)
	servers, _ := x["servers"].([]any)
	if len(servers) == 0 || servers[0].(map[string]any)["node"] != "DE1" {
		t.Fatalf("primary server = %v", servers)
	}
	if _, err := f.svc.Create(ctx, f.userID, second.Allocation.DeviceID, "vless", "", "", "ZZ9"); !errors.Is(err, connections.ErrNodeUnavailable) {
		t.Fatalf("missing node must not silently replace, err=%v", err)
	}
	live, err := f.st.Allocations().GetLiveByDevice(ctx, f.devID)
	if err != nil || live.ID != second.Allocation.ID {
		t.Fatalf("failed switch must keep the current allocation: %+v %v", live, err)
	}
}
