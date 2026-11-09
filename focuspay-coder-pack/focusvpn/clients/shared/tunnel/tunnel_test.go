package tunnel_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

func TestFromPartsAndWriteConf(t *testing.T) {
	parts := map[string]any{
		"interface": map[string]any{
			"address": "10.200.0.2/32",
			"dns":     []any{"10.200.0.1"},
			"mtu":     float64(1420),
		},
		"peer": map[string]any{
			"server_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
			"endpoint":          "de-01.focusvpn.example:51820",
			"allowed_ips":       []any{"0.0.0.0/0", "::/0"},
		},
		"protocol": map[string]any{
			"name": "amneziawg",
			"obfuscation": map[string]any{
				"junk_packet_count":              float64(4),
				"junk_min_size":                  float64(40),
				"junk_max_size":                  float64(70),
				"init_packet_junk_size":          float64(15),
				"response_packet_junk_size":      float64(20),
				"cookie_reply_junk_size":         float64(10),
				"transport_packet_junk_size":     float64(5),
				"init_packet_magic_header":       "100-110",
				"response_packet_magic_header":   "200-210",
				"underload_packet_magic_header":  "300-310",
				"transport_packet_magic_header":  "400-410",
				"special_junk_i1":                "<b 0xde01>",
			},
		},
	}
	priv := "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
	cfg, err := tunnel.FromParts(parts, priv, "focusvpn0")
	if err != nil {
		t.Fatalf("FromParts: %v", err)
	}
	if cfg.Jc != 4 || cfg.Jmin != 40 || cfg.Jmax != 70 {
		t.Fatalf("obfuscation: Jc=%d Jmin=%d Jmax=%d", cfg.Jc, cfg.Jmin, cfg.Jmax)
	}
	if cfg.S1 != 15 || cfg.H1 != "100-110" || cfg.I1 != "<b 0xde01>" {
		t.Fatalf("H/S/I: S1=%d H1=%s I1=%s", cfg.S1, cfg.H1, cfg.I1)
	}

	dir := t.TempDir()
	path, err := tunnel.WriteConf(dir, cfg)
	if err != nil {
		t.Fatalf("WriteConf: %v", err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	s := string(raw)
	for _, want := range []string{
		"[Interface]",
		"PrivateKey = " + priv,
		"Address = 10.200.0.2/32",
		"Jc = 4",
		"Jmin = 40",
		"Jmax = 70",
		"S1 = 15",
		"H1 = 100-110",
		"I1 = <b 0xde01>",
		"[Peer]",
		"Endpoint = de-01.focusvpn.example:51820",
		"PersistentKeepalive = 25",
	} {
		if !strings.Contains(s, want) {
			t.Fatalf("conf missing %q\n%s", want, s)
		}
	}
	if filepath.Base(path) != "focusvpn0.conf" {
		t.Fatalf("path = %s", path)
	}
}

func TestFromPartsRequiresObfuscation(t *testing.T) {
	parts := map[string]any{
		"interface": map[string]any{"address": "10.200.0.2/32"},
		"peer": map[string]any{
			"server_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
			"endpoint":          "x:1",
		},
		"protocol": map[string]any{"name": "amneziawg"},
	}
	_, err := tunnel.FromParts(parts, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "x")
	if err == nil {
		t.Fatal("expected error without Jc/Jmin/Jmax")
	}
}
