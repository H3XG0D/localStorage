package server_test

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/config"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
	"focusvpn.example/focusvpn/backend/internal/server"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

func newTestServer(t *testing.T) *httptest.Server {
	t.Helper()
	ts, _ := newTestServerWithStore(t)
	return ts
}

// grantAccess gives a registered user a live subscription (no implicit free plan).
func grantAccess(t *testing.T, st *memory.Store, email string) {
	t.Helper()
	u, err := st.Users().GetUserByEmail(context.Background(), email)
	if err != nil {
		t.Fatalf("grantAccess %s: %v", email, err)
	}
	st.SeedPlan(store.Plan{ID: "plan-test", Code: "test", Name: "Test", MaxDevices: 1, PeriodDays: 30})
	st.SeedSubscription(store.Subscription{
		ID: "sub-" + u.ID, UserID: u.ID, PlanID: "plan-test", Status: "active",
		StartsAt: time.Now().Add(-time.Hour), EndsAt: time.Now().Add(24 * time.Hour),
	})
}

func newTestServerWithStore(t *testing.T) (*httptest.Server, *memory.Store) {
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
	cfg := config.Config{
		Store:                   "memory",
		AccessTTL:               15 * time.Minute,
		RefreshTTL:              24 * time.Hour,
		JWTPrivateKey:           priv,
		JWTPublicKey:            pub,
		TokenHMACKey:            []byte("test-hmac-key-at-least-32-bytes-long!!"),
		ConfigSigningPrivateKey: cfgPriv,
		ConfigSigningPublicKey:  cfgPriv.Public().(ed25519.PublicKey),
		KEKID:                   "kek-v1",
		KEKKey:                  kek,
		AllocationAutoActive:    true, // A1 stub for tests
		RateLimits: config.RateLimits{
			RegisterPerHourPerIP:     5,
			LoginPerMinutePerIP:      10,
			LoginPerMinutePerAcct:    5,
			GeneralPerMinutePerToken: 120,
		},
	}
	st := memory.New()
	// Seed free plan + multi-node HEALTHY AmneziaWG catalog (P4-M4).
	st.SeedPlan(store.Plan{ID: "plan-free", Code: "free", Name: "Free", MaxDevices: 1, PeriodDays: 36500})
	obfDE := []byte(`{"junk_packet_count":4,"junk_min_size":40,"junk_max_size":70,"init_packet_junk_size":15,"response_packet_junk_size":20,"cookie_reply_junk_size":10,"transport_packet_junk_size":5,"init_packet_magic_header":"100-110","response_packet_magic_header":"200-210","underload_packet_magic_header":"300-310","transport_packet_magic_header":"400-410","special_junk_i1":"<b 0xde01>"}`)
	obfNL := []byte(`{"junk_packet_count":5,"junk_min_size":50,"junk_max_size":80,"init_packet_junk_size":12,"response_packet_junk_size":18,"cookie_reply_junk_size":8,"transport_packet_junk_size":4,"init_packet_magic_header":"1000-1010","response_packet_magic_header":"1100-1110","underload_packet_magic_header":"1200-1210","transport_packet_magic_header":"1300-1310","special_junk_i1":"<b 0x4e4c01>"}`)
	obfUS := []byte(`{"junk_packet_count":3,"junk_min_size":30,"junk_max_size":60,"init_packet_junk_size":10,"response_packet_junk_size":16,"cookie_reply_junk_size":6,"transport_packet_junk_size":3,"init_packet_magic_header":"2000-2010","response_packet_magic_header":"2100-2110","underload_packet_magic_header":"2200-2210","transport_packet_magic_header":"2300-2310","special_junk_i1":"<b 0x555301>"}`)
	for _, e := range []store.Endpoint{
		{
			ID: "ep-1", NodeID: "n-1", NodeName: "DE-01", Country: "DE", Region: "eu-central",
			Hostname: "de-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
			PublicKey: bytes.Repeat([]byte{9}, 32), Obfuscation: obfDE, Subnet: "10.200.0.0/24", Load: 0.2,
		},
		{
			ID: "ep-2", NodeID: "n-2", NodeName: "NL-01", Country: "NL", Region: "eu-west",
			Hostname: "nl-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
			PublicKey: bytes.Repeat([]byte{8}, 32), Obfuscation: obfNL, Subnet: "10.201.0.0/24", Load: 0.4,
		},
		{
			ID: "ep-3", NodeID: "n-3", NodeName: "US-01", Country: "US", Region: "us-east",
			Hostname: "us-01.focusvpn.example", Protocol: "amneziawg", Port: 51820, State: "HEALTHY",
			PublicKey: bytes.Repeat([]byte{7}, 32), Obfuscation: obfUS, Subnet: "10.202.0.0/24", Load: 0.1,
		},
	} {
		st.SeedEndpoint(e)
	}
	result := server.New(server.Deps{Config: cfg, Store: st, Limiter: ratelimit.NewMemory()})
	return httptest.NewServer(result.Handler), st
}

