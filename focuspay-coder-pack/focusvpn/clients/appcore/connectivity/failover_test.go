package connectivity

import (
	"testing"
	"time"

	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

func TestBackoffCaps(t *testing.T) {
	d0 := Backoff(0, time.Second, 30*time.Second)
	if d0 < time.Second || d0 > 2*time.Second {
		t.Fatalf("attempt0=%v", d0)
	}
	d10 := Backoff(10, time.Second, 30*time.Second)
	if d10 > 30*time.Second {
		t.Fatalf("capped=%v", d10)
	}
}

func TestPlanNext(t *testing.T) {
	var a, b apitypes.CandidateEndpoint
	a.Endpoint.ID = "a"
	b.Endpoint.ID = "b"
	p := NewPlan([]apitypes.CandidateEndpoint{a, b})
	p.MaxPasses = 2
	p.MaxAttempts = 10

	idx, _, refresh, exhausted := p.Next()
	if exhausted || refresh || idx != 0 {
		t.Fatalf("first: idx=%d refresh=%v exhausted=%v", idx, refresh, exhausted)
	}
	idx, _, refresh, exhausted = p.Next()
	if exhausted || refresh || idx != 1 {
		t.Fatalf("second: idx=%d", idx)
	}
	idx, _, refresh, exhausted = p.Next()
	if exhausted || refresh || idx != 0 {
		t.Fatalf("third: idx=%d refresh=%v exhausted=%v pass=%d", idx, refresh, exhausted, p.Pass)
	}
	idx, _, refresh, exhausted = p.Next()
	if exhausted || refresh || idx != 1 {
		t.Fatalf("fourth: idx=%d", idx)
	}
	_, _, refresh, exhausted = p.Next()
	if !refresh || exhausted {
		t.Fatalf("want refreshCP, got refresh=%v exhausted=%v pass=%d", refresh, exhausted, p.Pass)
	}
}

func TestPlanExhaustedEmpty(t *testing.T) {
	p := NewPlan(nil)
	_, _, _, exhausted := p.Next()
	if !exhausted {
		t.Fatal("empty should exhaust")
	}
}

func TestAfterFailure(t *testing.T) {
	var a, b, c apitypes.CandidateEndpoint
	a.Endpoint.ID, a.Node = "1", "DE-01"
	b.Endpoint.ID, b.Node = "2", "NL-01"
	c.Endpoint.ID, c.Node = "3", "US-01"
	p := NewPlan([]apitypes.CandidateEndpoint{a, b, c})
	p.AfterFailure("1")
	idx, _, _, _ := p.Next()
	if idx != 1 || PreferredNode(p.Candidates[idx]) != "NL-01" {
		t.Fatalf("want NL-01 next, idx=%d", idx)
	}
}

func TestPreferredNode(t *testing.T) {
	var c apitypes.CandidateEndpoint
	c.Endpoint.Host = "host.example"
	if PreferredNode(c) != "host.example" {
		t.Fatal("host fallback")
	}
	c.Node = "DE-01"
	if PreferredNode(c) != "DE-01" {
		t.Fatal("node wins")
	}
}
