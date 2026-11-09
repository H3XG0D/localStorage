package ratelimit

import (
	"testing"
	"time"
)

func TestMemoryAllowWithinLimit(t *testing.T) {
	m := NewMemory()
	for i := 0; i < 5; i++ {
		if !m.Allow("k", 5, time.Minute) {
			t.Fatalf("attempt %d should be allowed", i)
		}
	}
	if m.Allow("k", 5, time.Minute) {
		t.Fatal("6th attempt should be blocked")
	}
}

func TestMemoryWindowExpiry(t *testing.T) {
	m := NewMemory()
	base := time.Now()
	m.now = func() time.Time { return base }
	for i := 0; i < 3; i++ {
		if !m.Allow("k", 3, time.Minute) {
			t.Fatalf("attempt %d should be allowed", i)
		}
	}
	if m.Allow("k", 3, time.Minute) {
		t.Fatal("should be blocked at limit")
	}
	// advance beyond the window
	m.now = func() time.Time { return base.Add(2 * time.Minute) }
	if !m.Allow("k", 3, time.Minute) {
		t.Fatal("should be allowed after window expiry")
	}
}

func TestMemoryZeroLimitAllowsAll(t *testing.T) {
	m := NewMemory()
	if !m.Allow("k", 0, time.Minute) {
		t.Fatal("zero/disabled limit should allow")
	}
}