func getJSON(t *testing.T, url, bearer string) (*http.Response, []byte) {
	t.Helper()
	return doReq(t, http.MethodGet, url, nil, bearer)
}

func deleteJSON(t *testing.T, url, bearer string) (*http.Response, []byte) {
	t.Helper()
	return doReq(t, http.MethodDelete, url, nil, bearer)
}

func doReq(t *testing.T, method, url string, body []byte, bearer string) (*http.Response, []byte) {
	t.Helper()
	var r *bytes.Reader
	if body != nil {
		r = bytes.NewReader(body)
	} else {
		r = bytes.NewReader(nil)
	}
	req, _ := http.NewRequest(method, url, r)
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer resp.Body.Close()
	out := new(bytes.Buffer)
	_, _ = out.ReadFrom(resp.Body)
	return resp, out.Bytes()
}

func postJSON(t *testing.T, url string, body any, bearer string) (*http.Response, []byte) {
	t.Helper()
	buf, _ := json.Marshal(body)
	req, _ := http.NewRequest(http.MethodPost, url, bytes.NewReader(buf))
	req.Header.Set("Content-Type", "application/json")
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer resp.Body.Close()
	out := new(bytes.Buffer)
	_, _ = out.ReadFrom(resp.Body)
	return resp, out.Bytes()
}

func TestHealthEndpoint(t *testing.T) {
	ts := newTestServer(t)
	defer ts.Close()
	resp, err := http.Get(ts.URL + "/v1/health")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if resp.Header.Get("X-Request-Id") == "" {
		t.Fatal("expected X-Request-Id header")
	}
}

func TestVerticalSliceAuthFlow(t *testing.T) {
	ts := newTestServer(t)
	defer ts.Close()

	// register
	resp, body := postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "slice@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register status = %d body=%s", resp.StatusCode, body)
	}
	var reg apitypes.AuthResponse
	if err := json.Unmarshal(body, &reg); err != nil {
		t.Fatalf("decode register: %v", err)
	}
	if reg.Tokens.AccessToken == "" || reg.Tokens.RefreshToken == "" {
		t.Fatal("expected tokens from register")
	}
	if reg.Tokens.ExpiresIn != 900 {
		t.Fatalf("expires_in = %d, want 900", reg.Tokens.ExpiresIn)
	}

	// login
	resp, body = postJSON(t, ts.URL+"/v1/auth/login",
		apitypes.LoginRequest{Email: "slice@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("login status = %d body=%s", resp.StatusCode, body)
	}
	var login apitypes.AuthResponse
	_ = json.Unmarshal(body, &login)

	// refresh (token in Authorization header)
	resp, body = postJSON(t, ts.URL+"/v1/auth/refresh", struct{}{}, login.Tokens.RefreshToken)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("refresh status = %d body=%s", resp.StatusCode, body)
	}
	var refreshed apitypes.RefreshResponse
	_ = json.Unmarshal(body, &refreshed)
	if refreshed.RefreshToken == "" || refreshed.RefreshToken == login.Tokens.RefreshToken {
		t.Fatal("expected a rotated refresh token")
	}

	// reuse old refresh -> 401
	resp, _ = postJSON(t, ts.URL+"/v1/auth/refresh", struct{}{}, login.Tokens.RefreshToken)
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("reuse status = %d, want 401", resp.StatusCode)
	}
}

func TestMeRequiresAuth(t *testing.T) {
	ts := newTestServer(t)
	defer ts.Close()
	if resp, _ := getJSON(t, ts.URL+"/v1/me", ""); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("GET /v1/me without token = %d, want 401", resp.StatusCode)
	}
	if resp, _ := getJSON(t, ts.URL+"/v1/me", "not-a-jwt"); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("GET /v1/me bad token = %d, want 401", resp.StatusCode)
	}
}

