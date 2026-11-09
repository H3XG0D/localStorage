package sublink_test

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/connections"
	"focusvpn.example/focusvpn/backend/internal/devices"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/ratelimit"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
	"focusvpn.example/focusvpn/backend/internal/sublink"
)

type fixture struct {
	st     *memory.Store
	mux    *http.ServeMux
	userID string
	sub    store.Subscription
}

func newFixture(t *testing.T, occupySeat bool) fixture {
	t.Helper()
	st := memory.New()
	for _, ep := range []store.Endpoint{
		{ID: "ep-de1", NodeID: "n-de1", NodeName: "DE1", Country: "DE", Hostname: "de1.example", Protocol: "vless-ws",
			Port: 443, State: "HEALTHY", Subnet: "10.210.0.0/24", Load: 0.7, Capacity: 100,
			Xray: json.RawMessage(`{"transport":"xhttp","path":"/cdn/de1","mode":"auto"}`)},
		{ID: "ep-de2", NodeID: "n-de2", NodeName: "DE2", Country: "DE", Hostname: "de2.example", Protocol: "vless-ws",
			Port: 443, State: "HEALTHY", Subnet: "10.211.0.0/24", Load: 0.1, Capacity: 100,
			Xray: json.RawMessage(`{"transport":"ws","path":"/api/de2","alt":{"transport":"xhttp","path":"/cdn/de2","mode":"auto"}}`)},
		{ID: "ep-nl1", NodeID: "n-nl1", NodeName: "NL1", Country: "NL", Hostname: "nl1.example", Protocol: "vless-ws",
			Port: 443, State: "HEALTHY", Subnet: "10.212.0.0/24", Load: 0.4, Capacity: 100,
			Xray: json.RawMessage(`{"transport":"ws","path":"/api/nl1"}`)},
	} {
		st.SeedEndpoint(ep)
		_ = st.EnsureStateVersion(context.Background(), ep.NodeID)
	}
	st.SeedPlan(store.Plan{ID: "p-week", Code: "week", Name: "Week", MaxDevices: 1, PeriodDays: 7})
	userID := id.NewUUID()
	tg := int64(42)
	now := time.Now().UTC()
	if err := st.CreateUser(context.Background(), store.User{
		ID: userID, Email: userID + "@example.com", Role: "user", Status: "active",
		TelegramID: &tg, CreatedAt: now, UpdatedAt: now,
	}); err != nil {
		t.Fatal(err)
	}
	sub := store.Subscription{ID: id.NewUUID(), UserID: userID, PlanID: "p-week", Status: "active",
		StartsAt: now, EndsAt: now.Add(7 * 24 * time.Hour)}
	st.SeedSubscription(sub)
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	kek := mycrypto.KEK{ID: "kek-v1", Key: key}
	st.UseKEK(kek)
	_, cfgPriv, _ := ed25519.GenerateKey(rand.Reader)
	_, jwtPriv, _ := ed25519.GenerateKey(rand.Reader)
	issuer := auth.NewTokenIssuer(jwtPriv, jwtPriv.Public().(ed25519.PublicKey), key, time.Minute)
	connSvc := connections.NewService(st.Devices(), st.Endpoints(), st.Allocations(), st.Configurations(),
		st.Subscriptions(), st.NodeState(), kek, mycrypto.NewConfigSigner(cfgPriv), true, nil)
	deviceSvc := devices.NewService(st.Devices(), st.Subscriptions(), issuer)
	deviceSvc.SetRotation(st.Allocations(), st.Configurations(), connSvc)
	if occupySeat {
		pub := make([]byte, 32)
		_, _ = rand.Read(pub)
		if _, _, err := deviceSvc.Create(context.Background(), userID, "Pixel", "android", "", base64.StdEncoding.EncodeToString(pub)); err != nil {
			t.Fatal(err)
		}
	}
	svc := sublink.NewService(st.SubLinks(), st.Users(), st.Subscriptions(), st.Devices(),
		deviceSvc, connSvc, kek, issuer.HashRefresh, "https://focuspay.org/vpn-api/", "focusvpn1_bot")
	mux := http.NewServeMux()
	sublink.NewHandler(svc, ratelimit.NewMemory(), "secret").Routes(mux)
	return fixture{st: st, mux: mux, userID: userID, sub: sub}
}

