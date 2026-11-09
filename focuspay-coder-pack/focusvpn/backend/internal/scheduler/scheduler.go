// Package scheduler runs Control Plane background jobs (ARCHITECTURE §4, P4-M5).
package scheduler

import (
	"context"
	"log"
	"sync"
	"time"

	"focusvpn.example/focusvpn/backend/internal/connections"
)

// ConfigTTLRotator re-issues aged active configurations.
type ConfigTTLRotator interface {
	RotateAgedConfigs(ctx context.Context, cutoff time.Time) (int, error)
}

// VLESSSyncer marks silent nodes OFFLINE and re-pushes the Xray user set.
type VLESSSyncer interface {
	SyncVLESS(ctx context.Context, staleAfter time.Duration) error
}

// EdgeProber dials each fresh node's public TLS port and takes it offline
// when the port stays closed.
type EdgeProber interface {
	ProbeEdges(ctx context.Context, freshFor time.Duration) error
}

// SubscriptionExpirer flips live subscriptions past ends_at to expired.
type SubscriptionExpirer interface {
	ExpireSubscriptions(ctx context.Context, now time.Time) (int, error)
}

// ExcessTrimmer drops tunnels of devices past the live seat limit.
type ExcessTrimmer interface {
	TrimExcessDevices(ctx context.Context, now time.Time) (int, error)
}

// Options configure the scheduler loop.
type Options struct {
	Expirer   SubscriptionExpirer // optional
	Interval  time.Duration       // tick period; default 1m
	ConfigTTL time.Duration       // age before re-issue; default 24h
	// HeartbeatStale is how long a node may stay silent before it is OFFLINE; default 90s.
	HeartbeatStale time.Duration
	Now            func() time.Time
	Log            *log.Logger
}

// Scheduler ticks background jobs until Stop.
type Scheduler struct {
	rotator ConfigTTLRotator
	opts    Options

	mu     sync.Mutex
	cancel context.CancelFunc
	done   chan struct{}
}

// New builds a scheduler. rotator may be a *connections.Service.
func New(rotator ConfigTTLRotator, opts Options) *Scheduler {
	if opts.Interval <= 0 {
		opts.Interval = time.Minute
	}
	if opts.ConfigTTL <= 0 {
		opts.ConfigTTL = 24 * time.Hour
	}
	if opts.HeartbeatStale <= 0 {
		opts.HeartbeatStale = 90 * time.Second
	}
	if opts.Now == nil {
		opts.Now = time.Now
	}
	if opts.Log == nil {
		opts.Log = log.Default()
	}
	return &Scheduler{rotator: rotator, opts: opts, done: make(chan struct{})}
}

// Start begins the ticker loop in a background goroutine.
func (s *Scheduler) Start() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cancel != nil {
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.cancel = cancel
	s.done = make(chan struct{})
	go s.loop(ctx)
}

// Stop cancels the loop and waits for exit.
func (s *Scheduler) Stop() {
	s.mu.Lock()
	cancel := s.cancel
	done := s.done
	s.cancel = nil
	s.mu.Unlock()
	if cancel == nil {
		return
	}
	cancel()
	<-done
}

func (s *Scheduler) loop(ctx context.Context) {
	defer close(s.done)
	s.runOnce(ctx)
	t := time.NewTicker(s.opts.Interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			s.runOnce(ctx)
		}
	}
}

func (s *Scheduler) runOnce(ctx context.Context) {
	if s.opts.Expirer != nil {
		if n, err := s.opts.Expirer.ExpireSubscriptions(ctx, s.opts.Now()); err != nil {
			s.opts.Log.Printf("scheduler: expire subscriptions: %v", err)
		} else if n > 0 {
			s.opts.Log.Printf("scheduler: expired %d subscription(s)", n)
		}
	}
	if s.rotator == nil {
		return
	}
	if t, ok := s.rotator.(ExcessTrimmer); ok {
		if n, err := t.TrimExcessDevices(ctx, s.opts.Now()); err != nil {
			s.opts.Log.Printf("scheduler: trim excess devices: %v", err)
		} else if n > 0 {
			s.opts.Log.Printf("scheduler: trimmed %d excess device tunnel(s)", n)
		}
	}
	if v, ok := s.rotator.(VLESSSyncer); ok {
		if err := v.SyncVLESS(ctx, s.opts.HeartbeatStale); err != nil {
			s.opts.Log.Printf("scheduler: vless sync: %v", err)
		}
	}
	if p, ok := s.rotator.(EdgeProber); ok {
		if err := p.ProbeEdges(ctx, s.opts.HeartbeatStale); err != nil {
			s.opts.Log.Printf("scheduler: edge probe: %v", err)
		}
	}
	cutoff := s.opts.Now().Add(-s.opts.ConfigTTL)
	n, err := s.rotator.RotateAgedConfigs(ctx, cutoff)
	if err != nil {
		s.opts.Log.Printf("scheduler: config TTL rotate: %v", err)
		return
	}
	if n > 0 {
		s.opts.Log.Printf("scheduler: rotated %d aged configuration(s)", n)
	}
}

// RunOnce is exported for tests.
func (s *Scheduler) RunOnce(ctx context.Context) {
	s.runOnce(ctx)
}

// Ensure *connections.Service satisfies the scheduler job interfaces.
var (
	_ ConfigTTLRotator = (*connections.Service)(nil)
	_ VLESSSyncer      = (*connections.Service)(nil)
	_ ExcessTrimmer    = (*connections.Service)(nil)
	_ EdgeProber       = (*connections.Service)(nil)
)