func TestMeAndDevicesFlow(t *testing.T) {
	ts, st := newTestServerWithStore(t)
	defer ts.Close()

	// register a user
	resp, body := postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "dev@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register = %d body=%s", resp.StatusCode, body)
	}
	var reg apitypes.AuthResponse
	_ = json.Unmarshal(body, &reg)
	access := reg.Tokens.AccessToken

	// GET /v1/me: authorized, no subscription yet
	resp, body = getJSON(t, ts.URL+"/v1/me", access)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("me = %d body=%s", resp.StatusCode, body)
	}
	var me apitypes.MeResponse
	_ = json.Unmarshal(body, &me)
	if me.User.ID != reg.User.ID || me.User.Email != "dev@example.com" {
		t.Fatalf("me.user mismatch: %+v", me.User)
	}
	if me.Subscription != nil {
		t.Fatalf("expected nil subscription, got %+v", me.Subscription)
	}
	// No secret material must leak through /me.
	if bytes.Contains(body, []byte("password")) || bytes.Contains(body, []byte("hash")) {
		t.Fatalf("me response leaked sensitive field: %s", body)
	}

	// POST /v1/devices: first device (no plan seeded => free fallback => limit 1)
	key1 := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, 32))
	resp, body = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Phone", Platform: "ios", PublicKey: key1}, access)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("create device = %d body=%s", resp.StatusCode, body)
	}
	var cd apitypes.CreateDeviceResponse
	_ = json.Unmarshal(body, &cd)
	if cd.DeviceToken == "" {
		t.Fatal("expected one-time device_token")
	}
	if bytes.Contains(body, []byte("public_key")) || bytes.Contains(body, []byte("device_token_hash")) {
		t.Fatalf("device create leaked secret: %s", body)
	}

	// invalid public key length => 403 forbidden
	badKey := base64.StdEncoding.EncodeToString([]byte("too-short"))
	if resp, _ = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "X", Platform: "ios", PublicKey: badKey}, access); resp.StatusCode != http.StatusForbidden {
		t.Fatalf("bad key = %d, want 403", resp.StatusCode)
	}

	// second device exceeds free limit (1) => 409 too_many_devices
	key2 := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{2}, 32))
	if resp, _ = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Tablet", Platform: "android", PublicKey: key2}, access); resp.StatusCode != http.StatusConflict {
		t.Fatalf("second device = %d, want 409", resp.StatusCode)
	}

	// grant a pro subscription (max_devices 5) and retry
	st.SeedPlan(store.Plan{ID: "plan-pro", Code: "pro", Name: "Pro", MaxDevices: 5, PeriodDays: 30})
	st.SeedSubscription(store.Subscription{
		ID: "sub-1", UserID: reg.User.ID, PlanID: "plan-pro", Status: "active",
		StartsAt: time.Now().Add(-time.Hour), EndsAt: time.Now().Add(24 * time.Hour),
	})
	if resp, body = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Tablet", Platform: "android", PublicKey: key2}, access); resp.StatusCode != http.StatusCreated {
		t.Fatalf("second device after pro = %d body=%s", resp.StatusCode, body)
	}

	// GET /v1/devices: two devices
	resp, body = getJSON(t, ts.URL+"/v1/devices", access)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("list = %d body=%s", resp.StatusCode, body)
	}
	var list apitypes.DeviceListResponse
	_ = json.Unmarshal(body, &list)
	if len(list.Devices) != 2 {
		t.Fatalf("device count = %d, want 2", len(list.Devices))
	}

	// GET /v1/me: subscription now populated with devices_used=2
	resp, body = getJSON(t, ts.URL+"/v1/me", access)
	_ = json.Unmarshal(body, &me)
	if me.Subscription == nil || me.Subscription.Plan != "pro" || me.Subscription.MaxDevices != 5 || me.Subscription.DevicesUsed != 2 {
		t.Fatalf("me.subscription mismatch: %s", body)
	}

	// DELETE a device (owner) => 204, then it is revoked
	resp, _ = deleteJSON(t, ts.URL+"/v1/devices/"+list.Devices[0].ID, access)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("delete = %d, want 204", resp.StatusCode)
	}
	// deleting a non-existent device => 404
	if resp, _ = deleteJSON(t, ts.URL+"/v1/devices/nonexistent", access); resp.StatusCode != http.StatusNotFound {
		t.Fatalf("delete missing = %d, want 404", resp.StatusCode)
	}
}

