// Package nodehealth decides when a node leaves the pool and what the operator is told.
package nodehealth

import (
	"context"
	"crypto/tls"
	"net"
	"time"
)

const (
	// StaleReason is stored when the agent stops calling home.
	StaleReason = "агент не выходит на связь больше 90 секунд"
	// FailThreshold is how many bad reports in a row take a node offline.
	FailThreshold = 2
)

// Status is the node's serving state plus the counters that keep one blip from flapping it.
type Status struct {
	State       string
	Reason      string
	HealthFails int
	ProbeFails  int
}

// Report is one agent-side probe.
type Report struct {
	OK       bool
	Degraded bool
	Reason   string
}

// ApplyAgent folds a local probe into the status. DRAINING is left alone.
// Two failures in a row take the node offline. One success brings it back,
// unless the outside port check is still failing.
func ApplyAgent(s Status, r Report) Status {
	if s.State == "DRAINING" {
		return s
	}
	if !r.OK {
		s.HealthFails++
		if s.HealthFails >= FailThreshold {
			s.State = "OFFLINE"
			s.Reason = r.Reason
		}
		return s
	}
	s.HealthFails = 0
	if s.ProbeFails >= FailThreshold {
		return s
	}
	if r.Degraded {
		s.State = "DEGRADED"
		s.Reason = r.Reason
		return s
	}
	s.State = "HEALTHY"
	s.Reason = ""
	return s
}

// ApplyProbe folds a control-plane dial of the node's public TLS port.
func ApplyProbe(s Status, ok bool, reason string) Status {
	if s.State == "DRAINING" {
		return s
	}
	if !ok {
		s.ProbeFails++
		if s.ProbeFails >= FailThreshold {
			s.State = "OFFLINE"
			s.Reason = reason
		}
		return s
	}
	s.ProbeFails = 0
	if s.HealthFails >= FailThreshold {
		return s
	}
	if s.State == "DEGRADED" {
		return s
	}
	s.State = "HEALTHY"
	s.Reason = ""
	return s
}

// ApplyStale marks a silent node offline. Fail counters stay at zero so a
// later heartbeat from an agent that does not send a probe can bring it back.
func ApplyStale(s Status) Status {
	if s.State != "HEALTHY" && s.State != "DEGRADED" {
		return s
	}
	s.State = "OFFLINE"
	s.Reason = StaleReason
	return s
}

// ApplyLegacyHeartbeat is the path for agents that only send a pulse.
// A node taken offline by a probe stays offline.
func ApplyLegacyHeartbeat(s Status) Status {
	if s.State == "DRAINING" || s.HealthFails >= FailThreshold || s.ProbeFails >= FailThreshold {
		return s
	}
	if s.State == "OFFLINE" {
		s.State = "HEALTHY"
		if s.Reason == StaleReason {
			s.Reason = ""
		}
	}
	return s
}

// EdgeReason is the operator text for a failed dial from the control plane.
func EdgeReason(err error) string {
	msg := err.Error()
	if len(msg) > 180 {
		msg = msg[:180]
	}
	return "порт 443 с control plane не открывается: " + msg
}

// DialTLS opens the node's public HTTPS port. host is the certificate name.
func DialTLS(ctx context.Context, host string) (bool, string) {
	if host == "" {
		return false, "порт 443 с control plane не открывается: у ноды нет hostname"
	}
	d := &tls.Dialer{
		NetDialer: &net.Dialer{Timeout: 5 * time.Second},
		Config:    &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12},
	}
	conn, err := d.DialContext(ctx, "tcp", net.JoinHostPort(host, "443"))
	if err != nil {
		return false, EdgeReason(err)
	}
	_ = conn.Close()
	return true, ""
}

// Changed reports whether serving state or the stored reason moved.
func Changed(before, after Status) bool {
	return before.State != after.State || before.Reason != after.Reason ||
		before.HealthFails != after.HealthFails || before.ProbeFails != after.ProbeFails
}
