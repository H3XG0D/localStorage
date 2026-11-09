package memory_test

import (
	"context"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func TestSummaryWindowsAreInclusiveAndSkipTrials(t *testing.T) {
	ctx := context.Background()
	st := memory.New()
	st.SeedPlan(store.Plan{ID: "p-week", Code: "week", Name: "Week", MaxDevices: 1, PeriodDays: 7})
	now := time.Date(2026, 10, 7, 12, 0, 0, 0, time.UTC)
	grants := []struct {
		user, kind string
		at         time.Time
		days       int
	}{
		{"u1", "paid", now.Add(-30 * 24 * time.Hour), 7},           // exactly on the 30-day boundary: counted
		{"u2", "paid", now.Add(-30*24*time.Hour - time.Second), 7}, // just outside
		{"u3", "paid", now.Add(-time.Hour), 30},
		{"u4", "trial", now.Add(-time.Hour), 1},
	}
	for i, g := range grants {
		if _, err := st.Subscriptions().GrantSubscription(ctx, store.Grant{
			ExternalID: "ext-" + g.user, SubscriptionID: "sub-" + g.user, UserID: g.user,
			PlanID: "p-week", PlanCode: "week", Kind: g.kind, Days: g.days, At: g.at, TelegramID: int64(i + 1),
		}); err != nil {
			t.Fatal(err)
		}
	}
	sum, err := st.Summary(ctx, now)
	if err != nil {
		t.Fatal(err)
	}
	if sum.Purchases30d != 2 || sum.PurchasedDays30d != 37 {
		t.Fatalf("30d window: purchases=%d days=%d", sum.Purchases30d, sum.PurchasedDays30d)
	}
	if sum.Purchases1d != 1 || sum.Trials30d != 1 {
		t.Fatalf("1d purchases=%d trials=%d", sum.Purchases1d, sum.Trials30d)
	}
}
