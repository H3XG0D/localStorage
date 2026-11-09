// Package entitlement evaluates subscription access for servers/connections (plans/M3 §17-C, ADR-010).
package entitlement

import (
	"context"
	"errors"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Check grants access only with a live (trialing|active, ends_at > now)
// subscription. No row and an expired row both return ErrSubscriptionExpired
// (HTTP 402): access is bought or trialed through FocusPay, never implicit.
func Check(ctx context.Context, subs store.SubscriptionStore, userID string) error {
	_, _, err := subs.GetActiveByUser(ctx, userID)
	if errors.Is(err, store.ErrNoSubscription) {
		return store.ErrSubscriptionExpired
	}
	return err
}
