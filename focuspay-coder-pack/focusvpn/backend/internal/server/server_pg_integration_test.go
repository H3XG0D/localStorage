package server_test

// Integration tests against a real PostgreSQL instance. They are skipped unless
// FOCUSVPN_TEST_DATABASE_URL is set, so `go test ./...` stays green offline. Bring
// up the dev stack and point the URL at a disposable database, e.g.:
//
//	make dev-up
//	createdb: see docs/DATABASE.md "Local dev (Podman)"
//	FOCUSVPN_TEST_DATABASE_URL=postgres://focusvpn:focusvpn@localhost:5432/focusvpn_test?sslmode=disable go test ./backend/...
//
// These tests exercise DB-specific behavior (unique constraints, transactions,
// persistence across restart) against the real driver — not mocks.

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"focusvpn.example/focusvpn/backend/internal/platform/config"
	"focusvpn.example/focusvpn/backend/internal/platform/migrate"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/postgres"
	"focusvpn.example/focusvpn/backend/internal/server"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

func pgURL(t *testing.T) string {
	t.Helper()
	url := os.Getenv("FOCUSVPN_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("FOCUSVPN_TEST_DATABASE_URL not set; skipping PostgreSQL integration test")
	}
	return url
}

// freshPG migrates the schema and truncates all tables, returning a connected store.
func freshPG(t *testing.T, url string) *postgres.Store {
	t.Helper()
	if err := migrate.Up(url); err != nil {
		t.Fatalf("migrate up: %v", err)
	}
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	_, err = conn.Exec(ctx,
		`TRUNCATE refresh_tokens, vpn_configurations, vpn_allocations, devices, vpn_endpoints, vpn_nodes, subscriptions, plans, users RESTART IDENTITY CASCADE`)
	_ = conn.Close(ctx)
	if err != nil {
		t.Fatalf("truncate: %v", err)
	}
	st, err := postgres.New(ctx, url)
	if err != nil {
		t.Fatalf("store: %v", err)
	}
	return st
}

func execPG(t *testing.T, url, sql string, args ...any) {
	t.Helper()
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, sql, args...); err != nil {
		t.Fatalf("exec %q: %v", sql, err)
	}
}

func pgConfig(t *testing.T) config.Config {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	_, cfgPriv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("config keygen: %v", err)
	}
	kek := make([]byte, 32)
	_, _ = rand.Read(kek)
	return config.Config{
		Store:                   "postgres",
		AccessTTL:               15 * time.Minute,
		RefreshTTL:              24 * time.Hour,
		JWTPrivateKey:           priv,
		JWTPublicKey:            pub,
		TokenHMACKey:            []byte("test-hmac-key-at-least-32-bytes-long!!"),
		ConfigSigningPrivateKey: cfgPriv,
		ConfigSigningPublicKey:  cfgPriv.Public().(ed25519.PublicKey),
		KEKID:                   "kek-v1",
		KEKKey:                  kek,
		AllocationAutoActive:    true,
		RateLimits: config.RateLimits{
			RegisterPerHourPerIP:     100,
			LoginPerMinutePerIP:      100,
			LoginPerMinutePerAcct:    100,
			GeneralPerMinutePerToken: 1000,
		},
	}
}

func newServerWith(t *testing.T, cfg config.Config, st store.Store) *httptest.Server {
	t.Helper()
	result := server.New(server.Deps{Config: cfg, Store: st, Limiter: ratelimit.NewMemory()})
	return httptest.NewServer(result.Handler)
}

