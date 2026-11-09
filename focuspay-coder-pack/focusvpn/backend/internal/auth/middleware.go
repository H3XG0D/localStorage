package auth

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
)

// Principal is the authenticated caller derived from a valid access token.
type Principal struct {
	UserID string
	Role   string
}

type ctxKey struct{}

// PrincipalFrom returns the authenticated principal from the request context.
func PrincipalFrom(ctx context.Context) (Principal, bool) {
	p, ok := ctx.Value(ctxKey{}).(Principal)
	return p, ok
}

// Authenticator validates access tokens and applies the general per-token rate
// limit to authenticated endpoints (API.md §1 / SECURITY.md §6).
type Authenticator struct {
	issuer  *TokenIssuer
	limiter ratelimit.Limiter
	perMin  int
}

// NewAuthenticator builds an Authenticator.
func NewAuthenticator(issuer *TokenIssuer, limiter ratelimit.Limiter, perMin int) *Authenticator {
	return &Authenticator{issuer: issuer, limiter: limiter, perMin: perMin}
}

// Require wraps a handler, rejecting requests without a valid access token. On
// success the principal is attached to the request context.
func (a *Authenticator) Require(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token := bearer(r)
		if token == "" {
			httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "missing access token")
			return
		}
		claims, err := a.issuer.ParseAccess(token)
		if err != nil {
			if errors.Is(err, jwt.ErrTokenExpired) {
				httpx.WriteError(w, r, http.StatusUnauthorized, "expired_token", "access token expired")
				return
			}
			httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "invalid access token")
			return
		}
		p := Principal{UserID: claims.Subject, Role: claims.Role}
		if p.UserID == "" {
			httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "invalid access token")
			return
		}
		if a.perMin > 0 && !a.limiter.Allow("api:token:"+p.UserID, a.perMin, time.Minute) {
			httpx.WriteError(w, r, http.StatusTooManyRequests, "rate_limited", "too many requests, slow down")
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), ctxKey{}, p)))
	}
}
