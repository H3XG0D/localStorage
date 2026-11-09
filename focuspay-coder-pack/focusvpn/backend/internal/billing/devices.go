package billing

import (
	"context"
	"errors"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// DeviceManager is the device service surface the bot needs (devices.Service).
type DeviceManager interface {
	List(ctx context.Context, userID string) ([]store.Device, error)
	// Revoke revokes the user's device and its allocations; notFound reports a
	// missing or foreign device.
	Revoke(ctx context.Context, deviceID, userID string) error
}

// LiveCounter counts live allocations of a device (store.AllocationStore).
type LiveCounter interface {
	CountLiveByDevice(ctx context.Context, deviceID string) (int, error)
}

// ErrDeviceNotFound is returned for an unknown device or one owned by someone else.
var ErrDeviceNotFound = errors.New("billing: device not found")

// DeviceView is one device as the Telegram bot shows it.
type DeviceView struct {
	ID         string     `json:"id"`
	Name       string     `json:"name"`
	Platform   string     `json:"platform"`
	Status     string     `json:"status"`
	CreatedAt  time.Time  `json:"created_at"`
	LastSeenAt *time.Time `json:"last_seen_at,omitempty"`
	Connected  bool       `json:"connected"`
}

// UseDevices wires device listing/revocation for the bot. notFound is the device
// service's not-found sentinel.
func (s *Service) UseDevices(dm DeviceManager, live LiveCounter, notFound error) {
	s.devices, s.live, s.devNotFound = dm, live, notFound
}

// ListDevices returns the active devices of a Telegram user (empty if unknown).
func (s *Service) ListDevices(ctx context.Context, telegramID int64) ([]DeviceView, error) {
	if s.devices == nil {
		return nil, errors.New("billing: devices not wired")
	}
	u, err := s.users.GetUserByTelegramID(ctx, telegramID)
	if errors.Is(err, store.ErrNotFound) {
		return []DeviceView{}, nil
	}
	if err != nil {
		return nil, err
	}
	list, err := s.devices.List(ctx, u.ID)
	if err != nil {
		return nil, err
	}
	out := make([]DeviceView, 0, len(list))
	for _, d := range list {
		if d.Status != "active" {
			continue
		}
		v := DeviceView{ID: d.ID, Name: d.Name, Platform: d.Platform, Status: d.Status, CreatedAt: d.CreatedAt, LastSeenAt: d.LastSeenAt}
		if s.live != nil {
			n, err := s.live.CountLiveByDevice(ctx, d.ID)
			if err != nil {
				return nil, err
			}
			v.Connected = n > 0
		}
		out = append(out, v)
	}
	return out, nil
}

// RevokeDevice unbinds a device so the user can log in on another phone.
func (s *Service) RevokeDevice(ctx context.Context, telegramID int64, deviceID string) error {
	if s.devices == nil {
		return errors.New("billing: devices not wired")
	}
	u, err := s.users.GetUserByTelegramID(ctx, telegramID)
	if errors.Is(err, store.ErrNotFound) {
		return ErrDeviceNotFound
	}
	if err != nil {
		return err
	}
	err = s.devices.Revoke(ctx, deviceID, u.ID)
	if err != nil && (errors.Is(err, store.ErrNotFound) || (s.devNotFound != nil && errors.Is(err, s.devNotFound))) {
		return ErrDeviceNotFound
	}
	return err
}

// EndingView is one reminder candidate for the bot.
type EndingView struct {
	TelegramID int64     `json:"telegram_id"`
	PlanCode   string    `json:"plan_code"`
	Status     string    `json:"status"`
	EndsAt     time.Time `json:"ends_at"`
}

// ListEnding returns subscriptions ending in [from, to).
func (s *Service) ListEnding(ctx context.Context, from, to time.Time, limit int) ([]EndingView, error) {
	list, err := s.subs.ListEndingBetween(ctx, from, to, limit)
	if err != nil {
		return nil, err
	}
	out := make([]EndingView, 0, len(list))
	for _, e := range list {
		out = append(out, EndingView{TelegramID: e.TelegramID, PlanCode: e.PlanCode, Status: e.Status, EndsAt: e.EndsAt.UTC().Truncate(time.Second)})
	}
	return out, nil
}