func TestPostgresVerticalSlice(t *testing.T) {
	url := pgURL(t)
	st := freshPG(t, url)
	defer st.Close()
	ts := newServerWith(t, pgConfig(t), st)
	defer ts.Close()

	// register
	resp, body := postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "pg@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register = %d body=%s", resp.StatusCode, body)
	}
	var reg apitypes.AuthResponse
	_ = json.Unmarshal(body, &reg)

	// duplicate registration -> 409 (unique email constraint)
	if resp, _ = postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "pg@example.com", Password: "supersecret1"}, ""); resp.StatusCode != http.StatusConflict {
		t.Fatalf("duplicate register = %d, want 409", resp.StatusCode)
	}

	// login
	resp, body = postJSON(t, ts.URL+"/v1/auth/login",
		apitypes.LoginRequest{Email: "pg@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("login = %d body=%s", resp.StatusCode, body)
	}
	var login apitypes.AuthResponse
	_ = json.Unmarshal(body, &login)

	// refresh rotates
	resp, body = postJSON(t, ts.URL+"/v1/auth/refresh", struct{}{}, login.Tokens.RefreshToken)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("refresh = %d body=%s", resp.StatusCode, body)
	}
	var refreshed apitypes.RefreshResponse
	_ = json.Unmarshal(body, &refreshed)

	// reuse of the old refresh token -> 401 and family revoked
	if resp, _ = postJSON(t, ts.URL+"/v1/auth/refresh", struct{}{}, login.Tokens.RefreshToken); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("reuse = %d, want 401", resp.StatusCode)
	}
	// the rotated (now family-revoked) token is also rejected
	if resp, _ = postJSON(t, ts.URL+"/v1/auth/refresh", struct{}{}, refreshed.RefreshToken); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("post-reuse rotated token = %d, want 401", resp.StatusCode)
	}

	// GET /v1/me (authorized, no subscription yet)
	resp, body = getJSON(t, ts.URL+"/v1/me", login.Tokens.AccessToken)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("me = %d body=%s", resp.StatusCode, body)
	}
	var me apitypes.MeResponse
	_ = json.Unmarshal(body, &me)
	if me.User.Email != "pg@example.com" || me.Subscription != nil {
		t.Fatalf("unexpected /me: %s", body)
	}

	// seed a free plan (limit 1) so device creation has a plan basis
	execPG(t, url, `INSERT INTO plans (id, code, name, max_devices, period_days)
	                VALUES ('11111111-1111-1111-1111-111111111111','free','Free',1,36500)`)

	key1 := base64.StdEncoding.EncodeToString(bytesRepeat(1, 32))
	if resp, body = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Laptop", Platform: "linux", PublicKey: key1}, login.Tokens.AccessToken); resp.StatusCode != http.StatusCreated {
		t.Fatalf("device create = %d body=%s", resp.StatusCode, body)
	}
	// second device exceeds free limit -> 409
	key2 := base64.StdEncoding.EncodeToString(bytesRepeat(2, 32))
	if resp, _ = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Phone", Platform: "android", PublicKey: key2}, login.Tokens.AccessToken); resp.StatusCode != http.StatusConflict {
		t.Fatalf("device over limit = %d, want 409", resp.StatusCode)
	}
	// duplicate active public key -> 409 (partial unique index)
	if resp, _ = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Dup", Platform: "linux", PublicKey: key1}, login.Tokens.AccessToken); resp.StatusCode != http.StatusConflict {
		t.Fatalf("duplicate key = %d, want 409", resp.StatusCode)
	}

	// grant a pro subscription and confirm /me reflects it
	execPG(t, url, `INSERT INTO plans (id, code, name, max_devices, period_days)
	                VALUES ('22222222-2222-2222-2222-222222222222','pro','Pro',5,30)`)
	execPG(t, url, `INSERT INTO subscriptions (id, user_id, plan_id, status, starts_at, ends_at)
	                VALUES ('33333333-3333-3333-3333-333333333333',$1,'22222222-2222-2222-2222-222222222222','active', now() - interval '1 hour', now() + interval '30 days')`, reg.User.ID)

	resp, body = getJSON(t, ts.URL+"/v1/me", login.Tokens.AccessToken)
	_ = json.Unmarshal(body, &me)
	if me.Subscription == nil || me.Subscription.Plan != "pro" || me.Subscription.MaxDevices != 5 || me.Subscription.DevicesUsed != 1 {
		t.Fatalf("me.subscription mismatch: %s", body)
	}

	// logout revokes the family; the current refresh token no longer works
	if resp, _ = postJSON(t, ts.URL+"/v1/auth/logout",
		apitypes.LogoutRequest{RefreshToken: login.Tokens.RefreshToken}, login.Tokens.AccessToken); resp.StatusCode != http.StatusNoContent {
		t.Fatalf("logout = %d, want 204", resp.StatusCode)
	}
}

func TestPostgresPersistenceAcrossRestart(t *testing.T) {
	url := pgURL(t)
	st1 := freshPG(t, url)
	cfg := pgConfig(t) // fixed keys reused by both "restarts"

	ts1 := newServerWith(t, cfg, st1)
	resp, body := postJSON(t, ts1.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "persist@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register = %d body=%s", resp.StatusCode, body)
	}
	var reg apitypes.AuthResponse
	_ = json.Unmarshal(body, &reg)

	execPG(t, url, `INSERT INTO plans (id, code, name, max_devices, period_days)
	                VALUES ('11111111-1111-1111-1111-111111111111','free','Free',1,36500)`)
	key := base64.StdEncoding.EncodeToString(bytesRepeat(7, 32))
	if resp, body = postJSON(t, ts1.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Desktop", Platform: "linux", PublicKey: key}, reg.Tokens.AccessToken); resp.StatusCode != http.StatusCreated {
		t.Fatalf("device create = %d body=%s", resp.StatusCode, body)
	}

	// "restart": close the store/server and reconnect a fresh store + server.
	ts1.Close()
	_ = st1.Close()

	st2 := mustConnect(t, url)
	defer st2.Close()
	ts2 := newServerWith(t, cfg, st2)
	defer ts2.Close()

	// user persisted: login succeeds
	resp, body = postJSON(t, ts2.URL+"/v1/auth/login",
		apitypes.LoginRequest{Email: "persist@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("post-restart login = %d body=%s", resp.StatusCode, body)
	}
	var login apitypes.AuthResponse
	_ = json.Unmarshal(body, &login)

	// device persisted: list returns it
	resp, body = getJSON(t, ts2.URL+"/v1/devices", login.Tokens.AccessToken)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("post-restart list = %d body=%s", resp.StatusCode, body)
	}
	var list apitypes.DeviceListResponse
	_ = json.Unmarshal(body, &list)
	if len(list.Devices) != 1 || list.Devices[0].Name != "Desktop" {
		t.Fatalf("expected persisted device, got: %s", body)
	}
}

func mustConnect(t *testing.T, url string) *postgres.Store {
	t.Helper()
	st, err := postgres.New(context.Background(), url)
	if err != nil {
		t.Fatalf("reconnect: %v", err)
	}
	return st
}

func bytesRepeat(b byte, n int) []byte {
	out := make([]byte, n)
	for i := range out {
		out[i] = b
	}
	return out
}
