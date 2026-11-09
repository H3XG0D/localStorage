// Package memory is an in-memory store.Store implementation for tests and the
// CLI smoke harness. It is NOT the production store (see DATABASE.md / DECISIONS.md).
package memory

import (
	"bytes"
	"context"
	"errors"
	"sort"
	"strings"
	"sync"
	"time"

	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Store implements store.Store in process memory.
type Store struct {
	mu      sync.RWMutex
	users   map[string]store.User         // id -> user
	byEmail map[string]string             // lower(email) -> id
	byTG    map[int64]string              // telegram_id -> id
	refresh map[string]store.RefreshToken // id -> token
	byHash  map[string]string             // token_hash -> id
	devices map[string]store.Device       // id -> device

	// Seeded read-only reference data (subscriptions/plans) for tests. Keyed by user id.
	subs      map[string]store.Subscription // user_id -> latest subscription (any status)
	plans     map[string]store.Plan         // plan_id -> plan
	endpoints map[string]store.Endpoint     // id -> endpoint
	allocs    map[string]store.Allocation
	configs   map[string]store.Configuration
	billing   map[string]store.BillingEvent // idempotency_key -> event

	// M4: agent stores.
	nodeTokens map[string]store.NodeToken       // token_hash -> token
	nodeCerts  map[string]store.NodeCertificate // id -> cert
	nodeVers   map[string]int64                 // node_id -> version
	appLogins  map[string]store.AppLoginRequest // id -> login request
	subLinks   map[string]store.SubLink        // id -> subscription link
	traffic    map[trafficKey][2]int64          // node/day -> rx, tx
	nodeMeta   map[string]nodeMeta
	pauses     map[string]store.AllocationPause // allocation id -> pause
	kek        *mycrypto.KEK
	sealedUUID map[string][]byte // allocation id -> ciphertext, when KEK is set
}

// UseKEK installs the key that seals VLESS UUIDs. Without it the memory store
// keeps the UUID in plaintext (unit tests). With it, SealedVLESS returns ciphertext.
func (s *Store) UseKEK(kek mycrypto.KEK) {
	cp := kek
	s.kek = &cp
}

// SealedVLESS returns the ciphertext stored for an allocation, or nil.
func (s *Store) SealedVLESS(id string) []byte {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return append([]byte(nil), s.sealedUUID[id]...)
}

// New returns an empty in-memory store.
func New() *Store {
	return &Store{
		users:      make(map[string]store.User),
		byEmail:    make(map[string]string),
		byTG:       make(map[int64]string),
		refresh:    make(map[string]store.RefreshToken),
		byHash:     make(map[string]string),
		devices:    make(map[string]store.Device),
		subs:       make(map[string]store.Subscription),
		plans:      make(map[string]store.Plan),
		endpoints:  make(map[string]store.Endpoint),
		allocs:     make(map[string]store.Allocation),
		configs:    make(map[string]store.Configuration),
		billing:    make(map[string]store.BillingEvent),
		nodeTokens: make(map[string]store.NodeToken),
		nodeCerts:  make(map[string]store.NodeCertificate),
		nodeVers:   make(map[string]int64),
		appLogins:  make(map[string]store.AppLoginRequest),
		subLinks:   make(map[string]store.SubLink),
	}
}

// Users returns the user sub-store.
func (s *Store) Users() store.UserStore { return s }

// Refresh returns the refresh-token sub-store.
func (s *Store) Refresh() store.RefreshStore { return s }

// Devices returns the device sub-store.
func (s *Store) Devices() store.DeviceStore { return s }

// Subscriptions returns the subscription sub-store.
func (s *Store) Subscriptions() store.SubscriptionStore { return s }

// Endpoints returns the endpoint catalog sub-store.
func (s *Store) Endpoints() store.EndpointStore { return s }

// Allocations returns the allocation sub-store.
func (s *Store) Allocations() store.AllocationStore { return s }

// Configurations returns the configuration sub-store.
func (s *Store) Configurations() store.ConfigurationStore { return s }

// NodeTokens returns the node token sub-store.
func (s *Store) NodeTokens() store.NodeTokenStore { return s }

// NodeCerts returns the node certificate sub-store.
func (s *Store) NodeCerts() store.NodeCertStore { return s }

// NodeState returns the node state version sub-store.
func (s *Store) NodeState() store.NodeStateStore { return s }

// Nodes returns the node registration sub-store.
func (s *Store) Nodes() store.NodeCatalog { return s }

// Close is a no-op for the in-memory store.
func (s *Store) Close() error { return nil }

// SeedPlan registers a plan for test setups (test-only helper).
func (s *Store) SeedPlan(p store.Plan) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.plans[p.ID] = p
}

