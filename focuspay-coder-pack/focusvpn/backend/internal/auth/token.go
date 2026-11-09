package auth

import (
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"focusvpn.example/focusvpn/backend/internal/platform/id"
)

// Claims is the FocusVPN access-token claim set (ADR-006, SECURITY.md §3.2).
type Claims struct {
	Role string `json:"role"`
	jwt.RegisteredClaims
}

// TokenIssuer mints EdDSA (Ed25519) access tokens and derives refresh-token hashes.
type TokenIssuer struct {
	priv      ed25519.PrivateKey
	pub       ed25519.PublicKey
	hmacKey   []byte
	accessTTL time.Duration
}

// NewTokenIssuer constructs a TokenIssuer.
func NewTokenIssuer(priv ed25519.PrivateKey, pub ed25519.PublicKey, hmacKey []byte, accessTTL time.Duration) *TokenIssuer {
	return &TokenIssuer{priv: priv, pub: pub, hmacKey: hmacKey, accessTTL: accessTTL}
}

// AccessTTL returns the configured access-token lifetime.
func (t *TokenIssuer) AccessTTL() time.Duration { return t.accessTTL }

// IssueAccess signs an access JWT for the given user/role.
func (t *TokenIssuer) IssueAccess(userID, role string) (string, error) {
	now := time.Now()
	claims := Claims{
		Role: role,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			ID:        id.NewUUID(),
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(t.accessTTL)),
		},
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodEdDSA, claims)
	return tok.SignedString(t.priv)
}

// ParseAccess validates an access JWT and returns its claims.
func (t *TokenIssuer) ParseAccess(tokenStr string) (*Claims, error) {
	claims := &Claims{}
	_, err := jwt.ParseWithClaims(tokenStr, claims, func(tok *jwt.Token) (any, error) {
		if _, ok := tok.Method.(*jwt.SigningMethodEd25519); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", tok.Header["alg"])
		}
		return t.pub, nil
	}, jwt.WithValidMethods([]string{"EdDSA"}))
	if err != nil {
		return nil, err
	}
	return claims, nil
}

// HashRefresh returns a keyed HMAC-SHA256 of a refresh token so that a database
// leak cannot be validated offline (SECURITY.md §3.2).
func (t *TokenIssuer) HashRefresh(token string) string {
	mac := hmac.New(sha256.New, t.hmacKey)
	mac.Write([]byte(token))
	return base64.RawStdEncoding.EncodeToString(mac.Sum(nil))
}
