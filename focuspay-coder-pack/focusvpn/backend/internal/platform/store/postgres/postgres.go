// Package postgres is the production store.Store implementation backed by
// PostgreSQL (DATABASE.md). It uses pgx directly with hand-written, parameterized
// SQL (no ORM; sqlc deferred, see DECISIONS.md). All queries are parameterized to
// avoid SQL injection; unique-constraint violations map to store.ErrConflict.
package postgres

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"focusvpn.example/focusvpn/backend/internal/nodehealth"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Store implements store.Store against PostgreSQL.
type Store struct {
	pool *pgxpool.Pool
	kek  *mycrypto.KEK
}

// UseKEK installs the key that seals VLESS UUIDs at rest. Required before any
// allocation with a VLESS UUID is written or read.
func (s *Store) UseKEK(kek mycrypto.KEK) {
	cp := kek
	s.kek = &cp
}

// New connects to PostgreSQL and verifies connectivity. It returns an actionable
// error (never a silent fallback) when the database is unreachable.
func New(ctx context.Context, url string) (*Store, error) {
	if url == "" {
		return nil, errors.New("postgres: FOCUSVPN_DATABASE_URL is empty (set it or use FOCUSVPN_STORE=memory)")
	}
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("postgres: parse FOCUSVPN_DATABASE_URL: %w", err)
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("postgres: create pool: %w", err)
	}
	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres: cannot reach database (%s): %w", safeHost(cfg), err)
	}
	return &Store{pool: pool}, nil
}

func safeHost(cfg *pgxpool.Config) string {
	if cfg == nil || cfg.ConnConfig == nil {
		return "unknown"
	}
	return fmt.Sprintf("%s:%d/%s", cfg.ConnConfig.Host, cfg.ConnConfig.Port, cfg.ConnConfig.Database)
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

// Close releases the connection pool.
func (s *Store) Close() error {
	s.pool.Close()
	return nil
}

// isUnique reports whether err is a unique_violation.
func isUnique(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation
}

func isForeignKey(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation
}

// --- users -----------------------------------------------------------------

func (s *Store) CreateUser(ctx context.Context, u store.User) error {
	const q = `INSERT INTO users (id, email, password_hash, role, status, telegram_id, created_at, updated_at)
	           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`
	_, err := s.pool.Exec(ctx, q, u.ID, u.Email, u.PasswordHash, u.Role, u.Status, u.TelegramID, u.CreatedAt, u.UpdatedAt)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return nil
}

func (s *Store) GetUserByEmail(ctx context.Context, email string) (store.User, error) {
	const q = `SELECT id, email, password_hash, role, status, telegram_id, last_login_at, created_at, updated_at
	           FROM users WHERE email = $1`
	return scanUser(s.pool.QueryRow(ctx, q, email))
}

func (s *Store) GetUserByID(ctx context.Context, uid string) (store.User, error) {
	const q = `SELECT id, email, password_hash, role, status, telegram_id, last_login_at, created_at, updated_at
	           FROM users WHERE id = $1`
	return scanUser(s.pool.QueryRow(ctx, q, uid))
}

func (s *Store) GetUserByTelegramID(ctx context.Context, telegramID int64) (store.User, error) {
	const q = `SELECT id, email, password_hash, role, status, telegram_id, last_login_at, created_at, updated_at
	           FROM users WHERE telegram_id = $1`
	return scanUser(s.pool.QueryRow(ctx, q, telegramID))
}

func (s *Store) SetLastLogin(ctx context.Context, uid string, t time.Time) error {
	const q = `UPDATE users SET last_login_at = $2, updated_at = $2 WHERE id = $1`
	ct, err := s.pool.Exec(ctx, q, uid, t)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanUser(row rowScanner) (store.User, error) {
	var u store.User
	err := row.Scan(&u.ID, &u.Email, &u.PasswordHash, &u.Role, &u.Status, &u.TelegramID, &u.LastLoginAt, &u.CreatedAt, &u.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.User{}, store.ErrNotFound
	}
	if err != nil {
		return store.User{}, err
	}
	return u, nil
}

// --- refresh tokens --------------------------------------------------------

func (s *Store) CreateRefresh(ctx context.Context, rt store.RefreshToken) error {
	const q = `INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, device_id, expires_at, created_at)
	           VALUES ($1, $2, $3, $4, $5, $6, $7)`
	_, err := s.pool.Exec(ctx, q, rt.ID, rt.UserID, rt.FamilyID, rt.TokenHash, rt.DeviceID, rt.ExpiresAt, rt.CreatedAt)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return nil
}

func (s *Store) GetRefreshByHash(ctx context.Context, hash string) (store.RefreshToken, error) {
	const q = `SELECT id, user_id, family_id, token_hash, device_id, expires_at, revoked_at, replaced_by, created_at
	           FROM refresh_tokens WHERE token_hash = $1`
	var rt store.RefreshToken
	err := s.pool.QueryRow(ctx, q, hash).Scan(
		&rt.ID, &rt.UserID, &rt.FamilyID, &rt.TokenHash, &rt.DeviceID,
		&rt.ExpiresAt, &rt.RevokedAt, &rt.ReplacedBy, &rt.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.RefreshToken{}, store.ErrNotFound
	}
	if err != nil {
		return store.RefreshToken{}, err
	}
	return rt, nil
}

func (s *Store) MarkRotated(ctx context.Context, oldID, newID string, at time.Time) error {
	const q = `UPDATE refresh_tokens SET revoked_at = $3, replaced_by = $2 WHERE id = $1`
	ct, err := s.pool.Exec(ctx, q, oldID, newID, at)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}

func (s *Store) RevokeFamily(ctx context.Context, familyID string, at time.Time) error {
	const q = `UPDATE refresh_tokens SET revoked_at = $2 WHERE family_id = $1 AND revoked_at IS NULL`
	_, err := s.pool.Exec(ctx, q, familyID, at)
	return err
}

// --- devices ---------------------------------------------------------------

func (s *Store) CreateDevice(ctx context.Context, d store.Device, maxDevices int) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	// Serialize concurrent device creation for this user so the active-device
	// limit cannot be exceeded by a race.
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, d.UserID); err != nil {
		return err
	}
	if maxDevices > 0 {
		var active int
		if err := tx.QueryRow(ctx,
			`SELECT count(*) FROM devices WHERE user_id = $1 AND status = 'active'`, d.UserID).Scan(&active); err != nil {
			return err
		}
		if active >= maxDevices {
			return store.ErrDeviceLimit
		}
	}
	const q = `INSERT INTO devices (id, user_id, name, platform, app_version, public_key, device_token_hash, status, created_at, updated_at)
	           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`
	if _, err := tx.Exec(ctx, q,
		d.ID, d.UserID, d.Name, d.Platform, d.AppVersion, d.PublicKey, d.DeviceTokenHash, d.Status, d.CreatedAt, d.UpdatedAt); err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return tx.Commit(ctx)
}

