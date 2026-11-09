package sublink

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
)

// Handler exposes the bot issue route and the public Happ fetch.
type Handler struct {
	svc     *Service
	limiter ratelimit.Limiter
	token   string
}

// NewHandler wires routes. internalToken gates the bot route only.
func NewHandler(svc *Service, limiter ratelimit.Limiter, internalToken string) *Handler {
	return &Handler{svc: svc, limiter: limiter, token: internalToken}
}

// Routes registers POST /v1/internal/telegram/sub-link and GET /v1/sub/{token}.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/internal/telegram/sub-link", h.require(h.issue))
	mux.HandleFunc("GET /v1/sub/{token}", h.fetch)
}

func (h *Handler) issue(w http.ResponseWriter, r *http.Request) {
	var body struct {
		TelegramID int64 `json:"telegram_id"`
		Rotate     bool  `json:"rotate"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid json")
		return
	}
	issued, err := h.svc.Issue(r.Context(), body.TelegramID, body.Rotate)
	if err != nil {
		h.writeErr(w, r, err)
		return
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]any{
		"url":       issued.URL,
		"ends_at":   issued.EndsAt.UTC().Format(time.RFC3339),
		"device_id": issued.DeviceID,
	})
}

func (h *Handler) fetch(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "private, no-store")
	token := r.PathValue("token")
	ip := httpx.ClientIP(r)
	sum := sha256.Sum256([]byte(token))
	key := hex.EncodeToString(sum[:8])
	if h.limiter != nil && (!h.limiter.Allow("sub:ip:"+ip, 60, time.Minute) || !h.limiter.Allow("sub:tok:"+key, 120, time.Minute)) {
		httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many attempts")
		return
	}
	page, err := h.svc.Render(r.Context(), token)
	if err != nil {
		h.writeErr(w, r, err)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("profile-title", "base64:"+base64.StdEncoding.EncodeToString([]byte("FocusVPN")))
	w.Header().Set("profile-update-interval", "1")
	w.Header().Set("subscription-userinfo", "upload=0; download=0; total=0; expire="+strconv.FormatInt(page.Expires.Unix(), 10))
	if page.Support != "" {
		w.Header().Set("support-url", page.Support)
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(page.Body))
}

func (h *Handler) writeErr(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, ErrBadRequest):
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "telegram_id required")
	case errors.Is(err, ErrNotFound):
		httpx.WriteError(w, r, http.StatusNotFound, "not_found", "not found")
	case errors.Is(err, ErrNoSubscription):
		httpx.WriteError(w, r, http.StatusPaymentRequired, "no_subscription", "subscription required")
	case errors.Is(err, ErrTooManyDevices):
		httpx.WriteError(w, r, http.StatusConflict, "too_many_devices", "no free device seat")
	case errors.Is(err, ErrNoNodes):
		httpx.WriteError(w, r, http.StatusServiceUnavailable, "no_nodes", "no location available")
	default:
		log.Printf("sublink: %v", err)
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal error")
	}
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
