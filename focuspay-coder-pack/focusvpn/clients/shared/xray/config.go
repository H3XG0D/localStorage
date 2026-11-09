// Package xray builds VLESS+REALITY client JSON for Xray-core (MPL-2.0).
// We never fork/modify Xray sources — only generate config and exec the binary (ADR-002).
package xray

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// ClientConfig is the local material needed to write an Xray client JSON.
// VLESS UUID stays on-device (ARCHITECTURE: credential for REALITY auth).
type ClientConfig struct {
	UUID       string
	Flow       string // e.g. xtls-rprx-vision (reality) / "" (ws)
	Address    string
	Port       int
	ServerName string
	PublicKey  string // REALITY server public key (base64)
	ShortID    string
	Fingerprint string
	SpiderX    string
	SocksPort  int // local SOCKS inbound; default 10808
	Network    string // "tcp" (reality) or "ws" (vless+ws+tls)
	Security   string // "reality" or "tls"
	Host       string // ws Host header
	Path       string // ws path, e.g. /vpn-xxxx
}

// FromParts maps ConfigParts["xray"] (+ peer endpoint fallback) into ClientConfig.
// uuid must be provided by the caller (device-local); never sent by CP as a private key.
func FromParts(parts map[string]any, uuid string) (ClientConfig, error) {
	if uuid == "" {
		return ClientConfig{}, errors.New("xray: uuid required")
	}
	c := ClientConfig{
		UUID:        uuid,
		Flow:        "xtls-rprx-vision",
		Fingerprint: "chrome",
		SpiderX:     "/",
		SocksPort:   10808,
		Network:     "tcp",
		Security:    "reality",
	}

	raw, _ := parts["xray"].(map[string]any)
	if raw == nil {
		return ClientConfig{}, errors.New("xray: parts.xray missing")
	}

	if v, ok := raw["uuid"].(string); ok && v != "" {
		// CP may echo the assigned UUID; prefer caller-supplied device uuid if both set.
		_ = v
	}
	if v, ok := raw["flow"].(string); ok && v != "" {
		c.Flow = v
	} else if c.Network == "ws" {
		c.Flow = ""
	}
	if v, ok := raw["network"].(string); ok && v != "" {
		c.Network = v
	}
	if v, ok := raw["security"].(string); ok && v != "" {
		c.Security = v
	}
	if v, ok := raw["host"].(string); ok {
		c.Host = v
	}
	if v, ok := raw["path"].(string); ok {
		c.Path = v
	}
	if v, ok := raw["sni"].(string); ok && v != "" {
		c.ServerName = v
	}
	if v, ok := raw["address"].(string); ok {
		c.Address = v
	}
	if v, ok := asInt(raw["port"]); ok {
		c.Port = v
	}
	if reality, ok := raw["reality"].(map[string]any); ok {
		c.ServerName, _ = reality["server_name"].(string)
		c.PublicKey, _ = reality["public_key"].(string)
		c.ShortID, _ = reality["short_id"].(string)
		if fp, ok := reality["fingerprint"].(string); ok && fp != "" {
			c.Fingerprint = fp
		}
		if sx, ok := reality["spider_x"].(string); ok && sx != "" {
			c.SpiderX = sx
		}
	}

	// Fallback host:port from peer.endpoint when xray.address/port omitted.
	if c.Address == "" || c.Port == 0 {
		if peer, ok := parts["peer"].(map[string]any); ok {
			if ep, ok := peer["endpoint"].(string); ok && ep != "" {
				host, portStr, err := net.SplitHostPort(ep)
				if err == nil {
					if c.Address == "" {
						c.Address = host
					}
					if c.Port == 0 {
						if p, err := strconv.Atoi(portStr); err == nil {
							c.Port = p
						}
					}
				}
			}
		}
	}
	if c.Port == 0 {
		c.Port = 443
	}
	if c.Address == "" {
		return ClientConfig{}, errors.New("xray: address required")
	}
	if c.PublicKey == "" || c.ServerName == "" || c.ShortID == "" {
		if c.Network == "ws" && c.Security == "tls" {
			if c.Path == "" {
				return ClientConfig{}, errors.New("xray: ws.path required")
			}
			return c, nil
		}
		return ClientConfig{}, errors.New("xray: reality.server_name, public_key, short_id required")
	}
	return c, nil
}

