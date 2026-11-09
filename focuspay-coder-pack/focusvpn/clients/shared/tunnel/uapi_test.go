package tunnel

import (
	"encoding/base64"
	"strings"
	"testing"
)

func TestUAPIConfigIncludesJcAndHexKeys(t *testing.T) {
	priv := make([]byte, 32)
	pub := make([]byte, 32)
	for i := range priv {
		priv[i] = byte(i)
		pub[i] = byte(255 - i)
	}
	c := Config{
		PrivateKey: base64.StdEncoding.EncodeToString(priv),
		PeerPubKey: base64.StdEncoding.EncodeToString(pub),
		Endpoint:   "203.0.113.10:51820",
		Jc:         4,
		Jmin:       40,
		Jmax:       70,
		S1:         15,
		S2:         20,
		S3:         10,
		S4:         5,
		H1:         "100-110",
		H2:         "200-210",
		H3:         "300-310",
		H4:         "400-410",
		I1:         "<b 0xde01>",
		AllowedIPs: []string{"0.0.0.0/0"},
	}
	uapi, err := UAPIConfig(c)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"jc=4",
		"jmin=40",
		"jmax=70",
		"s1=15",
		"s2=20",
		"s3=10",
		"s4=5",
		"h1=100-110",
		"h2=200-210",
		"h3=300-310",
		"h4=400-410",
		"i1=<b 0xde01>",
		"endpoint=203.0.113.10:51820",
		"allowed_ip=0.0.0.0/0",
		"private_key=",
		"public_key=",
	} {
		if !strings.Contains(uapi, want) {
			t.Fatalf("missing %q in:\n%s", want, uapi)
		}
	}
	// UAPI keys are hex, not base64
	if strings.Contains(uapi, c.PrivateKey) {
		t.Fatal("private key should be hex-encoded, not base64")
	}
}

func TestUAPIConfigWireGuardOmitsJc(t *testing.T) {
	priv := make([]byte, 32)
	pub := make([]byte, 32)
	c := Config{
		PrivateKey: base64.StdEncoding.EncodeToString(priv),
		PeerPubKey: base64.StdEncoding.EncodeToString(pub),
		Endpoint:   "203.0.113.10:51820",
		AllowedIPs: []string{"0.0.0.0/0"},
	}
	uapi, err := UAPIConfigWireGuard(c)
	if err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{"jc=", "jmin=", "jmax="} {
		if strings.Contains(uapi, bad) {
			t.Fatalf("WG UAPI must not contain %s:\n%s", bad, uapi)
		}
	}
	if !strings.Contains(uapi, "endpoint=203.0.113.10:51820") {
		t.Fatal(uapi)
	}
}
