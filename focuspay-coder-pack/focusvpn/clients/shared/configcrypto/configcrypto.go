// Package configcrypto provides client-side ConfigParts signature verification
// (Ed25519 over canonical sorted JSON). Mirrors backend/platform/crypto framing
// from plans/M3 §17-D without importing backend/internal.
package configcrypto

import (
	"bytes"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"sort"
)

// ErrBadSignature is returned when verification fails.
var ErrBadSignature = errors.New("configcrypto: bad signature")

// SigningPayload is the object signed by the Control Plane.
type SigningPayload struct {
	ConfigVersion int            `json:"config_version"`
	Parts         map[string]any `json:"parts"`
}

// VerifyParts verifies an Ed25519 signature over canonical {config_version,parts}.
func VerifyParts(pub ed25519.PublicKey, version int, parts map[string]any, sig []byte) error {
	payload, err := CanonicalJSON(SigningPayload{ConfigVersion: version, Parts: parts})
	if err != nil {
		return err
	}
	if !ed25519.Verify(pub, payload, sig) {
		return ErrBadSignature
	}
	return nil
}

// CanonicalJSON marshals v with recursively sorted object keys.
func CanonicalJSON(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	return canonicalizeRaw(raw)
}

func canonicalizeRaw(raw []byte) ([]byte, error) {
	var v any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return marshalCanonical(v)
}

func marshalCanonical(v any) ([]byte, error) {
	switch t := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		var buf bytes.Buffer
		buf.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			kb, _ := json.Marshal(k)
			buf.Write(kb)
			buf.WriteByte(':')
			vb, err := marshalCanonical(t[k])
			if err != nil {
				return nil, err
			}
			buf.Write(vb)
		}
		buf.WriteByte('}')
		return buf.Bytes(), nil
	case []any:
		var buf bytes.Buffer
		buf.WriteByte('[')
		for i, el := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			eb, err := marshalCanonical(el)
			if err != nil {
				return nil, err
			}
			buf.Write(eb)
		}
		buf.WriteByte(']')
		return buf.Bytes(), nil
	case json.Number:
		return []byte(t.String()), nil
	default:
		return json.Marshal(t)
	}
}