// SyntheticForDryRun builds a valid-shaped config for CI when CP still returns xray:null.
// Not for production connect.
func SyntheticForDryRun(endpoint, uuid string) (ClientConfig, error) {
	if uuid == "" {
		return ClientConfig{}, errors.New("xray: uuid required")
	}
	host, portStr, err := net.SplitHostPort(endpoint)
	if err != nil {
		host = endpoint
		portStr = "443"
	}
	port, _ := strconv.Atoi(portStr)
	if port == 0 {
		port = 443
	}
	return ClientConfig{
		UUID:        uuid,
		Flow:        "xtls-rprx-vision",
		Address:     host,
		Port:        port,
		ServerName:  "www.cloudflare.com",
		PublicKey:   "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
		ShortID:     "abcd1234",
		Fingerprint: "chrome",
		SpiderX:     "/",
		SocksPort:   10808,
	}, nil
}

// Document is the Xray JSON root (inbound SOCKS + VLESS REALITY outbound).
type Document struct {
	Log       map[string]any   `json:"log"`
	Inbounds  []map[string]any `json:"inbounds"`
	Outbounds []map[string]any `json:"outbounds"`
}

// BuildDocument creates the JSON-serializable client config (no Xray source edits).
func BuildDocument(c ClientConfig) (Document, error) {
	if c.SocksPort <= 0 {
		c.SocksPort = 10808
	}
	if strings.TrimSpace(c.UUID) == "" || c.Address == "" || c.Port <= 0 {
		return Document{}, errors.New("xray: incomplete client config")
	}
	return Document{
		Log: map[string]any{"loglevel": "warning"},
		Inbounds: []map[string]any{{
			"tag":      "socks-in",
			"listen":   "127.0.0.1",
			"port":     c.SocksPort,
			"protocol": "socks",
			"settings": map[string]any{"udp": true},
		}},
		Outbounds: []map[string]any{{
			"tag":      "proxy",
			"protocol": "vless",
			"settings": map[string]any{
				"vnext": []map[string]any{{
					"address": c.Address,
					"port":    c.Port,
					"users": []map[string]any{{
						"id":         c.UUID,
						"encryption": "none",
						"flow":       c.Flow,
					}},
				}},
			},
			"streamSettings": buildStream(c),
		}},
	}, nil
}

func buildStream(c ClientConfig) map[string]any {
	if c.Network == "ws" {
		host := c.Host
		if host == "" {
			host = c.ServerName
		}
		return map[string]any{
			"network":  "ws",
			"security": "tls",
			"tlsSettings": map[string]any{
				"serverName":  c.ServerName,
				"fingerprint": c.Fingerprint,
			},
			"wsSettings": map[string]any{
				"path": hostPath(c),
				"headers": map[string]any{"Host": host},
			},
		}
	}
	return map[string]any{
		"network":  "tcp",
		"security": "reality",
		"realitySettings": map[string]any{
			"serverName":  c.ServerName,
			"fingerprint": c.Fingerprint,
			"publicKey":   c.PublicKey,
			"shortId":     c.ShortID,
			"spiderX":     c.SpiderX,
		},
	}
}

func hostPath(c ClientConfig) string {
	if c.Path != "" {
		return c.Path
	}
	return "/"
}

// WriteJSON writes the client config file (0600) and returns its path.
func WriteJSON(dir string, name string, c ClientConfig) (string, error) {
	if name == "" {
		name = "xray-client.json"
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	doc, err := BuildDocument(c)
	if err != nil {
		return "", err
	}
	path := filepath.Join(dir, name)
	b, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(path, b, 0600); err != nil {
		return "", err
	}
	return path, nil
}

func asInt(v any) (int, bool) {
	switch t := v.(type) {
	case float64:
		return int(t), true
	case int:
		return t, true
	case int64:
		return int(t), true
	case json.Number:
		n, err := t.Int64()
		return int(n), err == nil
	case string:
		n, err := strconv.Atoi(t)
		return n, err == nil
	default:
		return 0, false
	}
}

// ValidateDocument performs cheap structural checks (no xray binary required).
func ValidateDocument(doc Document) error {
	if len(doc.Outbounds) == 0 {
		return fmt.Errorf("xray: no outbounds")
	}
	ob := doc.Outbounds[0]
	if ob["protocol"] != "vless" {
		return fmt.Errorf("xray: expected vless outbound")
	}
	ss, _ := ob["streamSettings"].(map[string]any)
	if ss == nil {
		return fmt.Errorf("xray: missing streamSettings")
	}
	sec, _ := ss["security"].(string)
	if sec != "reality" && sec != "tls" {
		return fmt.Errorf("xray: expected reality or tls streamSettings")
	}
	return nil
}
