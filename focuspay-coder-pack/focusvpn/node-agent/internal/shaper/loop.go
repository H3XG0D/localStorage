package shaper

import (
	"context"
	"log"
	"sync"
	"time"
)

// Source is the Xray online-address list.
type Source interface {
	UserIPs(ctx context.Context) (map[string][]string, error)
}

// Loop refreshes tc classes and remembers who is over the address cap.
type Loop struct {
	Source Source
	Apply  *Applier
	Max    int
	Every  time.Duration

	mu     sync.Mutex
	shares []Share
}

// Shares returns the users over the address cap from the last successful read.
func (l *Loop) Shares() []Share {
	l.mu.Lock()
	defer l.mu.Unlock()
	out := make([]Share, len(l.shares))
	copy(out, l.shares)
	return out
}

// Run ticks until ctx is cancelled. The first pass runs immediately.
func (l *Loop) Run(ctx context.Context) {
	every := l.Every
	if every <= 0 {
		every = 2 * time.Second
	}
	l.tick(ctx)
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			l.tick(ctx)
		}
	}
}

func (l *Loop) tick(ctx context.Context) {
	if l.Source == nil {
		return
	}
	users, err := l.Source.UserIPs(ctx)
	if err != nil {
		log.Printf("shaper: online addresses: %v", err)
		l.mu.Lock()
		l.shares = nil
		l.mu.Unlock()
		return
	}
	shaped, over := Classify(users, l.Max)
	if l.Apply != nil {
		if err := l.Apply.Sync(ctx, shaped); err != nil {
			log.Printf("shaper: tc: %v", err)
		}
	}
	l.mu.Lock()
	l.shares = over
	l.mu.Unlock()
}