func TestDuplicateRegisterConflict(t *testing.T) {
	ts := newTestServer(t)
	defer ts.Close()
	body := apitypes.RegisterRequest{Email: "dup@example.com", Password: "supersecret1"}
	if resp, _ := postJSON(t, ts.URL+"/v1/auth/register", body, ""); resp.StatusCode != http.StatusCreated {
		t.Fatalf("first register status = %d", resp.StatusCode)
	}
	resp, _ := postJSON(t, ts.URL+"/v1/auth/register", body, "")
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("duplicate register status = %d, want 409", resp.StatusCode)
	}
}

func TestM3ServersConnectionsConfigFlow(t *testing.T) {
	ts, st := newTestServerWithStore(t)
	defer ts.Close()

	resp, body := postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "m3@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register = %d %s", resp.StatusCode, body)
	}
	grantAccess(t, st, "m3@example.com")
	var reg apitypes.AuthResponse
	_ = json.Unmarshal(body, &reg)
	access := reg.Tokens.AccessToken

	resp, body = getJSON(t, ts.URL+"/v1/servers", access)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("servers = %d %s", resp.StatusCode, body)
	}
	var servers apitypes.ServersResponse
	_ = json.Unmarshal(body, &servers)
	if len(servers.Endpoints) < 3 {
		t.Fatalf("servers want >=3 nodes: %s", body)
	}
	nodes := map[string]bool{}
	for _, e := range servers.Endpoints {
		nodes[e.Node] = true
		if e.Score <= 0 {
			t.Fatalf("expected scored endpoint: %+v", e)
		}
		if e.Node == "DE-01" && (e.Host != "de-01.focusvpn.example" || e.Port != 51820) {
			t.Fatalf("DE-01 host/port = %s:%d", e.Host, e.Port)
		}
	}
	for _, want := range []string{"DE-01", "NL-01", "US-01"} {
		if !nodes[want] {
			t.Fatalf("missing node %s in %s", want, body)
		}
	}

	key := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{3}, 32))
	resp, body = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Lap", Platform: "linux", PublicKey: key}, access)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("device = %d %s", resp.StatusCode, body)
	}
	var cd apitypes.CreateDeviceResponse
	_ = json.Unmarshal(body, &cd)

	resp, body = postJSON(t, ts.URL+"/v1/connections",
		apitypes.CreateConnectionRequest{DeviceID: cd.Device.ID, Protocol: "amneziawg", PreferredNode: "NL-01"}, access)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("connect = %d %s", resp.StatusCode, body)
	}
	var conn apitypes.CreateConnectionResponse
	_ = json.Unmarshal(body, &conn)
	if conn.Connection.Status != "active" || conn.ConfigID == "" {
		t.Fatalf("connect body: %s", body)
	}
	if len(conn.Candidates) < 2 {
		t.Fatalf("want multi-candidate failover list: %s", body)
	}
	if conn.Candidates[0].Endpoint.Host != "nl-01.focusvpn.example" {
		t.Fatalf("preferred NL-01 should rank first: %s", body)
	}

	// config fetch requires device token
	if resp, _ = getJSON(t, ts.URL+"/v1/configurations/"+conn.ConfigID, access); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("config with JWT = %d, want 401", resp.StatusCode)
	}
	req, _ := http.NewRequest(http.MethodGet, ts.URL+"/v1/configurations/"+conn.ConfigID, nil)
	req.Header.Set("X-Device-Token", cd.DeviceToken)
	r, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Body.Close()
	out := new(bytes.Buffer)
	_, _ = out.ReadFrom(r.Body)
	if r.StatusCode != http.StatusOK {
		t.Fatalf("config = %d %s", r.StatusCode, out.Bytes())
	}
	var cfg apitypes.ConfigPartsResponse
	_ = json.Unmarshal(out.Bytes(), &cfg)
	if cfg.ConfigVersion != 1 || cfg.Signature == "" || cfg.Parts["protocol"] == nil {
		t.Fatalf("config parts: %s", out.Bytes())
	}

	resp, _ = deleteJSON(t, ts.URL+"/v1/connections/"+conn.Connection.ID, access)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("delete = %d", resp.StatusCode)
	}
	req2, _ := http.NewRequest(http.MethodGet, ts.URL+"/v1/configurations/"+conn.ConfigID, nil)
	req2.Header.Set("X-Device-Token", cd.DeviceToken)
	r2, err2 := http.DefaultClient.Do(req2)
	if err2 != nil {
		t.Fatalf("config after revoke: %v", err2)
	}
	defer r2.Body.Close()
	if r2.StatusCode != http.StatusGone {
		t.Fatalf("after revoke config = %d, want 410", r2.StatusCode)
	}
}

