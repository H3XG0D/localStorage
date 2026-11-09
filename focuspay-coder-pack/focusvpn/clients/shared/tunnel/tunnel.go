// Package tunnel builds AmneziaWG configs from ConfigParts and drives awg/awg-quick
// as external processes (GPL tools are never linked — ADR-002). Shared by the Phase 2
// CLI harness and Phase 3 AppCore / Linux client.
package tunnel

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Config is the material needed to write an AmneziaWG interface file.
type Config struct {
	PrivateKey string // base64 client private key (never leaves the device)
	Address    string // e.g. 10.200.0.2/32
	DNS        []string
	MTU        int
	Jc         int
	Jmin       int
	Jmax       int
	// AmneziaWG 1.5/2.0-shaped params (amneziawg-go v0.2.19 UAPI: s1–s4, h1–h4, i1–i5).
	S1 int // init handshake padding
	S2 int // response padding
	S3 int // cookie padding
	S4 int // transport padding
	H1 string // magic header range/spec, e.g. "100-110"
	H2 string
	H3 string
	H4 string
	I1 string // optional CPS signature packets
	I2 string
	I3 string
	I4 string
	I5 string
	PeerPubKey string // base64 server public key
	Endpoint   string // host:port
	AllowedIPs []string
	Interface  string // e.g. focusvpn0
}

// FromParts maps ConfigParts JSON (API.md / connections.Service buildParts) into Config.
func FromParts(parts map[string]any, privateKeyB64, iface string) (Config, error) {
	if privateKeyB64 == "" {
		return Config{}, errors.New("tunnel: private key required")
	}
	if iface == "" {
		iface = "focusvpn0"
	}
	c := Config{PrivateKey: privateKeyB64, Interface: iface, MTU: 1420}

	ifaceMap, _ := parts["interface"].(map[string]any)
	peerMap, _ := parts["peer"].(map[string]any)
	protoMap, _ := parts["protocol"].(map[string]any)
	if ifaceMap == nil || peerMap == nil {
		return Config{}, errors.New("tunnel: missing interface/peer in parts")
	}

	c.Address, _ = ifaceMap["address"].(string)
	if c.Address == "" {
		return Config{}, errors.New("tunnel: missing interface.address")
	}
	if mtu, ok := asInt(ifaceMap["mtu"]); ok {
		c.MTU = mtu
	}
	c.DNS = asStringSlice(ifaceMap["dns"])

	c.PeerPubKey, _ = peerMap["server_public_key"].(string)
	c.Endpoint, _ = peerMap["endpoint"].(string)
	c.AllowedIPs = asStringSlice(peerMap["allowed_ips"])
	if c.PeerPubKey == "" || c.Endpoint == "" {
		return Config{}, errors.New("tunnel: missing peer.server_public_key or peer.endpoint")
	}
	if len(c.AllowedIPs) == 0 {
		c.AllowedIPs = []string{"0.0.0.0/0", "::/0"}
	}

	if protoMap != nil {
		if obf, ok := protoMap["obfuscation"].(map[string]any); ok {
			if v, ok := asInt(obf["junk_packet_count"]); ok {
				c.Jc = v
			}
			if v, ok := asInt(obf["junk_min_size"]); ok {
				c.Jmin = v
			}
			if v, ok := asInt(obf["junk_max_size"]); ok {
				c.Jmax = v
			}
			if v, ok := asInt(obf["init_packet_junk_size"]); ok {
				c.S1 = v
			}
			if v, ok := asInt(obf["response_packet_junk_size"]); ok {
				c.S2 = v
			}
			if v, ok := asInt(obf["cookie_reply_junk_size"]); ok {
				c.S3 = v
			}
			if v, ok := asInt(obf["transport_packet_junk_size"]); ok {
				c.S4 = v
			}
			c.H1 = asString(obf["init_packet_magic_header"])
			c.H2 = asString(obf["response_packet_magic_header"])
			c.H3 = asString(obf["underload_packet_magic_header"])
			c.H4 = asString(obf["transport_packet_magic_header"])
			c.I1 = asString(obf["special_junk_i1"])
			c.I2 = asString(obf["special_junk_i2"])
			c.I3 = asString(obf["special_junk_i3"])
			c.I4 = asString(obf["special_junk_i4"])
			c.I5 = asString(obf["special_junk_i5"])
		}
	}
	if c.Jc == 0 || c.Jmin == 0 || c.Jmax == 0 {
		return Config{}, errors.New("tunnel: AmneziaWG Jc/Jmin/Jmax required in protocol.obfuscation")
	}
	if c.H1 == "" || c.H2 == "" || c.H3 == "" || c.H4 == "" {
		return Config{}, errors.New("tunnel: AmneziaWG H1–H4 magic headers required in protocol.obfuscation")
	}
	if c.S1 < 0 || c.S2 < 0 || c.S3 < 0 || c.S4 < 0 {
		return Config{}, errors.New("tunnel: AmneziaWG S1–S4 must be non-negative")
	}
	return c, nil
}

