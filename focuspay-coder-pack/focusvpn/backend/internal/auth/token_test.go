package auth

import (
	"crypto/ed25519"
	"crypto/rand"
	"testing"
	"time"
)

func newTestIssuer(t *testing.T, ttl time.Duration) *TokenIssuer {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	return NewTokenIssuer(priv, pub, []byte("test-hmac-key-at-least-32-bytes-long!!"), ttl)
}

func TestIssueAndParseAccessEdDSA(t *testing.T) {
	iss := newTestIssuer(t, 15*time.Minute)
	tok, err := iss.IssueAccess("user-123", "user")
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	claims, err := iss.ParseAccess(tok)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if claims.Subject != "user-123" {
		t.Fatalf("sub = %q, want user-123", claims.Subject)
	}
	if claims.Role != "user" {
		t.Fatalf("role = %q, want user", claims.Role)
	}
	if claims.ID == "" {
		t.Fatal("expected non-empty jti")
	}
}

func TestParseAccessRejectsExpired(t *testing.T) {
	iss := newTestIssuer(t, -time.Minute) // already expired
	tok, err := iss.IssueAccess("u", "user")
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	if _, err := iss.ParseAccess(tok); err == nil {
		t.Fatal("expected expired token to be rejected")
	}
}

func TestParseAccessRejectsWrongKey(t *testing.T) {
	iss1 := newTestIssuer(t, time.Minute)
	iss2 := newTestIssuer(t, time.Minute)
	tok, _ := iss1.IssueAccess("u", "user")
	if _, err := iss2.ParseAccess(tok); err == nil {
		t.Fatal("expected token signed by other key to be rejected")
	}
}

func TestHashRefreshDeterministicAndKeyed(t *testing.T) {
	iss := newTestIssuer(t, time.Minute)
	h1 := iss.HashRefresh("token-abc")
	h2 := iss.HashRefresh("token-abc")
	if h1 != h2 {
		t.Fatal("hash should be deterministic for same input")
	}
	if h1 == "token-abc" {
		t.Fatal("hash must not equal plaintext")
	}
}
