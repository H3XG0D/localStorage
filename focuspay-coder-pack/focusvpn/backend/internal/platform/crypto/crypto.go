// Package crypto implements ConfigParts envelope encryption and Ed25519 signing
// per docs/plans/M3.md §8 (approved §17-D). Primitives: AES-256-GCM, Ed25519, SHA-256 only.
package crypto

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
)

const (
	magic      = "MVN1"
	formatVer  = byte(0x01)
	nonceSize  = 12
	dekSize    = 32
	gcmTagSize = 16
)

// Errors.
var (
	ErrBadBlob      = errors.New("crypto: malformed envelope blob")
	ErrUnknownKEK   = errors.New("crypto: unknown kek_id")
	ErrDecrypt      = errors.New("crypto: decrypt failed")
	ErrBadSignature = errors.New("crypto: bad signature")
)

// KEK is a named 32-byte AES key.
type KEK struct {
	ID  string
	Key []byte // 32 bytes
}

// Envelope encrypts plaintext under a random DEK wrapped by kek.
func Envelope(kek KEK, plaintext []byte) ([]byte, []byte, error) {
	if len(kek.Key) != dekSize {
		return nil, nil, fmt.Errorf("crypto: KEK must be %d bytes", dekSize)
	}
	if len(kek.ID) == 0 || len(kek.ID) > 255 {
		return nil, nil, errors.New("crypto: invalid kek_id length")
	}
	dek := make([]byte, dekSize)
	if _, err := rand.Read(dek); err != nil {
		return nil, nil, err
	}
	wrapNonce := make([]byte, nonceSize)
	if _, err := rand.Read(wrapNonce); err != nil {
		return nil, nil, err
	}
	dataNonce := make([]byte, nonceSize)
	if _, err := rand.Read(dataNonce); err != nil {
		return nil, nil, err
	}

	aad := aadBytes(kek.ID)
	wrapped, err := gcmSeal(kek.Key, wrapNonce, dek, aad)
	if err != nil {
		return nil, nil, err
	}
	ct, err := gcmSeal(dek, dataNonce, plaintext, aad)
	if err != nil {
		return nil, nil, err
	}

	var buf bytes.Buffer
	buf.WriteString(magic)
	buf.WriteByte(formatVer)
	buf.WriteByte(byte(len(kek.ID)))
	buf.WriteString(kek.ID)
	buf.Write(wrapNonce)
	buf.Write(wrapped)
	buf.Write(dataNonce)
	buf.Write(ct)

	sum := sha256.Sum256(plaintext)
	return buf.Bytes(), sum[:], nil
}

// OpenEnvelope decrypts a MVN1 blob using the matching KEK from keys (keyed by id).
func OpenEnvelope(keys map[string]KEK, blob []byte) ([]byte, error) {
	if len(blob) < 4+1+1+nonceSize+dekSize+gcmTagSize+nonceSize+gcmTagSize {
		return nil, ErrBadBlob
	}
	if string(blob[:4]) != magic {
		return nil, ErrBadBlob
	}
	if blob[4] != formatVer {
		return nil, ErrBadBlob
	}
	idLen := int(blob[5])
	off := 6
	if idLen == 0 || off+idLen > len(blob) {
		return nil, ErrBadBlob
	}
	kekID := string(blob[off : off+idLen])
	off += idLen
	kek, ok := keys[kekID]
	if !ok || len(kek.Key) != dekSize {
		return nil, ErrUnknownKEK
	}
	if off+nonceSize > len(blob) {
		return nil, ErrBadBlob
	}
	wrapNonce := blob[off : off+nonceSize]
	off += nonceSize
	wrappedLen := dekSize + gcmTagSize
	if off+wrappedLen > len(blob) {
		return nil, ErrBadBlob
	}
	wrapped := blob[off : off+wrappedLen]
	off += wrappedLen
	if off+nonceSize > len(blob) {
		return nil, ErrBadBlob
	}
	dataNonce := blob[off : off+nonceSize]
	off += nonceSize
	ct := blob[off:]
	if len(ct) < gcmTagSize {
		return nil, ErrBadBlob
	}

	aad := aadBytes(kekID)
	dek, err := gcmOpen(kek.Key, wrapNonce, wrapped, aad)
	if err != nil {
		return nil, ErrDecrypt
	}
	pt, err := gcmOpen(dek, dataNonce, ct, aad)
	if err != nil {
		return nil, ErrDecrypt
	}
	return pt, nil
}

func aadBytes(kekID string) []byte {
	b := make([]byte, 0, 4+1+len(kekID))
	b = append(b, magic...)
	b = append(b, formatVer)
	b = append(b, []byte(kekID)...)
	return b
}

func gcmSeal(key, nonce, plaintext, aad []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return gcm.Seal(nil, nonce, plaintext, aad), nil
}

func gcmOpen(key, nonce, ciphertext, aad []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return gcm.Open(nil, nonce, ciphertext, aad)
}

// CanonicalJSON returns compact JSON with object keys sorted at every level.
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

// SigningPayload is the object signed by ConfigSigner.
type SigningPayload struct {
	ConfigVersion int            `json:"config_version"`
	Parts         map[string]any `json:"parts"`
}

// ConfigSigner signs and verifies ConfigParts with Ed25519.
type ConfigSigner struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

// NewConfigSigner constructs a signer from a 32-byte seed or 64-byte private key.
func NewConfigSigner(priv ed25519.PrivateKey) *ConfigSigner {
	return &ConfigSigner{priv: priv, pub: priv.Public().(ed25519.PublicKey)}
}

// PublicKey returns the verification key.
func (s *ConfigSigner) PublicKey() ed25519.PublicKey { return s.pub }

// SignParts signs canonical {config_version, parts}.
func (s *ConfigSigner) SignParts(version int, parts map[string]any) (sig []byte, payload []byte, err error) {
	payload, err = CanonicalJSON(SigningPayload{ConfigVersion: version, Parts: parts})
	if err != nil {
		return nil, nil, err
	}
	return ed25519.Sign(s.priv, payload), payload, nil
}

// VerifyParts verifies an Ed25519 signature over the canonical payload.
func (s *ConfigSigner) VerifyParts(version int, parts map[string]any, sig []byte) error {
	return VerifyPartsPublic(s.pub, version, parts, sig)
}

// VerifyPartsPublic verifies ConfigParts with only the public key (client-side).
func VerifyPartsPublic(pub ed25519.PublicKey, version int, parts map[string]any, sig []byte) error {
	payload, err := CanonicalJSON(SigningPayload{ConfigVersion: version, Parts: parts})
	if err != nil {
		return err
	}
	if !ed25519.Verify(pub, payload, sig) {
		return ErrBadSignature
	}
	return nil
}

// ContentHash returns SHA-256 of plaintext.
func ContentHash(plaintext []byte) []byte {
	sum := sha256.Sum256(plaintext)
	return sum[:]
}
