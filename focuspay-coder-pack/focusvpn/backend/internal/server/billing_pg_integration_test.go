package server_test

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/billing"
	"focusvpn.example/focusvpn/backend/internal/connections"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/postgres"
)

const (
	pgWeekPlanID  = "aaaaaaaa-0000-4000-8000-000000000001"
	pgTrialPlanID = "aaaaaaaa-0000-4000-8000-000000000002"
)

func freshBillingPG(t *testing.T) (*postgres.Store, string) {
	t.Helper()
	url := pgURL(t)
	st := freshPG(t, url)
	t.Cleanup(func() { _ = st.Close() })
	execPG(t, url, `TRUNCATE billing_events CASCADE`)
	execPG(t, url, `INSERT INTO plans (id, code, name, max_devices, period_days) VALUES
		($1,'week','Week',1,7), ($2,'trial','Trial',1,1)`, pgWeekPlanID, pgTrialPlanID)
	return st, url
}

func TestPostgresGrantIsIdempotentAndStacks(t *testing.T) {
	st, _ := freshBillingPG(t)
	ctx := context.Background()
	svc := billing.New(st.Users(), st.Subscriptions())

	first, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "fp-1", TelegramID: 5001, Kind: "paid", PlanCode: "week", Days: 7, AmountKopecks: 30000})
	if err != nil {
		t.Fatal(err)
	}
	again, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "fp-1", TelegramID: 5001, Kind: "paid", PlanCode: "week", Days: 7, AmountKopecks: 30000})
	if err != nil {
		t.Fatal(err)
	}
	if !again.Idempotent || !again.EndsAt.Equal(first.EndsAt) {
		t.Fatalf("replay must not extend: %v -> %v (idem=%v)", first.EndsAt, again.EndsAt, again.Idempotent)
	}
	second, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "fp-2", TelegramID: 5001, Kind: "paid", PlanCode: "week", Days: 7, AmountKopecks: 30000})
	if err != nil {
		t.Fatal(err)
	}
	if d := second.EndsAt.Sub(first.EndsAt); d < 7*24*time.Hour-time.Second || d > 7*24*time.Hour+time.Second {
		t.Fatalf("second purchase must stack 7 days, got %v", d)
	}
	ev, err := st.Subscriptions().GetBillingEvent(ctx, "fp-2")
	if err != nil || ev.AmountKopecks != 30000 || ev.Kind != "paid" || ev.PlanCode != "week" {
		t.Fatalf("billing event: %+v %v", ev, err)
	}
}

func TestPostgresConcurrentGrantsDoNotLoseDays(t *testing.T) {
	st, _ := freshBillingPG(t)
	ctx := context.Background()
	svc := billing.New(st.Users(), st.Subscriptions())
	if _, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "seed", TelegramID: 5002, Kind: "paid", PlanCode: "week", Days: 1}); err != nil {
		t.Fatal(err)
	}
	const n = 8
	var wg sync.WaitGroup
	errs := make(chan error, 2*n)
	for i := 0; i < n; i++ {
		for _, ext := range []string{fmt.Sprintf("c-%d", i), fmt.Sprintf("c-%d", i)} { // each id twice
			wg.Add(1)
			go func(ext string) {
				defer wg.Done()
				_, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: ext, TelegramID: 5002, Kind: "paid", PlanCode: "week", Days: 7})
				errs <- err
			}(ext)
		}
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	status, err := svc.Status(ctx, 5002)
	if err != nil {
		t.Fatal(err)
	}
	seed, _ := st.Subscriptions().GetBillingEvent(ctx, "seed")
	want := seed.EndsAt.Add(n * 7 * 24 * time.Hour)
	if status.EndsAt == nil || status.EndsAt.Sub(want).Abs() > 2*time.Second {
		t.Fatalf("ends_at = %v, want %v (each distinct id counted exactly once)", status.EndsAt, want)
	}
}

func TestPostgresOneTrialPerUser(t *testing.T) {
	st, _ := freshBillingPG(t)
	ctx := context.Background()
	svc := billing.New(st.Users(), st.Subscriptions())
	if _, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "t-1", TelegramID: 5003, Kind: "trial", Days: 1}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "t-1", TelegramID: 5003, Kind: "trial", Days: 1}); err != nil {
		t.Fatalf("trial replay must be idempotent: %v", err)
	}
	_, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "t-2", TelegramID: 5003, Kind: "trial", Days: 1})
	if !errors.Is(err, store.ErrTrialUsed) {
		t.Fatalf("second trial: %v, want ErrTrialUsed", err)
	}
}

