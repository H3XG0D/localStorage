package crypto_test

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"testing"

	"focusvpn.example/focusvpn/backend/internal/platform/crypto"
)

func TestCanonicalJSONStable(t *testing.T) {
	a := map[string]any{"z": 1, "a": map[string]any{"y": true, "b": "x"}, "m": []any{"c", "a"}}
	b := map[string]any{"m": []any{"c", "a"}, "a": map[string]any{"b": "x", "y": true}, "z": 1}
	ca, err := crypto.CanonicalJSON(a)
	if err != nil {
		t.Fatal(err)
	}
	cb, err := crypto.CanonicalJSON(b)
	if err != nil {
		t.Fatal(err)
	}
	if string(ca) != string(cb) {
		t.Fatalf("not stable:\n%s\n%s", ca, cb)
	}
	if !json.Valid(ca) {
		t.Fatal("invalid json")
	}
}

func TestEnvelopeRoundTrip(t *testing.T) {
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	kek := crypto.KEK{ID: "kek-v1", Key: key}
	pt := []byte(`{"interface":{"address":"10.200.0.10/32"}}`)
	blob, hash, err := crypto.Envelope(kek, pt)
	if err != nil {
		t.Fatal(err)
	}
	if len(hash) != 32 {
		t.Fatalf("hash len %d", len(hash))
	}
	out, err := crypto.OpenEnvelope(map[string]crypto.KEK{"kek-v1": kek}, blob)
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != string(pt) {
		t.Fatalf("got %s", out)
	}
}

func TestSignVerify(t *testing.T) {
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	s := crypto.NewConfigSigner(priv)
	parts := map[string]any{
		"interface": map[string]any{"address": "10.200.0.10/32", "mtu": json.Number("1420")},
		"xray":      nil,
	}
	// use plain ints via CanonicalJSON from a Go struct path — SignParts accepts map
	parts = map[string]any{
		"interface": map[string]any{"address": "10.200.0.10/32", "mtu": 1420},
		"xray":      nil,
	}
	sig, _, err := s.SignParts(1, parts)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.VerifyParts(1, parts, sig); err != nil {
		t.Fatal(err)
	}
	if err := s.VerifyParts(2, parts, sig); err == nil {
		t.Fatal("expected bad signature for wrong version")
	}
}
