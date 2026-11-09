package postgres

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func (s *Store) AppLogins() store.AppLoginStore { return s }

func (s *Store) CreateAppLogin(ctx context.Context, req store.AppLoginRequest) error {
	const q = `INSERT INTO app_login_requests (
		id, start_token_hash, pair_code_hash, wait_token_hash,
		telegram_id, user_id, created_at, expires_at, attached_at, consumed_at
	) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`
	_, err := s.pool.Exec(ctx, q,
		req.ID, nullIfEmpty(req.StartTokenHash), nullIfEmpty(req.PairCodeHash), nullIfEmpty(req.WaitTokenHash),
		req.TelegramID, req.UserID, req.CreatedAt, req.ExpiresAt, req.AttachedAt, req.ConsumedAt,
	)
	if isUnique(err) {
		return store.ErrConflict
	}
	return err
}

func (s *Store) CreatePairCodeLogin(ctx context.Context, req store.AppLoginRequest) error {
	return s.CreateAppLogin(ctx, req)
}

func (s *Store) GetAppLoginByWaitHash(ctx context.Context, hash string) (store.AppLoginRequest, error) {
	return s.getAppLogin(ctx, `wait_token_hash = $1`, hash)
}

func (s *Store) GetAppLoginByStartHash(ctx context.Context, hash string) (store.AppLoginRequest, error) {
	return s.getAppLogin(ctx, `start_token_hash = $1`, hash)
}

func (s *Store) GetAppLoginByPairCodeHash(ctx context.Context, hash string) (store.AppLoginRequest, error) {
	return s.getAppLogin(ctx, `pair_code_hash = $1`, hash)
}

func (s *Store) getAppLogin(ctx context.Context, where string, arg string) (store.AppLoginRequest, error) {
	q := `SELECT id, start_token_hash, pair_code_hash, wait_token_hash,
		telegram_id, user_id, created_at, expires_at, attached_at, consumed_at
		FROM app_login_requests WHERE ` + where
	var r store.AppLoginRequest
	var startH, pairH, waitH *string
	err := s.pool.QueryRow(ctx, q, arg).Scan(
		&r.ID, &startH, &pairH, &waitH, &r.TelegramID, &r.UserID,
		&r.CreatedAt, &r.ExpiresAt, &r.AttachedAt, &r.ConsumedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return store.AppLoginRequest{}, store.ErrNotFound
	}
	if err != nil {
		return store.AppLoginRequest{}, err
	}
	if startH != nil {
		r.StartTokenHash = *startH
	}
	if pairH != nil {
		r.PairCodeHash = *pairH
	}
	if waitH != nil {
		r.WaitTokenHash = *waitH
	}
	return r, nil
}

func (s *Store) AttachAppLogin(ctx context.Context, startHash string, telegramID int64, userID string, at time.Time) error {
	const q = `UPDATE app_login_requests
		SET telegram_id = $2, user_id = $3, attached_at = $4
		WHERE start_token_hash = $1 AND consumed_at IS NULL AND expires_at > $4`
	tag, err := s.pool.Exec(ctx, q, startHash, telegramID, userID, at)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return store.ErrNotFound
	}
	return nil
}

func (s *Store) ConsumeAppLogin(ctx context.Context, id string, at time.Time) error {
	const q = `UPDATE app_login_requests SET consumed_at = $2
		WHERE id = $1 AND consumed_at IS NULL`
	tag, err := s.pool.Exec(ctx, q, id, at)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return store.ErrConflict
	}
	return nil
}

func nullIfEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
