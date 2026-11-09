package client

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"focusvpn.example/focusvpn/clients/appcore/engine"
	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

func TestXrayConnectWritesTunJSON(t *testing.T) {
	var protocol string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/connections" && r.Method == http.MethodPost:
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			protocol = body["protocol"]
			_ = json.NewEncoder(w).Encode(apitypes.CreateConnectionResponse{
				Connection: apitypes.ConnectionDTO{ID: "c1", Status: "active"},
				ConfigID:   "cfg1",
			})
		case r.URL.Path == "/v1/configurations/cfg1":
			_ = json.NewEncoder(w).Encode(apitypes.ConfigPartsResponse{
				ConfigVersion: 1,
				Parts: map[string]any{
					"xray": map[string]any{
						"uuid": "11111111-1111-1111-1111-111111111111",
						"servers": []any{
							map[string]any{
								"node": "DE2", "address": "de2.example", "port": 443,
								"sni": "de2.example", "host": "de2.example",
								"path": "/cdn/de2", "transport": "xhttp", "mode": "packet-up",
							},
						},
					},
				},
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dir := t.TempDir()
	st := storage.NewMemory()
	_ = st.Set(storage.KeyAccessToken, []byte("acc"))
	_ = st.Set(storage.KeyRefreshToken, []byte("ref"))
	_ = st.Set(storage.KeyDeviceID, []byte("dev"))
	_ = st.Set(storage.KeyDeviceToken, []byte("dtok"))
	_ = st.Set(storage.KeyPrivateKey, []byte("cHJpdg=="))
	app, err := New(Options{
		APIBase: srv.URL,
		Store:   st,
		Engine:  engine.NewXray(true),
		ConfDir: dir,
		DryRun:  true,
	})
	if err != nil {
		t.Fatal(err)
	}
	res, err := app.Connect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if protocol != "vless" {
		t.Fatalf("protocol %q", protocol)
	}
	raw, err := os.ReadFile(res.Assembled.ConfPath)
	if err != nil {
		t.Fatal(err)
	}
	text := string(raw)
	for _, want := range []string{`"protocol": "tun"`, `"xhttp"`, `"packet-up"`, "domain:ru", "11111111-1111-1111-1111-111111111111"} {
		if !strings.Contains(text, want) {
			t.Fatalf("missing %s\n%s", want, text)
		}
	}
	if strings.Contains(text, "xray.tun.fd") {
		t.Fatal("fd handoff is android-only")
	}
	if !strings.Contains(text, `"autoSystemRoutingTable"`) || !strings.Contains(text, `0.0.0.0/0`) {
		t.Fatal("tun must install the default route")
	}
}

func TestXrayConnectPrefersWebSocket(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/connections" && r.Method == http.MethodPost:
			_ = json.NewEncoder(w).Encode(apitypes.CreateConnectionResponse{
				Connection: apitypes.ConnectionDTO{ID: "c1", Status: "active"},
				ConfigID:   "cfg1",
			})
		case r.URL.Path == "/v1/configurations/cfg1":
			_ = json.NewEncoder(w).Encode(apitypes.ConfigPartsResponse{
				ConfigVersion: 1,
				Parts: map[string]any{
					"xray": map[string]any{
						"uuid": "11111111-1111-1111-1111-111111111111",
						"servers": []any{
							map[string]any{
								"node": "NL1", "address": "nl.example", "port": 443,
								"sni": "nl.example", "host": "nl.example",
								"path": "/cdn/nl", "transport": "xhttp", "mode": "packet-up",
							},
							map[string]any{
								"node": "NL1", "address": "nl.example", "port": 443,
								"sni": "nl.example", "host": "nl.example",
								"path": "/api/nl", "transport": "ws",
							},
						},
					},
				},
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dir := t.TempDir()
	st := storage.NewMemory()
	_ = st.Set(storage.KeyAccessToken, []byte("acc"))
	_ = st.Set(storage.KeyRefreshToken, []byte("ref"))
	_ = st.Set(storage.KeyDeviceID, []byte("dev"))
	_ = st.Set(storage.KeyDeviceToken, []byte("dtok"))
	_ = st.Set(storage.KeyPrivateKey, []byte("cHJpdg=="))
	app, err := New(Options{
		APIBase: srv.URL,
		Store:   st,
		Engine:  engine.NewXray(true),
		ConfDir: dir,
		DryRun:  true,
	})
	if err != nil {
		t.Fatal(err)
	}
	res, err := app.Connect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(res.Assembled.ConfPath)
	if err != nil {
		t.Fatal(err)
	}
	text := string(raw)
	if !strings.Contains(text, `"network":"ws"`) && !strings.Contains(text, `"network": "ws"`) {
		t.Fatalf("desktop tun must dial websocket:\n%s", text)
	}
	if strings.Contains(text, "packet-up") {
		t.Fatal("xhttp packet-up must not be the desktop transport when websocket is available")
	}
}
