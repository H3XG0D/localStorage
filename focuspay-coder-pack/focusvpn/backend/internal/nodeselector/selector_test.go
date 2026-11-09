package nodeselector

import (
	"testing"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func TestRankTopNAndPreferred(t *testing.T) {
	pub := make([]byte, 32)
	list := []store.Endpoint{
		{ID: "b", NodeName: "NL-01", Region: "eu-west", State: "HEALTHY", PublicKey: pub, Load: 0.5},
		{ID: "a", NodeName: "DE-01", Region: "eu-central", State: "HEALTHY", PublicKey: pub, Load: 0.5},
		{ID: "c", NodeName: "US-01", Region: "us-east", State: "DEGRADED", PublicKey: pub, Load: 0.0},
		{ID: "d", NodeName: "XX-01", Region: "eu-west", State: "HEALTHY", PublicKey: nil},
	}
	got := Rank(list, Query{PreferredNode: "DE-01", Limit: 3})
	if len(got) != 3 {
		t.Fatalf("len=%d want 3 (bad pubkey excluded)", len(got))
	}
	if got[0].Endpoint.NodeName != "DE-01" {
		t.Fatalf("preferred should win first=%s score=%v", got[0].Endpoint.NodeName, got[0].Score)
	}
	got2 := Rank(list, Query{Limit: 2})
	if len(got2) != 2 {
		t.Fatalf("limit: %d", len(got2))
	}
}

func TestRankRegionFilter(t *testing.T) {
	pub := make([]byte, 32)
	list := []store.Endpoint{
		{ID: "1", NodeName: "DE-01", Region: "eu-central", State: "HEALTHY", PublicKey: pub},
		{ID: "2", NodeName: "US-01", Region: "us-east", State: "HEALTHY", PublicKey: pub},
	}
	got := Rank(list, Query{Region: "us-east", Limit: 3})
	if len(got) != 1 || got[0].Endpoint.NodeName != "US-01" {
		t.Fatalf("%+v", got)
	}
}

func TestRankVLESSWithoutKeyLeastLoadedFirst(t *testing.T) {
	list := []store.Endpoint{
		{ID: "1", NodeName: "DE1", Protocol: "vless-ws", State: "HEALTHY", Load: 0.8},
		{ID: "2", NodeName: "DE2", Protocol: "vless-ws", State: "HEALTHY", Load: 0.1},
		{ID: "3", NodeName: "DE3", Protocol: "vless-ws", State: "OFFLINE", Load: 0},
	}
	got := Rank(list, Query{Limit: 3})
	if len(got) != 2 {
		t.Fatalf("len=%d want 2 (offline excluded, no pubkey ok): %+v", len(got), got)
	}
	if got[0].Endpoint.NodeName != "DE2" || got[1].Endpoint.NodeName != "DE1" {
		t.Fatalf("least loaded first: %s, %s", got[0].Endpoint.NodeName, got[1].Endpoint.NodeName)
	}
}

func TestRankDegradedLower(t *testing.T) {
	pub := make([]byte, 32)
	list := []store.Endpoint{
		{ID: "1", NodeName: "A", State: "DEGRADED", PublicKey: pub, Load: 0},
		{ID: "2", NodeName: "B", State: "HEALTHY", PublicKey: pub, Load: 0},
	}
	got := Rank(list, Query{Limit: 2})
	if got[0].Endpoint.NodeName != "B" {
		t.Fatalf("healthy should win: %+v", got)
	}
}
