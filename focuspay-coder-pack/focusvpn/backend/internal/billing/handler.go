package billing

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Handler exposes internal billing routes (X-Internal-Token).
type Handler struct {
	svc   *Service
	token string
}

// NewHandler wires billing routes.
func NewHandler(svc *Service, internalToken string) *Handler {
	return &Handler{svc: svc, token: internalToken}
}

// Routes registers internal endpoints on mux.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/internal/telegram/upsert", h.require(h.upsert))
	mux.HandleFunc("POST /v1/internal/billing/grant", h.require(h.grant))
	mux.HandleFunc("GET /v1/internal/billing/grants/{id}", h.require(h.getGrant))
	mux.HandleFunc("GET /v1/internal/billing/grants", h.require(h.listGrants))
	mux.HandleFunc("GET /v1/internal/billing/status", h.require(h.status))
	mux.HandleFunc("GET /v1/internal/billing/ending", h.require(h.ending))
	mux.HandleFunc("GET /v1/internal/telegram/devices", h.require(h.listDevices))
	mux.HandleFunc("POST /v1/internal/telegram/devices/revoke", h.require(h.revokeDevice))
}

func telegramIDParam(r *http.Request) (int64, bool) {
	tg, err := strconv.ParseInt(r.URL.Query().Get("telegram_id"), 10, 64)
	return tg, err == nil && tg > 0
}

func (h *Handler) listDevices(w http.ResponseWriter, r *http.Request) {
	tg, ok := telegramIDParam(r)
	if !ok {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "telegram_id required")
		return
	}
	list, err := h.svc.ListDevices(r.Context(), tg)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "list failed")
		return
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]any{"devices": list})
}

func (h *Handler) revokeDevice(w http.ResponseWriter, r *http.Request) {
	var body struct {
		TelegramID int64  `json:"telegram_id"`
		DeviceID   string `json:"device_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.TelegramID <= 0 || body.DeviceID == "" {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "telegram_id and device_id required")
		return
	}
	switch err := h.svc.RevokeDevice(r.Context(), body.TelegramID, body.DeviceID); {
	case err == nil:
		w.WriteHeader(http.StatusNoContent)
	case errors.Is(err, ErrDeviceNotFound):
		httpx.WriteError(w, r, http.StatusNotFound, "not_found", "device not found")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "revoke failed")
	}
}

// ending lists subscriptions ending in [from, to) (RFC3339; default now-24h .. now+24h).
func (h *Handler) ending(w http.ResponseWriter, r *http.Request) {
	now := time.Now().UTC()
	from, to := now.Add(-24*time.Hour), now.Add(24*time.Hour)
	for key, dst := range map[string]*time.Time{"from": &from, "to": &to} {
		if v := r.URL.Query().Get(key); v != "" {
			t, err := time.Parse(time.RFC3339, v)
			if err != nil {
				httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", key+" must be RFC3339")
				return
			}
			*dst = t
		}
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	list, err := h.svc.ListEnding(r.Context(), from, to, limit)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "list failed")
		return
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]any{"subscriptions": list})
}

func (h *Handler) require(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if h.token == "" {
			httpx.WriteError(w, r, http.StatusServiceUnavailable, "internal_disabled", "FOCUSVPN_INTERNAL_TOKEN not configured")
			return
		}
		if r.Header.Get("X-Internal-Token") != h.token {
			httpx.WriteError(w, r, http.StatusUnauthorized, "unauthorized", "invalid internal token")
			return
		}
		next(w, r)
	}
}

func (h *Handler) upsert(w http.ResponseWriter, r *http.Request) {
	var body struct {
		TelegramID int64 `json:"telegram_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid json")
		return
	}
	res, err := h.svc.UpsertTelegramUser(r.Context(), body.TelegramID)
	if err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	httpx.WriteJSON(w, http.StatusOK, res)
}

func (h *Handler) grant(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ExternalID string `json:"external_id"`
		TelegramID int64  `json:"telegram_id"`
		Kind       string `json:"kind"`
		PlanCode   string `json:"plan_code"`
		Days       int    `json:"days"`
		AmountRUB  string `json:"amount_rub"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid json")
		return
	}
	kopecks, err := ParseRubles(body.AmountRUB)
	if err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	res, err := h.svc.Grant(r.Context(), GrantRequest{
		ExternalID: body.ExternalID, TelegramID: body.TelegramID, Kind: body.Kind,
		PlanCode: body.PlanCode, Days: body.Days, AmountKopecks: kopecks,
	})
	switch {
	case err == nil:
		httpx.WriteJSON(w, http.StatusOK, res)
	case errors.Is(err, ErrInvalid), errors.Is(err, store.ErrNoSubscription):
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", err.Error())
	case errors.Is(err, store.ErrTrialUsed):
		httpx.WriteError(w, r, http.StatusConflict, "trial_used", "trial already used")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "grant failed")
	}
}

func (h *Handler) getGrant(w http.ResponseWriter, r *http.Request) {
	res, err := h.svc.GetGrant(r.Context(), r.PathValue("id"))
	switch {
	case err == nil:
		httpx.WriteJSON(w, http.StatusOK, res)
	case errors.Is(err, store.ErrNotFound):
		httpx.WriteError(w, r, http.StatusNotFound, "not_found", "grant not found")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "lookup failed")
	}
}

func (h *Handler) listGrants(w http.ResponseWriter, r *http.Request) {
	since := time.Now().Add(-31 * 24 * time.Hour)
	if v := r.URL.Query().Get("since"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "since must be RFC3339")
			return
		}
		since = t
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	res, err := h.svc.ListGrants(r.Context(), since, limit)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "list failed")
		return
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]any{"grants": res})
}

func (h *Handler) status(w http.ResponseWriter, r *http.Request) {
	tgStr := r.URL.Query().Get("telegram_id")
	tg, err := strconv.ParseInt(tgStr, 10, 64)
	if err != nil || tg <= 0 {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "telegram_id required")
		return
	}
	res, err := h.svc.Status(r.Context(), tg)
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", err.Error())
		return
	}
	httpx.WriteJSON(w, http.StatusOK, res)
}
