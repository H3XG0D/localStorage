package nodehealth

import "testing"

func TestTwoAgentFailuresTakeTheNodeOffline(t *testing.T) {
	s := Status{State: "HEALTHY"}
	s = ApplyAgent(s, Report{Reason: "Xray не отвечает: connection refused"})
	if s.State != "HEALTHY" || s.HealthFails != 1 {
		t.Fatalf("one blip must stay up: %+v", s)
	}
	s = ApplyAgent(s, Report{Reason: "Xray не отвечает: connection refused"})
	if s.State != "OFFLINE" || s.Reason == "" {
		t.Fatalf("second failure: %+v", s)
	}
	s = ApplyLegacyHeartbeat(s)
	if s.State != "OFFLINE" {
		t.Fatalf("a bare pulse must not clear a probe failure: %+v", s)
	}
	s = ApplyAgent(s, Report{OK: true})
	if s.State != "HEALTHY" || s.Reason != "" || s.HealthFails != 0 {
		t.Fatalf("a green probe brings it back: %+v", s)
	}
}

func TestDrainingIsSticky(t *testing.T) {
	s := Status{State: "DRAINING", Reason: "смена железа"}
	got := ApplyAgent(s, Report{Reason: "Xray не отвечает"})
	got = ApplyAgent(got, Report{Reason: "Xray не отвечает"})
	got = ApplyProbe(got, false, "порт закрыт")
	got = ApplyStale(got)
	if got != s {
		t.Fatalf("draining changed: %+v", got)
	}
}

func TestEdgeFailureDoesNotEraseAgentFailure(t *testing.T) {
	s := Status{State: "OFFLINE", Reason: "Xray не отвечает", HealthFails: 2}
	s = ApplyProbe(s, true, "")
	if s.State != "OFFLINE" || s.Reason != "Xray не отвечает" {
		t.Fatalf("open 443 must not hide a dead Xray: %+v", s)
	}
}

func TestCertificateWarningStaysSelectable(t *testing.T) {
	s := ApplyAgent(Status{State: "HEALTHY"}, Report{OK: true, Degraded: true, Reason: "сертификат истекает 09.10.2026 12:00 UTC"})
	if s.State != "DEGRADED" || s.Reason == "" {
		t.Fatalf("%+v", s)
	}
	s = ApplyProbe(s, true, "")
	if s.State != "DEGRADED" {
		t.Fatalf("edge success must keep the certificate warning: %+v", s)
	}
}

func TestStaleThenLegacyHeartbeatRecovers(t *testing.T) {
	s := ApplyStale(Status{State: "HEALTHY"})
	if s.State != "OFFLINE" || s.Reason != StaleReason {
		t.Fatalf("%+v", s)
	}
	s = ApplyLegacyHeartbeat(s)
	if s.State != "HEALTHY" || s.Reason != "" {
		t.Fatalf("agent without a probe can return: %+v", s)
	}
}

func TestTwoEdgeFailures(t *testing.T) {
	s := Status{State: "HEALTHY"}
	s = ApplyProbe(s, false, "порт 443 с control plane не открывается: timeout")
	if s.State != "HEALTHY" {
		t.Fatalf("first edge miss: %+v", s)
	}
	s = ApplyProbe(s, false, "порт 443 с control plane не открывается: timeout")
	if s.State != "OFFLINE" || s.ProbeFails != 2 {
		t.Fatalf("%+v", s)
	}
}
