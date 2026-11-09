package xray

import (
	"encoding/json"
	"net"
	"strings"
	"testing"
)

func TestProfileAndTunDocument(t *testing.T) {
	parts := map[string]any{
		"xray": map[string]any{
			"uuid": "11111111-1111-1111-1111-111111111111",
			"servers": []any{
				map[string]any{
					"node": "DE2", "address": "de2.example", "port": float64(443),
					"sni": "de2.example", "host": "de2.example", "path": "/api/de2", "transport": "ws",
				},
				map[string]any{
					"node": "DE2", "address": "de2.example", "port": float64(443),
					"path": "/cdn/de2", "transport": "xhttp", "mode": "auto",
					"sni": "de2.example", "host": "de2.example",
				},
			},
		},
	}
	prof, err := ProfileFromParts(parts)
	if err != nil {
		t.Fatal(err)
	}
	if prof.UUID != "11111111-1111-1111-1111-111111111111" {
		t.Fatal(prof.UUID)
	}
	if prof.Servers[0].Transport != "ws" || prof.Servers[1].Transport != "xhttp" {
		t.Fatalf("%+v", prof.Servers)
	}
	prefixes, err := LoadRUPrefixes()
	if err != nil {
		t.Fatal(err)
	}
	doc, err := BuildTunDocument(prof.Servers[1], prof.UUID, prefixes)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(doc)
	s := string(raw)
	if strings.Contains(s, "xray.tun.fd") {
		t.Fatal("desktop tun must create the device itself")
	}
	if !strings.Contains(s, `"name":"xray0"`) && !strings.Contains(s, `"name": "xray0"`) {
		t.Fatalf("tun name missing: %s", s)
	}
	inbounds := doc["inbounds"].([]any)
	if inbounds[0].(map[string]any)["protocol"] != "tun" {
		t.Fatal(inbounds[0])
	}
	settings := inbounds[0].(map[string]any)["settings"].(map[string]any)
	routes, _ := settings["autoSystemRoutingTable"].([]any)
	if len(routes) != 1 || routes[0] != "0.0.0.0/0" {
		t.Fatalf("system route: %#v", settings["autoSystemRoutingTable"])
	}
	if settings["autoOutboundsInterface"] != "auto" {
		t.Fatal(settings["autoOutboundsInterface"])
	}
	if inbounds[1].(map[string]any)["protocol"] != "socks" || inbounds[1].(map[string]any)["port"] != SocksPort {
		t.Fatal(inbounds[1])
	}
	outbounds := doc["outbounds"].([]any)
	proxy := outbounds[0].(map[string]any)
	stream := proxy["streamSettings"].(map[string]any)
	if stream["network"] != "xhttp" {
		t.Fatal(stream["network"])
	}
	xs := stream["xhttpSettings"].(map[string]any)
	if xs["path"] != "/cdn/de2" || xs["mode"] != "auto" || xs["host"] != "de2.example" {
		t.Fatalf("%+v", xs)
	}
	alpn := stream["tlsSettings"].(map[string]any)["alpn"].([]any)
	if alpn[0] != "http/1.1" {
		t.Fatal(alpn)
	}
	if outbounds[1].(map[string]any)["tag"] != "dns-out" || outbounds[2].(map[string]any)["protocol"] != "freedom" {
		t.Fatal(outbounds)
	}
	if strings.Contains(s, "flow") {
		t.Fatal("vless user must not set flow")
	}
	routing := doc["routing"].(map[string]any)
	if routing["domainStrategy"] != "IPIfNonMatch" {
		t.Fatal(routing["domainStrategy"])
	}
	rules := routing["rules"].([]any)
	if rules[0].(map[string]any)["outboundTag"] != "dns-out" {
		t.Fatal(rules[0])
	}
	domains := rules[1].(map[string]any)["domain"].([]string)
	if !contains(domains, "domain:ru") || !contains(domains, "domain:yandex.net") || !contains(domains, "domain:vk.com") {
		t.Fatal(domains)
	}
	cidrs := rules[2].(map[string]any)["ip"].([]string)
	if !contains(cidrs, "10.0.0.0/8") {
		t.Fatal("private cidr")
	}
	if !anyCIDR(cidrs, "77.88.8.8") {
		t.Fatal("yandex dns should be direct")
	}
	if anyCIDR(cidrs, "1.1.1.1") || anyCIDR(cidrs, "8.8.8.8") {
		t.Fatal("public resolvers must stay in the tunnel")
	}
	dns := doc["dns"].(map[string]any)["servers"].([]any)
	if dns[0].(map[string]any)["address"] != "77.88.8.8" || dns[1] != "https://1.1.1.1/dns-query" {
		t.Fatal(dns)
	}

	ws, err := BuildTunDocument(prof.Servers[0], prof.UUID, prefixes)
	if err != nil {
		t.Fatal(err)
	}
	wsRaw, _ := json.Marshal(ws)
	if !strings.Contains(string(wsRaw), `"network":"ws"`) && !strings.Contains(string(wsRaw), `"network": "ws"`) {
		t.Fatal("ws transport")
	}
}

func contains(list []string, want string) bool {
	for _, s := range list {
		if s == want {
			return true
		}
	}
	return false
}

func anyCIDR(cidrs []string, ip string) bool {
	parsed := net.ParseIP(ip)
	for _, c := range cidrs {
		_, n, err := net.ParseCIDR(c)
		if err != nil || n == nil || parsed == nil {
			continue
		}
		if n.Contains(parsed) {
			return true
		}
	}
	return false
}