func TestPostgresExpiryDropsVLESSUser(t *testing.T) {
	st, url := freshBillingPG(t)
	ctx := context.Background()
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	kek := mycrypto.KEK{ID: "kek-v1", Key: key}
	st.UseKEK(kek)

	bsvc := billing.New(st.Users(), st.Subscriptions())
	g, err := bsvc.Grant(ctx, billing.GrantRequest{ExternalID: "v-1", TelegramID: 5004, Kind: "paid", PlanCode: "week", Days: 7})
	if err != nil {
		t.Fatal(err)
	}
	nodeID, epID := id.NewUUID(), id.NewUUID()
	execPG(t, url, `INSERT INTO vpn_nodes (id, name, country, region, state, capacity, hostname)
		VALUES ($1,'PG1','DE','eu','HEALTHY',100,'pg1.example')`, nodeID)
	execPG(t, url, `INSERT INTO vpn_endpoints (id, node_id, protocol, port, state, public_key, obfuscation, subnet, xray)
		VALUES ($1,$2,'vless',443,'HEALTHY',NULL,'{}'::jsonb,'10.230.0.0/24'::cidr,'{"transport":"ws","path":"/x"}'::jsonb)`, epID, nodeID)
	devID := id.NewUUID()
	devPub := make([]byte, 32)
	_, _ = rand.Read(devPub)
	now := time.Now().UTC()
	if err := st.Devices().CreateDevice(ctx, store.Device{ID: devID, UserID: g.UserID, Name: "phone", Platform: "android",
		PublicKey: devPub, Status: "active", CreatedAt: now, UpdatedAt: now}, 1); err != nil {
		t.Fatal(err)
	}
	_, cfgPriv, _ := ed25519.GenerateKey(rand.Reader)
	csvc := connections.NewService(st.Devices(), st.Endpoints(), st.Allocations(), st.Configurations(),
		st.Subscriptions(), st.NodeState(), kek, mycrypto.NewConfigSigner(cfgPriv), true, nil)

	first, err := csvc.Create(ctx, g.UserID, devID, "vless-ws", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	second, err := csvc.Create(ctx, g.UserID, devID, "vless", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if second.Allocation.ID != first.Allocation.ID || second.Configuration.Version <= first.Configuration.Version {
		t.Fatalf("reuse must reissue on the same allocation: %+v / %+v", first.Allocation, second.Configuration)
	}
	active, err := st.Configurations().GetActiveByAllocation(ctx, first.Allocation.ID)
	if err != nil || active.ID != second.Configuration.ID {
		t.Fatalf("exactly the reissued config must be active: %v %v", active.ID, err)
	}
	if old, _ := st.Configurations().GetConfigurationByID(ctx, first.Configuration.ID); old.Status == "active" {
		t.Fatal("old config must be revoked")
	}

	live, err := st.Allocations().ListLiveEntitledVLESS(ctx, time.Now())
	if err != nil || len(live) != 1 || live[0].VLESSUUID != first.Allocation.VLESSUUID {
		t.Fatalf("desired set: %+v %v", live, err)
	}
	if n, err := st.Subscriptions().ExpireSubscriptions(ctx, time.Now().Add(8*24*time.Hour)); err != nil || n != 1 {
		t.Fatalf("expire: n=%d err=%v", n, err)
	}
	if live, _ := st.Allocations().ListLiveEntitledVLESS(ctx, time.Now()); len(live) != 0 {
		t.Fatalf("expired user must leave the desired set: %+v", live)
	}
	if _, _, err := st.Subscriptions().GetActiveByUser(ctx, g.UserID); !errors.Is(err, store.ErrNoSubscription) {
		t.Fatalf("expired subscription must not be active: %v", err)
	}
}

func TestPostgresListEndingBetween(t *testing.T) {
	st, _ := freshBillingPG(t)
	ctx := context.Background()
	svc := billing.New(st.Users(), st.Subscriptions())
	if _, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "e-1", TelegramID: 5005, Kind: "trial", Days: 1}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Grant(ctx, billing.GrantRequest{ExternalID: "e-2", TelegramID: 5006, Kind: "paid", PlanCode: "week", Days: 7}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	got, err := svc.ListEnding(ctx, now, now.Add(48*time.Hour), 0)
	if err != nil || len(got) != 1 || got[0].TelegramID != 5005 || got[0].PlanCode != "trial" {
		t.Fatalf("ending: %+v %v", got, err)
	}
}
