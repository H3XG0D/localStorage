// Package config fetches ConfigParts, verifies signatures, and assembles tunnel configs.
package config

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"focusvpn.example/focusvpn/clients/appcore/apierr"
	"focusvpn.example/focusvpn/clients/appcore/connectivity"
	"focusvpn.example/focusvpn/clients/appcore/engine"
	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
	"focusvpn.example/focusvpn/clients/shared/configcrypto"
	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

// Service talks to servers/connections/configurations APIs.
type Service struct {
	api       string
	http      *http.Client
	store     storage.SecureStorage
	verifyPub ed25519.PublicKey // optional; nil skips verify
	iface     string
}

// New constructs a ConfigService. verifyPub may be nil to skip signature checks in tests.
func New(apiBase string, store storage.SecureStorage, verifyPub ed25519.PublicKey, iface string) *Service {
	if iface == "" {
		iface = "focusvpn0"
	}
	return &Service{
		api:       apiBase,
		http:      &http.Client{Timeout: 35 * time.Second},
		store:     store,
		verifyPub: verifyPub,
		iface:     iface,
	}
}

// ConnectResult is returned after allocation + config fetch + assemble.
type ConnectResult struct {
	ConnectionID string
	ConfigID     string
	Status       string
	Assembled    engine.AssembledConfig
	Parts        map[string]any
	Candidates   []apitypes.CandidateEndpoint
}

// Connect ensures a device connection, fetches ConfigParts, verifies, assembles.
// preferredNode is optional (e.g. "DE-01"); empty lets CP score freely.
// protocol empty means amneziawg (CLI smokes). The GUI passes vless.
func (s *Service) Connect(ctx context.Context, access, deviceID, deviceToken, privateKeyB64, preferredNode, protocol string) (ConnectResult, error) {
	if protocol == "" {
		protocol = "amneziawg"
	}
	body := map[string]string{
		"device_id": deviceID, "protocol": protocol,
	}
	if preferredNode != "" {
		body["preferred_node"] = preferredNode
	}
	var connResp apitypes.CreateConnectionResponse
	if err := s.doJSON(ctx, http.MethodPost, "/v1/connections", access, "", body, &connResp); err != nil {
		return ConnectResult{}, err
	}
	_ = connectivity.SaveCandidates(s.store, connResp.Candidates)
	var partsResp apitypes.ConfigPartsResponse
	if err := s.doJSON(ctx, http.MethodGet, "/v1/configurations/"+connResp.ConfigID, "", deviceToken, nil, &partsResp); err != nil {
		return ConnectResult{}, err
	}
	if s.verifyPub != nil {
		sig, err := base64.StdEncoding.DecodeString(partsResp.Signature)
		if err != nil {
			return ConnectResult{}, fmt.Errorf("config: signature: %w", err)
		}
		if err := configcrypto.VerifyParts(s.verifyPub, partsResp.ConfigVersion, partsResp.Parts, sig); err != nil {
			return ConnectResult{}, fmt.Errorf("config: verify: %w", err)
		}
	}
	var tc tunnel.Config
	if protocol != "vless" {
		var err error
		tc, err = tunnel.FromParts(partsResp.Parts, privateKeyB64, s.iface)
		if err != nil {
			return ConnectResult{}, err
		}
	}
	_ = s.store.Set(storage.KeyConnectionID, []byte(connResp.Connection.ID))
	return ConnectResult{
		ConnectionID: connResp.Connection.ID,
		ConfigID:     connResp.ConfigID,
		Status:       connResp.Connection.Status,
		Assembled:    engine.AssembledConfig{Tunnel: tc},
		Parts:        partsResp.Parts,
		Candidates:   connResp.Candidates,
	}, nil
}

// Disconnect revokes the connection on the CP.
func (s *Service) Disconnect(ctx context.Context, access, connectionID string) error {
	return s.doJSON(ctx, http.MethodDelete, "/v1/connections/"+connectionID, access, "", nil, nil)
}

// ListServers returns selectable endpoints.
func (s *Service) ListServers(ctx context.Context, access string) (apitypes.ServersResponse, error) {
	var out apitypes.ServersResponse
	err := s.doJSON(ctx, http.MethodGet, "/v1/servers", access, "", nil, &out)
	return out, err
}

func (s *Service) doJSON(ctx context.Context, method, path, bearer, deviceToken string, body, dst any) error {
	var rdr io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(buf)
	}
	req, err := http.NewRequestWithContext(ctx, method, s.api+path, rdr)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	if deviceToken != "" {
		req.Header.Set("X-Device-Token", deviceToken)
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return apierr.FromBody(resp.StatusCode, raw)
	}
	if dst == nil || len(raw) == 0 || resp.StatusCode == http.StatusNoContent {
		return nil
	}
	return json.Unmarshal(raw, dst)
}