func (s *Store) ListDevicesByUser(ctx context.Context, userID string) ([]store.Device, error) {
	const q = `SELECT id, user_id, name, platform, app_version, public_key, device_token_hash, status, last_seen_at, created_at, updated_at, revoked_at
	           FROM devices WHERE user_id = $1 ORDER BY created_at, id`
	rows, err := s.pool.Query(ctx, q, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.Device
	for rows.Next() {
		var d store.Device
		if err := rows.Scan(&d.ID, &d.UserID, &d.Name, &d.Platform, &d.AppVersion, &d.PublicKey,
			&d.DeviceTokenHash, &d.Status, &d.LastSeenAt, &d.CreatedAt, &d.UpdatedAt, &d.RevokedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func (s *Store) GetDeviceByID(ctx context.Context, did string) (store.Device, error) {
	const q = `SELECT id, user_id, name, platform, app_version, public_key, device_token_hash, status, last_seen_at, created_at, updated_at, revoked_at
	           FROM devices WHERE id = $1`
	var d store.Device
	err := s.pool.QueryRow(ctx, q, did).Scan(&d.ID, &d.UserID, &d.Name, &d.Platform, &d.AppVersion, &d.PublicKey,
		&d.DeviceTokenHash, &d.Status, &d.LastSeenAt, &d.CreatedAt, &d.UpdatedAt, &d.RevokedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Device{}, store.ErrNotFound
	}
	if err != nil {
		return store.Device{}, err
	}
	return d, nil
}

func (s *Store) RevokeDevice(ctx context.Context, did, userID string, at time.Time) error {
	const q = `UPDATE devices SET status = 'revoked', revoked_at = $3, updated_at = $3
	           WHERE id = $1 AND user_id = $2 AND status = 'active'`
	ct, err := s.pool.Exec(ctx, q, did, userID, at)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}

func (s *Store) CountActiveDevicesByUser(ctx context.Context, userID string) (int, error) {
	var n int
	err := s.pool.QueryRow(ctx,
		`SELECT count(*) FROM devices WHERE user_id = $1 AND status = 'active'`, userID).Scan(&n)
	return n, err
}

func (s *Store) UpdateDevicePublicKey(ctx context.Context, did, userID string, publicKey []byte, at time.Time) error {
	const q = `UPDATE devices SET public_key = $3, updated_at = $4
	           WHERE id = $1 AND user_id = $2 AND status = 'active'`
	ct, err := s.pool.Exec(ctx, q, did, userID, publicKey, at)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	if ct.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}

// --- subscriptions ---------------------------------------------------------

func (s *Store) GetActiveByUser(ctx context.Context, userID string) (store.Subscription, store.Plan, error) {
	const q = `SELECT
	    s.id, s.user_id, s.plan_id, s.status, s.starts_at, s.ends_at, s.auto_renew, s.provider, s.external_ref, s.created_at, s.updated_at,
	    p.id, p.code, p.name, p.max_devices, p.max_speed_mbps, p.max_traffic_gb, p.period_days, p.price_cents, p.features
	  FROM subscriptions s
	  JOIN plans p ON p.id = s.plan_id
	  WHERE s.user_id = $1 AND s.status IN ('active','trialing') AND s.ends_at > now()
	  ORDER BY s.ends_at DESC
	  LIMIT 1`
	var sub store.Subscription
	var p store.Plan
	err := s.pool.QueryRow(ctx, q, userID).Scan(
		&sub.ID, &sub.UserID, &sub.PlanID, &sub.Status, &sub.StartsAt, &sub.EndsAt, &sub.AutoRenew, &sub.Provider, &sub.ExternalRef, &sub.CreatedAt, &sub.UpdatedAt,
		&p.ID, &p.Code, &p.Name, &p.MaxDevices, &p.MaxSpeedMbps, &p.MaxTrafficGB, &p.PeriodDays, &p.PriceCents, &p.Features)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Subscription{}, store.Plan{}, store.ErrNoSubscription
	}
	if err != nil {
		return store.Subscription{}, store.Plan{}, err
	}
	return sub, p, nil
}

func (s *Store) GetPlanByCode(ctx context.Context, code string) (store.Plan, error) {
	const q = `SELECT id, code, name, max_devices, max_speed_mbps, max_traffic_gb, period_days, price_cents, features
	           FROM plans WHERE code = $1`
	var p store.Plan
	err := s.pool.QueryRow(ctx, q, code).Scan(
		&p.ID, &p.Code, &p.Name, &p.MaxDevices, &p.MaxSpeedMbps, &p.MaxTrafficGB, &p.PeriodDays, &p.PriceCents, &p.Features)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Plan{}, store.ErrNotFound
	}
	if err != nil {
		return store.Plan{}, err
	}
	return p, nil
}

func (s *Store) GetLatestByUser(ctx context.Context, userID string) (store.Subscription, store.Plan, error) {
	const q = `SELECT
	    s.id, s.user_id, s.plan_id, s.status, s.starts_at, s.ends_at, s.auto_renew, s.provider, s.external_ref, s.created_at, s.updated_at,
	    p.id, p.code, p.name, p.max_devices, p.max_speed_mbps, p.max_traffic_gb, p.period_days, p.price_cents, p.features
	  FROM subscriptions s
	  JOIN plans p ON p.id = s.plan_id
	  WHERE s.user_id = $1
	  ORDER BY s.updated_at DESC
	  LIMIT 1`
	var sub store.Subscription
	var p store.Plan
	err := s.pool.QueryRow(ctx, q, userID).Scan(
		&sub.ID, &sub.UserID, &sub.PlanID, &sub.Status, &sub.StartsAt, &sub.EndsAt, &sub.AutoRenew, &sub.Provider, &sub.ExternalRef, &sub.CreatedAt, &sub.UpdatedAt,
		&p.ID, &p.Code, &p.Name, &p.MaxDevices, &p.MaxSpeedMbps, &p.MaxTrafficGB, &p.PeriodDays, &p.PriceCents, &p.Features)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Subscription{}, store.Plan{}, store.ErrNoSubscription
	}
	if err != nil {
		return store.Subscription{}, store.Plan{}, err
	}
	return sub, p, nil
}

const billingEventCols = `idempotency_key, telegram_id, days, subscription_id, user_id, kind, plan_code, amount_kopecks, ends_at, created_at`

func scanBillingEvent(row pgx.Row) (store.BillingEvent, error) {
	var ev store.BillingEvent
	err := row.Scan(&ev.IdempotencyKey, &ev.TelegramID, &ev.Days, &ev.SubscriptionID, &ev.UserID,
		&ev.Kind, &ev.PlanCode, &ev.AmountKopecks, &ev.EndsAt, &ev.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.BillingEvent{}, store.ErrNotFound
	}
	return ev, err
}

const subscriptionCols = `id, user_id, plan_id, status, starts_at, ends_at, auto_renew, provider, external_ref, created_at, updated_at`

func scanSubscription(row pgx.Row) (store.Subscription, error) {
	var sub store.Subscription
	err := row.Scan(&sub.ID, &sub.UserID, &sub.PlanID, &sub.Status, &sub.StartsAt, &sub.EndsAt, &sub.AutoRenew,
		&sub.Provider, &sub.ExternalRef, &sub.CreatedAt, &sub.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Subscription{}, store.ErrNotFound
	}
	return sub, err
}

func (s *Store) GetBillingEvent(ctx context.Context, key string) (store.BillingEvent, error) {
	return scanBillingEvent(s.pool.QueryRow(ctx,
		`SELECT `+billingEventCols+` FROM billing_events WHERE idempotency_key = $1`, key))
}

// GrantSubscription serialises grants per user (advisory lock), so the event row
// and the subscription change commit together or not at all.
func (s *Store) GrantSubscription(ctx context.Context, g store.Grant) (store.GrantResult, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return store.GrantResult{}, err
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext('billing:' || $1::text))`, g.UserID); err != nil {
		return store.GrantResult{}, err
	}
	ev, err := scanBillingEvent(tx.QueryRow(ctx,
		`SELECT `+billingEventCols+` FROM billing_events WHERE idempotency_key = $1`, g.ExternalID))
	if err == nil {
		sub, err := scanSubscription(tx.QueryRow(ctx,
			`SELECT `+subscriptionCols+` FROM subscriptions WHERE id = $1`, ev.SubscriptionID))
		if err != nil {
			return store.GrantResult{}, err
		}
		return store.GrantResult{Event: ev, Subscription: sub, Idempotent: true}, nil
	} else if !errors.Is(err, store.ErrNotFound) {
		return store.GrantResult{}, err
	}
	if g.Kind == "trial" {
		var used bool
		if err := tx.QueryRow(ctx,
			`SELECT EXISTS (SELECT 1 FROM billing_events WHERE user_id = $1 AND kind = 'trial')`, g.UserID).Scan(&used); err != nil {
			return store.GrantResult{}, err
		}
		if used {
			return store.GrantResult{}, store.ErrTrialUsed
		}
	}
	if g.Kind == store.GrantDevice {
		sub, err := scanSubscription(tx.QueryRow(ctx, `
			SELECT `+subscriptionCols+` FROM subscriptions
			WHERE user_id = $1 AND status IN ('active','trialing') AND ends_at > $2
			ORDER BY ends_at DESC LIMIT 1 FOR UPDATE`, g.UserID, g.At))
		if errors.Is(err, store.ErrNotFound) {
			return store.GrantResult{}, store.ErrNoSubscription
		}
		if err != nil {
			return store.GrantResult{}, err
		}
		ends := g.At.Add(time.Duration(g.Days) * 24 * time.Hour)
		ev = store.BillingEvent{
			IdempotencyKey: g.ExternalID, TelegramID: g.TelegramID, Days: g.Days,
			SubscriptionID: sub.ID, UserID: g.UserID, Kind: g.Kind, PlanCode: g.PlanCode,
			AmountKopecks: g.AmountKopecks, EndsAt: &ends, CreatedAt: g.At,
		}
		if _, err := tx.Exec(ctx, `INSERT INTO billing_events (`+billingEventCols+`) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
			ev.IdempotencyKey, ev.TelegramID, ev.Days, ev.SubscriptionID, ev.UserID,
			ev.Kind, ev.PlanCode, ev.AmountKopecks, ev.EndsAt, ev.CreatedAt); err != nil {
			return store.GrantResult{}, err
		}
		if err := tx.Commit(ctx); err != nil {
			return store.GrantResult{}, err
		}
		return store.GrantResult{Event: ev, Subscription: sub}, nil
	}

	period := time.Duration(g.Days) * 24 * time.Hour
	sub, err := scanSubscription(tx.QueryRow(ctx,
		`SELECT `+subscriptionCols+` FROM subscriptions
		 WHERE user_id = $1 AND status IN ('active','trialing') FOR UPDATE`, g.UserID))
	switch {
	case err == nil:
		base := sub.EndsAt
		if base.Before(g.At) {
			base = g.At
		}
		sub.EndsAt = base.Add(period)
		if g.Kind != "trial" {
			sub.Status = "active"
			sub.PlanID = g.PlanID
		}
		sub.UpdatedAt = g.At
		if _, err := tx.Exec(ctx, `
			UPDATE subscriptions SET plan_id = $2, status = $3, ends_at = $4, provider = $5, external_ref = $6, updated_at = $7
			WHERE id = $1`,
			sub.ID, sub.PlanID, sub.Status, sub.EndsAt, store.BillingProvider, g.ExternalID, g.At); err != nil {
			return store.GrantResult{}, err
		}
	case errors.Is(err, store.ErrNotFound):
		status := "active"
		if g.Kind == "trial" {
			status = "trialing"
		}
		prov, ref := store.BillingProvider, g.ExternalID
		sub = store.Subscription{
			ID: g.SubscriptionID, UserID: g.UserID, PlanID: g.PlanID, Status: status,
			StartsAt: g.At, EndsAt: g.At.Add(period), Provider: &prov, ExternalRef: &ref,
			CreatedAt: g.At, UpdatedAt: g.At,
		}
		if _, err := tx.Exec(ctx, `
			INSERT INTO subscriptions (`+subscriptionCols+`)
			VALUES ($1,$2,$3,$4,$5,$6,false,$7,$8,$9,$10)`,
			sub.ID, sub.UserID, sub.PlanID, sub.Status, sub.StartsAt, sub.EndsAt,
			sub.Provider, sub.ExternalRef, sub.CreatedAt, sub.UpdatedAt); err != nil {
			if isUnique(err) {
				return store.GrantResult{}, store.ErrConflict
			}
			return store.GrantResult{}, err
		}
	default:
		return store.GrantResult{}, err
	}

	ends := sub.EndsAt
	ev = store.BillingEvent{
		IdempotencyKey: g.ExternalID, TelegramID: g.TelegramID, Days: g.Days,
		SubscriptionID: sub.ID, UserID: g.UserID, Kind: g.Kind, PlanCode: g.PlanCode,
		AmountKopecks: g.AmountKopecks, EndsAt: &ends, CreatedAt: g.At,
	}
	if _, err := tx.Exec(ctx, `INSERT INTO billing_events (`+billingEventCols+`) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		ev.IdempotencyKey, ev.TelegramID, ev.Days, ev.SubscriptionID, ev.UserID,
		ev.Kind, ev.PlanCode, ev.AmountKopecks, ev.EndsAt, ev.CreatedAt); err != nil {
		if isUnique(err) {
			if g.Kind == "trial" {
				return store.GrantResult{}, store.ErrTrialUsed
			}
			return store.GrantResult{}, store.ErrConflict
		}
		return store.GrantResult{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return store.GrantResult{}, err
	}
	return store.GrantResult{Event: ev, Subscription: sub}, nil
}

func (s *Store) ListBillingEvents(ctx context.Context, since time.Time, limit int) ([]store.BillingEvent, error) {
	rows, err := s.pool.Query(ctx, `SELECT `+billingEventCols+` FROM billing_events
		WHERE created_at >= $1 ORDER BY created_at, idempotency_key LIMIT $2`, since, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.BillingEvent
	for rows.Next() {
		ev, err := scanBillingEvent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, ev)
	}
	return out, rows.Err()
}

func (s *Store) ExpireSubscriptions(ctx context.Context, now time.Time) (int, error) {
	ct, err := s.pool.Exec(ctx, `
		UPDATE subscriptions SET status = 'expired', updated_at = $1
		WHERE status IN ('active','trialing') AND ends_at <= $1`, now)
	if err != nil {
		return 0, err
	}
	return int(ct.RowsAffected()), nil
}

func (s *Store) ListEndingBetween(ctx context.Context, from, to time.Time, limit int) ([]store.EndingSubscription, error) {
	if limit <= 0 || limit > 1000 {
		limit = 500
	}
	rows, err := s.pool.Query(ctx, `
		SELECT DISTINCT ON (s.user_id) u.telegram_id, s.user_id, p.code, s.status, s.ends_at
		FROM subscriptions s
		JOIN users u ON u.id = s.user_id
		JOIN plans p ON p.id = s.plan_id
		WHERE u.telegram_id IS NOT NULL AND s.status IN ('active','trialing','expired')
		  AND s.ends_at >= $1 AND s.ends_at < $2
		ORDER BY s.user_id, s.ends_at DESC
		LIMIT $3`, from, to, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.EndingSubscription
	for rows.Next() {
		var e store.EndingSubscription
		if err := rows.Scan(&e.TelegramID, &e.UserID, &e.PlanCode, &e.Status, &e.EndsAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func (s *Store) ListLiveDeviceSlots(ctx context.Context, userID string, now time.Time) ([]store.DeviceSlot, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT plan_code, ends_at FROM billing_events
		WHERE user_id = $1 AND kind = 'device' AND ends_at > $2
		ORDER BY ends_at`, userID, now)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.DeviceSlot
	for rows.Next() {
		var slot store.DeviceSlot
		if err := rows.Scan(&slot.PlanCode, &slot.EndsAt); err != nil {
			return nil, err
		}
		out = append(out, slot)
	}
	return out, rows.Err()
}

