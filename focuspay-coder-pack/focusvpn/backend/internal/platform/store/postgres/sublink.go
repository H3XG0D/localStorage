package postgres

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func (s *Store) SubLinks() store.SubLinkStore { return s }

func (s *Store) CreateSubLink(ctx context.Context, l store.SubLink) error {
	const q = `INSERT INTO subscription_links (id, user_id, device_id, token_hash, token_enc, created_at, revoked_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7)`
	_, err := s.pool.Exec(ctx, q, l.ID, l.UserID, l.DeviceID, l.TokenHash, l.TokenEnc, l.CreatedAt, l.RevokedAt)
	if isUnique(err) {
		return store.ErrConflict
	}
	if isForeignKey(err) {
		return store.ErrNotFound
	}
	return err
}

func (s *Store) GetLiveSubLinkByUser(ctx context.Context, userID string) (store.SubLink, error) {
	return s.getLiveSubLink(ctx, `user_id = $1 AND revoked_at IS NULL`, userID)
}

func (s *Store) GetLiveSubLinkByTokenHash(ctx context.Context, hash string) (store.SubLink, error) {
	return s.getLiveSubLink(ctx, `token_hash = $1 AND revoked_at IS NULL`, hash)
}

func (s *Store) getLiveSubLink(ctx context.Context, where, arg string) (store.SubLink, error) {
	const cols = `id, user_id, device_id, token_hash, token_enc, created_at, revoked_at`
	var l store.SubLink
	err := s.pool.QueryRow(ctx, `SELECT `+cols+` FROM subscription_links WHERE `+where, arg).Scan(
		&l.ID, &l.UserID, &l.DeviceID, &l.TokenHash, &l.TokenEnc, &l.CreatedAt, &l.RevokedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.SubLink{}, store.ErrNotFound
	}
	return l, err
}

func (s *Store) RevokeSubLink(ctx context.Context, id string, at time.Time) error {
	tag, err := s.pool.Exec(ctx, `UPDATE subscription_links SET revoked_at = $2 WHERE id = $1 AND revoked_at IS NULL`, id, at)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}
