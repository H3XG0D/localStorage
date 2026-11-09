// Package servers serves GET /v1/servers (API.md §5, plans/M3).
package servers

import (
	"errors"
	"net/http"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/nodeselector"
	"focusvpn.example/focusvpn/backend/internal/platform/entitlement"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes GET /v1/servers.
type Handler struct {
	endpoints store.EndpointStore
	subs      store.SubscriptionStore
	auth      *auth.Authenticator
}

// NewHandler wires the servers handler.
func NewHandler(endpoints store.EndpointStore, subs store.SubscriptionStore, a *auth.Authenticator) *Handler {
	return &Handler{endpoints: endpoints, subs: subs, auth: a}
}

// Routes registers endpoints.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/servers", h.auth.Require(h.List))
}

// List handles GET /v1/servers.
func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	if err := entitlement.Check(r.Context(), h.subs, p.UserID); err != nil {
		if errors.Is(err, store.ErrSubscriptionExpired) {
			httpx.WriteError(w, r, http.StatusPaymentRequired, "subscription_expired", "subscription expired")
			return
		}
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	q := r.URL.Query()
	protocol := q.Get("protocol")
	country := q.Get("country")
	region := q.Get("region")
	preferred := q.Get("preferred_node")
	list, err := h.endpoints.ListSelectable(r.Context(), protocol, country)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	// Score all selectable endpoints for the UI location list (not top-N failover cut).
	ranked := nodeselector.Rank(list, nodeselector.Query{
		Protocol: protocol, Country: country, Region: region,
		PreferredNode: preferred, Limit: len(list),
	})
	out := apitypes.ServersResponse{Endpoints: make([]apitypes.EndpointDTO, 0, len(ranked))}
	for _, c := range ranked {
		e := c.Endpoint
		out.Endpoints = append(out.Endpoints, apitypes.EndpointDTO{
			ID: e.ID, Node: e.NodeName, Country: e.Country, Region: e.Region, Protocol: e.Protocol, Score: c.Score,
			Host: e.Hostname, Port: e.Port,
		})
	}
	httpx.WriteJSON(w, http.StatusOK, out)
}
