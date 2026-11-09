package connections

import (
	"errors"
	"net/http"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/nodeselector"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes connection HTTP endpoints.
type Handler struct {
	svc  *Service
	auth *auth.Authenticator
}

// NewHandler wires the handler.
func NewHandler(svc *Service, a *auth.Authenticator) *Handler {
	return &Handler{svc: svc, auth: a}
}

// Routes registers routes.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/connections", h.auth.Require(h.Create))
	mux.HandleFunc("DELETE /v1/connections/{id}", h.auth.Require(h.Revoke))
}

// Create handles POST /v1/connections.
func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	var req apitypes.CreateConnectionRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid request body")
		return
	}
	preferred := req.PreferredNode
	if preferred == "" {
		preferred = req.SelectedNode // UI alias
	}
	res, err := h.svc.Create(r.Context(), p.UserID, req.DeviceID, req.Protocol, req.Country, req.Region, preferred)
	if err != nil {
		writeErr(w, r, err)
		return
	}
	code := http.StatusCreated
	if !res.Created {
		code = http.StatusOK
	}
	httpx.WriteJSON(w, code, apitypes.CreateConnectionResponse{
		Connection:    apitypes.ConnectionDTO{ID: res.Allocation.ID, Status: res.APIStatus},
		Candidates:    mapCandidates(res.Candidates),
		ConfigID:      res.Configuration.ID,
		ConfigVersion: res.Configuration.Version,
	})
}

func mapCandidates(in []nodeselector.Scored) []apitypes.CandidateEndpoint {
	out := make([]apitypes.CandidateEndpoint, 0, len(in))
	for _, c := range in {
		var cand apitypes.CandidateEndpoint
		cand.Endpoint.ID = c.Endpoint.ID
		cand.Endpoint.Host = c.Endpoint.Hostname
		cand.Endpoint.Port = c.Endpoint.Port
		cand.Endpoint.Protocol = c.Endpoint.Protocol
		cand.Node = c.Endpoint.NodeName
		cand.Score = c.Score
		out = append(out, cand)
	}
	return out
}

// Revoke handles DELETE /v1/connections/{id}.
func (h *Handler) Revoke(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	id := r.PathValue("id")
	if id == "" {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "missing connection id")
		return
	}
	if err := h.svc.Revoke(r.Context(), p.UserID, id); err != nil {
		writeErr(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func writeErr(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, ErrValidation):
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid request")
	case errors.Is(err, ErrDeviceNotFound):
		httpx.WriteError(w, r, http.StatusNotFound, "device_not_found", "device not found")
	case errors.Is(err, ErrForbidden):
		httpx.WriteError(w, r, http.StatusForbidden, "forbidden", "forbidden")
	case errors.Is(err, ErrNodeUnavailable):
		httpx.WriteError(w, r, http.StatusServiceUnavailable, "node_unavailable", "no healthy endpoint available")
	case errors.Is(err, ErrTooManyAllocations):
		httpx.WriteError(w, r, http.StatusConflict, "too_many_allocations", "allocation limit reached")
	case errors.Is(err, ErrTooManyDevices):
		httpx.WriteError(w, r, http.StatusConflict, "too_many_devices", "device limit reached")
	case errors.Is(err, ErrSubscriptionExpired), errors.Is(err, store.ErrSubscriptionExpired):
		httpx.WriteError(w, r, http.StatusPaymentRequired, "subscription_expired", "subscription expired")
	case errors.Is(err, ErrNotFound):
		httpx.WriteError(w, r, http.StatusNotFound, "not_found", "connection not found")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
	}
}
