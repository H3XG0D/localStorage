// Package billing implements internal Telegram upsert + FocusPay grants (ADR-007, ADR-010).
package billing

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

const (
	PlanWeek   = "week"
	KindPaid   = "paid"
	KindTrial  = "trial"
	KindDevice = store.GrantDevice
)

// Service wires store for internal billing APIs.
type Service struct {
	users store.UserStore
	subs  store.SubscriptionStore
	now   func() time.Time

	devices     DeviceManager
	live        LiveCounter
	devNotFound error
}

// New constructs a billing Service.
func New(users store.UserStore, subs store.SubscriptionStore) *Service {
	return &Service{users: users, subs: subs, now: time.Now}
}

// UpsertResult is returned by UpsertTelegramUser.
type UpsertResult struct {
	UserID     string `json:"user_id"`
	TelegramID int64  `json:"telegram_id"`
	Created    bool   `json:"created"`
	Email      string `json:"email"`
}

// UpsertTelegramUser finds or creates a FocusVPN user for a Telegram id.
func (s *Service) UpsertTelegramUser(ctx context.Context, telegramID int64) (UpsertResult, error) {
	if telegramID <= 0 {
		return UpsertResult{}, fmt.Errorf("billing: telegram_id required")
	}
	if u, err := s.users.GetUserByTelegramID(ctx, telegramID); err == nil {
		return UpsertResult{UserID: u.ID, TelegramID: telegramID, Created: false, Email: u.Email}, nil
	} else if !errors.Is(err, store.ErrNotFound) {
		return UpsertResult{}, err
	}
	now := time.Now().UTC()
	uid := id.NewUUID()
	email := fmt.Sprintf("tg_%d@telegram.focusvpn.local", telegramID)
	hash, err := randomUnusableHash()
	if err != nil {
		return UpsertResult{}, err
	}
	tg := telegramID
	u := store.User{
		ID: uid, Email: email, PasswordHash: hash, Role: "user", Status: "active",
		TelegramID: &tg, CreatedAt: now, UpdatedAt: now,
	}
	if err := s.users.CreateUser(ctx, u); err != nil {
		if errors.Is(err, store.ErrConflict) {
			// race: fetch again
			existing, err2 := s.users.GetUserByTelegramID(ctx, telegramID)
			if err2 != nil {
				return UpsertResult{}, err
			}
			return UpsertResult{UserID: existing.ID, TelegramID: telegramID, Created: false, Email: existing.Email}, nil
		}
		return UpsertResult{}, err
	}
	return UpsertResult{UserID: uid, TelegramID: telegramID, Created: true, Email: email}, nil
}

// GrantRequest is a FocusPay-confirmed purchase or trial (ADR-010).
type GrantRequest struct {
	ExternalID    string
	TelegramID    int64
	Kind          string
	PlanCode      string
	Days          int
	AmountKopecks int64
}

// GrantResult is returned by Grant and GetGrant.
type GrantResult struct {
	ExternalID     string    `json:"external_id"`
	TelegramID     int64     `json:"telegram_id"`
	UserID         string    `json:"user_id"`
	SubscriptionID string    `json:"subscription_id"`
	Kind           string    `json:"kind"`
	PlanCode       string    `json:"plan_code"`
	Days           int       `json:"days"`
	AmountKopecks  int64     `json:"amount_kopecks"`
	Status         string    `json:"status"`
	EndsAt         time.Time `json:"ends_at"`
	Idempotent     bool      `json:"idempotent"`
	CreatedAt      time.Time `json:"created_at"`
}

// ErrInvalid marks a request CP refuses before changing anything.
var ErrInvalid = errors.New("billing: invalid grant")

const maxGrantDays = 365

// Grant adds days for a FocusPay purchase id. Repeating the same id is a no-op
// that returns the original result, so FocusPay may retry freely.
func (s *Service) Grant(ctx context.Context, req GrantRequest) (GrantResult, error) {
	if req.ExternalID == "" || len(req.ExternalID) > 128 || req.TelegramID <= 0 ||
		req.Days <= 0 || req.Days > maxGrantDays || req.AmountKopecks < 0 {
		return GrantResult{}, fmt.Errorf("%w: external_id, telegram_id, days 1..%d required", ErrInvalid, maxGrantDays)
	}
	switch req.Kind {
	case KindPaid, KindDevice:
		if req.PlanCode == "" || req.PlanCode == KindTrial {
			return GrantResult{}, fmt.Errorf("%w: plan_code required", ErrInvalid)
		}
	case KindTrial:
		req.PlanCode, req.AmountKopecks = KindTrial, 0
	default:
		return GrantResult{}, fmt.Errorf("%w: kind must be paid|trial", ErrInvalid)
	}
	up, err := s.UpsertTelegramUser(ctx, req.TelegramID)
	if err != nil {
		return GrantResult{}, err
	}
	plan, err := s.subs.GetPlanByCode(ctx, req.PlanCode)
	if errors.Is(err, store.ErrNotFound) {
		plan, err = s.subs.GetPlanByCode(ctx, PlanWeek)
	}
	if err != nil {
		return GrantResult{}, fmt.Errorf("billing: plan lookup: %w", err)
	}
	res, err := s.subs.GrantSubscription(ctx, store.Grant{
		ExternalID: req.ExternalID, SubscriptionID: id.NewUUID(), TelegramID: req.TelegramID,
		UserID: up.UserID, PlanID: plan.ID, PlanCode: req.PlanCode, Kind: req.Kind,
		Days: req.Days, AmountKopecks: req.AmountKopecks, At: s.now().UTC(),
	})
	if err != nil {
		return GrantResult{}, err
	}
	return toGrantResult(res.Event, res.Subscription, res.Idempotent), nil
}

