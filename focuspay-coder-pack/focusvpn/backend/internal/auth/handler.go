package auth

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/config"
	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Handler exposes the auth HTTP endpoints (API.md §2).
type Handler struct {
	svc     *Service
	limiter ratelimit.Limiter
	limits  config.RateLimits
}

// NewHandler wires the auth handler.
func NewHandler(svc *Service, limiter ratelimit.Limiter, limits config.RateLimits) *Handler {
	return &Handler{svc: svc, limiter: limiter, limits: limits}
}

// Routes registers auth endpoints on mux.
func (h *Handler) Routes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/auth/register", h.Register)
	mux.HandleFunc("POST /v1/auth/login", h.Login)
	mux.HandleFunc("POST /v1/auth/refresh", h.Refresh)
	mux.HandleFunc("POST /v1/auth/logout", h.Logout)
}

// Register handles POST /v1/auth/register.
func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	ip := httpx.ClientIP(r)
	if !h.limiter.Allow("register:ip:"+ip, h.limits.RegisterPerHourPerIP, time.Hour) {
		httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many registrations, retry later")
		return
	}
	var req apitypes.RegisterRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid request body")
		return
	}
	u, toks, err := h.svc.Register(r.Context(), req.Email, req.Password)
	if err != nil {
		h.writeServiceError(w, r, err)
		return
	}
	httpx.WriteJSON(w, http.StatusCreated, apitypes.AuthResponse{
		User:   apitypes.UserDTO{ID: u.ID, Email: u.Email, Role: u.Role},
		Tokens: toTokens(toks),
	})
}

// Login handles POST /v1/auth/login.
func (h *Handler) Login(w http.ResponseWriter, r *http.Request) {
	ip := httpx.ClientIP(r)
	var req apitypes.LoginRequest
	if err := httpx.DecodeJSON(r, &req); err != nil {
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid request body")
		return
	}
	acct := strings.ToLower(strings.TrimSpace(req.Email))
	if !h.limiter.Allow("login:ip:"+ip, h.limits.LoginPerMinutePerIP, time.Minute) ||
		!h.limiter.Allow("login:acct:"+acct, h.limits.LoginPerMinutePerAcct, time.Minute) {
		httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many login attempts, retry later")
		return
	}
	u, toks, err := h.svc.Login(r.Context(), req.Email, req.Password)
	if err != nil {
		h.writeServiceError(w, r, err)
		return
	}
	httpx.WriteJSON(w, http.StatusOK, apitypes.AuthResponse{
		User:   apitypes.UserDTO{ID: u.ID, Email: u.Email, Role: u.Role},
		Tokens: toTokens(toks),
	})
}

// Refresh handles POST /v1/auth/refresh. The refresh token is taken from the
// Authorization: Bearer header (API.md §2).
func (h *Handler) Refresh(w http.ResponseWriter, r *http.Request) {
	token := bearer(r)
	if token == "" {
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "missing refresh token")
		return
	}
	toks, err := h.svc.Refresh(r.Context(), token)
	if err != nil {
		h.writeServiceError(w, r, err)
		return
	}
	httpx.WriteJSON(w, http.StatusOK, apitypes.RefreshResponse{
		AccessToken:  toks.Access,
		RefreshToken: toks.Refresh,
		ExpiresIn:    toks.ExpiresIn,
	})
}

// Logout handles POST /v1/auth/logout.
func (h *Handler) Logout(w http.ResponseWriter, r *http.Request) {
	var req apitypes.LogoutRequest
	_ = httpx.DecodeJSON(r, &req)
	token := req.RefreshToken
	if token == "" {
		token = bearer(r)
	}
	if err := h.svc.Logout(r.Context(), token); err != nil {
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "logout failed")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) writeServiceError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, ErrValidation):
		httpx.WriteError(w, r, http.StatusUnprocessableEntity, "validation_error", "invalid email or password")
	case errors.Is(err, ErrEmailExists):
		httpx.WriteError(w, r, http.StatusConflict, "email_already_exists", "email already registered")
	case errors.Is(err, ErrInvalidCreds):
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_credentials", "invalid email or password")
	case errors.Is(err, ErrInvalidToken):
		httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "invalid token")
	case errors.Is(err, ErrExpiredToken):
		httpx.WriteError(w, r, http.StatusUnauthorized, "expired_token", "token expired")
	case errors.Is(err, ErrAccountStatus):
		httpx.WriteError(w, r, http.StatusForbidden, "forbidden", "account not active")
	default:
		httpx.WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
	}
}

func toTokens(t Tokens) apitypes.Tokens {
	return apitypes.Tokens{AccessToken: t.Access, RefreshToken: t.Refresh, ExpiresIn: t.ExpiresIn}
}

func bearer(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if len(h) > 7 && strings.EqualFold(h[:7], "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return ""
}
