package connections_test

import (
	"context"
	"crypto/rand"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/connections"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func addPhone(t *testing.T, f vlessFixture, name string, created time.Time) string {
	t.Helper()
	pub := make([]byte, 32)
	if _, err := rand.Read(pub); err != nil {
		t.Fatal(err)
	}
	id := id.NewUUID()
	if err := f.st.CreateDevice(context.Background(), store.Device{
		ID: id, UserID: f.userID, Name: name, Platform: "android", PublicKey: pub,
		DeviceTokenHash: id, Status: "active", CreatedAt: created, UpdatedAt: created,
	}, 5); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestSecondPhoneNeedsAnExtraSeat(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	now := time.Now().UTC()
	second := addPhone(t, f, "tablet", now.Add(time.Second))

	if _, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Create(ctx, f.userID, second, "vless", "", "", ""); err != connections.ErrTooManyDevices {
		t.Fatalf("second phone without a seat: %v", err)
	}
	if _, err := f.st.GrantSubscription(ctx, store.Grant{
		ExternalID: "slot-1", SubscriptionID: f.sub.ID, UserID: f.userID, PlanID: "p-week",
		PlanCode: "month", Kind: store.GrantDevice, Days: 1, At: now,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Create(ctx, f.userID, second, "vless", "", "", ""); err != nil {
		t.Fatalf("live seat must allow the second phone: %v", err)
	}
}

func TestOverLimitTunnelIsRevoked(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	now := time.Now().UTC()
	f.st.SeedPlan(store.Plan{ID: "p-week", Code: "week", Name: "Week", MaxDevices: 2, PeriodDays: 7})
	second := addPhone(t, f, "tablet", now.Add(time.Second))
	if _, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Create(ctx, f.userID, second, "vless", "", "", ""); err != nil {
		t.Fatal(err)
	}
	f.st.SeedPlan(store.Plan{ID: "p-week", Code: "week", Name: "Week", MaxDevices: 1, PeriodDays: 7})

	if _, err := f.svc.Create(ctx, f.userID, second, "vless", "", "", ""); err != connections.ErrTooManyDevices {
		t.Fatalf("existing tunnel past the limit: %v", err)
	}
	if _, err := f.st.GetLiveByDevice(ctx, second); err != store.ErrNotFound {
		t.Fatalf("over-limit tunnel must be revoked: %v", err)
	}
	again, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", "")
	if err != nil || again.Created {
		t.Fatalf("oldest phone keeps its tunnel: created=%v %v", again.Created, err)
	}
}

func TestTrimDropsNewerTunnelWhenSeatExpires(t *testing.T) {
	f := newVLESSFixture(t)
	ctx := context.Background()
	now := time.Now().UTC()
	second := addPhone(t, f, "tablet", now.Add(time.Second))
	if _, err := f.st.GrantSubscription(ctx, store.Grant{
		ExternalID: "slot-1", SubscriptionID: f.sub.ID, UserID: f.userID, PlanID: "p-week",
		PlanCode: "week", Kind: store.GrantDevice, Days: 1, At: now,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Create(ctx, f.userID, f.devID, "vless", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Create(ctx, f.userID, second, "vless", "", "", ""); err != nil {
		t.Fatal(err)
	}
	n, err := f.svc.TrimExcessDevices(ctx, now.Add(48*time.Hour))
	if err != nil || n != 1 {
		t.Fatalf("expired seat should drop the newer tunnel: n=%d %v", n, err)
	}
	if _, err := f.st.GetLiveByDevice(ctx, second); err != store.ErrNotFound {
		t.Fatalf("newer tunnel still live: %v", err)
	}
	if _, err := f.st.GetLiveByDevice(ctx, f.devID); err != nil {
		t.Fatalf("oldest phone must stay connected: %v", err)
	}
}
