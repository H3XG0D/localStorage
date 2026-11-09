package scheduler_test

import (
	"context"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/scheduler"
)

func TestSchedulerRunOnce(t *testing.T) {
	var calls int
	fake := rotatorFunc(func(ctx context.Context, cutoff time.Time) (int, error) {
		calls++
		return 0, nil
	})
	s := scheduler.New(fake, scheduler.Options{
		Interval:  time.Hour,
		ConfigTTL: time.Hour,
		Now:       func() time.Time { return time.Unix(1700000000, 0) },
	})
	s.RunOnce(context.Background())
	if calls != 1 {
		t.Fatalf("calls=%d", calls)
	}
}

type rotatorFunc func(ctx context.Context, cutoff time.Time) (int, error)

func (f rotatorFunc) RotateAgedConfigs(ctx context.Context, cutoff time.Time) (int, error) {
	return f(ctx, cutoff)
}

type expirerFunc func(ctx context.Context, now time.Time) (int, error)

func (f expirerFunc) ExpireSubscriptions(ctx context.Context, now time.Time) (int, error) {
	return f(ctx, now)
}

func TestSchedulerExpiresSubscriptions(t *testing.T) {
	at := time.Unix(1700000000, 0)
	var got time.Time
	s := scheduler.New(nil, scheduler.Options{
		Now:     func() time.Time { return at },
		Expirer: expirerFunc(func(_ context.Context, now time.Time) (int, error) { got = now; return 1, nil }),
	})
	s.RunOnce(context.Background())
	if !got.Equal(at) {
		t.Fatalf("expirer not called with scheduler clock: %v", got)
	}
}
