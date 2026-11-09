package billing

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/devices"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func newSvc(t *testing.T) (*Service, *memory.Store) {
	t.Helper()
	st := memory.New()
	st.SeedSmokeCatalog()
	return New(st.Users(), st.Subscriptions()), st
}

func TestUpsertIdempotent(t *testing.T) {
	svc, _ := newSvc(t)
	up, err := svc.UpsertTelegramUser(context.Background(), 424242)
	if err != nil || !up.Created {
		t.Fatalf("upsert: %+v %v", up, err)
	}
	up2, err := svc.UpsertTelegramUser(context.Background(), 424242)
	if err != nil || up2.Created || up2.UserID != up.UserID {
		t.Fatalf("upsert2: %+v %v", up2, err)
	}
}

func TestGrantIdempotentByExternalID(t *testing.T) {
	svc, _ := newSvc(t)
	ctx := context.Background()
	req := GrantRequest{ExternalID: "p-1", TelegramID: 424242, Kind: KindPaid, PlanCode: "month", Days: 30, AmountKopecks: 99000}
	res, err := svc.Grant(ctx, req)
	if err != nil || res.Idempotent {
		t.Fatalf("grant: %+v %v", res, err)
	}
	if res.EndsAt.Before(time.Now().UTC().Add(29*24*time.Hour)) || res.Status != "active" {
		t.Fatalf("bad result: %+v", res)
	}
	again, err := svc.Grant(ctx, req)
	if err != nil || !again.Idempotent || !again.EndsAt.Equal(res.EndsAt) {
		t.Fatalf("replay must not extend: %+v %v", again, err)
	}
	got, err := svc.GetGrant(ctx, "p-1")
	if err != nil || got.AmountKopecks != 99000 || got.PlanCode != "month" {
		t.Fatalf("get grant: %+v %v", got, err)
	}
	if _, err := svc.GetGrant(ctx, "missing"); !errors.Is(err, store.ErrNotFound) {
		t.Fatalf("missing grant: %v", err)
	}
}

func TestGrantStacksOnLiveSubscription(t *testing.T) {
	svc, _ := newSvc(t)
	ctx := context.Background()
	first, err := svc.Grant(ctx, GrantRequest{ExternalID: "t-1", TelegramID: 7, Kind: KindTrial, Days: 1})
	if err != nil || first.Status != "trialing" {
		t.Fatalf("trial: %+v %v", first, err)
	}
	paid, err := svc.Grant(ctx, GrantRequest{ExternalID: "p-2", TelegramID: 7, Kind: KindPaid, PlanCode: "week", Days: 7, AmountKopecks: 30000})
	if err != nil {
		t.Fatal(err)
	}
	if want := first.EndsAt.Add(7 * 24 * time.Hour); !paid.EndsAt.Equal(want) || paid.Status != "active" {
		t.Fatalf("paid days must stack on trial: got %v want %v (%s)", paid.EndsAt, want, paid.Status)
	}
}

func TestSecondTrialRefused(t *testing.T) {
	svc, _ := newSvc(t)
	ctx := context.Background()
	if _, err := svc.Grant(ctx, GrantRequest{ExternalID: "t-1", TelegramID: 9, Kind: KindTrial, Days: 1}); err != nil {
		t.Fatal(err)
	}
	_, err := svc.Grant(ctx, GrantRequest{ExternalID: "t-2", TelegramID: 9, Kind: KindTrial, Days: 1})
	if !errors.Is(err, store.ErrTrialUsed) {
		t.Fatalf("want ErrTrialUsed, got %v", err)
	}
}

func TestGrantValidation(t *testing.T) {
	svc, _ := newSvc(t)
	bad := []GrantRequest{
		{TelegramID: 1, Kind: KindPaid, PlanCode: "week", Days: 7},
		{ExternalID: "x", TelegramID: 1, Kind: KindPaid, PlanCode: "week", Days: 0},
		{ExternalID: "x", TelegramID: 1, Kind: KindPaid, PlanCode: "week", Days: 400},
		{ExternalID: "x", TelegramID: 1, Kind: "gift", PlanCode: "week", Days: 7},
		{ExternalID: "x", TelegramID: 1, Kind: KindPaid, Days: 7},
	}
	for i, req := range bad {
		if _, err := svc.Grant(context.Background(), req); !errors.Is(err, ErrInvalid) {
			t.Fatalf("case %d: want ErrInvalid, got %v", i, err)
		}
	}
}

