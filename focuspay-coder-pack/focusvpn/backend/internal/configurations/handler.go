// Package configurations serves GET /v1/configurations/:id (API.md §7, plans/M3).
package configurations

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"

	"focusvpn.example/focusvpn/backend/internal/auth"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/entitlement"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes configuration fetch.
type Handler struct {
	configs store.ConfigurationStore
	subs    store.SubscriptionStore
	device  *auth.DeviceAuthenticator
	keks    map[string]mycrypto.KEK
}

// NewHandler wires the handler.
func NewHandler(configs store.ConfigurationStore, subs store.SubscriptionStore, device *auth.DeviceAuthenticator, keks map[string]mycrypto.KEK) *Handler {
	return &Handler{configs: configs, subs: subs, device: device, keks: keks}
}

// Routes registers routes.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/configurations/{id}", h.device.Require(h.Get))
}

// Get handles GET /v1/configurations/{id}.
func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	dev, ok := auth.DeviceFrom(r.Context())
	if !ok {
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "not authenticated")
		return
	}
	id := r.PathValue("id")
	if id == "" {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "missing config id")
		return
	}
	cfg, err := h.configs.GetConfigurationByID(r.Context(), id)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			httpx.WriteError(w, r, http.StatusNotFound, "not_found", "configuration not found")
			return
		}
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	if cfg.DeviceID != dev.ID {
		httpx.WriteError(w, r, http.StatusForbidden, "forbidden", "forbidden")
		return
	}
	if cfg.Status != "active" {
		httpx.WriteError(w, r, http.StatusGone, "gone", "configuration revoked")
		return
	}
	if err := entitlement.Check(r.Context(), h.subs, dev.UserID); err != nil {
		if errors.Is(err, store.ErrSubscriptionExpired) {
			httpx.WriteError(w, r, http.StatusPaymentRequired, "subscription_expired", "subscription expired")
			return
		}
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	pt, err := mycrypto.OpenEnvelope(h.keks, cfg.ContentEncrypted)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	var parts map[string]any
	if err := json.Unmarshal(pt, &parts); err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	httpx.WriteJSON(w, http.StatusOK, apitypes.ConfigPartsResponse{
		ConfigVersion: cfg.Version,
		Signature:     base64.StdEncoding.EncodeToString(cfg.Signature),
		Parts:         parts,
	})
}