// SeedSubscription registers a user's subscription (test-only helper).
func (s *Store) SeedSubscription(sub store.Subscription) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.subs[sub.UserID] = sub
}

// SeedEndpoint registers an endpoint for tests / NodeSelector.
func (s *Store) SeedEndpoint(e store.Endpoint) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.endpoints[e.ID] = e
}

func emailKey(e string) string { return strings.ToLower(strings.TrimSpace(e)) }

// CreateUser inserts a user, enforcing unique email (and telegram_id when set).
func (s *Store) CreateUser(_ context.Context, u store.User) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.byEmail[emailKey(u.Email)]; ok {
		return store.ErrConflict
	}
	if u.TelegramID != nil {
		if _, ok := s.byTG[*u.TelegramID]; ok {
			return store.ErrConflict
		}
	}
	s.users[u.ID] = u
	s.byEmail[emailKey(u.Email)] = u.ID
	if u.TelegramID != nil {
		s.byTG[*u.TelegramID] = u.ID
	}
	return nil
}

// GetUserByEmail looks up a user by (case-insensitive) email.
func (s *Store) GetUserByEmail(_ context.Context, email string) (store.User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	id, ok := s.byEmail[emailKey(email)]
	if !ok {
		return store.User{}, store.ErrNotFound
	}
	return s.users[id], nil
}

// GetUserByID looks up a user by id.
func (s *Store) GetUserByID(_ context.Context, id string) (store.User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	u, ok := s.users[id]
	if !ok {
		return store.User{}, store.ErrNotFound
	}
	return u, nil
}

// GetUserByTelegramID looks up a user linked to a Telegram account.
func (s *Store) GetUserByTelegramID(_ context.Context, telegramID int64) (store.User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	id, ok := s.byTG[telegramID]
	if !ok {
		return store.User{}, store.ErrNotFound
	}
	return s.users[id], nil
}

// SetLastLogin updates last_login_at.
func (s *Store) SetLastLogin(_ context.Context, id string, t time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	u, ok := s.users[id]
	if !ok {
		return store.ErrNotFound
	}
	u.LastLoginAt = &t
	u.UpdatedAt = t
	s.users[id] = u
	return nil
}

// CreateRefresh inserts a refresh token.
func (s *Store) CreateRefresh(_ context.Context, rt store.RefreshToken) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.byHash[rt.TokenHash]; ok {
		return store.ErrConflict
	}
	s.refresh[rt.ID] = rt
	s.byHash[rt.TokenHash] = rt.ID
	return nil
}

// GetRefreshByHash returns a token by its hash.
func (s *Store) GetRefreshByHash(_ context.Context, hash string) (store.RefreshToken, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	id, ok := s.byHash[hash]
	if !ok {
		return store.RefreshToken{}, store.ErrNotFound
	}
	return s.refresh[id], nil
}

// MarkRotated revokes oldID and points it to newID.
func (s *Store) MarkRotated(_ context.Context, oldID, newID string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	rt, ok := s.refresh[oldID]
	if !ok {
		return store.ErrNotFound
	}
	rt.RevokedAt = &at
	rt.ReplacedBy = &newID
	s.refresh[oldID] = rt
	return nil
}

// RevokeFamily revokes every non-revoked token in a family (reuse detection).
func (s *Store) RevokeFamily(_ context.Context, familyID string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, rt := range s.refresh {
		if rt.FamilyID == familyID && rt.RevokedAt == nil {
			rt.RevokedAt = &at
			s.refresh[id] = rt
		}
	}
	return nil
}

