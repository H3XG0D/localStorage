package main

import (
	"encoding/hex"
	"encoding/json"
	"regexp"
	"testing"
)

// bTag matches an AmneziaWG CPS "<b 0x...>" byte tag.
var bTag = regexp.MustCompile(`<b 0x([^>]*)>`)

// TestSeedI1IsValidHex guards the seeded CPS signatures: amneziawg-go rejects a
// non-hex <b> tag at IpcSet ("failed to build <b>: encoding/hex"), which kills
// the tunnel on-device while every string-based test still passes.
func TestSeedI1IsValidHex(t *testing.T) {
	for name, raw := range map[string]string{
		"DE": awgObfuscation,
		"NL": awgObfuscationNL,
		"US": awgObfuscationUS,
	} {
		var obf map[string]any
		if err := json.Unmarshal([]byte(raw), &obf); err != nil {
			t.Fatalf("%s: obfuscation is not JSON: %v", name, err)
		}
		i1, _ := obf["special_junk_i1"].(string)
		if i1 == "" {
			continue
		}
		tags := bTag.FindAllStringSubmatch(i1, -1)
		if len(tags) == 0 {
			t.Fatalf("%s: I1 %q has no <b 0x..> tag", name, i1)
		}
		for _, m := range tags {
			if _, err := hex.DecodeString(m[1]); err != nil {
				t.Errorf("%s: I1 %q has invalid hex %q: %v", name, i1, m[1], err)
			}
		}
	}
}

func TestDevPubKeyIsWireGuardSized(t *testing.T) {
	for _, tag := range []byte{0x01, 0x02, 0x03} {
		if got := len(devPubKey(tag)); got != 32 {
			t.Fatalf("devPubKey(%#x) len = %d, want 32", tag, got)
		}
	}
}
