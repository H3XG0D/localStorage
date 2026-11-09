package auth

import (
	"context"
	"errors"
	"strings"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Service-level errors, mapped to HTTP codes by the handler.
var (
	ErrValidation     = errors.New("validation_error")
	ErrEmailExists    = errors.New("email_already_exists")
	ErrInvalidCreds   = errors.New("invalid_credentials")
	ErrInvalidToken   = errors.New("invalid_token")
	ErrExpiredToken   = errors.New("expired_token")
	ErrAccountStatus  = errors.New("forbidden")
)

// Tokens is the credential bundle returned to callers.
type Tokens struct {
	Access    string
	Refresh   string
	ExpiresIn int
}

// Service implements the auth vertical slice (register/login/refresh/logout).
type Service struct {
	users      store.UserStore
	refresh    store.RefreshStore
	issuer     *TokenIssuer
	refreshTTL time.Duration
	now        func() time.Time
}

// NewService constructs the auth service.
func NewService(users store.UserStore, refresh store.RefreshStore, issuer *TokenIssuer, refreshTTL time.Duration) *Service {
	return &Service{users: users, refresh: refresh, issuer: issuer, refreshTTL: refreshTTL, now: time.Now}
}

// Register creates a user and returns an initial token bundle.
func (s *Service) Register(ctx context.Context, email, password string) (store.User, Tokens, error) {
	email = strings.TrimSpace(email)
	if !validEmail(email) || !validPassword(password) {
		return store.User{}, Tokens{}, ErrValidation
	}
	hash, err := HashPassword(password)
	if err != nil {
		return store.User{}, Tokens{}, err
	}
	now := s.now()
	u := store.User{
		ID:           id.NewUUID(),
		Email:        email,
		PasswordHash: hash,
		Role:         "user",
		Status:       "active",
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	if err := s.users.CreateUser(ctx, u); err != nil {
		if errors.Is(err, store.ErrConflict) {
			return store.User{}, Tokens{}, ErrEmailExists
		}
		return store.User{}, Tokens{}, err
	}
	toks, err := s.newFamily(ctx, u)
	if err != nil {
		return store.User{}, Tokens{}, err
	}
	return u, toks, nil
}

// Login authenticates a user and returns a fresh token family.
func (s *Service) Login(ctx context.Context, email, password string) (store.User, Tokens, error) {
	u, err := s.users.GetUserByEmail(ctx, strings.TrimSpace(email))
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			// Run a dummy verify to reduce timing-based user enumeration.
			_, _ = VerifyPassword(password, dummyHash)
			return store.User{}, Tokens{}, ErrInvalidCreds
		}
		return store.User{}, Tokens{}, err
	}
	ok, err := VerifyPassword(password, u.PasswordHash)
	if err != nil || !ok {
		return store.User{}, Tokens{}, ErrInvalidCreds
	}
	if u.Status != "active" {
		return store.User{}, Tokens{}, ErrAccountStatus
	}
	_ = s.users.SetLastLogin(ctx, u.ID, s.now())
	toks, err := s.newFamily(ctx, u)
	if err != nil {
		return store.User{}, Tokens{}, err
	}
	return u, toks, nil
}

// Refresh rotates a refresh token. Presenting an already-revoked token triggers
// reuse detection: the whole family is revoked (ADR-006).
func (s *Service) Refresh(ctx context.Context, refreshToken string) (Tokens, error) {
	if refreshToken == "" {
		return Tokens{}, ErrInvalidToken
	}
	hash := s.issuer.HashRefresh(refreshToken)
	rt, err := s.refresh.GetRefreshByHash(ctx, hash)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return Tokens{}, ErrInvalidToken
		}
		return Tokens{}, err
	}
	if rt.RevokedAt != nil {
		// Reuse of a rotated/revoked token: revoke the entire family.
		_ = s.refresh.RevokeFamily(ctx, rt.FamilyID, s.now())
		return Tokens{}, ErrInvalidToken
	}
	if s.now().After(rt.ExpiresAt) {
		return Tokens{}, ErrExpiredToken
	}
	u, err := s.users.GetUserByID(ctx, rt.UserID)
	if err != nil {
		return Tokens{}, ErrInvalidToken
	}

	newToken, newHash := s.mintRefresh()
	newID := id.NewUUID()
	now := s.now()
	if err := s.refresh.CreateRefresh(ctx, store.RefreshToken{
		ID:        newID,
		UserID:    u.ID,
		FamilyID:  rt.FamilyID,
		TokenHash: newHash,
		ExpiresAt: now.Add(s.refreshTTL),
		CreatedAt: now,
	}); err != nil {
		return Tokens{}, err
	}
	if err := s.refresh.MarkRotated(ctx, rt.ID, newID, now); err != nil {
		return Tokens{}, err
	}
	access, err := s.issuer.IssueAccess(u.ID, u.Role)
	if err != nil {
		return Tokens{}, err
	}
	return Tokens{Access: access, Refresh: newToken, ExpiresIn: int(s.issuer.AccessTTL().Seconds())}, nil
}

// Logout revokes the token's family. It is idempotent.
func (s *Service) Logout(ctx context.Context, refreshToken string) error {
	if refreshToken == "" {
		return nil
	}
	rt, err := s.refresh.GetRefreshByHash(ctx, s.issuer.HashRefresh(refreshToken))
	if err != nil {
		return nil
	}
	return s.refresh.RevokeFamily(ctx, rt.FamilyID, s.now())
}

// IssueTokenBundle creates a fresh access + refresh family for an authenticated user
// (e.g. Telegram app login after bot attach).
func (s *Service) IssueTokenBundle(ctx context.Context, u store.User) (Tokens, error) {
	return s.newFamily(ctx, u)
}

// newFamily issues an access token plus a brand-new refresh-token family.
func (s *Service) newFamily(ctx context.Context, u store.User) (Tokens, error) {
	token, hash := s.mintRefresh()
	now := s.now()
	if err := s.refresh.CreateRefresh(ctx, store.RefreshToken{
		ID:        id.NewUUID(),
		UserID:    u.ID,
		FamilyID:  id.NewUUID(),
		TokenHash: hash,
		ExpiresAt: now.Add(s.refreshTTL),
		CreatedAt: now,
	}); err != nil {
		return Tokens{}, err
	}
	access, err := s.issuer.IssueAccess(u.ID, u.Role)
	if err != nil {
		return Tokens{}, err
	}
	return Tokens{Access: access, Refresh: token, ExpiresIn: int(s.issuer.AccessTTL().Seconds())}, nil
}

func (s *Service) mintRefresh() (token, hash string) {
	token = id.NewOpaqueToken(32)
	return token, s.issuer.HashRefresh(token)
}

func validEmail(email string) bool {
	at := strings.IndexByte(email, '@')
	if at <= 0 || at == len(email)-1 {
		return false
	}
	return strings.IndexByte(email[at+1:], '.') >= 0 && len(email) <= 254
}

func validPassword(pw string) bool {
	return len(pw) >= 10 && len(pw) <= 1024
}

// dummyHash is a real argon2id hash used to equalize login timing for unknown
// emails (mitigates user enumeration). Its plaintext is irrelevant.
var dummyHash string

func init() {
	h, err := HashPassword("timing-equalization-placeholder")
	if err != nil {
		panic("auth: cannot init dummy hash: " + err.Error())
	}
	dummyHash = h
}