// CreateDevice inserts a device, enforcing the active-device limit and the
// unique active public key / device token hash.
func (s *Store) CreateDevice(_ context.Context, d store.Device, maxDevices int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	active := 0
	for _, ex := range s.devices {
		if ex.DeviceTokenHash == d.DeviceTokenHash {
			return store.ErrConflict
		}
		if ex.UserID == d.UserID && ex.Status == "active" {
			active++
			if bytes.Equal(ex.PublicKey, d.PublicKey) {
				return store.ErrConflict
			}
		}
	}
	if maxDevices > 0 && active >= maxDevices {
		return store.ErrDeviceLimit
	}
	s.devices[d.ID] = d
	return nil
}

// ListDevicesByUser returns a user's devices ordered by creation time.
func (s *Store) ListDevicesByUser(_ context.Context, userID string) ([]store.Device, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.Device
	for _, d := range s.devices {
		if d.UserID == userID {
			out = append(out, d)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt.Equal(out[j].CreatedAt) {
			return out[i].ID < out[j].ID
		}
		return out[i].CreatedAt.Before(out[j].CreatedAt)
	})
	return out, nil
}

// GetDeviceByID returns a device by id.
func (s *Store) GetDeviceByID(_ context.Context, id string) (store.Device, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	d, ok := s.devices[id]
	if !ok {
		return store.Device{}, store.ErrNotFound
	}
	return d, nil
}

// RevokeDevice marks a user's active device revoked (authorization scoped by userID).
func (s *Store) RevokeDevice(_ context.Context, id, userID string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	d, ok := s.devices[id]
	if !ok || d.UserID != userID || d.Status != "active" {
		return store.ErrNotFound
	}
	d.Status = "revoked"
	d.RevokedAt = &at
	d.UpdatedAt = at
	s.devices[id] = d
	return nil
}

// CountActiveDevicesByUser counts a user's active devices.
func (s *Store) CountActiveDevicesByUser(_ context.Context, userID string) (int, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	n := 0
	for _, d := range s.devices {
		if d.UserID == userID && d.Status == "active" {
			n++
		}
	}
	return n, nil
}

// UpdateDevicePublicKey updates an active device's public key (scoped by userID).
func (s *Store) UpdateDevicePublicKey(_ context.Context, id, userID string, publicKey []byte, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	d, ok := s.devices[id]
	if !ok || d.UserID != userID || d.Status != "active" {
		return store.ErrNotFound
	}
	for _, ex := range s.devices {
		if ex.ID == id || ex.Status != "active" {
			continue
		}
		if bytes.Equal(ex.PublicKey, publicKey) {
			return store.ErrConflict
		}
	}
	d.PublicKey = append([]byte(nil), publicKey...)
	d.UpdatedAt = at
	s.devices[id] = d
	return nil
}

// GetActiveByUser returns the user's seeded live subscription and its plan.
func (s *Store) GetActiveByUser(_ context.Context, userID string) (store.Subscription, store.Plan, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sub, ok := s.subs[userID]
	if !ok || (sub.Status != "active" && sub.Status != "trialing") || !sub.EndsAt.After(time.Now()) {
		return store.Subscription{}, store.Plan{}, store.ErrNoSubscription
	}
	plan, ok := s.plans[sub.PlanID]
	if !ok {
		return store.Subscription{}, store.Plan{}, store.ErrNoSubscription
	}
	return sub, plan, nil
}

// GetPlanByCode returns a seeded plan by code.
func (s *Store) GetPlanByCode(_ context.Context, code string) (store.Plan, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, p := range s.plans {
		if p.Code == code {
			return p, nil
		}
	}
	return store.Plan{}, store.ErrNotFound
}

// GetLatestByUser returns any seeded subscription for the user.
func (s *Store) GetLatestByUser(_ context.Context, userID string) (store.Subscription, store.Plan, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sub, ok := s.subs[userID]
	if !ok {
		return store.Subscription{}, store.Plan{}, store.ErrNoSubscription
	}
	plan, ok := s.plans[sub.PlanID]
	if !ok {
		return store.Subscription{}, store.Plan{}, store.ErrNoSubscription
	}
	return sub, plan, nil
}

