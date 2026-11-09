package memory

import (
	"context"
	"encoding/json"
	"log"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// devPubKey is exactly 32 bytes (WireGuard key size); nodeselector.Rank drops non-32 keys.
func devPubKey(tag byte) []byte {
	b := make([]byte, 32)
	for i := range b {
		b[i] = tag
	}
	return b
}

// SeedSmokeCatalog seeds the free/week plans and three HEALTHY AmneziaWG endpoints
// (DE-01, NL-01, US-01) for CLI smoke / memory-store harnesses (FOCUSVPN_MEMORY_SEED=1).
// Not for production. Each node has a unique Jc/Jmin/Jmax + H1–H4 / S1–S4 set.
func (s *Store) SeedSmokeCatalog() {
	planID := "11111111-1111-1111-1111-111111111111"
	s.SeedPlan(store.Plan{
		ID: planID, Code: "free", Name: "Free", MaxDevices: 1, PeriodDays: 36500, PriceCents: 0,
		Features: json.RawMessage(`{}`),
	})
	s.SeedPlan(store.Plan{
		ID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4", Code: "week", Name: "Week",
		MaxDevices: 1, PeriodDays: 7, PriceCents: 30000,
		Features: json.RawMessage(`{"source":"focuspay_wallet"}`),
	})
	for _, p := range []store.Plan{
		{ID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa5", Code: "month", Name: "Month", MaxDevices: 1, PeriodDays: 30},
		{ID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa6", Code: "q3", Name: "3 months", MaxDevices: 1, PeriodDays: 90},
		{ID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa7", Code: "trial", Name: "Trial", MaxDevices: 1, PeriodDays: 1},
	} {
		p.Features = json.RawMessage(`{"source":"focuspay_wallet"}`)
		s.SeedPlan(p)
	}
	// Distinct DEV pubkeys (32 bytes each) — same family as seed A1 stub.
	obfDE := json.RawMessage(`{"junk_packet_count":4,"junk_min_size":40,"junk_max_size":70,"init_packet_junk_size":15,"response_packet_junk_size":20,"cookie_reply_junk_size":10,"transport_packet_junk_size":5,"init_packet_magic_header":"100-110","response_packet_magic_header":"200-210","underload_packet_magic_header":"300-310","transport_packet_magic_header":"400-410","special_junk_i1":"<b 0xde01>"}`)
	obfNL := json.RawMessage(`{"junk_packet_count":5,"junk_min_size":50,"junk_max_size":80,"init_packet_junk_size":12,"response_packet_junk_size":18,"cookie_reply_junk_size":8,"transport_packet_junk_size":4,"init_packet_magic_header":"1000-1010","response_packet_magic_header":"1100-1110","underload_packet_magic_header":"1200-1210","transport_packet_magic_header":"1300-1310","special_junk_i1":"<b 0x4e4c01>"}`)
	obfUS := json.RawMessage(`{"junk_packet_count":3,"junk_min_size":30,"junk_max_size":60,"init_packet_junk_size":10,"response_packet_junk_size":16,"cookie_reply_junk_size":6,"transport_packet_junk_size":3,"init_packet_magic_header":"2000-2010","response_packet_magic_header":"2100-2110","underload_packet_magic_header":"2200-2210","transport_packet_magic_header":"2300-2310","special_junk_i1":"<b 0x555301>"}`)
	nodes := []store.Endpoint{
		{
			ID: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", NodeID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
			NodeName: "DE-01", Country: "DE", Region: "eu-central",
			Hostname: "de-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
			PublicKey: devPubKey(0x01), Obfuscation: obfDE,
			Subnet: "10.200.0.0/24", Load: 0.2,
		},
		{
			ID: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2", NodeID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2",
			NodeName: "NL-01", Country: "NL", Region: "eu-west",
			Hostname: "nl-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
			PublicKey: devPubKey(0x02), Obfuscation: obfNL,
			Subnet: "10.201.0.0/24", Load: 0.4,
		},
		{
			ID: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3", NodeID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3",
			NodeName: "US-01", Country: "US", Region: "us-east",
			Hostname: "us-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
			PublicKey: devPubKey(0x03), Obfuscation: obfUS,
			Subnet: "10.202.0.0/24", Load: 0.1,
		},
	}
	for _, e := range nodes {
		s.SeedEndpoint(e)
		_ = s.EnsureStateVersion(context.Background(), e.NodeID)
	}
	log.Println("WARN: FOCUSVPN_MEMORY_SEED=1 — seeded free plan + DE/NL/US HEALTHY DEV pubkeys (smoke only)")
}
