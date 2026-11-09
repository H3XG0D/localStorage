package billing

import (
	"context"
	"errors"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

type storeDevices struct{ st *memory.Store }

func (d storeDevices) List(ctx context.Context, userID string) ([]store.Device, error) {
	return d.st.Devices().ListDevicesByUser(ctx, userID)
}

func (d storeDevices) Revoke(ctx context.Context, deviceID, userID string) error {
	return d.st.Devices().RevokeDevice(ctx, deviceID, userID, time.Now())
}

func seedDevice(t *testing.T, st *memory.Store, userID, devID string) {
	t.Helper()
	now := time.Now().UTC()
	pub := make([]byte, 32)
	pub[0] = byte(len(devID))
	if err := st.Devices().CreateDevice(context.Background(), store.Device{
		ID: devID, UserID: userID, Name: "Pixel", Platform: "android", PublicKey: pub, DeviceTokenHash: "h-" + devID,
		Status: "active", CreatedAt: now, UpdatedAt: now,
	}, 5); err != nil {
		t.Fatal(err)
	}
}

func TestDevicesListAndRevokeByTelegram(t *testing.T) {
	svc, st := newSvc(t)
	svc.UseDevices(storeDevices{st}, st.Allocations(), nil)
	ctx := context.Background()
	alice, _ := svc.UpsertTelegramUser(ctx, 111)
	bob, _ := svc.UpsertTelegramUser(ctx, 222)
	seedDevice(t, st, alice.UserID, "dev-a")
	seedDevice(t, st, bob.UserID, "dev-bb")

	list, err := svc.ListDevices(ctx, 111)
	if err != nil || len(list) != 1 || list[0].ID != "dev-a" || list[0].Connected {
		t.Fatalf("list: %+v %v", list, err)
	}
	if err := svc.RevokeDevice(ctx, 111, "dev-bb"); !errors.Is(err, ErrDeviceNotFound) {
		t.Fatalf("foreign device: %v", err)
	}
	if err := svc.RevokeDevice(ctx, 999, "dev-a"); !errors.Is(err, ErrDeviceNotFound) {
		t.Fatalf("unknown user: %v", err)
	}
	if err := svc.RevokeDevice(ctx, 111, "dev-a"); err != nil {
		t.Fatal(err)
	}
	if list, _ := svc.ListDevices(ctx, 111); len(list) != 0 {
		t.Fatalf("revoked device still listed: %+v", list)
	}
	if list, _ := svc.ListDevices(ctx, 333); list == nil || len(list) != 0 {
		t.Fatalf("unknown user must get an empty list: %+v", list)
	}
}

func TestListEndingWindow(t *testing.T) {
	svc, _ := newSvc(t)
	ctx := context.Background()
	if _, err := svc.Grant(ctx, GrantRequest{ExternalID: "t-1", TelegramID: 7001, Kind: KindTrial, Days: 1}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Grant(ctx, GrantRequest{ExternalID: "p-1", TelegramID: 7002, Kind: KindPaid, PlanCode: "month", Days: 30}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	got, err := svc.ListEnding(ctx, now, now.Add(48*time.Hour), 0)
	if err != nil || len(got) != 1 || got[0].TelegramID != 7001 || got[0].PlanCode != "trial" {
		t.Fatalf("ending: %+v %v", got, err)
	}
}
