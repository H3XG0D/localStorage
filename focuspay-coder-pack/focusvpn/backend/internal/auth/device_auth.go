package auth

import (
	"context"
	"net/http"

	"focusvpn.example/focusvpn/backend/internal/platform/httpx"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

type deviceCtxKey struct{}

// DeviceFrom returns the device authenticated via X-Device-Token.
func DeviceFrom(ctx context.Context) (store.Device, bool) {
	d, ok := ctx.Value(deviceCtxKey{}).(store.Device)
	return d, ok
}

// DeviceAuthenticator validates X-Device-Token against the devices store.
type DeviceAuthenticator struct {
	devices store.DeviceStore
	issuer  *TokenIssuer
}

// NewDeviceAuthenticator constructs a device-token authenticator.
func NewDeviceAuthenticator(devices store.DeviceStore, issuer *TokenIssuer) *DeviceAuthenticator {
	return &DeviceAuthenticator{devices: devices, issuer: issuer}
}

// Require wraps a handler requiring a valid X-Device-Token.
func (a *DeviceAuthenticator) Require(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		tok := r.Header.Get("X-Device-Token")
		if tok == "" {
			httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "missing device token")
			return
		}
		hash := a.issuer.HashRefresh(tok)
		d, err := a.devices.GetDeviceByTokenHash(r.Context(), hash)
		if err != nil {
			httpx.WriteError(w, r, http.StatusUnauthorized, "invalid_token", "invalid device token")
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), deviceCtxKey{}, d)))
	}
}
