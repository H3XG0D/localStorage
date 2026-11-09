// Package devices implements device registration/listing/revocation (API.md §4).
// It never stores client private keys; only the client's public key and a keyed
// hash of the one-time device token are persisted.
package devices

import (
	"context"
	"encoding/base64"
	"errors"
	"strings"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Service-level errors, mapped to HTTP codes by the handler.
var (
	ErrValidation  = errors.New("validation_error")
	ErrBadKey      = errors.New("forbidden")        // public key wrong length/encoding
	ErrTooManyDevs = errors.New("too_many_devices") // plan limit reached
	ErrKeyInUse    = errors.New("conflict")         // duplicate active public key
	ErrNotFound    = errors.New("not_found")
	ErrForbidden   = errors.New("authz_forbidden") // JWT/device mismatch
)

// x25519 public keys are 32 bytes.
const x25519KeyLen = 32

var validPlatforms = map[string]bool{
	"android": true, "ios": true, "macos": true, "windows": true, "linux": true,
	// link is the Happ subscription key: it occupies a seat, it is not a Focus app.
	"link": true,
}

// tokenHasher hashes an opaque device token so a DB leak cannot be replayed.
type tokenHasher interface {
	HashRefresh(token string) string
}

// configReissuer re-signs active ConfigParts after a client key rotation and
// revokes a device's connections when the device is unlinked.
type configReissuer interface {
	ReissueConfig(ctx context.Context, old store.Configuration) (store.Configuration, error)
	RevokeByDevice(ctx context.Context, deviceID string) error
}

// Service implements the device vertical slice.
type Service struct {
	devices  store.DeviceStore
	subs     store.SubscriptionStore
	allocs   store.AllocationStore
	configs  store.ConfigurationStore
	reissuer configReissuer
	hasher   tokenHasher
	now      func() time.Time
}

// NewService constructs the device service. The hasher is the auth TokenIssuer.
// Call SetRotation before rotate-key is used.
func NewService(devices store.DeviceStore, subs store.SubscriptionStore, issuer *auth.TokenIssuer) *Service {
	return &Service{devices: devices, subs: subs, hasher: issuer, now: time.Now}
}

// SetRotation wires allocation/config stores and a config reissuer (connections.Service).
func (s *Service) SetRotation(allocs store.AllocationStore, configs store.ConfigurationStore, reissuer configReissuer) {
	s.allocs = allocs
	s.configs = configs
	s.reissuer = reissuer
}

// Create registers a device for the user and returns the device plus a one-time
// device token (returned to the caller only once; only its hash is stored).
func (s *Service) Create(ctx context.Context, userID, name, platform, appVersion, publicKeyB64 string) (store.Device, string, error) {
	name = strings.TrimSpace(name)
	platform = strings.TrimSpace(platform)
	if name == "" || len(name) > 100 || !validPlatforms[platform] {
		return store.Device{}, "", ErrValidation
	}
	key, err := base64.StdEncoding.DecodeString(strings.TrimSpace(publicKeyB64))
	if err != nil || len(key) != x25519KeyLen {
		return store.Device{}, "", ErrBadKey
	}

	max, err := s.deviceLimit(ctx, userID)
	if err != nil {
		return store.Device{}, "", err
	}

	token := id.NewOpaqueToken(32)
	now := s.now()
	d := store.Device{
		ID:              id.NewUUID(),
		UserID:          userID,
		Name:            name,
		Platform:        platform,
		PublicKey:       key,
		DeviceTokenHash: s.hasher.HashRefresh(token),
		Status:          "active",
		CreatedAt:       now,
		UpdatedAt:       now,
	}
	if v := strings.TrimSpace(appVersion); v != "" {
		d.AppVersion = &v
	}

	if err := s.devices.CreateDevice(ctx, d, max); err != nil {
		switch {
		case errors.Is(err, store.ErrDeviceLimit):
			return store.Device{}, "", ErrTooManyDevs
		case errors.Is(err, store.ErrConflict):
			return store.Device{}, "", ErrKeyInUse
		default:
			return store.Device{}, "", err
		}
	}
	return d, token, nil
}

// deviceLimit resolves the caller's active-device cap: the live subscription's
// plan plus unexpired extra-device seats. Without a live subscription the cap
// is the free plan, then 1. Extra seats resume only while a subscription is live.
func (s *Service) deviceLimit(ctx context.Context, userID string) (int, error) {
	if _, plan, err := s.subs.GetActiveByUser(ctx, userID); err == nil {
		slots, err := s.subs.ListLiveDeviceSlots(ctx, userID, s.now())
		if err != nil {
			return 0, err
		}
		return plan.MaxDevices + len(slots), nil
	} else if !errors.Is(err, store.ErrNoSubscription) {
		return 0, err
	}
	if plan, err := s.subs.GetPlanByCode(ctx, "free"); err == nil {
		return plan.MaxDevices, nil
	} else if !errors.Is(err, store.ErrNotFound) {
		return 0, err
	}
	return 1, nil
}

// List returns the caller's devices.
func (s *Service) List(ctx context.Context, userID string) ([]store.Device, error) {
	return s.devices.ListDevicesByUser(ctx, userID)
}

// Revoke revokes one of the caller's active devices.
func (s *Service) Revoke(ctx context.Context, deviceID, userID string) error {
	if err := s.devices.RevokeDevice(ctx, deviceID, userID, s.now()); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return ErrNotFound
		}
		return err
	}
	if s.reissuer != nil {
		return s.reissuer.RevokeByDevice(ctx, deviceID)
	}
	return nil
}

