package sublink

import (
	"strings"
	"testing"
)

func TestShareLinkWS(t *testing.T) {
	got := ShareLink("11111111-1111-1111-1111-111111111111", Server{
		Node: "DE2", Country: "DE", Address: "de2.example", Port: 443,
		SNI: "de2.example", Host: "de2.example", Path: "/api/de2", Transport: "ws",
	}, "Германия · DE2")
	want := "vless://11111111-1111-1111-1111-111111111111@de2.example:443?encryption=none&fp=chrome&host=de2.example&path=%2Fapi%2Fde2&security=tls&sni=de2.example&type=ws#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%C2%B7%20DE2"
	if got != want {
		t.Fatalf("share link\n got %s\nwant %s", got, want)
	}
}

func TestShareLinksSecondTransportIsNamed(t *testing.T) {
	lines := ShareLinks("11111111-1111-1111-1111-111111111111", []Server{
		{Node: "DE2", Country: "DE", Address: "de2.example", Port: 443, SNI: "de2.example", Host: "de2.example", Path: "/api/de2", Transport: "ws"},
		{Node: "DE2", Country: "DE", Address: "de2.example", Port: 443, SNI: "de2.example", Host: "de2.example", Path: "/cdn/de2", Transport: "xhttp", Mode: "auto"},
	})
	if len(lines) != 1 {
		t.Fatalf("lines: %v", lines)
	}
	if strings.Contains(lines[0], "type=xhttp") || strings.Contains(lines[0], "mode=auto") {
		t.Fatalf("xhttp row leaked into the Happ list: %s", lines[0])
	}
	if !strings.Contains(lines[0], "type=ws") || !strings.Contains(lines[0], "path=%2Fapi%2Fde2") {
		t.Fatalf("ws row: %s", lines[0])
	}
}
