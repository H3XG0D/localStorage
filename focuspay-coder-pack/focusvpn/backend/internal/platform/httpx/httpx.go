// Package httpx provides HTTP plumbing shared by all Control Plane modules:
// request-id propagation, panic recovery, JSON helpers and the standard error
// envelope (API.md §1).
package httpx

import (
	"context"
	"encoding/json"
	"log"
	"net"
	"net/http"

	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

type ctxKey int

const requestIDKey ctxKey = iota

// RequestID returns the request id stored in ctx, or "".
func RequestID(ctx context.Context) string {
	if v, ok := ctx.Value(requestIDKey).(string); ok {
		return v
	}
	return ""
}

// WithRequestID assigns an X-Request-Id to each request and echoes it back.
func WithRequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rid := r.Header.Get("X-Request-Id")
		if rid == "" {
			rid = id.NewUUID()
		}
		w.Header().Set("X-Request-Id", rid)
		ctx := context.WithValue(r.Context(), requestIDKey, rid)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// Recover converts panics into 500 responses instead of crashing the server.
func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("panic: %v (request_id=%s)", rec, RequestID(r.Context()))
				WriteError(w, r, http.StatusInternalServerError, "internal_error", "internal server error")
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// WriteJSON writes v as JSON with the given status code.
func WriteJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if v != nil {
		_ = json.NewEncoder(w).Encode(v)
	}
}

// WriteError writes the standard error envelope.
func WriteError(w http.ResponseWriter, r *http.Request, status int, code, msg string) {
	WriteJSON(w, status, apitypes.ErrorEnvelope{Error: apitypes.ErrorBody{
		Code:      code,
		Message:   msg,
		RequestID: RequestID(r.Context()),
	}})
}

// DecodeJSON decodes the request body into dst, rejecting unknown fields.
func DecodeJSON(r *http.Request, dst any) error {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	return dec.Decode(dst)
}

// ClientIP extracts a best-effort client IP for rate limiting (dev: RemoteAddr).
func ClientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
