package probe

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestFirstFailureWins(t *testing.T) {
	c := Checks{
		Xray:   func(context.Context) error { return nil },
		TLS:    func(context.Context) (time.Time, error) { return time.Now().Add(90 * 24 * time.Hour), nil },
		Decoy:  func(context.Context) error { return errors.New("connection refused") },
		Egress: func(context.Context) error { return errors.New("should not run") },
	}
	got := c.Run(context.Background())
	if got.OK || got.Reason != "сайт-заглушка не отвечает: connection refused" {
		t.Fatalf("%+v", got)
	}
}

func TestXrayDownIsTheReason(t *testing.T) {
	c := Checks{Xray: func(context.Context) error { return errors.New("connection refused") }}
	got := c.Run(context.Background())
	if got.OK || got.Reason != "Xray не отвечает: connection refused" {
		t.Fatalf("%+v", got)
	}
}

func TestSoonCertificateIsDegradedNotOffline(t *testing.T) {
	exp := time.Date(2026, 10, 9, 12, 0, 0, 0, time.UTC)
	c := Checks{
		Xray: func(context.Context) error { return nil },
		TLS:  func(context.Context) (time.Time, error) { return exp, nil },
		Now:  func() time.Time { return exp.Add(-10 * time.Hour) },
	}
	got := c.Run(context.Background())
	if !got.OK || !got.Degraded || got.Reason == "" {
		t.Fatalf("%+v", got)
	}
}