// GetBillingEvent returns a prior grant by idempotency key.
func (s *Store) GetBillingEvent(_ context.Context, key string) (store.BillingEvent, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	ev, ok := s.billing[key]
	if !ok {
		return store.BillingEvent{}, store.ErrNotFound
	}
	return ev, nil
}

// GrantSubscription applies a grant and its billing event under one lock.
func (s *Store) GrantSubscription(_ context.Context, g store.Grant) (store.GrantResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if ev, ok := s.billing[g.ExternalID]; ok {
		for _, sub := range s.subs {
			if sub.ID == ev.SubscriptionID {
				return store.GrantResult{Event: ev, Subscription: sub, Idempotent: true}, nil
			}
		}
		return store.GrantResult{}, store.ErrNotFound
	}
	if g.Kind == "trial" {
		for _, ev := range s.billing {
			if ev.UserID == g.UserID && ev.Kind == "trial" {
				return store.GrantResult{}, store.ErrTrialUsed
			}
		}
	}
	if g.Kind == store.GrantDevice {
		sub, ok := s.subs[g.UserID]
		if !ok || (sub.Status != "active" && sub.Status != "trialing") || !sub.EndsAt.After(g.At) {
			return store.GrantResult{}, store.ErrNoSubscription
		}
		ends := g.At.Add(time.Duration(g.Days) * 24 * time.Hour)
		ev := store.BillingEvent{
			IdempotencyKey: g.ExternalID, TelegramID: g.TelegramID, Days: g.Days,
			SubscriptionID: sub.ID, UserID: g.UserID, Kind: g.Kind, PlanCode: g.PlanCode,
			AmountKopecks: g.AmountKopecks, EndsAt: &ends, CreatedAt: g.At,
		}
		s.billing[g.ExternalID] = ev
		return store.GrantResult{Event: ev, Subscription: sub}, nil
	}
	period := time.Duration(g.Days) * 24 * time.Hour
	sub, ok := s.subs[g.UserID]
	if ok && (sub.Status == "active" || sub.Status == "trialing") {
		base := sub.EndsAt
		if base.Before(g.At) {
			base = g.At
		}
		sub.EndsAt = base.Add(period)
		if g.Kind != "trial" {
			sub.Status = "active"
			sub.PlanID = g.PlanID
		}
	} else {
		status := "active"
		if g.Kind == "trial" {
			status = "trialing"
		}
		sub = store.Subscription{
			ID: g.SubscriptionID, UserID: g.UserID, PlanID: g.PlanID, Status: status,
			StartsAt: g.At, EndsAt: g.At.Add(period), CreatedAt: g.At,
		}
	}
	prov, ref := store.BillingProvider, g.ExternalID
	sub.Provider, sub.ExternalRef, sub.UpdatedAt = &prov, &ref, g.At
	s.subs[g.UserID] = sub
	ends := sub.EndsAt
	ev := store.BillingEvent{
		IdempotencyKey: g.ExternalID, TelegramID: g.TelegramID, Days: g.Days,
		SubscriptionID: sub.ID, UserID: g.UserID, Kind: g.Kind, PlanCode: g.PlanCode,
		AmountKopecks: g.AmountKopecks, EndsAt: &ends, CreatedAt: g.At,
	}
	s.billing[g.ExternalID] = ev
	return store.GrantResult{Event: ev, Subscription: sub}, nil
}

