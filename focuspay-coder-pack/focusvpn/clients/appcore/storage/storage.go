// Package storage defines SecureStorage for tokens and device keys (CLIENT_ARCHITECTURE §6).
package storage

import "errors"

// ErrNotFound is returned when a key is missing.
var ErrNotFound = errors.New("storage: not found")

// SecureStorage persists secrets on-device. Private keys and tokens never leave the device.
type SecureStorage interface {
	Get(key string) ([]byte, error)
	Set(key string, value []byte) error
	Delete(key string) error
}

// Well-known keys.
const (
	KeyAccessToken     = "access_token"
	KeyRefreshToken    = "refresh_token"
	KeyAccessExpiresAt = "access_expires_at" // unix milliseconds, decimal
	KeyDeviceID        = "device_id"
	KeyDeviceToken     = "device_token"
	KeyPrivateKey      = "private_key" // base64 x25519
	KeyPublicKey       = "public_key"  // base64 x25519
	KeyConnectionID    = "connection_id"
	KeyConfPath        = "conf_path"
	KeyAPIBase         = "api_base"
	KeyEmail           = "email"
	KeySelectedNode    = "selected_node"
	KeyCandidates      = "failover_candidates" // JSON []apitypes.CandidateEndpoint
)
