// Package id generates RFC 4122 v4 UUIDs and opaque tokens using crypto/rand.
// Kept dependency-free on purpose (see DECISIONS.md: minimal dependencies).
package id

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
)

// NewUUID returns a random UUIDv4 string (36 chars, canonical form).
func NewUUID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("id: crypto/rand failed: " + err.Error())
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	dst := make([]byte, 36)
	hex.Encode(dst[0:8], b[0:4])
	dst[8] = '-'
	hex.Encode(dst[9:13], b[4:6])
	dst[13] = '-'
	hex.Encode(dst[14:18], b[6:8])
	dst[18] = '-'
	hex.Encode(dst[19:23], b[8:10])
	dst[23] = '-'
	hex.Encode(dst[24:36], b[10:16])
	return string(dst)
}

// NewOpaqueToken returns n cryptographically-random bytes as URL-safe base64
// (no padding). Used for refresh and device tokens (SECURITY.md §3.2).
func NewOpaqueToken(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic("id: crypto/rand failed: " + err.Error())
	}
	return base64.RawURLEncoding.EncodeToString(b)
}
