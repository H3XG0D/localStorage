// Package nodeselector ranks HEALTHY/DEGRADED endpoints for GET /v1/servers
// and POST /v1/connections (ARCHITECTURE §9, P4-M4).
package nodeselector

import (
	"sort"
	"strings"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

const DefaultLimit = 3

// Query filters and preferences for ranking.
type Query struct {
	Protocol      string
	Country       string
	Region        string
	PreferredNode string // e.g. DE-01 — score boost when NodeName matches
	Limit         int    // top-N; default 3
}

// Scored is an endpoint with a selection score.
type Scored struct {
	Endpoint store.Endpoint
	Score    float64
}

// Rank filters (region/protocol/country already partly applied by ListSelectable),
// scores, and returns top-N candidates sorted by score desc then ID asc.
func Rank(list []store.Endpoint, q Query) []Scored {
	limit := q.Limit
	if limit <= 0 {
		limit = DefaultLimit
	}
	pref := strings.TrimSpace(q.PreferredNode)
	region := strings.TrimSpace(q.Region)

	var scored []Scored
	for _, e := range list {
		if e.State != "HEALTHY" && e.State != "DEGRADED" {
			continue
		}
		if !store.IsVLESS(e.Protocol) && len(e.PublicKey) != 32 {
			continue
		}
		if region != "" && !strings.EqualFold(e.Region, region) {
			continue
		}
		scored = append(scored, Scored{Endpoint: e, Score: score(e, pref)})
	}
	sort.SliceStable(scored, func(i, j int) bool {
		if scored[i].Score != scored[j].Score {
			return scored[i].Score > scored[j].Score
		}
		return scored[i].Endpoint.ID < scored[j].Endpoint.ID
	})
	if len(scored) > limit {
		scored = scored[:limit]
	}
	return scored
}

func score(e store.Endpoint, preferredNode string) float64 {
	s := 1.0
	if e.State == "DEGRADED" {
		s = 0.5
	}
	load := e.Load
	if load < 0 {
		load = 0
	}
	if load > 1 {
		load = 1
	}
	s -= load * 0.4
	if preferredNode != "" && strings.EqualFold(e.NodeName, preferredNode) {
		s += 0.25
	}
	if s < 0 {
		s = 0
	}
	return s
}
