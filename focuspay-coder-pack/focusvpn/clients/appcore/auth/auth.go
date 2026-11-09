// Package auth implements AuthService against the Control Plane (API.md §2).
package auth

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"time"

	"focusvpn.example/focusvpn/clients/appcore/apierr"
	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// lead is how early an access token is rotated. Two callers must not both
// present the same refresh token: the second is reuse detection.
const lead = time.Minute

// Service handles register/login/refresh/logout with token persistence.
type Service struct {
	api   string
	http  *http.Client
	store storage.SecureStorage
	mu    sync.Mutex
}

// TelegramStart is the deep link the app opens and the token it polls.
type TelegramStart struct {
	DeepLink  string `json:"deep_link"`
	WaitToken string `json:"wait_token"`
	ExpiresIn int    `json:"expires_in"`
}

// New constructs an AuthService.
func New(apiBase string, store storage.SecureStorage) *Service {
	return &Service{
		api:   apiBase,
		http:  &http.Client{Timeout: 30 * time.Second},
		store: store,
	}
}

// Register creates an account and stores tokens.
func (s *Service) Register(ctx context.Context, email, password string) error {
	var resp apitypes.AuthResponse
	if err := s.post(ctx, "/v1/auth/register", map[string]string{
		"email": email, "password": password,
	}, "", &resp); err != nil {
		return err
	}
	return s.saveTokens(resp.Tokens)
}

// Login authenticates and stores tokens.
func (s *Service) Login(ctx context.Context, email, password string) error {
	var resp apitypes.AuthResponse
	if err := s.post(ctx, "/v1/auth/login", map[string]string{
		"email": email, "password": password,
	}, "", &resp); err != nil {
		return err
	}
	return s.saveTokens(resp.Tokens)
}

// Refresh rotates tokens using the stored refresh token (Bearer).
func (s *Service) Refresh(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.refreshLocked(ctx)
}

func (s *Service) refreshLocked(ctx context.Context) error {
	rt, err := s.store.Get(storage.KeyRefreshToken)
	if err != nil {
		return fmt.Errorf("auth: no refresh token: %w", err)
	}
	var resp apitypes.RefreshResponse
	if err := s.post(ctx, "/v1/auth/refresh", nil, string(rt), &resp); err != nil {
		return err
	}
	return s.saveTokens(apitypes.Tokens{
		AccessToken:  resp.AccessToken,
		RefreshToken: resp.RefreshToken,
		ExpiresIn:    resp.ExpiresIn,
	})
}

// EnsureAccess returns a token, rotating it when less than a minute remains.
// A network failure keeps the current token so a blip does not look like logout.
func (s *Service) EnsureAccess(ctx context.Context) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	tok, err := s.accessLocked()
	if err != nil {
		return "", err
	}
	if !s.needsRefreshLocked() {
		return tok, nil
	}
	if err := s.refreshLocked(ctx); err != nil {
		if tok != "" && !apierr.IsAccessRejected(err) {
			return tok, nil
		}
		return "", err
	}
	return s.accessLocked()
}

// RefreshAfterReject rotates once when a call presented usedAccess and got 401.
// If another caller already rotated, the new token is returned and the refresh
// token is not presented again.
func (s *Service) RefreshAfterReject(ctx context.Context, usedAccess string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	cur, err := s.accessLocked()
	if err != nil {
		return "", err
	}
	if cur != "" && cur != usedAccess {
		return cur, nil
	}
	if err := s.refreshLocked(ctx); err != nil {
		return "", err
	}
	return s.accessLocked()
}

// TelegramStart begins a deep-link login. It does not store tokens.
func (s *Service) TelegramStart(ctx context.Context) (TelegramStart, error) {
	var out TelegramStart
	err := s.post(ctx, "/v1/auth/telegram/start", map[string]string{}, "", &out)
	return out, err
}

