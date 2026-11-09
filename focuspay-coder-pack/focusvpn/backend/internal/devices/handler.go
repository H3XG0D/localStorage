package devices

import (
	"errors"
	"net/http"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes the device HTTP endpoints (API.md §4).
type Handler struct {
	svc        *Service
	auth       *auth.Authenticator
	deviceAuth *auth.DeviceAuthenticator
}

// NewHandler wires the device handler.
func NewHandler(svc *Service, a *auth.Authenticator, deviceAuth *auth.DeviceAuthenticator) *Handler {
	return &Handler{svc: svc, auth: a, deviceAuth: deviceAuth}
}

// Routes registers the authenticated device endpoints.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/devices", h.auth.Require(h.List))
	mux.HandleFunc("POST /v1/devices", h.auth.Require(h.Create))
	mux.HandleFunc("DELETE /v1/devices/{id}", h.auth.Require(h.Revoke))
	mux.HandleFunc("POST /v1/devices/{id}/rotate-key", h.auth.Require(h.deviceAuth.Require(h.RotateKey)))
}

// Create handles POST /v1/devices.
func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	var req apitypes.CreateDeviceRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid request body")
		return
	}
	d, token, err := h.svc.Create(r.Context(), p.UserID, req.Name, req.Platform, req.AppVersion, req.PublicKey)
	if err != nil {
		writeDeviceError(w, r, err)
		return
	}
	httpx.WriteJSON(w, http.StatusCreated, apitypes.CreateDeviceResponse{
		Device:      toDeviceDTO(d),
		DeviceToken: token,
	})
}

// List handles GET /v1/devices.
func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	ds, err := h.svc.List(r.Context(), p.UserID)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	out := apitypes.DeviceListResponse{Devices: make([]apitypes.DeviceDTO, 0, len(ds))}
	for _, d := range ds {
		out.Devices = append(out.Devices, toDeviceDTO(d))
	}
	httpx.WriteJSON(w, http.StatusOK, out)
}

// Revoke handles DELETE /v1/devices/{id}.
func (h *Handler) Revoke(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	id := r.PathValue("id")
	if id == "" {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "missing device id")
		return
	}
	if err := h.svc.Revoke(r.Context(), id, p.UserID); err != nil {
		writeDeviceError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// RotateKey handles POST /v1/devices/{id}/rotate-key (JWT owner + X-Device-Token).
func (h *Handler) RotateKey(w http.ResponseWriter, r *http.Request) {
	p, _ := auth.PrincipalFrom(r.Context())
	dev, ok := auth.DeviceFrom(r.Context())
	if !ok {
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "missing device token")
		return
	}
	id := r.PathValue("id")
	if id == "" || id != dev.ID || dev.UserID != p.UserID {
		httpx.WriteError(w, r, http.StatusForbidden, "forbidden", "device mismatch")
		return
	}
	var req apitypes.RotateKeyRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid request body")
		return
	}
	res, err := h.svc.RotateKey(r.Context(), p.UserID, id, req.PublicKey)
	if err != nil {
		writeDeviceError(w, r, err)
		return
	}
	httpx.WriteJSON(w, http.StatusOK, apitypes.RotateKeyResponse{
		Device:            toDeviceDTO(res.Device),
		ConfigVersionBump: res.ConfigVersionBump,
	})
}

func writeDeviceError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, ErrValidation):
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid device fields")
	case errors.Is(err, ErrBadKey), errors.Is(err, ErrForbidden):
		httpx.WriteError(w, r, http.StatusForbidden, "forbidden", "invalid public key")
	case errors.Is(err, ErrTooManyDevs):
		httpx.WriteError(w, r, http.StatusConflict, "too_many_devices", "device limit reached for plan")
	case errors.Is(err, ErrKeyInUse):
		httpx.WriteError(w, r, http.StatusConflict, "conflict", "public key already registered")
	case errors.Is(err, ErrNotFound):
		httpx.WriteError(w, r, http.StatusNotFound, "not_found", "device not found")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
	}
}

func toDeviceDTO(d store.Device) apitypes.DeviceDTO {
	dto := apitypes.DeviceDTO{
		ID:        d.ID,
		Name:      d.Name,
		Platform:  d.Platform,
		Status:    d.Status,
		CreatedAt: d.CreatedAt.UTC().Format(time.RFC3339),
	}
	if d.AppVersion != nil {
		dto.AppVersion = *d.AppVersion
	}
	if d.LastSeenAt != nil {
		s := d.LastSeenAt.UTC().Format(time.RFC3339)
		dto.LastSeenAt = &s
	}
	return dto
}