// GetGrant returns a recorded grant by FocusPay purchase id (ErrNotFound if none).
func (s *Service) GetGrant(ctx context.Context, externalID string) (GrantResult, error) {
	ev, err := s.subs.GetBillingEvent(ctx, externalID)
	if err != nil {
		return GrantResult{}, err
	}
	sub, err := s.subs.GetSubscriptionByID(ctx, ev.SubscriptionID)
	if err != nil {
		return GrantResult{}, err
	}
	return toGrantResult(ev, sub, true), nil
}

// ListGrants returns recorded grants since a point in time (for FocusPay reconciliation).
func (s *Service) ListGrants(ctx context.Context, since time.Time, limit int) ([]GrantResult, error) {
	if limit <= 0 || limit > 5000 {
		limit = 5000
	}
	evs, err := s.subs.ListBillingEvents(ctx, since, limit)
	if err != nil {
		return nil, err
	}
	out := make([]GrantResult, 0, len(evs))
	for _, ev := range evs {
		out = append(out, toGrantResult(ev, store.Subscription{ID: ev.SubscriptionID}, true))
	}
	return out, nil
}

func toGrantResult(ev store.BillingEvent, sub store.Subscription, idem bool) GrantResult {
	ends := sub.EndsAt
	if ev.EndsAt != nil {
		ends = *ev.EndsAt
	}
	return GrantResult{
		ExternalID: ev.IdempotencyKey, TelegramID: ev.TelegramID, UserID: ev.UserID, SubscriptionID: sub.ID,
		Kind: ev.Kind, PlanCode: ev.PlanCode, Days: ev.Days, AmountKopecks: ev.AmountKopecks,
		Status: sub.Status, EndsAt: ends.UTC().Truncate(time.Second), Idempotent: idem,
		CreatedAt: ev.CreatedAt.UTC().Truncate(time.Second),
	}
}

// StatusResult describes subscription for a Telegram user.
type StatusResult struct {
	UserID         string           `json:"user_id,omitempty"`
	TelegramID     int64            `json:"telegram_id"`
	HasUser        bool             `json:"has_user"`
	HasLive        bool             `json:"has_live"`
	SubscriptionID string           `json:"subscription_id,omitempty"`
	PlanCode       string           `json:"plan_code,omitempty"`
	Status         string           `json:"status,omitempty"`
	EndsAt         *time.Time       `json:"ends_at,omitempty"`
	MaxDevices     int              `json:"max_devices"`
	BaseDevices    int              `json:"base_devices"`
	ExtraSlots     []DeviceSlotView `json:"extra_slots"`
}

// DeviceSlotView is one unexpired extra-device seat.
type DeviceSlotView struct {
	PlanCode string    `json:"plan_code"`
	EndsAt   time.Time `json:"ends_at"`
}

// Status returns billing status for a Telegram id.
func (s *Service) Status(ctx context.Context, telegramID int64) (StatusResult, error) {
	out := StatusResult{TelegramID: telegramID, ExtraSlots: []DeviceSlotView{}}
	u, err := s.users.GetUserByTelegramID(ctx, telegramID)
	if errors.Is(err, store.ErrNotFound) {
		return out, nil
	}
	if err != nil {
		return out, err
	}
	out.HasUser = true
	out.UserID = u.ID
	now := s.now().UTC()
	slots, err := s.subs.ListLiveDeviceSlots(ctx, u.ID, now)
	if err != nil {
		return out, err
	}
	out.ExtraSlots = make([]DeviceSlotView, 0, len(slots))
	for _, slot := range slots {
		out.ExtraSlots = append(out.ExtraSlots, DeviceSlotView{
			PlanCode: slot.PlanCode, EndsAt: slot.EndsAt.UTC().Truncate(time.Second),
		})
	}
	sub, plan, err := s.subs.GetActiveByUser(ctx, u.ID)
	if errors.Is(err, store.ErrNoSubscription) {
		return out, nil
	}
	if err != nil {
		return out, err
	}
	out.HasLive = true
	out.SubscriptionID = sub.ID
	out.PlanCode = plan.Code
	out.Status = sub.Status
	ends := sub.EndsAt
	out.EndsAt = &ends
	out.BaseDevices = plan.MaxDevices
	out.MaxDevices = plan.MaxDevices + len(out.ExtraSlots)
	return out, nil
}

func randomUnusableHash() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return "!telegram:" + hex.EncodeToString(b), nil
}
