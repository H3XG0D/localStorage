// Package ratelimit implements the approved MVP rate limits (SECURITY.md §6,
// DECISIONS.md). The Limiter interface allows a Redis-backed implementation in a
// later milestone; the in-memory sliding-window limiter is used for dev/tests and
// is fully exercised by the auth handlers.
package ratelimit

import (
	"sync"
	"time"
)

// Limiter reports whether an action identified by key is allowed under a limit
// within window. Implementations must be safe for concurrent use.
type Limiter interface {
	Allow(key string, limit int, window time.Duration) bool
}

// Memory is an in-memory sliding-window limiter.
type Memory struct {
	mu   sync.Mutex
	hits map[string][]time.Time
	now  func() time.Time
}

// NewMemory returns an empty in-memory limiter.
func NewMemory() *Memory {
	return &Memory{hits: make(map[string][]time.Time), now: time.Now}
}

// Allow records an attempt and returns false when the limit is exceeded.
func (m *Memory) Allow(key string, limit int, window time.Duration) bool {
	if limit <= 0 {
		return true
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	now := m.now()
	cutoff := now.Add(-window)
	times := m.hits[key][:0:0]
	for _, t := range m.hits[key] {
		if t.After(cutoff) {
			times = append(times, t)
		}
	}
	if len(times) >= limit {
		m.hits[key] = times
		return false
	}
	m.hits[key] = append(times, now)
	return true
}
