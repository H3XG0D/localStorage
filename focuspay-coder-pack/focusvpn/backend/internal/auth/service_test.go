package auth

import (
	"context"
	"errors"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func newTestService(t *testing.T) *Service {
	t.Helper()
	st := memory.New()
	iss := newTestIssuer(t, 15*time.Minute)
	return NewService(st.Users(), st.Refresh(), iss, 24*time.Hour)
}

func TestRegisterLoginFlow(t *testing.T) {
	svc := newTestService(t)
	ctx := context.Background()

	u, toks, err := svc.Register(ctx, "user@example.com", "supersecret1")
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	if u.Role != "user" || u.Status != "active" {
		t.Fatalf("unexpected user: %+v", u)
	}
	if toks.Access == "" || toks.Refresh == "" {
		t.Fatal("expected tokens on register")
	}

	if _, _, err := svc.Register(ctx, "user@example.com", "supersecret1"); !errors.Is(err, ErrEmailExists) {
		t.Fatalf("expected ErrEmailExists, got %v", err)
	}

	if _, _, err := svc.Login(ctx, "user@example.com", "wrongpassword1"); !errors.Is(err, ErrInvalidCreds) {
		t.Fatalf("expected ErrInvalidCreds, got %v", err)
	}

	_, toks2, err := svc.Login(ctx, "user@example.com", "supersecret1")
	if err != nil {
		t.Fatalf("login: %v", err)
	}
	if toks2.Access == "" {
		t.Fatal("expected access token on login")
	}
}

func TestRegisterValidation(t *testing.T) {
	svc := newTestService(t)
	ctx := context.Background()
	if _, _, err := svc.Register(ctx, "bad-email", "supersecret1"); !errors.Is(err, ErrValidation) {
		t.Fatalf("expected validation error for email, got %v", err)
	}
	if _, _, err := svc.Register(ctx, "ok@example.com", "short"); !errors.Is(err, ErrValidation) {
		t.Fatalf("expected validation error for password, got %v", err)
	}
}

func TestRefreshRotationAndReuseDetection(t *testing.T) {
	svc := newTestService(t)
	ctx := context.Background()

	_, toks, err := svc.Register(ctx, "rot@example.com", "supersecret1")
	if err != nil {
		t.Fatalf("register: %v", err)
	}

	// First rotation succeeds and returns a new refresh token.
	rotated, err := svc.Refresh(ctx, toks.Refresh)
	if err != nil {
		t.Fatalf("refresh: %v", err)
	}
	if rotated.Refresh == toks.Refresh {
		t.Fatal("expected a rotated (different) refresh token")
	}

	// Reusing the original (now revoked) token must fail and revoke the family.
	if _, err := svc.Refresh(ctx, toks.Refresh); !errors.Is(err, ErrInvalidToken) {
		t.Fatalf("expected ErrInvalidToken on reuse, got %v", err)
	}

	// The rotated token must now also be revoked (whole family killed).
	if _, err := svc.Refresh(ctx, rotated.Refresh); !errors.Is(err, ErrInvalidToken) {
		t.Fatalf("expected family revocation to invalidate rotated token, got %v", err)
	}
}

func TestRefreshInvalidToken(t *testing.T) {
	svc := newTestService(t)
	if _, err := svc.Refresh(context.Background(), "does-not-exist"); !errors.Is(err, ErrInvalidToken) {
		t.Fatalf("expected ErrInvalidToken, got %v", err)
	}
}

func TestLogoutRevokesFamily(t *testing.T) {
	svc := newTestService(t)
	ctx := context.Background()
	_, toks, err := svc.Register(ctx, "out@example.com", "supersecret1")
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	if err := svc.Logout(ctx, toks.Refresh); err != nil {
		t.Fatalf("logout: %v", err)
	}
	if _, err := svc.Refresh(ctx, toks.Refresh); !errors.Is(err, ErrInvalidToken) {
		t.Fatalf("expected token invalid after logout, got %v", err)
	}
}
