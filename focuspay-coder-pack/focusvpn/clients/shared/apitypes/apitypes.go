// Package apitypes holds the wire contracts shared between the Control Plane
// HTTP API and the FocusVPN clients (Phase 2: CLI harness). Keeping the DTOs in
// one place prevents drift between server and clients (see CLIENT_ARCHITECTURE.md
// §7 and DECISIONS.md "Дрейф клиентских кодовых баз").
package apitypes

// ErrorEnvelope is the single error shape returned by the API (API.md §1).
type ErrorEnvelope struct {
	Error ErrorBody `json:"error"`
}

// ErrorBody carries a machine-readable code and human message.
type ErrorBody struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	RequestID string `json:"request_id,omitempty"`
}

// HealthResponse is returned by GET /v1/health.
type HealthResponse struct {
	Status string `json:"status"`
}

// UserDTO is the public representation of a user.
type UserDTO struct {
	ID    string `json:"id"`
	Email string `json:"email"`
	Role  string `json:"role"`
}

// Tokens is the credential bundle returned on register/login.
type Tokens struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
}

// RegisterRequest is the body of POST /v1/auth/register.
type RegisterRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

// AuthResponse is returned by register and login.
type AuthResponse struct {
	User   UserDTO `json:"user"`
	Tokens Tokens  `json:"tokens"`
}

// LoginRequest is the body of POST /v1/auth/login.
type LoginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

// RefreshResponse is returned by POST /v1/auth/refresh.
type RefreshResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
}

// LogoutRequest is the body of POST /v1/auth/logout.
type LogoutRequest struct {
	RefreshToken string `json:"refresh_token"`
}

// SubscriptionDTO is the user-safe view of a subscription (API.md §3). It never
// exposes billing provider references or internal identifiers.
type SubscriptionDTO struct {
	Status      string `json:"status"`
	Plan        string `json:"plan"` // plan code, e.g. "pro"
	EndsAt      string `json:"ends_at"`
	MaxDevices  int    `json:"max_devices"`
	DevicesUsed int    `json:"devices_used"`
}

// MeResponse is returned by GET /v1/me. Subscription is null when the user has
// no active subscription.
type MeResponse struct {
	User         UserDTO          `json:"user"`
	Subscription *SubscriptionDTO `json:"subscription"`
}

// DeviceDTO is the public representation of a device (API.md §4). Public keys and
// device-token hashes are never included.
type DeviceDTO struct {
	ID         string  `json:"id"`
	Name       string  `json:"name"`
	Platform   string  `json:"platform"`
	AppVersion string  `json:"app_version,omitempty"`
	Status     string  `json:"status"`
	LastSeenAt *string `json:"last_seen_at,omitempty"`
	CreatedAt  string  `json:"created_at"`
}

// DeviceListResponse is returned by GET /v1/devices.
type DeviceListResponse struct {
	Devices []DeviceDTO `json:"devices"`
}

// CreateDeviceRequest is the body of POST /v1/devices. PublicKey is a base64
// (std) encoded 32-byte x25519 key.
type CreateDeviceRequest struct {
	Name       string `json:"name"`
	Platform   string `json:"platform"`
	AppVersion string `json:"app_version,omitempty"`
	PublicKey  string `json:"public_key"`
}

// CreateDeviceResponse is returned by POST /v1/devices. DeviceToken is returned
// exactly once; only its hash is persisted.
type CreateDeviceResponse struct {
	Device      DeviceDTO `json:"device"`
	DeviceToken string    `json:"device_token"`
}

// RotateKeyRequest is the body of POST /v1/devices/:id/rotate-key.
type RotateKeyRequest struct {
	PublicKey string `json:"public_key"`
}

// RotateKeyResponse is returned by POST /v1/devices/:id/rotate-key.
type RotateKeyResponse struct {
	Device            DeviceDTO `json:"device"`
	ConfigVersionBump bool      `json:"config_version_bump"`
}

// EndpointDTO is a selectable VPN endpoint (API.md §5).
type EndpointDTO struct {
	ID       string  `json:"id"`
	Node     string  `json:"node"`
	Country  string  `json:"country"`
	Region   string  `json:"region"`
	Protocol string  `json:"protocol"`
	Score    float64 `json:"score"`
	Host     string  `json:"host,omitempty"`
	Port     int     `json:"port,omitempty"`
}

// ServersResponse is returned by GET /v1/servers.
type ServersResponse struct {
	Endpoints []EndpointDTO `json:"endpoints"`
}

// CreateConnectionRequest is the body of POST /v1/connections.
type CreateConnectionRequest struct {
	DeviceID      string `json:"device_id"`
	Protocol      string `json:"protocol"`
	Country       string `json:"country,omitempty"`
	Region        string `json:"region,omitempty"`
	PreferredNode string `json:"preferred_node,omitempty"` // e.g. DE-01
	SelectedNode  string `json:"selected_node,omitempty"`  // UI alias for preferred_node
}

// ConnectionDTO is the public connection/allocation view.
type ConnectionDTO struct {
	ID     string `json:"id"`
	Status string `json:"status"` // API: provisioning|active|revoked|failed
}

// CandidateEndpoint is a failover candidate.
type CandidateEndpoint struct {
	Endpoint struct {
		ID       string `json:"id"`
		Host     string `json:"host"`
		Port     int    `json:"port"`
		Protocol string `json:"protocol"`
	} `json:"endpoint"`
	Node  string  `json:"node,omitempty"` // e.g. DE-01 — for preferred_node retry
	Score float64 `json:"score"`
}

// CreateConnectionResponse is returned by POST /v1/connections.
type CreateConnectionResponse struct {
	Connection    ConnectionDTO       `json:"connection"`
	Candidates    []CandidateEndpoint `json:"candidates"`
	ConfigID      string              `json:"config_id"`
	ConfigVersion int                 `json:"config_version"`
}

// ConfigPartsResponse is returned by GET /v1/configurations/:id.
type ConfigPartsResponse struct {
	ConfigVersion int            `json:"config_version"`
	Signature     string         `json:"signature"`
	Parts         map[string]any `json:"parts"`
}
