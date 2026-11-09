package applogin

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/billing"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

var (
	ErrNotReady    = errors.New("not_ready")
	ErrExpired     = errors.New("expired")
	ErrInvalidCode = errors.New("invalid_code")
)

// Service implements Telegram app login flows.
type Service struct {
	logins  store.AppLoginStore
	users   store.UserStore
	billing *billing.Service
	auth    *auth.Service
	hasher  func(string) string
	botUser string
	ttl     time.Duration
	now     func() time.Time
}

// NewService wires dependencies. hasher should match refresh/device token hashing.
func NewService(
	logins store.AppLoginStore,
	users store.UserStore,
	bill *billing.Service,
	authSvc *auth.Service,
	hasher func(string) string,
	botUsername string,
	ttl time.Duration,
) *Service {
	if ttl <= 0 {
		ttl = 5 * time.Minute
	}
	botUsername = strings.TrimPrefix(strings.TrimSpace(botUsername), "@")
	return &Service{
		logins:  logins,
		users:   users,
		billing: bill,
		auth:    authSvc,
		hasher:  hasher,
		botUser: botUsername,
		ttl:     ttl,
		now:     time.Now,
	}
}

// StartResult is returned to the mobile app for deep-link login.
type StartResult struct {
	DeepLink  string `json:"deep_link"`
	WaitToken string `json:"wait_token"`
	ExpiresIn int    `json:"expires_in"`
}

// Start creates a pending login and returns bot deep link + wait token.
func (s *Service) Start(ctx context.Context) (StartResult, error) {
	startRaw, err := randomHex(16)
	if err != nil {
		return StartResult{}, err
	}
	waitRaw := id.NewOpaqueToken(24)
	now := s.now()
	req := store.AppLoginRequest{
		ID:             id.NewUUID(),
		StartTokenHash: s.hasher("vpnauth:" + startRaw),
		WaitTokenHash:  s.hasher("wait:" + waitRaw),
		CreatedAt:      now,
		ExpiresAt:      now.Add(s.ttl),
	}
	if err := s.logins.CreateAppLogin(ctx, req); err != nil {
		return StartResult{}, err
	}
	bot := s.botUser
	if bot == "" {
		bot = "FocusVPNBot"
	}
	link := fmt.Sprintf("https://t.me/%s?start=vpnauth_%s", bot, startRaw)
	return StartResult{
		DeepLink:  link,
		WaitToken: waitRaw,
		ExpiresIn: int(s.ttl.Seconds()),
	}, nil
}

// Wait polls until the bot attached Telegram, then issues JWT bundle.
func (s *Service) Wait(ctx context.Context, waitToken string) (store.User, auth.Tokens, error) {
	waitToken = strings.TrimSpace(waitToken)
	if waitToken == "" {
		return store.User{}, auth.Tokens{}, ErrInvalidCode
	}
	req, err := s.logins.GetAppLoginByWaitHash(ctx, s.hasher("wait:"+waitToken))
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return store.User{}, auth.Tokens{}, ErrInvalidCode
		}
		return store.User{}, auth.Tokens{}, err
	}
	now := s.now()
	if now.After(req.ExpiresAt) {
		return store.User{}, auth.Tokens{}, ErrExpired
	}
	if req.ConsumedAt != nil {
		return store.User{}, auth.Tokens{}, ErrInvalidCode
	}
	if req.UserID == nil || req.AttachedAt == nil {
		return store.User{}, auth.Tokens{}, ErrNotReady
	}
	u, toks, err := s.finish(ctx, req)
	return u, toks, err
}

// RedeemCode exchanges a bot-issued short code for tokens.
func (s *Service) RedeemCode(ctx context.Context, code string) (store.User, auth.Tokens, error) {
	code = normalizePairCode(code)
	if code == "" {
		return store.User{}, auth.Tokens{}, ErrInvalidCode
	}
	req, err := s.logins.GetAppLoginByPairCodeHash(ctx, s.hasher("pair:"+code))
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return store.User{}, auth.Tokens{}, ErrInvalidCode
		}
		return store.User{}, auth.Tokens{}, err
	}
	now := s.now()
	if now.After(req.ExpiresAt) {
		return store.User{}, auth.Tokens{}, ErrExpired
	}
	if req.ConsumedAt != nil {
		return store.User{}, auth.Tokens{}, ErrInvalidCode
	}
	if req.UserID == nil {
		return store.User{}, auth.Tokens{}, ErrInvalidCode
	}
	return s.finish(ctx, req)
}

func (s *Service) finish(ctx context.Context, req store.AppLoginRequest) (store.User, auth.Tokens, error) {
	if req.UserID == nil {
		return store.User{}, auth.Tokens{}, ErrInvalidCode
	}
	u, err := s.users.GetUserByID(ctx, *req.UserID)
	if err != nil {
		return store.User{}, auth.Tokens{}, err
	}
	if err := s.logins.ConsumeAppLogin(ctx, req.ID, s.now()); err != nil {
		return store.User{}, auth.Tokens{}, err
	}
	_ = s.users.SetLastLogin(ctx, u.ID, s.now())
	toks, err := s.auth.IssueTokenBundle(ctx, u)
	if err != nil {
		return store.User{}, auth.Tokens{}, err
	}
	return u, toks, nil
}

// AttachLogin binds Telegram identity to a pending deep-link login (bot /start vpnauth_).
func (s *Service) AttachLogin(ctx context.Context, startToken string, telegramID int64) error {
	startRaw := normalizeStartToken(startToken)
	if startRaw == "" || telegramID <= 0 {
		return ErrInvalidCode
	}
	up, err := s.billing.UpsertTelegramUser(ctx, telegramID)
	if err != nil {
		return err
	}
	return s.logins.AttachAppLogin(ctx, s.hasher("vpnauth:"+startRaw), telegramID, up.UserID, s.now())
}

// IssuePairCode creates a short code for manual entry in the app.
func (s *Service) IssuePairCode(ctx context.Context, telegramID int64) (string, error) {
	if telegramID <= 0 {
		return "", ErrInvalidCode
	}
	up, err := s.billing.UpsertTelegramUser(ctx, telegramID)
	if err != nil {
		return "", err
	}
	code, err := randomPairCode(8)
	if err != nil {
		return "", err
	}
	now := s.now()
	req := store.AppLoginRequest{
		ID:           id.NewUUID(),
		PairCodeHash: s.hasher("pair:" + code),
		TelegramID:   &telegramID,
		UserID:       &up.UserID,
		CreatedAt:    now,
		ExpiresAt:    now.Add(s.ttl),
		AttachedAt:   &now,
	}
	if err := s.logins.CreatePairCodeLogin(ctx, req); err != nil {
		return "", err
	}
	return code, nil
}

func normalizeStartToken(raw string) string {
	raw = strings.TrimSpace(raw)
	raw = strings.TrimPrefix(raw, "vpnauth_")
	raw = strings.TrimPrefix(raw, "/start ")
	return strings.TrimSpace(raw)
}

func normalizePairCode(code string) string {
	code = strings.ToUpper(strings.TrimSpace(code))
	code = strings.ReplaceAll(code, " ", "")
	code = strings.ReplaceAll(code, "-", "")
	return code
}

func randomHex(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

const pairAlphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

func randomPairCode(n int) (string, error) {
	b := make([]byte, n)
	r := make([]byte, n)
	if _, err := rand.Read(r); err != nil {
		return "", err
	}
	for i := range b {
		b[i] = pairAlphabet[int(r[i])%len(pairAlphabet)]
	}
	return string(b), nil
}