// RotateKeyResult is returned by RotateKey.
type RotateKeyResult struct {
	Device            store.Device
	ConfigVersionBump bool
}

// RotateKey replaces the device's x25519 public key, updates live allocation
// peer keys, and re-issues the active config (API.md §4 rotate-key).
func (s *Service) RotateKey(ctx context.Context, userID, deviceID, publicKeyB64 string) (RotateKeyResult, error) {
	key, err := base64.StdEncoding.DecodeString(strings.TrimSpace(publicKeyB64))
	if err != nil || len(key) != x25519KeyLen {
		return RotateKeyResult{}, ErrBadKey
	}
	if s.allocs == nil || s.configs == nil || s.reissuer == nil {
		return RotateKeyResult{}, errors.New("rotation not configured")
	}
	now := s.now()
	if err := s.devices.UpdateDevicePublicKey(ctx, deviceID, userID, key, now); err != nil {
		switch {
		case errors.Is(err, store.ErrNotFound):
			return RotateKeyResult{}, ErrNotFound
		case errors.Is(err, store.ErrConflict):
			return RotateKeyResult{}, ErrKeyInUse
		default:
			return RotateKeyResult{}, err
		}
	}
	if err := s.allocs.UpdateLivePeerPublicKey(ctx, deviceID, key, now); err != nil {
		return RotateKeyResult{}, err
	}
	d, err := s.devices.GetDeviceByID(ctx, deviceID)
	if err != nil {
		return RotateKeyResult{}, err
	}
	bump := false
	alloc, err := s.allocs.GetLiveByDevice(ctx, deviceID)
	if err == nil {
		cfg, cerr := s.configs.GetActiveByAllocation(ctx, alloc.ID)
		if cerr == nil {
			if _, rerr := s.reissuer.ReissueConfig(ctx, cfg); rerr != nil {
				return RotateKeyResult{}, rerr
			}
			bump = true
		} else if !errors.Is(cerr, store.ErrNotFound) {
			return RotateKeyResult{}, cerr
		}
	} else if !errors.Is(err, store.ErrNotFound) {
		return RotateKeyResult{}, err
	}
	return RotateKeyResult{Device: d, ConfigVersionBump: bump}, nil
}
