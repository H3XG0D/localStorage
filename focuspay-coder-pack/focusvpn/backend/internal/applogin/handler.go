package applogin

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes Telegram app login HTTP routes.
type Handler struct {
	svc     *Service
	limiter ratelimit.Limiter
	token   string
}

// NewHandler wires routes.
func NewHandler(svc *Service, limiter ratelimit.Limiter, internalToken string) *Handler {
	return &Handler{svc: svc, limiter: limiter, token: internalToken}
}

// Routes registers public + internal endpoints.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/auth/telegram/start", h.start)
	mux.HandleFunc("GET /v1/auth/telegram/wait", h.wait)
	mux.HandleFunc("POST /v1/auth/telegram/code", h.redeemCode)
	mux.HandleFunc("POST /v1/internal/telegram/attach-login", h.require(h.attachLogin))
	mux.HandleFunc("POST /v1/internal/telegram/login-code", h.require(h.loginCode))
}

func (h *Handler) start(w http.ResponseWriter, r *http.Request) {
	ip := httpx.ClientIP(r)
	if !h.limiter.Allow("tglogin:start:ip:"+ip, 30, time.Minute) {
		httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many attempts")
		return
	}
	res, err := h.svc.Start(r.Context())
	if err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "could not start login")
		return
	}
	httpx.WriteJSON(w, http.StatusOK, res)
}

func (h *Handler) wait(w http.ResponseWriter, r *http.Request) {
	wait := r.URL.Query().Get("wait_token")
	ip := httpx.ClientIP(r)
	if !h.limiter.Allow("tglogin:wait:ip:"+ip, 120, time.Minute) {
		httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many attempts")
		return
	}
	u, toks, err := h.svc.Wait(r.Context(), wait)
	if errors.Is(err, ErrNotReady) {
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"status":"pending"}`))
		return
	}
	if err != nil {
		h.writeErr(w, r, err)
		return
	}
	h.writeAuth(w, u, toks)
}

func (h *Handler) redeemCode(w http.ResponseWriter, r *http.Request) {
	ip := httpx.ClientIP(r)
	if !h.limiter.Allow("tglogin:code:ip:"+ip, 20, time.Minute) {
		httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many attempts")
		return
	}
	var body struct {
		Code string `json:"code"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid json")
		return
	}
	u, toks, err := h.svc.RedeemCode(r.Context(), body.Code)
	if err != nil {
		h.writeErr(w, r, err)
		return
	}
	h.writeAuth(w, u, toks)
}

func (h *Handler) attachLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		StartToken string `json:"start_token"`
		TelegramID int64  `json:"telegram_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid json")
		return
	}
	if err := h.svc.AttachLogin(r.Context(), body.StartToken, body.TelegramID); err != nil {
		if errors.Is(err, ErrInvalidCode) {
			httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid start token")
			return
		}
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]string{"status": "attached"})
}

func (h *Handler) loginCode(w http.ResponseWriter, r *http.Request) {
	var body struct {
		TelegramID int64 `json:"telegram_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", "invalid json")
		return
	}
	code, err := h.svc.IssuePairCode(r.Context(), body.TelegramID)
	if err != nil {
		httpx.WriteError(w, r, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	httpx.WriteJSON(w, http.StatusOK, map[string]any{
		"code":       code,
		"expires_in": int(h.svc.ttl.Seconds()),
	})
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

func (h *Handler) writeErr(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, ErrExpired):
		httpx.WriteError(w, r, http.StatusGone, "expired", "login expired")
	case errors.Is(err, ErrInvalidCode):
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_code", "invalid or used code")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
	}
}

func (h *Handler) writeAuth(w http.ResponseWriter, u store.User, toks auth.Tokens) {
	httpx.WriteJSON(w, http.StatusOK, apitypes.AuthResponse{
		User: apitypes.UserDTO{ID: u.ID, Email: u.Email, Role: u.Role},
		Tokens: apitypes.Tokens{
			AccessToken:  toks.Access,
			RefreshToken: toks.Refresh,
			ExpiresIn:    toks.ExpiresIn,
		},
	})
}