func (s *Store) ListOverLimitDeviceIDs(ctx context.Context, now time.Time) ([]string, error) {
	rows, err := s.pool.Query(ctx, `
		WITH live AS (
			SELECT DISTINCT ON (s.user_id) s.user_id, p.max_devices
			FROM subscriptions s
			JOIN plans p ON p.id = s.plan_id
			WHERE s.status IN ('active','trialing') AND s.ends_at > $1
			ORDER BY s.user_id, s.ends_at DESC
		),
		seats AS (
			SELECT l.user_id,
			       l.max_devices + (
			         SELECT COUNT(*)::int FROM billing_events e
			         WHERE e.user_id = l.user_id AND e.kind = 'device' AND e.ends_at > $1
			       ) AS lim
			FROM live l
		),
		ranked AS (
			SELECT d.id, d.user_id,
			       ROW_NUMBER() OVER (PARTITION BY d.user_id ORDER BY d.created_at ASC, d.id ASC) AS n
			FROM devices d
			WHERE d.status = 'active'
		)
		SELECT r.id
		FROM ranked r
		JOIN seats s ON s.user_id = r.user_id
		WHERE r.n > s.lim
		ORDER BY r.id`, now)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

func (s *Store) GetSubscriptionByID(ctx context.Context, id string) (store.Subscription, error) {
	const q = `SELECT id, user_id, plan_id, status, starts_at, ends_at, auto_renew, provider, external_ref, created_at, updated_at
	           FROM subscriptions WHERE id = $1`
	var sub store.Subscription
	err := s.pool.QueryRow(ctx, q, id).Scan(
		&sub.ID, &sub.UserID, &sub.PlanID, &sub.Status, &sub.StartsAt, &sub.EndsAt, &sub.AutoRenew,
		&sub.Provider, &sub.ExternalRef, &sub.CreatedAt, &sub.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Subscription{}, store.ErrNotFound
	}
	if err != nil {
		return store.Subscription{}, err
	}
	return sub, nil
}

func (s *Store) GetDeviceByTokenHash(ctx context.Context, hash string) (store.Device, error) {
	const q = `SELECT id, user_id, name, platform, app_version, public_key, device_token_hash, status, last_seen_at, created_at, updated_at, revoked_at
	           FROM devices WHERE device_token_hash = $1 AND status = 'active'`
	var d store.Device
	err := s.pool.QueryRow(ctx, q, hash).Scan(&d.ID, &d.UserID, &d.Name, &d.Platform, &d.AppVersion, &d.PublicKey,
		&d.DeviceTokenHash, &d.Status, &d.LastSeenAt, &d.CreatedAt, &d.UpdatedAt, &d.RevokedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Device{}, store.ErrNotFound
	}
	if err != nil {
		return store.Device{}, err
	}
	return d, nil
}

const endpointCols = `e.id, e.node_id, n.name, n.country, n.region, COALESCE(n.hostname,''), e.protocol, e.port, e.state,
	e.public_key, e.obfuscation, host(e.subnet)||'/'||masklen(e.subnet), e.load, e.peer_count,
	n.capacity, e.xray, n.last_heartbeat_at`

func scanEndpoint(row pgx.Row) (store.Endpoint, error) {
	var e store.Endpoint
	err := row.Scan(&e.ID, &e.NodeID, &e.NodeName, &e.Country, &e.Region, &e.Hostname, &e.Protocol, &e.Port, &e.State,
		&e.PublicKey, &e.Obfuscation, &e.Subnet, &e.Load, &e.PeerCount, &e.Capacity, &e.Xray, &e.LastHeartbeatAt)
	return e, err
}

func (s *Store) queryEndpoints(ctx context.Context, q string, args ...any) ([]store.Endpoint, error) {
	rows, err := s.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.Endpoint
	for rows.Next() {
		e, err := scanEndpoint(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func (s *Store) ListSelectable(ctx context.Context, protocol, country string) ([]store.Endpoint, error) {
	return s.queryEndpoints(ctx, `SELECT `+endpointCols+`
	           FROM vpn_endpoints e
	           JOIN vpn_nodes n ON n.id = e.node_id
	           WHERE e.state IN ('HEALTHY','DEGRADED')
	             AND (e.public_key IS NOT NULL OR e.protocol = ANY($3))
	             AND ($1 = '' OR e.protocol = $1)
	             AND ($2 = '' OR n.country = $2)
	           ORDER BY e.id`, protocol, country, store.VLESSProtocols)
}

func (s *Store) ListEndpoints(ctx context.Context) ([]store.Endpoint, error) {
	return s.queryEndpoints(ctx, `SELECT `+endpointCols+`
	           FROM vpn_endpoints e
	           JOIN vpn_nodes n ON n.id = e.node_id
	           ORDER BY e.id`)
}

func (s *Store) GetEndpointByID(ctx context.Context, id string) (store.Endpoint, error) {
	e, err := scanEndpoint(s.pool.QueryRow(ctx, `SELECT `+endpointCols+`
	           FROM vpn_endpoints e
	           JOIN vpn_nodes n ON n.id = e.node_id
	           WHERE e.id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Endpoint{}, store.ErrNotFound
	}
	if err != nil {
		return store.Endpoint{}, err
	}
	return e, nil
}

func (s *Store) RecordNodeHeartbeat(ctx context.Context, nodeID string, online int, at time.Time) error {
	return s.RecordNodePulse(ctx, nodeID, online, at, nil)
}

func (s *Store) RecordNodePulse(ctx context.Context, nodeID string, online int, at time.Time, health *store.NodeHealth) error {
	return s.withNodeStatus(ctx, nodeID, online, at, true, func(st nodehealth.Status) nodehealth.Status {
		if health == nil {
			return nodehealth.ApplyLegacyHeartbeat(st)
		}
		return nodehealth.ApplyAgent(st, nodehealth.Report{OK: health.OK, Degraded: health.Degraded, Reason: health.Reason})
	})
}

func (s *Store) ApplyEdgeProbe(ctx context.Context, nodeID string, ok bool, reason string) error {
	return s.withNodeStatus(ctx, nodeID, 0, time.Time{}, false, func(st nodehealth.Status) nodehealth.Status {
		return nodehealth.ApplyProbe(st, ok, reason)
	})
}

func (s *Store) ListEdgeHosts(ctx context.Context, since time.Time) ([]store.EdgeHost, error) {
	rows, err := s.pool.Query(ctx,
		`SELECT id, hostname FROM vpn_nodes
		 WHERE COALESCE(hostname, '') <> ''
		   AND last_heartbeat_at IS NOT NULL AND last_heartbeat_at >= $1
		   AND state <> 'DRAINING'
		 ORDER BY id`, since)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.EdgeHost
	for rows.Next() {
		var h store.EdgeHost
		if err := rows.Scan(&h.NodeID, &h.Hostname); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

// withNodeStatus loads the node, applies decide, and writes state back.
// When touch is set, last_heartbeat_at, peer_count and load move too.
// online is ignored when touch is false; the current peer_count is kept.
func (s *Store) withNodeStatus(ctx context.Context, nodeID string, online int, at time.Time, touch bool, decide func(nodehealth.Status) nodehealth.Status) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx) //nolint:errcheck
	var st nodehealth.Status
	var capacity, peer int
	err = tx.QueryRow(ctx,
		`SELECT state, COALESCE(status_reason, ''), health_fails, probe_fails, capacity,
		        COALESCE((SELECT max(peer_count) FROM vpn_endpoints e WHERE e.node_id = vpn_nodes.id), 0)
		 FROM vpn_nodes WHERE id = $1`, nodeID).
		Scan(&st.State, &st.Reason, &st.HealthFails, &st.ProbeFails, &capacity, &peer)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.ErrNotFound
	}
	if err != nil {
		return err
	}
	st = decide(st)
	if !touch {
		online = peer
		at = time.Now().UTC()
	}
	if _, err := tx.Exec(ctx,
		`UPDATE vpn_nodes
		 SET state = $2, status_reason = NULLIF($3, ''), health_fails = $4, probe_fails = $5,
		     last_heartbeat_at = CASE WHEN $6 THEN $7 ELSE last_heartbeat_at END,
		     updated_at = $7
		 WHERE id = $1`,
		nodeID, st.State, st.Reason, st.HealthFails, st.ProbeFails, touch, at); err != nil {
		return err
	}
	load := 0.0
	if capacity > 0 {
		load = float64(online) / float64(capacity)
	}
	if _, err := tx.Exec(ctx,
		`UPDATE vpn_endpoints
		 SET state = $2, updated_at = $5,
		     peer_count = CASE WHEN $6 THEN $3 ELSE peer_count END,
		     load = CASE WHEN $6 THEN $4 ELSE load END,
		     last_probe_at = CASE WHEN $6 THEN $5 ELSE last_probe_at END
		 WHERE node_id = $1`,
		nodeID, st.State, online, load, at, touch); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *Store) MarkStaleOffline(ctx context.Context, before time.Time) ([]string, error) {
	rows, err := s.pool.Query(ctx,
		`UPDATE vpn_endpoints e SET state = 'OFFLINE', updated_at = now()
		 FROM vpn_nodes n
		 WHERE n.id = e.node_id AND n.last_heartbeat_at IS NOT NULL AND n.last_heartbeat_at < $1
		   AND e.state IN ('HEALTHY','DEGRADED')
		   AND n.state IN ('HEALTHY','DEGRADED')
		 RETURNING e.node_id`, before)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	seen := map[string]bool{}
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(out) > 0 {
		_, err = s.pool.Exec(ctx,
			`UPDATE vpn_nodes SET state = 'OFFLINE', status_reason = $2, updated_at = now()
			 WHERE id = ANY($1) AND state IN ('HEALTHY','DEGRADED')`, out, nodehealth.StaleReason)
	}
	return out, err
}

const allocCols = `id, user_id, device_id, endpoint_id, host(ip), peer_public_key, vless_uuid_enc, status, created_at, updated_at, revoked_at`

func (s *Store) scanAlloc(row pgx.Row) (store.Allocation, error) {
	var a store.Allocation
	var blob []byte
	err := row.Scan(&a.ID, &a.UserID, &a.DeviceID, &a.EndpointID, &a.IP, &a.PeerPublicKey, &blob, &a.Status, &a.CreatedAt, &a.UpdatedAt, &a.RevokedAt)
	if err != nil {
		return a, err
	}
	a.VLESSUUID, err = s.openUUID(blob)
	return a, err
}

func (s *Store) sealUUID(plain string) (blob []byte, hash string, err error) {
	if plain == "" {
		return nil, "", nil
	}
	if s.kek == nil {
		return nil, "", errors.New("postgres: KEK is not set; refusing to store a VLESS UUID")
	}
	blob, _, err = mycrypto.Envelope(*s.kek, []byte(plain))
	if err != nil {
		return nil, "", err
	}
	sum := sha256.Sum256([]byte(plain))
	return blob, hex.EncodeToString(sum[:]), nil
}

func (s *Store) openUUID(blob []byte) (string, error) {
	if len(blob) == 0 {
		return "", nil
	}
	if s.kek == nil {
		return "", errors.New("postgres: KEK is not set; refusing to read a VLESS UUID")
	}
	plain, err := mycrypto.OpenEnvelope(map[string]mycrypto.KEK{s.kek.ID: *s.kek}, blob)
	if err != nil {
		return "", err
	}
	return string(plain), nil
}

func (s *Store) queryAllocs(ctx context.Context, q string, args ...any) ([]store.Allocation, error) {
	rows, err := s.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.Allocation
	for rows.Next() {
		a, err := s.scanAlloc(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func (s *Store) CreateAllocation(ctx context.Context, a store.Allocation) error {
	blob, hash, err := s.sealUUID(a.VLESSUUID)
	if err != nil {
		return err
	}
	const q = `INSERT INTO vpn_allocations (id, user_id, device_id, endpoint_id, ip, peer_public_key, vless_uuid_enc, vless_uuid_hash, status, created_at, updated_at)
	           VALUES ($1,$2,$3,$4,$5::inet,$6,$7,NULLIF($8,''),$9,$10,$11)`
	_, err = s.pool.Exec(ctx, q, a.ID, a.UserID, a.DeviceID, a.EndpointID, a.IP, a.PeerPublicKey, blob, hash, a.Status, a.CreatedAt, a.UpdatedAt)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return nil
}

func (s *Store) GetAllocationByID(ctx context.Context, id string) (store.Allocation, error) {
	a, err := s.scanAlloc(s.pool.QueryRow(ctx, `SELECT `+allocCols+` FROM vpn_allocations WHERE id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Allocation{}, store.ErrNotFound
	}
	if err != nil {
		return store.Allocation{}, err
	}
	return a, nil
}

func (s *Store) GetLiveByDevice(ctx context.Context, deviceID string) (store.Allocation, error) {
	a, err := s.scanAlloc(s.pool.QueryRow(ctx, `SELECT `+allocCols+`
	           FROM vpn_allocations
	           WHERE device_id = $1 AND status IN ('pending','active')
	           ORDER BY created_at DESC LIMIT 1`, deviceID))
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Allocation{}, store.ErrNotFound
	}
	if err != nil {
		return store.Allocation{}, err
	}
	return a, nil
}

func (s *Store) CountLiveByDevice(ctx context.Context, deviceID string) (int, error) {
	var n int
	err := s.pool.QueryRow(ctx, `SELECT count(*) FROM vpn_allocations WHERE device_id = $1 AND status IN ('pending','active')`, deviceID).Scan(&n)
	return n, err
}

func (s *Store) ListLiveIPs(ctx context.Context, endpointID string) ([]string, error) {
	rows, err := s.pool.Query(ctx, `SELECT host(ip) FROM vpn_allocations WHERE endpoint_id = $1 AND status IN ('pending','active')`, endpointID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ips []string
	for rows.Next() {
		var ip string
		if err := rows.Scan(&ip); err != nil {
			return nil, err
		}
		ips = append(ips, ip)
	}
	return ips, rows.Err()
}

func (s *Store) ListLiveByEndpoint(ctx context.Context, endpointID string) ([]store.Allocation, error) {
	return s.queryAllocs(ctx, `SELECT `+allocCols+` FROM vpn_allocations WHERE endpoint_id = $1 AND status IN ('pending','active')`, endpointID)
}

func (s *Store) ListLiveEntitledVLESS(ctx context.Context, now time.Time) ([]store.Allocation, error) {
	return s.queryAllocs(ctx, `SELECT `+allocCols+` FROM vpn_allocations a
	           WHERE a.status IN ('pending','active') AND a.vless_uuid_enc IS NOT NULL
	             AND EXISTS (SELECT 1 FROM vpn_endpoints e WHERE e.id = a.endpoint_id AND e.protocol = ANY($1))
	             AND EXISTS (SELECT 1 FROM subscriptions s WHERE s.user_id = a.user_id
	                         AND s.status IN ('trialing','active') AND s.ends_at > $2)
	             AND NOT EXISTS (SELECT 1 FROM allocation_pauses p
	                             WHERE p.allocation_id = a.id AND p.until_at > $2)
	           ORDER BY a.id`, store.VLESSProtocols, now)
}

func (s *Store) UpsertAllocationPause(ctx context.Context, p store.AllocationPause) (bool, error) {
	now := p.UpdatedAt
	if now.IsZero() {
		now = time.Now().UTC()
	}
	var until time.Time
	err := s.pool.QueryRow(ctx, `SELECT until_at FROM allocation_pauses WHERE allocation_id = $1`, p.AllocationID).Scan(&until)
	fresh := false
	if errors.Is(err, pgx.ErrNoRows) {
		fresh = true
	} else if err != nil {
		return false, err
	} else if !until.After(now) {
		fresh = true
	}
	var node any
	if p.NodeID != "" {
		node = p.NodeID
	}
	_, err = s.pool.Exec(ctx,
		`INSERT INTO allocation_pauses (allocation_id, ip_count, reason, until_at, node_id, updated_at)
		 VALUES ($1, $2, $3, $4, $5, $6)
		 ON CONFLICT (allocation_id) DO UPDATE SET
		   ip_count = EXCLUDED.ip_count, reason = EXCLUDED.reason, until_at = EXCLUDED.until_at,
		   node_id = EXCLUDED.node_id, updated_at = EXCLUDED.updated_at`,
		p.AllocationID, p.IPCount, p.Reason, p.Until, node, now)
	if err != nil {
		if isForeignKey(err) {
			return false, store.ErrNotFound
		}
		return false, err
	}
	return fresh, nil
}

func (s *Store) SetAllocationStatus(ctx context.Context, id, status string, at time.Time) error {
	var q string
	var err error
	var ct pgconn.CommandTag
	if status == "revoked" {
		q = `UPDATE vpn_allocations SET status = $2, updated_at = $3, revoked_at = $3 WHERE id = $1`
		ct, err = s.pool.Exec(ctx, q, id, status, at)
	} else {
		q = `UPDATE vpn_allocations SET status = $2, updated_at = $3 WHERE id = $1`
		ct, err = s.pool.Exec(ctx, q, id, status, at)
	}
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	if ct.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}

func (s *Store) UpdateLivePeerPublicKey(ctx context.Context, deviceID string, publicKey []byte, at time.Time) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE vpn_allocations SET peer_public_key = $2, updated_at = $3
		 WHERE device_id = $1 AND status IN ('pending','active')`,
		deviceID, publicKey, at)
	return err
}

func (s *Store) CreateConfiguration(ctx context.Context, c store.Configuration) error {
	const q = `INSERT INTO vpn_configurations (id, allocation_id, device_id, version, content_encrypted, content_hash, signature, status, rotated_at, created_at, updated_at)
	           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`
	_, err := s.pool.Exec(ctx, q, c.ID, c.AllocationID, c.DeviceID, c.Version, c.ContentEncrypted, c.ContentHash, c.Signature, c.Status, c.RotatedAt, c.CreatedAt, c.UpdatedAt)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return nil
}

func (s *Store) GetConfigurationByID(ctx context.Context, id string) (store.Configuration, error) {
	const q = `SELECT id, allocation_id, device_id, version, content_encrypted, content_hash, signature, status, rotated_at, created_at, updated_at
	           FROM vpn_configurations WHERE id = $1`
	var c store.Configuration
	err := s.pool.QueryRow(ctx, q, id).Scan(&c.ID, &c.AllocationID, &c.DeviceID, &c.Version, &c.ContentEncrypted, &c.ContentHash, &c.Signature, &c.Status, &c.RotatedAt, &c.CreatedAt, &c.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Configuration{}, store.ErrNotFound
	}
	if err != nil {
		return store.Configuration{}, err
	}
	return c, nil
}

func (s *Store) GetActiveByAllocation(ctx context.Context, allocationID string) (store.Configuration, error) {
	const q = `SELECT id, allocation_id, device_id, version, content_encrypted, content_hash, signature, status, rotated_at, created_at, updated_at
	           FROM vpn_configurations WHERE allocation_id = $1 AND status = 'active'`
	var c store.Configuration
	err := s.pool.QueryRow(ctx, q, allocationID).Scan(&c.ID, &c.AllocationID, &c.DeviceID, &c.Version, &c.ContentEncrypted, &c.ContentHash, &c.Signature, &c.Status, &c.RotatedAt, &c.CreatedAt, &c.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.Configuration{}, store.ErrNotFound
	}
	if err != nil {
		return store.Configuration{}, err
	}
	return c, nil
}

func (s *Store) RevokeByAllocation(ctx context.Context, allocationID string, at time.Time) error {
	_, err := s.pool.Exec(ctx, `UPDATE vpn_configurations SET status = 'revoked', updated_at = $2 WHERE allocation_id = $1 AND status = 'active'`, allocationID, at)
	return err
}

func (s *Store) ReplaceActiveConfiguration(ctx context.Context, c store.Configuration, at time.Time) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `UPDATE vpn_configurations SET status = 'revoked', updated_at = $2 WHERE allocation_id = $1 AND status = 'active'`, c.AllocationID, at); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO vpn_configurations (id, allocation_id, device_id, version, content_encrypted, content_hash, signature, status, rotated_at, created_at, updated_at)
	           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		c.ID, c.AllocationID, c.DeviceID, c.Version, c.ContentEncrypted, c.ContentHash, c.Signature, c.Status, c.RotatedAt, c.CreatedAt, c.UpdatedAt); err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return tx.Commit(ctx)
}

func (s *Store) ListActiveOlderThan(ctx context.Context, t time.Time) ([]store.Configuration, error) {
	const q = `SELECT id, allocation_id, device_id, version, content_encrypted, content_hash, signature, status, rotated_at, created_at, updated_at
	           FROM vpn_configurations
	           WHERE status = 'active' AND COALESCE(rotated_at, created_at) < $1
	           ORDER BY COALESCE(rotated_at, created_at) ASC`
	rows, err := s.pool.Query(ctx, q, t)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []store.Configuration
	for rows.Next() {
		var c store.Configuration
		if err := rows.Scan(&c.ID, &c.AllocationID, &c.DeviceID, &c.Version, &c.ContentEncrypted, &c.ContentHash, &c.Signature, &c.Status, &c.RotatedAt, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// --- M4: NodeTokenStore ---

func (s *Store) CreateNodeToken(ctx context.Context, t store.NodeToken) error {
	const q = `INSERT INTO node_tokens (id, node_id, token_hash, expires_at, created_at)
	           VALUES ($1,$2,$3,$4,$5)`
	_, err := s.pool.Exec(ctx, q, t.ID, t.NodeID, t.TokenHash, t.ExpiresAt, t.CreatedAt)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return nil
}

func (s *Store) ConsumeNodeToken(ctx context.Context, hash string, at time.Time) (store.NodeToken, error) {
	const q = `UPDATE node_tokens SET used_at = $2
	           WHERE token_hash = $1 AND used_at IS NULL AND expires_at > $2
	           RETURNING id, node_id, token_hash, used_at, expires_at, created_at`
	var t store.NodeToken
	err := s.pool.QueryRow(ctx, q, hash, at).Scan(&t.ID, &t.NodeID, &t.TokenHash, &t.UsedAt, &t.ExpiresAt, &t.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.NodeToken{}, store.ErrNotFound
	}
	return t, err
}

// --- M4: NodeCertStore ---

func (s *Store) CreateNodeCert(ctx context.Context, c store.NodeCertificate) error {
	const q = `INSERT INTO node_certificates (id, node_id, serial, cert_pem, issued_at, expires_at)
	           VALUES ($1,$2,$3,$4,$5,$6)`
	_, err := s.pool.Exec(ctx, q, c.ID, c.NodeID, c.Serial, c.CertPEM, c.IssuedAt, c.ExpiresAt)
	if err != nil {
		if isUnique(err) {
			return store.ErrConflict
		}
		return err
	}
	return nil
}

func (s *Store) GetLatestNodeCert(ctx context.Context, nodeID string) (store.NodeCertificate, error) {
	const q = `SELECT id, node_id, serial, cert_pem, issued_at, expires_at, revoked_at
	           FROM node_certificates WHERE node_id = $1 AND revoked_at IS NULL
	           ORDER BY issued_at DESC LIMIT 1`
	var c store.NodeCertificate
	err := s.pool.QueryRow(ctx, q, nodeID).Scan(&c.ID, &c.NodeID, &c.Serial, &c.CertPEM, &c.IssuedAt, &c.ExpiresAt, &c.RevokedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.NodeCertificate{}, store.ErrNotFound
	}
	return c, err
}

// --- M4: NodeStateStore ---

func (s *Store) GetStateVersion(ctx context.Context, nodeID string) (int64, error) {
	var v int64
	err := s.pool.QueryRow(ctx, `SELECT version FROM node_state_versions WHERE node_id = $1`, nodeID).Scan(&v)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, store.ErrNotFound
	}
	return v, err
}

func (s *Store) IncrementStateVersion(ctx context.Context, nodeID string) (int64, error) {
	var v int64
	err := s.pool.QueryRow(ctx,
		`UPDATE node_state_versions SET version = version + 1, updated_at = now()
		 WHERE node_id = $1 RETURNING version`, nodeID).Scan(&v)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, store.ErrNotFound
	}
	return v, err
}

func (s *Store) EnsureStateVersion(ctx context.Context, nodeID string) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO node_state_versions (node_id, version) VALUES ($1, 0)
		 ON CONFLICT (node_id) DO NOTHING`, nodeID)
	return err
}
