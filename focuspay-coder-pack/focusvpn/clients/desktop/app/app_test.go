package app

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"focusvpn.example/focusvpn/clients/appcore/engine"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

func TestDesktopBindingsAuthStatus(t *testing.T) {
	dir := t.TempDir()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/register" && r.Method == http.MethodPost:
			_ = json.NewEncoder(w).Encode(apitypes.AuthResponse{
				Tokens: apitypes.Tokens{AccessToken: "a", RefreshToken: "r", ExpiresIn: 900},
			})
		case r.URL.Path == "/v1/devices" && r.Method == http.MethodPost:
			_ = json.NewEncoder(w).Encode(apitypes.CreateDeviceResponse{
				Device:      apitypes.DeviceDTO{ID: "dev1"},
				DeviceToken: "dtok",
			})
		case r.URL.Path == "/v1/servers":
			_ = json.NewEncoder(w).Encode(apitypes.ServersResponse{
				Endpoints: []apitypes.EndpointDTO{{ID: "e1", Node: "DE-01", Country: "DE", Protocol: "amneziawg"}},
			})
		case r.URL.Path == "/v1/connections" && r.Method == http.MethodPost:
			_ = json.NewEncoder(w).Encode(apitypes.CreateConnectionResponse{
				Connection: apitypes.ConnectionDTO{ID: "c1", Status: "active"},
				ConfigID:   "cfg1",
			})
		case r.URL.Path == "/v1/configurations/cfg1":
			parts := map[string]any{
				"interface": map[string]any{
					"address": "10.8.0.2/32",
					"dns":     []any{"1.1.1.1"},
				},
				"peer": map[string]any{
					// 32-byte key, standard base64 (amneziawg-go IpcSet)
					"server_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
					"endpoint":          "1.2.3.4:51820",
					"allowed_ips":       []any{"0.0.0.0/0"},
				},
				"protocol": map[string]any{
					"obfuscation": map[string]any{
						"junk_packet_count":                4,
						"junk_min_size":                    40,
						"junk_max_size":                    70,
						"init_packet_junk_size":            15,
						"response_packet_junk_size":        20,
						"cookie_reply_junk_size":           10,
						"transport_packet_junk_size":       5,
						"init_packet_magic_header":         "100-110",
						"response_packet_magic_header":     "200-210",
						"underload_packet_magic_header":    "300-310",
						"transport_packet_magic_header":    "400-410",
					},
				},
			}
			_ = json.NewEncoder(w).Encode(apitypes.ConfigPartsResponse{
				ConfigVersion: 1,
				Parts:         parts,
				Signature:     "",
			})
		case r.Method == http.MethodDelete:
			w.WriteHeader(http.StatusNoContent)
		default:
			t.Logf("unhandled %s %s", r.Method, r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()

	a := New(Options{APIBase: srv.URL, DataDir: dir, ConfDir: filepath.Join(dir, "conf"), DryRun: true})
	if err := a.Register("u@example.com", "password-long-1"); err != nil {
		t.Fatalf("register: %v", err)
	}
	st := a.Status()
	if !st.LoggedIn || st.Email != "u@example.com" {
		t.Fatalf("status: %+v", st)
	}
	servers, err := a.ListServers()
	if err != nil || len(servers.Endpoints) != 1 || servers.Endpoints[0].Node != "DE-01" {
		t.Fatalf("servers: %+v %v", servers, err)
	}
	if err := a.SelectNode("DE-01"); err != nil {
		t.Fatal(err)
	}
	res, err := a.Connect()
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	if res.ConfPath == "" {
		t.Fatal("expected conf path")
	}
	if _, err := os.Stat(res.ConfPath); err != nil {
		t.Fatal(err)
	}
	st = a.Status()
	if st.State != string(engine.StateConnected) {
		t.Fatalf("want connected, got %s", st.State)
	}
	if st.SelectedNode != "DE-01" {
		t.Fatalf("selected: %q", st.SelectedNode)
	}
	if err := a.Disconnect(); err != nil {
		t.Fatal(err)
	}
}
