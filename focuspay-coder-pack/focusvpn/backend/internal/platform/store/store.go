// Package store defines persistence contracts for the Control Plane. The
// production source of truth is PostgreSQL (DATABASE.md); the in-memory
// implementation under store/memory is for unit/integration tests and the CLI
// smoke harness only (DECISIONS.md). Both implement the same interfaces so the
// business modules do not depend on the concrete backend.
package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

// Common storage errors.
var (
	ErrNotFound            = errors.New("store: not found")
	ErrConflict            = errors.New("store: conflict")
	ErrDeviceLimit         = errors.New("store: device limit reached")
	ErrNoSubscription      = errors.New("store: no active subscription")
	ErrAllocationLimit     = errors.New("store: allocation limit reached")
	ErrNoCapacity          = errors.New("store: no capacity")
	ErrSubscriptionExpired = errors.New("store: subscription expired")
	ErrTrialUsed           = errors.New("store: trial already used")
)

// User mirrors the users table (DATABASE.md §2.1).
type User struct {
	ID           string
	Email        string
	PasswordHash string
	Role         string
	Status       string
	TelegramID   *int64 // FocusPay / VPN bot link (ADR-007); nil if email-only
	LastLoginAt  *time.Time
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

// RefreshToken mirrors the refresh_tokens table (DATABASE.md §3.1).
type RefreshToken struct {
	ID         string
	UserID     string
	FamilyID   string
	TokenHash  string
	DeviceID   *string
	ExpiresAt  time.Time
	RevokedAt  *time.Time
	ReplacedBy *string
	CreatedAt  time.Time
}

// UserStore persists users.
type UserStore interface {
	CreateUser(ctx context.Context, u User) error
	GetUserByEmail(ctx context.Context, email string) (User, error)
	GetUserByID(ctx context.Context, id string) (User, error)
	GetUserByTelegramID(ctx context.Context, telegramID int64) (User, error)
	SetLastLogin(ctx context.Context, id string, t time.Time) error
}

// RefreshStore persists refresh tokens and supports rotation + family revocation
// for reuse detection (ADR-006).
type RefreshStore interface {
	CreateRefresh(ctx context.Context, rt RefreshToken) error
	GetRefreshByHash(ctx context.Context, hash string) (RefreshToken, error)
	MarkRotated(ctx context.Context, oldID, newID string, at time.Time) error
	RevokeFamily(ctx context.Context, familyID string, at time.Time) error
}

// Device mirrors the devices table (DATABASE.md §2.2). PublicKey holds the raw
// x25519 key bytes; DeviceTokenHash is a keyed hash and is never returned by the API.
type Device struct {
	ID              string
	UserID          string
	Name            string
	Platform        string
	AppVersion      *string
	PublicKey       []byte
	DeviceTokenHash string
	Status          string
	LastSeenAt      *time.Time
	CreatedAt       time.Time
	UpdatedAt       time.Time
	RevokedAt       *time.Time
}

// Plan mirrors the plans table (DATABASE.md §2.3).
type Plan struct {
	ID           string
	Code         string
	Name         string
	MaxDevices   int
	MaxSpeedMbps *int
	MaxTrafficGB *int64
	PeriodDays   int
	PriceCents   int
	Features     json.RawMessage
}

// Subscription mirrors the subscriptions table (DATABASE.md §2.4).
type Subscription struct {
	ID          string
	UserID      string
	PlanID      string
	Status      string
	StartsAt    time.Time
	EndsAt      time.Time
	AutoRenew   bool
	Provider    *string
	ExternalRef *string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// DeviceStore persists user devices. It never stores client private keys.
type DeviceStore interface {
	// CreateDevice inserts a device, atomically enforcing the per-user active
	// device limit (maxDevices <= 0 means unlimited). Returns ErrDeviceLimit if
	// the active count would exceed the limit, or ErrConflict on a duplicate
	// active public key / device token hash.
	CreateDevice(ctx context.Context, d Device, maxDevices int) error
	ListDevicesByUser(ctx context.Context, userID string) ([]Device, error)
	GetDeviceByID(ctx context.Context, id string) (Device, error)
	// RevokeDevice marks a user's active device revoked. Scoped by userID for
	// authorization. Returns ErrNotFound if no matching active device exists.
	RevokeDevice(ctx context.Context, id, userID string, at time.Time) error
	CountActiveDevicesByUser(ctx context.Context, userID string) (int, error)
	// GetDeviceByTokenHash looks up an active device by its keyed token hash.
	GetDeviceByTokenHash(ctx context.Context, hash string) (Device, error)
	// UpdateDevicePublicKey sets a new x25519 public key on an active device owned
	// by userID. Returns ErrNotFound if missing/revoked/wrong owner, ErrConflict if
	// another active device already holds the key.
	UpdateDevicePublicKey(ctx context.Context, id, userID string, publicKey []byte, at time.Time) error
	// ListOverLimitDeviceIDs returns active devices past the live seat limit
	// (plan max_devices plus unexpired device grants). Oldest devices stay.
	// Users without a live subscription are skipped.
	ListOverLimitDeviceIDs(ctx context.Context, now time.Time) ([]string, error)
}

// BillingEvent records an idempotent subscription grant (ADR-007, ADR-010).
// IdempotencyKey is the FocusPay purchase id.
type BillingEvent struct {
	IdempotencyKey string
	TelegramID     int64
	Days           int
	SubscriptionID string
	UserID         string
	Kind           string // paid | trial | device
	PlanCode       string
	AmountKopecks  int64
	EndsAt         *time.Time
	CreatedAt      time.Time
}

// GrantDevice is an extra-device purchase. It does not extend the subscription.
const GrantDevice = "device"

// DeviceSlot is one unexpired extra-device purchase.
type DeviceSlot struct {
	PlanCode string
	EndsAt   time.Time
}

// BillingProvider tags subscriptions created by FocusPay grants.
const BillingProvider = "focuspay_wallet"

// Grant adds days to a user's subscription on behalf of a FocusPay purchase.
// SubscriptionID is used only when the user has no live subscription.
type Grant struct {
	ExternalID     string
	SubscriptionID string
	TelegramID     int64
	UserID         string
	PlanID         string
	PlanCode       string
	Kind           string // paid | trial | device
	Days           int
	AmountKopecks  int64
	At             time.Time
}

// GrantResult is the subscription state after a grant.
type GrantResult struct {
	Event        BillingEvent
	Subscription Subscription
	Idempotent   bool
}

// SubscriptionStore reads subscription/plan state for a user.
type SubscriptionStore interface {
	// GetActiveByUser returns the user's live (trialing|active, ends_at > now)
	// subscription and its plan, or ErrNoSubscription if none.
	GetActiveByUser(ctx context.Context, userID string) (Subscription, Plan, error)
	// GetPlanByCode returns a plan by its code (e.g. "free"), or ErrNotFound.
	GetPlanByCode(ctx context.Context, code string) (Plan, error)
	// GetLatestByUser returns the most recent subscription of any status (for
	// distinguishing "no row" vs "expired"). ErrNoSubscription if none.
	GetLatestByUser(ctx context.Context, userID string) (Subscription, Plan, error)
	// GrantSubscription applies a grant and records its billing event atomically.
	// A repeated ExternalID returns the original result with Idempotent=true.
	// A second trial for the same user fails with ErrTrialUsed.
	GrantSubscription(ctx context.Context, g Grant) (GrantResult, error)
	// GetBillingEvent returns a prior grant by idempotency key, or ErrNotFound.
	GetBillingEvent(ctx context.Context, key string) (BillingEvent, error)
	// ListBillingEvents returns grants created at or after since, oldest first.
	ListBillingEvents(ctx context.Context, since time.Time, limit int) ([]BillingEvent, error)
	// ExpireSubscriptions marks live subscriptions with ends_at <= now as expired.
	ExpireSubscriptions(ctx context.Context, now time.Time) (int, error)
	// GetSubscriptionByID loads a subscription by id.
	GetSubscriptionByID(ctx context.Context, id string) (Subscription, error)
	// ListEndingBetween returns Telegram users whose latest subscription ends in
	// [from, to), any status (reminders before and after expiry).
	ListEndingBetween(ctx context.Context, from, to time.Time, limit int) ([]EndingSubscription, error)
	// ListLiveDeviceSlots returns unexpired extra-device grants (kind=device),
	// soonest end first. They do not require a live subscription.
	ListLiveDeviceSlots(ctx context.Context, userID string, now time.Time) ([]DeviceSlot, error)
}

// EndingSubscription is one reminder candidate.
type EndingSubscription struct {
	TelegramID int64
	UserID     string
	PlanCode   string
	Status     string
	EndsAt     time.Time
}

// Endpoint is a join of vpn_endpoints + vpn_nodes fields needed for selection and ConfigParts.
type Endpoint struct {
	ID          string
	NodeID      string
	NodeName    string
	Country     string
	Region      string
	Hostname    string
	Protocol    string
	Port        int
	State       string
	PublicKey   []byte
	Obfuscation json.RawMessage
	Subnet      string // CIDR, e.g. 10.200.0.0/24
	Load        float64
	PeerCount   int
	Capacity    int             // node capacity in concurrent users; 0 = unknown
	Xray        json.RawMessage // VLESS transport settings (migration 000007); nil for WG
	// LastHeartbeatAt is the node's last agent telemetry; nil if no agent ever reported.
	LastHeartbeatAt *time.Time
}

// ProtocolVLESS is the canonical endpoint protocol for Xray/VLESS nodes.
// "vless-ws" and "xray" are legacy aliases still accepted on input.
const ProtocolVLESS = "vless"

// VLESSProtocols are endpoint protocols served by Xray on the node.
var VLESSProtocols = []string{ProtocolVLESS, "vless-ws", "xray"}

// CanonicalProtocol maps legacy VLESS aliases to ProtocolVLESS.
func CanonicalProtocol(protocol string) string {
	if IsVLESS(protocol) {
		return ProtocolVLESS
	}
	return protocol
}

// IsVLESS reports whether an endpoint protocol is served by Xray.
func IsVLESS(protocol string) bool {
	for _, p := range VLESSProtocols {
		if p == protocol {
			return true
		}
	}
	return false
}

// Allocation mirrors vpn_allocations (DATABASE.md §2.7).
type Allocation struct {
	ID            string
	UserID        string
	DeviceID      string
	EndpointID    string
	IP            string // dotted or CIDR host form without mask
	PeerPublicKey []byte
	VLESSUUID     string // empty for WireGuard-family allocations
	Status        string
	CreatedAt     time.Time
	UpdatedAt     time.Time
	RevokedAt     *time.Time
}

// Configuration mirrors vpn_configurations (DATABASE.md §2.8).
type Configuration struct {
	ID               string
	AllocationID     string
	DeviceID         string
	Version          int
	ContentEncrypted []byte
	ContentHash      []byte
	Signature        []byte
	Status           string
	RotatedAt        *time.Time
	CreatedAt        time.Time
	UpdatedAt        time.Time
}

// EndpointStore reads catalog endpoints for NodeSelector / servers API.
type EndpointStore interface {
	// ListSelectable returns HEALTHY (and optionally DEGRADED) endpoints, optionally filtered.
	ListSelectable(ctx context.Context, protocol, country string) ([]Endpoint, error)
	GetEndpointByID(ctx context.Context, id string) (Endpoint, error)
	// ListEndpoints returns every endpoint regardless of state.
	ListEndpoints(ctx context.Context) ([]Endpoint, error)
	// RecordNodeHeartbeat stores agent telemetry: last_heartbeat_at on the node,
	// peer_count/load (online/capacity) on its endpoints, and OFFLINE -> HEALTHY
	// when the node was not taken down by a probe.
	RecordNodeHeartbeat(ctx context.Context, nodeID string, online int, at time.Time) error
	// RecordNodePulse is RecordNodeHeartbeat plus an optional local probe.
	// A nil health keeps the legacy pulse behaviour.
	RecordNodePulse(ctx context.Context, nodeID string, online int, at time.Time, health *NodeHealth) error
	// ApplyEdgeProbe records a control-plane dial of the node's public TLS port.
	ApplyEdgeProbe(ctx context.Context, nodeID string, ok bool, reason string) error
	// ListEdgeHosts returns nodes whose agent has reported since `since` and that
	// are not draining. The caller dials Hostname:443.
	ListEdgeHosts(ctx context.Context, since time.Time) ([]EdgeHost, error)
	// MarkStaleOffline sets HEALTHY/DEGRADED endpoints OFFLINE when their node has
	// reported before but not since `before`. Returns the affected node IDs.
	MarkStaleOffline(ctx context.Context, before time.Time) ([]string, error)
}

// NodeHealth is one local probe from the node agent.
type NodeHealth struct {
	OK       bool
	Degraded bool
	Reason   string
}

// EdgeHost is a node the control plane should dial.
type EdgeHost struct {
	NodeID   string
	Hostname string
}

// NodeReport is one node row of the operator report.
type NodeReport struct {
	NodeID          string
	Name            string
	Country         string
	State           string // worst endpoint state on the node
	Online          int
	Capacity        int
	Load            float64
	LastHeartbeatAt *time.Time
	StatusReason    string
	RxToday         int64
	TxToday         int64
	Rx30d           int64
	Tx30d           int64
}

// AllocationPause keeps one UUID out of the Xray user set until Until.
type AllocationPause struct {
	AllocationID string
	IPCount      int
	Reason       string
	Until        time.Time
	NodeID       string
	NodeName     string
	UpdatedAt    time.Time
}

// ReportSummary is the operator report (FocusPay admin /x8/vpn).
type ReportSummary struct {
	ActiveSubscriptions int
	ActiveDevices       int
	LiveConnections     int
	Purchases1d         int
	Purchases7d         int
	Purchases30d        int
	PurchasedDays30d    int
	Trials30d           int
	Nodes               []NodeReport
	Pauses              []AllocationPause
}

// ReportStore holds traffic counters and builds the operator report.
type ReportStore interface {
	// AddNodeTraffic adds byte counters to the node's daily (UTC) traffic row.
	AddNodeTraffic(ctx context.Context, nodeID string, day time.Time, rx, tx int64) error
	Summary(ctx context.Context, now time.Time) (ReportSummary, error)
}

// AllocationStore persists VPN IP allocations.
type AllocationStore interface {
	CreateAllocation(ctx context.Context, a Allocation) error
	GetAllocationByID(ctx context.Context, id string) (Allocation, error)
	// GetLiveByDevice returns pending or active allocation for the device, if any.
	GetLiveByDevice(ctx context.Context, deviceID string) (Allocation, error)
	CountLiveByDevice(ctx context.Context, deviceID string) (int, error)
	ListLiveIPs(ctx context.Context, endpointID string) ([]string, error)
	// ListLiveByEndpoint returns pending and active allocations for an endpoint
	// (used by the node-agent desired-state builder).
	ListLiveByEndpoint(ctx context.Context, endpointID string) ([]Allocation, error)
	// ListLiveEntitledVLESS returns live allocations on VLESS endpoints whose user
	// has a live subscription ending after now (desired user set for Xray nodes).
	// Allocations paused for sharing are left out.
	ListLiveEntitledVLESS(ctx context.Context, now time.Time) ([]Allocation, error)
	// UpsertAllocationPause records or extends a sharing pause. fresh is true when
	// the allocation was not already paused, so the caller should wake the nodes.
	UpsertAllocationPause(ctx context.Context, p AllocationPause) (fresh bool, err error)
	SetAllocationStatus(ctx context.Context, id, status string, at time.Time) error
	// UpdateLivePeerPublicKey sets peer_public_key on all pending/active allocations
	// for the device (no-op / nil error if none).
	UpdateLivePeerPublicKey(ctx context.Context, deviceID string, publicKey []byte, at time.Time) error
}

// ConfigurationStore persists encrypted+signed config versions.
type ConfigurationStore interface {
	CreateConfiguration(ctx context.Context, c Configuration) error
	GetConfigurationByID(ctx context.Context, id string) (Configuration, error)
	GetActiveByAllocation(ctx context.Context, allocationID string) (Configuration, error)
	RevokeByAllocation(ctx context.Context, allocationID string, at time.Time) error
	// ReplaceActiveConfiguration revokes the allocation's active config and inserts
	// c as the new active one atomically; on error the old config stays active.
	ReplaceActiveConfiguration(ctx context.Context, c Configuration, at time.Time) error
	// ListActiveOlderThan returns active configs whose coalesce(rotated_at, created_at) is before t.
	ListActiveOlderThan(ctx context.Context, t time.Time) ([]Configuration, error)
}

// NodeToken is a one-time registration token for a node agent (migration 000003).
type NodeToken struct {
	ID        string
	NodeID    string
	TokenHash string // SHA-256 hex of the raw token
	UsedAt    *time.Time
	ExpiresAt time.Time
	CreatedAt time.Time
}

// NodeCertificate records an issued mTLS certificate (for revocation tracking).
type NodeCertificate struct {
	ID        string
	NodeID    string
	Serial    int64
	CertPEM   string
	IssuedAt  time.Time
	ExpiresAt time.Time
	RevokedAt *time.Time
}

// NodeTokenStore manages one-time agent registration tokens.
type NodeTokenStore interface {
	// CreateNodeToken inserts a new registration token.
	CreateNodeToken(ctx context.Context, t NodeToken) error
	// ConsumeNodeToken marks the token used and returns it. Returns ErrNotFound
	// if no matching unused, unexpired token exists.
	ConsumeNodeToken(ctx context.Context, hash string, at time.Time) (NodeToken, error)
}

// NodeCertStore persists issued mTLS node certificates.
type NodeCertStore interface {
	CreateNodeCert(ctx context.Context, c NodeCertificate) error
	// GetLatestNodeCert returns the most recently issued (non-revoked) cert for
	// a node, or ErrNotFound.
	GetLatestNodeCert(ctx context.Context, nodeID string) (NodeCertificate, error)
}

// AppLoginRequest tracks Telegram deep-link / short-code app login (E2).
type AppLoginRequest struct {
	ID             string
	StartTokenHash string
	PairCodeHash   string
	WaitTokenHash  string
	TelegramID     *int64
	UserID         *string
	CreatedAt      time.Time
	ExpiresAt      time.Time
	AttachedAt     *time.Time
	ConsumedAt     *time.Time
}

// SubLink is a stable HTTPS key for Happ and similar clients. The raw token
// lives only inside TokenEnc (KEK envelope) so the bot can show the same URL
// again. TokenHash is the lookup key. One live row per user.
type SubLink struct {
	ID        string
	UserID    string
	DeviceID  string
	TokenHash string
	TokenEnc  []byte
	CreatedAt time.Time
	RevokedAt *time.Time
}

// SubLinkStore persists subscription links.
type SubLinkStore interface {
	CreateSubLink(ctx context.Context, l SubLink) error
	GetLiveSubLinkByUser(ctx context.Context, userID string) (SubLink, error)
	GetLiveSubLinkByTokenHash(ctx context.Context, hash string) (SubLink, error)
	RevokeSubLink(ctx context.Context, id string, at time.Time) error
}

// AppLoginStore persists one-time Telegram app login handshakes.
type AppLoginStore interface {
	CreateAppLogin(ctx context.Context, req AppLoginRequest) error
	GetAppLoginByWaitHash(ctx context.Context, hash string) (AppLoginRequest, error)
	GetAppLoginByStartHash(ctx context.Context, hash string) (AppLoginRequest, error)
	GetAppLoginByPairCodeHash(ctx context.Context, hash string) (AppLoginRequest, error)
	AttachAppLogin(ctx context.Context, startHash string, telegramID int64, userID string, at time.Time) error
	ConsumeAppLogin(ctx context.Context, id string, at time.Time) error
	CreatePairCodeLogin(ctx context.Context, req AppLoginRequest) error
}

// NodeStateStore manages the desired-state version counter per node.
type NodeStateStore interface {
	// GetStateVersion returns the current version for a node.
	GetStateVersion(ctx context.Context, nodeID string) (int64, error)
	// IncrementStateVersion atomically bumps the version and returns the new value.
	IncrementStateVersion(ctx context.Context, nodeID string) (int64, error)
	// EnsureStateVersion upserts a version row (used by migrations / seed).
	EnsureStateVersion(ctx context.Context, nodeID string) error
}

// Store aggregates the sub-stores and lifecycle.
type Store interface {
	Users() UserStore
	Refresh() RefreshStore
	Devices() DeviceStore
	Subscriptions() SubscriptionStore
	Endpoints() EndpointStore
	Allocations() AllocationStore
	Configurations() ConfigurationStore
	NodeTokens() NodeTokenStore
	NodeCerts() NodeCertStore
	NodeState() NodeStateStore
	AppLogins() AppLoginStore
	SubLinks() SubLinkStore
	Reports() ReportStore
	Nodes() NodeCatalog
	Close() error
}

// VLESSNode is the operator input for registering one Xray node.
type VLESSNode struct {
	Name     string
	Country  string
	Region   string
	Hostname string
	Capacity int
	Subnet   string          // empty = pick the next free 10.210.x.0/24
	Xray     json.RawMessage // transport settings stored on the endpoint
}

// NodeCatalog registers VLESS nodes. Idempotent on node name.
type NodeCatalog interface {
	// UpsertVLESSNode inserts or updates a node and its vless endpoint.
	// Existing node/endpoint state (HEALTHY/OFFLINE) is not reset.
	// Returns the node id and endpoint id.
	UpsertVLESSNode(ctx context.Context, n VLESSNode) (nodeID, endpointID string, err error)
}

// AssignSubnet returns requested when it is set, otherwise the first free
// 10.210.N.0/24 that is not in used (CIDR strings).
func AssignSubnet(used []string, requested string) string {
	if requested != "" {
		return requested
	}
	taken := map[int]bool{}
	for _, c := range used {
		var o int
		if _, err := fmt.Sscanf(c, "10.210.%d.", &o); err == nil {
			taken[o] = true
		}
	}
	for i := 1; i < 250; i++ {
		if !taken[i] {
			return fmt.Sprintf("10.210.%d.0/24", i)
		}
	}
	return "10.211.0.0/24"
}
