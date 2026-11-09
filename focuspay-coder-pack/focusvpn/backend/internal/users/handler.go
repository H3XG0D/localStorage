// Package users serves user-facing profile endpoints (API.md §3). It returns
// only user-safe fields; password hashes and other secret material never leave
// the store layer.
package users

import (
	"errors"
	"net/http"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes GET /v1/me.
type Handler struct {
	users   store.UserStore
	subs    store.SubscriptionStore
	devices store.DeviceStore
	auth    *auth.Authenticator
}

// NewHandler wires the users handler.
func NewHandler(users store.UserStore, subs store.SubscriptionStore, devices store.DeviceStore, a *auth.Authenticator) *Handler {
	return &Handler{users: users, subs: subs, devices: devices, auth: a}
}

// Routes registers the authenticated user endpoints.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/me", h.auth.Require(h.Me))
}

// Me handles GET /v1/me for the authenticated principal.
func (h *Handler) Me(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "not authenticated")
		return
	}
	u, err := h.users.GetUserByID(r.Context(), p.UserID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "user not found")
			return
		}
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}

	resp := apitypes.MeResponse{
		User: apitypes.UserDTO{ID: u.ID, Email: u.Email, Role: u.Role},
	}

	sub, plan, err := h.subs.GetActiveByUser(r.Context(), u.ID)
	switch {
	case err == nil:
		used, cerr := h.devices.CountActiveDevicesByUser(r.Context(), u.ID)
		if cerr != nil {
			httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
			return
		}
		slots, serr := h.subs.ListLiveDeviceSlots(r.Context(), u.ID, time.Now())
		if serr != nil {
			httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
			return
		}
		resp.Subscription = &apitypes.SubscriptionDTO{
			Status:      sub.Status,
			Plan:        plan.Code,
			EndsAt:      sub.EndsAt.UTC().Format(time.RFC3339),
			MaxDevices:  plan.MaxDevices + len(slots),
			DevicesUsed: used,
		}
	case errors.Is(err, store.ErrNoSubscription):
		// No active subscription => subscription is null (API.md §3).
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}

	httpx.WriteJSON(w, http.StatusOK, resp)
}
