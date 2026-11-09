// Package device implements DeviceService: local x25519 keygen + CP registration.
package device

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"golang.org/x/crypto/curve25519"

	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Service manages the local device identity.
type Service struct {
	api   string
	http  *http.Client
	store storage.SecureStorage
}

// New constructs a DeviceService.
func New(apiBase string, store storage.SecureStorage) *Service {
	return &Service{
		api:   apiBase,
		http:  &http.Client{Timeout: 30 * time.Second},
		store: store,
	}
}

// EnsureDevice returns an existing registered device or creates one.
func (s *Service) EnsureDevice(ctx context.Context, accessToken, name, platform string) (deviceID, deviceToken string, err error) {
	if id, e := s.store.Get(storage.KeyDeviceID); e == nil {
		tok, e2 := s.store.Get(storage.KeyDeviceToken)
		if e2 == nil && len(id) > 0 && len(tok) > 0 {
			return string(id), string(tok), nil
		}
	}
	privB64, pubB64, err := Keygen()
	if err != nil {
		return "", "", err
	}
	if err := s.store.Set(storage.KeyPrivateKey, []byte(privB64)); err != nil {
		return "", "", err
	}
	if err := s.store.Set(storage.KeyPublicKey, []byte(pubB64)); err != nil {
		return "", "", err
	}
	body := apitypes.CreateDeviceRequest{Name: name, Platform: platform, PublicKey: pubB64}
	var resp apitypes.CreateDeviceResponse
	if err := s.postJSON(ctx, "/v1/devices", accessToken, body, &resp); err != nil {
		return "", "", err
	}
	if err := s.store.Set(storage.KeyDeviceID, []byte(resp.Device.ID)); err != nil {
		return "", "", err
	}
	if err := s.store.Set(storage.KeyDeviceToken, []byte(resp.DeviceToken)); err != nil {
		return "", "", err
	}
	return resp.Device.ID, resp.DeviceToken, nil
}

// PrivateKeyB64 returns the stored device private key.
func (s *Service) PrivateKeyB64() (string, error) {
	b, err := s.store.Get(storage.KeyPrivateKey)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// Keygen creates a clamped x25519 keypair (base64).
func Keygen() (privB64, pubB64 string, err error) {
	var priv [32]byte
	if _, err = rand.Read(priv[:]); err != nil {
		return "", "", err
	}
	priv[0] &= 248
	priv[31] &= 127
	priv[31] |= 64
	var pub [32]byte
	curve25519.ScalarBaseMult(&pub, &priv)
	return base64.StdEncoding.EncodeToString(priv[:]), base64.StdEncoding.EncodeToString(pub[:]), nil
}

func (s *Service) postJSON(ctx context.Context, path, bearer string, body, dst any) error {
	buf, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.api+path, bytes.NewReader(buf))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+bearer)
	resp, err := s.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("device: %s HTTP %d: %s", path, resp.StatusCode, bytes.TrimSpace(raw))
	}
	return json.Unmarshal(raw, dst)
}
