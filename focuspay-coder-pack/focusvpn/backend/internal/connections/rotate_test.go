package connections_test

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/connections"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func TestRotateAgedConfigsReissuesVersion(t *testing.T) {
	st := memory.New()
	pub := make([]byte, 32)
	_, _ = rand.Read(pub)
	st.SeedEndpoint(store.Endpoint{
		ID: "ep-1", NodeID: "n-1", NodeName: "DE-01", Country: "DE", Region: "eu-central",
		Hostname: "de-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
		PublicKey: pub, Obfuscation: json.RawMessage(`{"junk_packet_count":4,"junk_min_size":40,"junk_max_size":70,"init_packet_junk_size":15,"response_packet_junk_size":20,"cookie_reply_junk_size":10,"transport_packet_junk_size":5,"init_packet_magic_header":"100-110","response_packet_magic_header":"200-210","underload_packet_magic_header":"300-310","transport_packet_magic_header":"400-410"}`),
		Subnet: "10.200.0.0/24",
	})
	st.SeedPlan(store.Plan{ID: "p1", Code: "free", Name: "Free", MaxDevices: 1, PeriodDays: 36500})

	userID := id.NewUUID()
	devID := id.NewUUID()
	_ = st.CreateUser(context.Background(), store.User{
		ID: userID, Email: "rot@example.com", PasswordHash: "x", Role: "user", Status: "active",
		CreatedAt: time.Now(), UpdatedAt: time.Now(),
	})
	devPub := make([]byte, 32)
	_, _ = rand.Read(devPub)
	_ = st.CreateDevice(context.Background(), store.Device{
		ID: devID, UserID: userID, Name: "t", Platform: "linux", PublicKey: devPub,
		Status: "active", CreatedAt: time.Now(), UpdatedAt: time.Now(),
	}, 5)

	now := time.Now().UTC()
	allocID := id.NewUUID()
	_ = st.CreateAllocation(context.Background(), store.Allocation{
		ID: allocID, UserID: userID, DeviceID: devID, EndpointID: "ep-1",
		IP: "10.200.0.2", PeerPublicKey: append([]byte(nil), devPub...), Status: "active",
		CreatedAt: now, UpdatedAt: now,
	})

	oldCreated := now.Add(-48 * time.Hour)
	oldID := id.NewUUID()
	_ = st.CreateConfiguration(context.Background(), store.Configuration{
		ID: oldID, AllocationID: allocID, DeviceID: devID, Version: 1,
		ContentEncrypted: []byte("blob"), ContentHash: []byte("hash"), Signature: []byte("sig"),
		Status: "active", CreatedAt: oldCreated, UpdatedAt: oldCreated,
	})

	_, cfgPriv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	kek := make([]byte, 32)
	_, _ = rand.Read(kek)
	svc := connections.NewService(
		st.Devices(), st.Endpoints(), st.Allocations(), st.Configurations(),
		st.Subscriptions(), st.NodeState(),
		mycrypto.KEK{ID: "kek-v1", Key: kek},
		mycrypto.NewConfigSigner(cfgPriv),
		true, nil,
	)

	n, err := svc.RotateAgedConfigs(context.Background(), now.Add(-24*time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Fatalf("rotated=%d want 1", n)
	}

	old, err := st.GetConfigurationByID(context.Background(), oldID)
	if err != nil {
		t.Fatal(err)
	}
	if old.Status != "revoked" {
		t.Fatalf("old status=%s", old.Status)
	}
	active, err := st.GetActiveByAllocation(context.Background(), allocID)
	if err != nil {
		t.Fatal(err)
	}
	if active.Version != 2 {
		t.Fatalf("version=%d want 2", active.Version)
	}
	if active.RotatedAt == nil {
		t.Fatal("expected rotated_at set")
	}
	if len(active.Signature) == 0 || len(active.ContentEncrypted) == 0 {
		t.Fatal("expected re-signed envelope")
	}
}