// ListBillingEvents returns grants created at or after since, oldest first.
func (s *Store) ListBillingEvents(_ context.Context, since time.Time, limit int) ([]store.BillingEvent, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.BillingEvent
	for _, ev := range s.billing {
		if !ev.CreatedAt.Before(since) {
			out = append(out, ev)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt.Equal(out[j].CreatedAt) {
			return out[i].IdempotencyKey < out[j].IdempotencyKey
		}
		return out[i].CreatedAt.Before(out[j].CreatedAt)
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

// ExpireSubscriptions marks live subscriptions past ends_at as expired.
func (s *Store) ExpireSubscriptions(_ context.Context, now time.Time) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	n := 0
	for uid, sub := range s.subs {
		if (sub.Status == "active" || sub.Status == "trialing") && !sub.EndsAt.After(now) {
			sub.Status = "expired"
			sub.UpdatedAt = now
			s.subs[uid] = sub
			n++
		}
	}
	return n, nil
}

// ListEndingBetween returns Telegram users whose subscription ends in [from, to).
func (s *Store) ListEndingBetween(_ context.Context, from, to time.Time, limit int) ([]store.EndingSubscription, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.EndingSubscription
	for uid, sub := range s.subs {
		u, ok := s.users[uid]
		if !ok || u.TelegramID == nil || sub.EndsAt.Before(from) || !sub.EndsAt.Before(to) {
			continue
		}
		if sub.Status != "active" && sub.Status != "trialing" && sub.Status != "expired" {
			continue
		}
		out = append(out, store.EndingSubscription{
			TelegramID: *u.TelegramID, UserID: uid, PlanCode: s.plans[sub.PlanID].Code, Status: sub.Status, EndsAt: sub.EndsAt,
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EndsAt.Before(out[j].EndsAt) })
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

// ListLiveDeviceSlots returns unexpired extra-device grants, soonest end first.
func (s *Store) ListLiveDeviceSlots(_ context.Context, userID string, now time.Time) ([]store.DeviceSlot, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.DeviceSlot
	for _, ev := range s.billing {
		if ev.UserID == userID && ev.Kind == store.GrantDevice && ev.EndsAt != nil && ev.EndsAt.After(now) {
			out = append(out, store.DeviceSlot{PlanCode: ev.PlanCode, EndsAt: *ev.EndsAt})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EndsAt.Before(out[j].EndsAt) })
	return out, nil
}

// ListOverLimitDeviceIDs returns active devices past the live seat limit.
func (s *Store) ListOverLimitDeviceIDs(_ context.Context, now time.Time) ([]string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	byUser := map[string][]store.Device{}
	for _, d := range s.devices {
		if d.Status == "active" {
			byUser[d.UserID] = append(byUser[d.UserID], d)
		}
	}
	var out []string
	for uid, devs := range byUser {
		sub, ok := s.subs[uid]
		if !ok || (sub.Status != "active" && sub.Status != "trialing") || !sub.EndsAt.After(now) {
			continue
		}
		plan, ok := s.plans[sub.PlanID]
		if !ok {
			continue
		}
		extra := 0
		for _, ev := range s.billing {
			if ev.UserID == uid && ev.Kind == store.GrantDevice && ev.EndsAt != nil && ev.EndsAt.After(now) {
				extra++
			}
		}
		sort.Slice(devs, func(i, j int) bool {
			if devs[i].CreatedAt.Equal(devs[j].CreatedAt) {
				return devs[i].ID < devs[j].ID
			}
			return devs[i].CreatedAt.Before(devs[j].CreatedAt)
		})
		lim := plan.MaxDevices + extra
		if len(devs) > lim {
			for _, d := range devs[lim:] {
				out = append(out, d.ID)
			}
		}
	}
	sort.Strings(out)
	return out, nil
}

// GetSubscriptionByID loads a subscription by id.
func (s *Store) GetSubscriptionByID(_ context.Context, id string) (store.Subscription, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, sub := range s.subs {
		if sub.ID == id {
			return sub, nil
		}
	}
	return store.Subscription{}, store.ErrNotFound
}

// GetDeviceByTokenHash looks up an active device by token hash.
func (s *Store) GetDeviceByTokenHash(_ context.Context, hash string) (store.Device, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, d := range s.devices {
		if d.DeviceTokenHash == hash && d.Status == "active" {
			return d, nil
		}
	}
	return store.Device{}, store.ErrNotFound
}

func (s *Store) ListSelectable(_ context.Context, protocol, country string) ([]store.Endpoint, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.Endpoint
	for _, e := range s.endpoints {
		if e.State != "HEALTHY" && e.State != "DEGRADED" {
			continue
		}
		if protocol != "" && e.Protocol != protocol {
			continue
		}
		if country != "" && e.Country != country {
			continue
		}
		if len(e.PublicKey) == 0 && !store.IsVLESS(e.Protocol) {
			continue
		}
		out = append(out, e)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

func (s *Store) GetEndpointByID(_ context.Context, id string) (store.Endpoint, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	e, ok := s.endpoints[id]
	if !ok {
		return store.Endpoint{}, store.ErrNotFound
	}
	return e, nil
}

func (s *Store) CreateAllocation(_ context.Context, a store.Allocation) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, ex := range s.allocs {
		if ex.EndpointID == a.EndpointID && ex.IP == a.IP && (ex.Status == "pending" || ex.Status == "active") {
			return store.ErrConflict
		}
		if a.Status == "active" && ex.DeviceID == a.DeviceID && ex.EndpointID == a.EndpointID && ex.Status == "active" {
			return store.ErrConflict
		}
	}
	if a.VLESSUUID != "" && s.kek != nil {
		blob, _, err := mycrypto.Envelope(*s.kek, []byte(a.VLESSUUID))
		if err != nil {
			return err
		}
		if s.sealedUUID == nil {
			s.sealedUUID = map[string][]byte{}
		}
		s.sealedUUID[a.ID] = blob
		if bytes.Contains(blob, []byte(a.VLESSUUID)) {
			return errors.New("memory: VLESS UUID leaked into ciphertext")
		}
	}
	s.allocs[a.ID] = a
	return nil
}

func (s *Store) GetAllocationByID(_ context.Context, id string) (store.Allocation, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	a, ok := s.allocs[id]
	if !ok {
		return store.Allocation{}, store.ErrNotFound
	}
	return a, nil
}

func (s *Store) GetLiveByDevice(_ context.Context, deviceID string) (store.Allocation, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var found *store.Allocation
	for _, a := range s.allocs {
		if a.DeviceID == deviceID && (a.Status == "pending" || a.Status == "active") {
			cp := a
			if found == nil || a.CreatedAt.After(found.CreatedAt) {
				found = &cp
			}
		}
	}
	if found == nil {
		return store.Allocation{}, store.ErrNotFound
	}
	return *found, nil
}

func (s *Store) CountLiveByDevice(_ context.Context, deviceID string) (int, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	n := 0
	for _, a := range s.allocs {
		if a.DeviceID == deviceID && (a.Status == "pending" || a.Status == "active") {
			n++
		}
	}
	return n, nil
}

func (s *Store) ListLiveIPs(_ context.Context, endpointID string) ([]string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var ips []string
	for _, a := range s.allocs {
		if a.EndpointID == endpointID && (a.Status == "pending" || a.Status == "active") {
			ips = append(ips, a.IP)
		}
	}
	return ips, nil
}

func (s *Store) ListLiveByEndpoint(_ context.Context, endpointID string) ([]store.Allocation, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.Allocation
	for _, a := range s.allocs {
		if a.EndpointID == endpointID && (a.Status == "pending" || a.Status == "active") {
			out = append(out, a)
		}
	}
	return out, nil
}

// UpdateLivePeerPublicKey updates peer keys on live allocations for a device.
func (s *Store) UpdateLivePeerPublicKey(_ context.Context, deviceID string, publicKey []byte, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, a := range s.allocs {
		if a.DeviceID == deviceID && (a.Status == "pending" || a.Status == "active") {
			a.PeerPublicKey = append([]byte(nil), publicKey...)
			a.UpdatedAt = at
			s.allocs[id] = a
		}
	}
	return nil
}

func (s *Store) SetAllocationStatus(_ context.Context, id, status string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.allocs[id]
	if !ok {
		return store.ErrNotFound
	}
	a.Status = status
	a.UpdatedAt = at
	if status == "revoked" {
		a.RevokedAt = &at
	}
	s.allocs[id] = a
	return nil
}

func (s *Store) CreateConfiguration(_ context.Context, c store.Configuration) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, ex := range s.configs {
		if ex.AllocationID == c.AllocationID && ex.Version == c.Version {
			return store.ErrConflict
		}
		if c.Status == "active" && ex.AllocationID == c.AllocationID && ex.Status == "active" {
			return store.ErrConflict
		}
	}
	s.configs[c.ID] = c
	return nil
}

func (s *Store) GetConfigurationByID(_ context.Context, id string) (store.Configuration, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	c, ok := s.configs[id]
	if !ok {
		return store.Configuration{}, store.ErrNotFound
	}
	return c, nil
}

func (s *Store) GetActiveByAllocation(_ context.Context, allocationID string) (store.Configuration, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, c := range s.configs {
		if c.AllocationID == allocationID && c.Status == "active" {
			return c, nil
		}
	}
	return store.Configuration{}, store.ErrNotFound
}

func (s *Store) RevokeByAllocation(_ context.Context, allocationID string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, c := range s.configs {
		if c.AllocationID == allocationID && c.Status == "active" {
			c.Status = "revoked"
			c.UpdatedAt = at
			s.configs[id] = c
		}
	}
	return nil
}

// ReplaceActiveConfiguration revokes the active config and inserts c under one lock.
func (s *Store) ReplaceActiveConfiguration(_ context.Context, c store.Configuration, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, ex := range s.configs {
		if ex.AllocationID == c.AllocationID && ex.Version == c.Version {
			return store.ErrConflict
		}
	}
	for id, ex := range s.configs {
		if ex.AllocationID == c.AllocationID && ex.Status == "active" {
			ex.Status = "revoked"
			ex.UpdatedAt = at
			s.configs[id] = ex
		}
	}
	s.configs[c.ID] = c
	return nil
}

func (s *Store) ListActiveOlderThan(_ context.Context, t time.Time) ([]store.Configuration, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []store.Configuration
	for _, c := range s.configs {
		if c.Status != "active" {
			continue
		}
		age := c.CreatedAt
		if c.RotatedAt != nil {
			age = *c.RotatedAt
		}
		if age.Before(t) {
			out = append(out, c)
		}
	}
	return out, nil
}

// --- M4: NodeTokenStore ---

func (s *Store) CreateNodeToken(_ context.Context, t store.NodeToken) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.nodeTokens[t.TokenHash]; ok {
		return store.ErrConflict
	}
	s.nodeTokens[t.TokenHash] = t
	return nil
}

func (s *Store) ConsumeNodeToken(_ context.Context, hash string, at time.Time) (store.NodeToken, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.nodeTokens[hash]
	if !ok || t.UsedAt != nil || at.After(t.ExpiresAt) {
		return store.NodeToken{}, store.ErrNotFound
	}
	t.UsedAt = &at
	s.nodeTokens[hash] = t
	return t, nil
}

// --- M4: NodeCertStore ---

func (s *Store) CreateNodeCert(_ context.Context, c store.NodeCertificate) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.nodeCerts[c.ID] = c
	return nil
}

func (s *Store) GetLatestNodeCert(_ context.Context, nodeID string) (store.NodeCertificate, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var found *store.NodeCertificate
	for _, c := range s.nodeCerts {
		if c.NodeID == nodeID && c.RevokedAt == nil {
			cp := c
			if found == nil || c.IssuedAt.After(found.IssuedAt) {
				found = &cp
			}
		}
	}
	if found == nil {
		return store.NodeCertificate{}, store.ErrNotFound
	}
	return *found, nil
}

// --- M4: NodeStateStore ---

func (s *Store) GetStateVersion(_ context.Context, nodeID string) (int64, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.nodeVers[nodeID]
	if !ok {
		return 0, store.ErrNotFound
	}
	return v, nil
}

func (s *Store) IncrementStateVersion(_ context.Context, nodeID string) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.nodeVers[nodeID]++
	return s.nodeVers[nodeID], nil
}

func (s *Store) EnsureStateVersion(_ context.Context, nodeID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.nodeVers[nodeID]; !ok {
		s.nodeVers[nodeID] = 0
	}
	return nil
}
