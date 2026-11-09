package applogin_test

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"strings"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/applogin"
	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/billing"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func testStack(t *testing.T) *applogin.Service {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	issuer := auth.NewTokenIssuer(priv, pub, []byte("test-hmac-key-at-least-32-bytes-long!!"), time.Minute)
	st := memory.New()
	st.SeedSmokeCatalog()
	authSvc := auth.NewService(st, st, issuer, 24*time.Hour)
	bill := billing.New(st, st)
	return applogin.NewService(st, st, bill, authSvc, issuer.HashRefresh, "TestBot", 5*time.Minute)
}

func TestDeepLinkLogin(t *testing.T) {
	svc := testStack(t)
	ctx := context.Background()
	start, err := svc.Start(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(start.DeepLink, "vpnauth_") {
		t.Fatalf("deep link: %s", start.DeepLink)
	}
	_, _, err = svc.Wait(ctx, start.WaitToken)
	if err != applogin.ErrNotReady {
		t.Fatalf("wait: %v", err)
	}
	raw := strings.TrimPrefix(start.DeepLink[strings.LastIndex(start.DeepLink, "vpnauth_"):], "vpnauth_")
	if err := svc.AttachLogin(ctx, "vpnauth_"+raw, 4242); err != nil {
		t.Fatal(err)
	}
	u, toks, err := svc.Wait(ctx, start.WaitToken)
	if err != nil {
		t.Fatal(err)
	}
	if u.ID == "" || toks.Access == "" {
		t.Fatal("expected tokens")
	}
}

func TestPairCodeLogin(t *testing.T) {
	svc := testStack(t)
	ctx := context.Background()
	code, err := svc.IssuePairCode(ctx, 777)
	if err != nil {
		t.Fatal(err)
	}
	u, toks, err := svc.RedeemCode(ctx, code)
	if err != nil {
		t.Fatal(err)
	}
	if u.Email == "" || toks.Refresh == "" {
		t.Fatal("expected auth bundle")
	}
}
