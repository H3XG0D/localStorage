package xray

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestFromPartsAndBuildDocument(t *testing.T) {
	parts := map[string]any{
		"peer": map[string]any{"endpoint": "203.0.113.10:8443"},
		"xray": map[string]any{
			"flow": "xtls-rprx-vision",
			"reality": map[string]any{
				"server_name": "www.example.com",
				"public_key":  "pubKeyExample===========================",
				"short_id":    "deadbeef",
			},
		},
	}
	c, err := FromParts(parts, "11111111-1111-1111-1111-111111111111")
	if err != nil {
		t.Fatal(err)
	}
	if c.Address != "203.0.113.10" || c.Port != 8443 {
		t.Fatalf("endpoint fallback: %+v", c)
	}
	doc, err := BuildDocument(c)
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateDocument(doc); err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(doc)
	s := string(b)
	for _, want := range []string{`"vless"`, `"reality"`, `"www.example.com"`, `"deadbeef"`} {
		if !strings.Contains(s, want) {
			t.Fatalf("missing %s in %s", want, s)
		}
	}
}

func TestWriteJSON(t *testing.T) {
	dir := t.TempDir()
	c, err := SyntheticForDryRun("1.2.3.4:443", "22222222-2222-2222-2222-222222222222")
	if err != nil {
		t.Fatal(err)
	}
	path, err := WriteJSON(dir, "", c)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var doc Document
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if err := ValidateDocument(doc); err != nil {
		t.Fatal(err)
	}
}

func TestFromPartsMissingXray(t *testing.T) {
	_, err := FromParts(map[string]any{}, "u")
	if err == nil {
		t.Fatal("expected error")
	}
}