// TelegramWait polls a pending login. ready is false on HTTP 202.
// On success the tokens are stored; the caller still registers the device.
func (s *Service) TelegramWait(ctx context.Context, waitToken string) (apitypes.AuthResponse, bool, error) {
	q := url.Values{}
	q.Set("wait_token", waitToken)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.api+"/v1/auth/telegram/wait?"+q.Encode(), nil)
	if err != nil {
		return apitypes.AuthResponse{}, false, err
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return apitypes.AuthResponse{}, false, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode == http.StatusAccepted {
		return apitypes.AuthResponse{}, false, nil
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return apitypes.AuthResponse{}, false, apierr.FromBody(resp.StatusCode, raw)
	}
	var out apitypes.AuthResponse
	if err := json.Unmarshal(raw, &out); err != nil {
		return apitypes.AuthResponse{}, false, err
	}
	if err := s.saveTokens(out.Tokens); err != nil {
		return apitypes.AuthResponse{}, false, err
	}
	return out, true, nil
}

// LoginCode redeems a bot access code and stores tokens.
func (s *Service) LoginCode(ctx context.Context, code string) (apitypes.AuthResponse, error) {
	var resp apitypes.AuthResponse
	if err := s.post(ctx, "/v1/auth/telegram/code", map[string]string{"code": code}, "", &resp); err != nil {
		return apitypes.AuthResponse{}, err
	}
	if err := s.saveTokens(resp.Tokens); err != nil {
		return apitypes.AuthResponse{}, err
	}
	return resp, nil
}

// Me returns the signed-in user and subscription.
func (s *Service) Me(ctx context.Context, access string) (apitypes.MeResponse, error) {
	var out apitypes.MeResponse
	err := s.get(ctx, "/v1/me", access, &out)
	return out, err
}

// ListDevices returns the account's devices.
func (s *Service) ListDevices(ctx context.Context, access string) (apitypes.DeviceListResponse, error) {
	var out apitypes.DeviceListResponse
	err := s.get(ctx, "/v1/devices", access, &out)
	return out, err
}

// Logout revokes the refresh family and clears local tokens.
func (s *Service) Logout(ctx context.Context) error {
	rt, _ := s.store.Get(storage.KeyRefreshToken)
	if len(rt) > 0 {
		_ = s.post(ctx, "/v1/auth/logout", map[string]string{"refresh_token": string(rt)}, "", nil)
	}
	_ = s.store.Delete(storage.KeyAccessToken)
	_ = s.store.Delete(storage.KeyRefreshToken)
	_ = s.store.Delete(storage.KeyAccessExpiresAt)
	return nil
}

// AccessToken returns the current access token or error.
func (s *Service) AccessToken() (string, error) {
	b, err := s.store.Get(storage.KeyAccessToken)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func (s *Service) accessLocked() (string, error) {
	b, err := s.store.Get(storage.KeyAccessToken)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func (s *Service) needsRefreshLocked() bool {
	b, err := s.store.Get(storage.KeyAccessExpiresAt)
	if err != nil || len(b) == 0 {
		return false
	}
	ms, err := strconv.ParseInt(string(b), 10, 64)
	if err != nil || ms <= 0 {
		return false
	}
	return time.Until(time.UnixMilli(ms)) <= lead
}

func (s *Service) saveTokens(t apitypes.Tokens) error {
	if err := s.store.Set(storage.KeyAccessToken, []byte(t.AccessToken)); err != nil {
		return err
	}
	if err := s.store.Set(storage.KeyRefreshToken, []byte(t.RefreshToken)); err != nil {
		return err
	}
	if t.ExpiresIn > 0 {
		exp := time.Now().Add(time.Duration(t.ExpiresIn) * time.Second).UnixMilli()
		return s.store.Set(storage.KeyAccessExpiresAt, []byte(strconv.FormatInt(exp, 10)))
	}
	_ = s.store.Delete(storage.KeyAccessExpiresAt)
	return nil
}

func (s *Service) post(ctx context.Context, path string, body any, bearer string, dst any) error {
	var rdr io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(buf)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.api+path, rdr)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return apierr.FromBody(resp.StatusCode, raw)
	}
	if dst == nil || len(raw) == 0 {
		return nil
	}
	return json.Unmarshal(raw, dst)
}

func (s *Service) get(ctx context.Context, path, bearer string, dst any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.api+path, nil)
	if err != nil {
		return err
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return apierr.FromBody(resp.StatusCode, raw)
	}
	if dst == nil || len(raw) == 0 {
		return nil
	}
	return json.Unmarshal(raw, dst)
}