func TestExpiredSubscriptionIsNotLive(t *testing.T) {
	svc, st := newSvc(t)
	ctx := context.Background()
	res, err := svc.Grant(ctx, GrantRequest{ExternalID: "p-3", TelegramID: 11, Kind: KindPaid, PlanCode: "week", Days: 1})
	if err != nil {
		t.Fatal(err)
	}
	n, err := st.ExpireSubscriptions(ctx, res.EndsAt.Add(time.Second))
	if err != nil || n != 1 {
		t.Fatalf("expire: %d %v", n, err)
	}
	status, err := svc.Status(ctx, 11)
	if err != nil || status.HasLive {
		t.Fatalf("status after expiry: %+v %v", status, err)
	}
}

func TestDeviceGrantAddsSeatWithoutExtendingSubscription(t *testing.T) {
	svc, st := newSvc(t)
	ctx := context.Background()
	sub, err := svc.Grant(ctx, GrantRequest{ExternalID: "p-1", TelegramID: 42, Kind: KindPaid, PlanCode: "week", Days: 7, AmountKopecks: 30000})
	if err != nil {
		t.Fatal(err)
	}
	slot, err := svc.Grant(ctx, GrantRequest{ExternalID: "d-1", TelegramID: 42, Kind: KindDevice, PlanCode: "month", Days: 30, AmountKopecks: 99000})
	if err != nil {
		t.Fatal(err)
	}
	if !slot.EndsAt.After(sub.EndsAt.Add(20 * 24 * time.Hour)) {
		t.Fatalf("slot must outlive the week subscription: slot %v sub %v", slot.EndsAt, sub.EndsAt)
	}
	status, err := svc.Status(ctx, 42)
	if err != nil || !status.HasLive || status.EndsAt == nil || !status.EndsAt.Truncate(time.Second).Equal(sub.EndsAt) {
		t.Fatalf("subscription end moved: %+v %v", status, err)
	}
	if status.BaseDevices != 1 || status.MaxDevices != 2 || len(status.ExtraSlots) != 1 || status.ExtraSlots[0].PlanCode != "month" {
		t.Fatalf("seats: %+v", status)
	}
	again, err := svc.Grant(ctx, GrantRequest{ExternalID: "d-1", TelegramID: 42, Kind: KindDevice, PlanCode: "month", Days: 30, AmountKopecks: 99000})
	if err != nil || !again.Idempotent || !again.EndsAt.Equal(slot.EndsAt) {
		t.Fatalf("replay: %+v %v", again, err)
	}
	if _, err := svc.Grant(ctx, GrantRequest{ExternalID: "d-2", TelegramID: 42, Kind: KindDevice, PlanCode: "week", Days: 7, AmountKopecks: 30000}); err != nil {
		t.Fatal(err)
	}
	status, err = svc.Status(ctx, 42)
	if err != nil || status.MaxDevices != 3 || len(status.ExtraSlots) != 2 {
		t.Fatalf("second seat: %+v %v", status, err)
	}
	if _, err := svc.Grant(ctx, GrantRequest{ExternalID: "d-x", TelegramID: 99, Kind: KindDevice, PlanCode: "week", Days: 7, AmountKopecks: 30000}); !errors.Is(err, store.ErrNoSubscription) {
		t.Fatalf("device grant without subscription: %v", err)
	}

	_, priv, _ := ed25519.GenerateKey(nil)
	issuer := auth.NewTokenIssuer(priv, priv.Public().(ed25519.PublicKey), bytes.Repeat([]byte{1}, 32), time.Hour)
	devs := devices.NewService(st.Devices(), st.Subscriptions(), issuer)
	pub := func() string {
		t.Helper()
		b := make([]byte, 32)
		if _, err := rand.Read(b); err != nil {
			t.Fatal(err)
		}
		return base64.StdEncoding.EncodeToString(b)
	}
	if _, _, err := devs.Create(ctx, sub.UserID, "phone", "android", "", pub()); err != nil {
		t.Fatal(err)
	}
	if _, _, err := devs.Create(ctx, sub.UserID, "phone-2", "android", "", pub()); err != nil {
		t.Fatal(err)
	}
	if _, _, err := devs.Create(ctx, sub.UserID, "phone-3", "android", "", pub()); err != nil {
		t.Fatal(err)
	}
	if _, _, err := devs.Create(ctx, sub.UserID, "phone-4", "android", "", pub()); !errors.Is(err, devices.ErrTooManyDevs) {
		t.Fatalf("fourth device: %v", err)
	}
}

func TestParseRubles(t *testing.T) {
	ok := map[string]int64{"": 0, "300": 30000, "990.5": 99050, "2490.00": 249000, "0.01": 1}
	for in, want := range ok {
		if got, err := ParseRubles(in); err != nil || got != want {
			t.Fatalf("%q: got %d %v", in, got, err)
		}
	}
	for _, in := range []string{"-1", "1.234", "1e3", "1.+5", "abc", "1."} {
		if _, err := ParseRubles(in); err == nil {
			t.Fatalf("%q must fail", in)
		}
	}
}