func (f fixture) post(t *testing.T, rotate bool, token string) *httptest.ResponseRecorder {
	t.Helper()
	body := `{"telegram_id":42,"rotate":false}`
	if rotate {
		body = `{"telegram_id":42,"rotate":true}`
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/internal/telegram/sub-link", strings.NewReader(body))
	if token != "" {
		req.Header.Set("X-Internal-Token", token)
	}
	rec := httptest.NewRecorder()
	f.mux.ServeHTTP(rec, req)
	return rec
}

func issuedURL(t *testing.T, rec *httptest.ResponseRecorder) string {
	t.Helper()
	if rec.Code != http.StatusOK {
		t.Fatalf("issue %d %s", rec.Code, rec.Body.String())
	}
	var out struct {
		URL string `json:"url"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	return out.URL
}

func fetchLines(t *testing.T, mux *http.ServeMux, rawURL string) (lines []string, hdr http.Header) {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, cpPath(t, rawURL), nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("fetch %d %s", rec.Code, rec.Body.String())
	}
	plain, err := base64.StdEncoding.DecodeString(strings.TrimSpace(rec.Body.String()))
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range strings.Split(strings.TrimSpace(string(plain)), "\n") {
		if line != "" {
			lines = append(lines, line)
		}
	}
	return lines, rec.Header()
}

func remark(t *testing.T, line string) string {
	t.Helper()
	i := strings.LastIndex(line, "#")
	if i < 0 {
		t.Fatalf("no remark: %s", line)
	}
	name, err := url.PathUnescape(line[i+1:])
	if err != nil {
		t.Fatal(err)
	}
	return name
}

func uuidOf(t *testing.T, line string) string {
	t.Helper()
	rest := strings.TrimPrefix(line, "vless://")
	at := strings.Index(rest, "@")
	if at < 0 {
		t.Fatalf("no uuid: %s", line)
	}
	return rest[:at]
}

func TestSubscriptionLinkIsStableAndListsNodes(t *testing.T) {
	f := newFixture(t, false)
	first := issuedURL(t, f.post(t, false, "secret"))
	second := issuedURL(t, f.post(t, false, "secret"))
	if first != second {
		t.Fatalf("second issue changed the url:\n%s\n%s", first, second)
	}
	if !strings.HasPrefix(first, "https://focuspay.org/vpn-api/v1/sub/") {
		t.Fatal(first)
	}
	lines, hdr := fetchLines(t, f.mux, first)
	if len(lines) != 2 {
		t.Fatalf("want 2 websocket lines, got %d: %v", len(lines), lines)
	}
	for _, ln := range lines {
		if strings.Contains(ln, "type=xhttp") {
			t.Fatalf("xhttp row leaked: %s", ln)
		}
	}
	if !strings.Contains(lines[0], "de2.example:443") || !strings.Contains(lines[0], "type=ws") || !strings.Contains(lines[0], "path=%2Fapi%2Fde2") {
		t.Fatalf("primary: %s", lines[0])
	}
	if remark(t, lines[0]) != "Германия · DE2" {
		t.Fatalf("primary name: %s", remark(t, lines[0]))
	}
	if remark(t, lines[1]) != "Нидерланды · NL1" || !strings.Contains(lines[1], "type=ws") {
		t.Fatalf("nl: %s", lines[1])
	}
	if hdr.Get("profile-title") != "base64:Rm9jdXNWUE4=" {
		t.Fatalf("title: %s", hdr.Get("profile-title"))
	}
	if hdr.Get("profile-update-interval") != "1" {
		t.Fatal(hdr.Get("profile-update-interval"))
	}
	if hdr.Get("support-url") != "https://t.me/focusvpn1_bot" {
		t.Fatal(hdr.Get("support-url"))
	}
	if !strings.Contains(hdr.Get("subscription-userinfo"), "expire="+strconv.FormatInt(f.sub.EndsAt.Unix(), 10)) {
		t.Fatalf("userinfo %s want expire %d", hdr.Get("subscription-userinfo"), f.sub.EndsAt.Unix())
	}
	if hdr.Get("Cache-Control") != "private, no-store" {
		t.Fatal(hdr.Get("Cache-Control"))
	}
	again, _ := fetchLines(t, f.mux, first)
	if uuidOf(t, again[0]) != uuidOf(t, lines[0]) {
		t.Fatal("refresh changed the uuid")
	}
}

func TestRotateKillsTheOldLink(t *testing.T) {
	f := newFixture(t, false)
	oldURL := issuedURL(t, f.post(t, false, "secret"))
	oldLines, _ := fetchLines(t, f.mux, oldURL)
	newURL := issuedURL(t, f.post(t, true, "secret"))
	if newURL == oldURL {
		t.Fatal("rotate kept the url")
	}
	oldReq := httptest.NewRequest(http.MethodGet, mustPath(t, oldURL), nil)
	oldRec := httptest.NewRecorder()
	f.mux.ServeHTTP(oldRec, oldReq)
	if oldRec.Code != http.StatusNotFound {
		t.Fatalf("old link %d %s", oldRec.Code, oldRec.Body.String())
	}
	newLines, _ := fetchLines(t, f.mux, newURL)
	if uuidOf(t, newLines[0]) == uuidOf(t, oldLines[0]) {
		t.Fatal("rotate kept the vless uuid")
	}
}

func TestLinkNeedsAFreeSeatAndASubscription(t *testing.T) {
	full := newFixture(t, true)
	rec := full.post(t, false, "secret")
	if rec.Code != http.StatusConflict || !strings.Contains(rec.Body.String(), "too_many_devices") {
		t.Fatalf("occupied seat: %d %s", rec.Code, rec.Body.String())
	}

	bare := newFixture(t, false)
	expired := bare.sub
	expired.EndsAt = time.Now().Add(-time.Minute)
	bare.st.SeedSubscription(expired)
	rec = bare.post(t, false, "secret")
	if rec.Code != http.StatusPaymentRequired || !strings.Contains(rec.Body.String(), "no_subscription") {
		t.Fatalf("expired issue: %d %s", rec.Code, rec.Body.String())
	}

	live := newFixture(t, false)
	raw := issuedURL(t, live.post(t, false, "secret"))
	expired = live.sub
	expired.EndsAt = time.Now().Add(-time.Minute)
	live.st.SeedSubscription(expired)
	req := httptest.NewRequest(http.MethodGet, mustPath(t, raw), nil)
	got := httptest.NewRecorder()
	live.mux.ServeHTTP(got, req)
	if got.Code != http.StatusPaymentRequired {
		t.Fatalf("expired fetch: %d %s", got.Code, got.Body.String())
	}

	noTok := live.post(t, false, "")
	if noTok.Code != http.StatusUnauthorized {
		t.Fatalf("missing token: %d", noTok.Code)
	}
	unknown := httptest.NewRequest(http.MethodGet, "/v1/sub/not-a-key", nil)
	unk := httptest.NewRecorder()
	live.mux.ServeHTTP(unk, unknown)
	if unk.Code != http.StatusNotFound {
		t.Fatalf("unknown token: %d", unk.Code)
	}
}

func cpPath(t *testing.T, raw string) string {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return strings.TrimPrefix(u.Path, "/vpn-api")
}

func mustPath(t *testing.T, raw string) string {
	t.Helper()
	return cpPath(t, raw)
}