func TestRotateKey(t *testing.T) {
	ts, st := newTestServerWithStore(t)
	defer ts.Close()

	resp, body := postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "rotate@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register = %d %s", resp.StatusCode, body)
	}
	grantAccess(t, st, "rotate@example.com")
	var reg apitypes.AuthResponse
	_ = json.Unmarshal(body, &reg)
	access := reg.Tokens.AccessToken

	key1 := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{11}, 32))
	resp, body = postJSON(t, ts.URL+"/v1/devices",
		apitypes.CreateDeviceRequest{Name: "Phone", Platform: "android", PublicKey: key1}, access)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("device = %d %s", resp.StatusCode, body)
	}
	var cd apitypes.CreateDeviceResponse
	_ = json.Unmarshal(body, &cd)

	resp, body = postJSON(t, ts.URL+"/v1/connections",
		apitypes.CreateConnectionRequest{DeviceID: cd.Device.ID, Protocol: "amneziawg"}, access)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("connect = %d %s", resp.StatusCode, body)
	}
	var conn apitypes.CreateConnectionResponse
	_ = json.Unmarshal(body, &conn)
	oldConfigID := conn.ConfigID

	key2 := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{12}, 32))
	buf, _ := json.Marshal(apitypes.RotateKeyRequest{PublicKey: key2})
	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/v1/devices/"+cd.Device.ID+"/rotate-key", bytes.NewReader(buf))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+access)
	req.Header.Set("X-Device-Token", cd.DeviceToken)
	r, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Body.Close()
	out := new(bytes.Buffer)
	_, _ = out.ReadFrom(r.Body)
	if r.StatusCode != http.StatusOK {
		t.Fatalf("rotate-key = %d %s", r.StatusCode, out.Bytes())
	}
	var rk apitypes.RotateKeyResponse
	_ = json.Unmarshal(out.Bytes(), &rk)
	if !rk.ConfigVersionBump || rk.Device.ID != cd.Device.ID {
		t.Fatalf("rotate body: %s", out.Bytes())
	}

	dev, err := st.GetDeviceByID(t.Context(), cd.Device.ID)
	if err != nil {
		t.Fatal(err)
	}
	wantKey, _ := base64.StdEncoding.DecodeString(key2)
	if !bytes.Equal(dev.PublicKey, wantKey) {
		t.Fatalf("device pubkey not updated")
	}
	alloc, err := st.GetLiveByDevice(t.Context(), cd.Device.ID)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(alloc.PeerPublicKey, wantKey) {
		t.Fatalf("allocation peer pubkey not updated")
	}
	cfg, err := st.GetActiveByAllocation(t.Context(), alloc.ID)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Version != 2 || cfg.ID == oldConfigID {
		t.Fatalf("expected version 2 new config, got v=%d id=%s old=%s", cfg.Version, cfg.ID, oldConfigID)
	}

	req2, _ := http.NewRequest(http.MethodGet, ts.URL+"/v1/configurations/"+oldConfigID, nil)
	req2.Header.Set("X-Device-Token", cd.DeviceToken)
	r2, err2 := http.DefaultClient.Do(req2)
	if err2 != nil {
		t.Fatal(err2)
	}
	defer r2.Body.Close()
	if r2.StatusCode != http.StatusGone {
		t.Fatalf("old config = %d, want 410", r2.StatusCode)
	}

	// missing device token → 401
	if resp, _ = postJSON(t, ts.URL+"/v1/devices/"+cd.Device.ID+"/rotate-key",
		apitypes.RotateKeyRequest{PublicKey: key2}, access); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("rotate without device token = %d, want 401", resp.StatusCode)
	}
}

func TestNoSubscriptionIsPaymentRequired(t *testing.T) {
	ts := newTestServer(t)
	defer ts.Close()
	resp, body := postJSON(t, ts.URL+"/v1/auth/register",
		apitypes.RegisterRequest{Email: "nosub@example.com", Password: "supersecret1"}, "")
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("register = %d %s", resp.StatusCode, body)
	}
	var reg apitypes.AuthResponse
	_ = json.Unmarshal(body, &reg)
	if resp, body = getJSON(t, ts.URL+"/v1/servers", reg.Tokens.AccessToken); resp.StatusCode != http.StatusPaymentRequired {
		t.Fatalf("servers without subscription = %d %s, want 402", resp.StatusCode, body)
	}
}