// WriteConf writes an awg-quick-compatible .conf file and returns its path.
func WriteConf(dir string, c Config) (string, error) {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	path := filepath.Join(dir, c.Interface+".conf")
	var b strings.Builder
	b.WriteString("[Interface]\n")
	b.WriteString("PrivateKey = " + c.PrivateKey + "\n")
	b.WriteString("Address = " + c.Address + "\n")
	if len(c.DNS) > 0 {
		b.WriteString("DNS = " + strings.Join(c.DNS, ", ") + "\n")
	}
	if c.MTU > 0 {
		b.WriteString(fmt.Sprintf("MTU = %d\n", c.MTU))
	}
	b.WriteString(fmt.Sprintf("Jc = %d\n", c.Jc))
	b.WriteString(fmt.Sprintf("Jmin = %d\n", c.Jmin))
	b.WriteString(fmt.Sprintf("Jmax = %d\n", c.Jmax))
	b.WriteString(fmt.Sprintf("S1 = %d\n", c.S1))
	b.WriteString(fmt.Sprintf("S2 = %d\n", c.S2))
	b.WriteString(fmt.Sprintf("S3 = %d\n", c.S3))
	b.WriteString(fmt.Sprintf("S4 = %d\n", c.S4))
	b.WriteString("H1 = " + c.H1 + "\n")
	b.WriteString("H2 = " + c.H2 + "\n")
	b.WriteString("H3 = " + c.H3 + "\n")
	b.WriteString("H4 = " + c.H4 + "\n")
	if c.I1 != "" {
		b.WriteString("I1 = " + c.I1 + "\n")
	}
	if c.I2 != "" {
		b.WriteString("I2 = " + c.I2 + "\n")
	}
	if c.I3 != "" {
		b.WriteString("I3 = " + c.I3 + "\n")
	}
	if c.I4 != "" {
		b.WriteString("I4 = " + c.I4 + "\n")
	}
	if c.I5 != "" {
		b.WriteString("I5 = " + c.I5 + "\n")
	}
	b.WriteString("\n[Peer]\n")
	b.WriteString("PublicKey = " + c.PeerPubKey + "\n")
	b.WriteString("Endpoint = " + c.Endpoint + "\n")
	b.WriteString("AllowedIPs = " + strings.Join(c.AllowedIPs, ", ") + "\n")
	b.WriteString("PersistentKeepalive = 25\n")
	if err := os.WriteFile(path, []byte(b.String()), 0600); err != nil {
		return "", err
	}
	return path, nil
}

// Available reports whether awg and awg-quick are on PATH.
func Available() bool {
	_, e1 := exec.LookPath("awg")
	_, e2 := exec.LookPath("awg-quick")
	return e1 == nil && e2 == nil
}

// Up runs `awg-quick up <conf>`.
func Up(ctx context.Context, confPath string) error {
	return run(ctx, "awg-quick", "up", confPath)
}

// Down runs `awg-quick down <conf>`.
func Down(ctx context.Context, confPath string) error {
	return run(ctx, "awg-quick", "down", confPath)
}

// Handshake waits until awg show reports a non-zero latest handshake for iface.
func Handshake(ctx context.Context, iface string, timeout time.Duration) (time.Time, error) {
	deadline := time.Now().Add(timeout)
	for {
		if ctx.Err() != nil {
			return time.Time{}, ctx.Err()
		}
		ts, ok, err := latestHandshake(ctx, iface)
		if err != nil {
			return time.Time{}, err
		}
		if ok {
			return ts, nil
		}
		if time.Now().After(deadline) {
			return time.Time{}, fmt.Errorf("tunnel: handshake timeout after %s on %s", timeout, iface)
		}
		select {
		case <-ctx.Done():
			return time.Time{}, ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
}

var handshakeRe = regexp.MustCompile(`(?i)latest handshake:\s*(.+)`)

func latestHandshake(ctx context.Context, iface string) (time.Time, bool, error) {
	out, err := exec.CommandContext(ctx, "awg", "show", iface).CombinedOutput()
	if err != nil {
		return time.Time{}, false, fmt.Errorf("awg show %s: %w (%s)", iface, err, bytes.TrimSpace(out))
	}
	m := handshakeRe.FindSubmatch(out)
	if m == nil {
		return time.Time{}, false, nil
	}
	s := strings.TrimSpace(string(m[1]))
	if s == "" || strings.EqualFold(s, "(none)") || strings.HasPrefix(strings.ToLower(s), "0 ") {
		return time.Time{}, false, nil
	}
	// awg prints relative times like "1 minute, 2 seconds ago" — treat any non-empty as success.
	return time.Now().UTC(), true, nil
}

func run(ctx context.Context, name string, args ...string) error {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s %s: %w", name, strings.Join(args, " "), err)
	}
	return nil
}

func asInt(v any) (int, bool) {
	switch t := v.(type) {
	case float64:
		return int(t), true
	case json.Number:
		n, err := t.Int64()
		return int(n), err == nil
	case int:
		return t, true
	case int64:
		return int(t), true
	case string:
		n, err := strconv.Atoi(t)
		return n, err == nil
	default:
		return 0, false
	}
}

func asStringSlice(v any) []string {
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	var out []string
	for _, x := range arr {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func asString(v any) string {
	s, _ := v.(string)
	return strings.TrimSpace(s)
}

// MustDecodeKey validates a base64 32-byte key.
func MustDecodeKey(b64 string) error {
	raw, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return fmt.Errorf("tunnel: key base64: %w", err)
	}
	if len(raw) != 32 {
		return fmt.Errorf("tunnel: key must be 32 bytes, got %d", len(raw))
	}
	return nil
}
