package tunnel

import (
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"strings"
)

// UAPIConfig formats an AmneziaWG userspace IPC "set" configuration
// (hex keys + jc/jmin/jmax + s1–s4 + h1–h4 + optional i1–i5).
// Compatible with amneziawg-go Device.IpcSet (pin v0.2.19).
func UAPIConfig(c Config) (string, error) {
	if c.Jc <= 0 || c.Jmin <= 0 || c.Jmax <= 0 {
		return "", fmt.Errorf("tunnel: Jc/Jmin/Jmax must be positive")
	}
	if c.H1 == "" || c.H2 == "" || c.H3 == "" || c.H4 == "" {
		return "", fmt.Errorf("tunnel: H1–H4 magic headers required")
	}
	if c.S1 < 0 || c.S2 < 0 || c.S3 < 0 || c.S4 < 0 {
		return "", fmt.Errorf("tunnel: S1–S4 must be non-negative")
	}
	return uapiConfig(c, true)
}

// UAPIConfigWireGuard formats a plain WireGuard IPC "set" (no AmneziaWG junk fields).
// Compatible with golang.zx2c4.com/wireguard Device.IpcSet.
func UAPIConfigWireGuard(c Config) (string, error) {
	return uapiConfig(c, false)
}

func uapiConfig(c Config, withObfuscation bool) (string, error) {
	privHex, err := b64KeyToHex(c.PrivateKey)
	if err != nil {
		return "", fmt.Errorf("tunnel: private key: %w", err)
	}
	pubHex, err := b64KeyToHex(c.PeerPubKey)
	if err != nil {
		return "", fmt.Errorf("tunnel: peer public key: %w", err)
	}
	if c.Endpoint == "" {
		return "", fmt.Errorf("tunnel: endpoint required")
	}
	allowed := c.AllowedIPs
	if len(allowed) == 0 {
		allowed = []string{"0.0.0.0/0", "::/0"}
	}

	var b strings.Builder
	b.WriteString("private_key=")
	b.WriteString(privHex)
	b.WriteByte('\n')
	if withObfuscation {
		fmt.Fprintf(&b, "jc=%d\n", c.Jc)
		fmt.Fprintf(&b, "jmin=%d\n", c.Jmin)
		fmt.Fprintf(&b, "jmax=%d\n", c.Jmax)
		fmt.Fprintf(&b, "s1=%d\n", c.S1)
		fmt.Fprintf(&b, "s2=%d\n", c.S2)
		fmt.Fprintf(&b, "s3=%d\n", c.S3)
		fmt.Fprintf(&b, "s4=%d\n", c.S4)
		fmt.Fprintf(&b, "h1=%s\n", c.H1)
		fmt.Fprintf(&b, "h2=%s\n", c.H2)
		fmt.Fprintf(&b, "h3=%s\n", c.H3)
		fmt.Fprintf(&b, "h4=%s\n", c.H4)
		for i, v := range []string{c.I1, c.I2, c.I3, c.I4, c.I5} {
			if v == "" {
				continue
			}
			fmt.Fprintf(&b, "i%d=%s\n", i+1, v)
		}
	}
	b.WriteString("replace_peers=true\n")
	b.WriteString("public_key=")
	b.WriteString(pubHex)
	b.WriteByte('\n')
	b.WriteString("endpoint=")
	b.WriteString(c.Endpoint)
	b.WriteByte('\n')
	b.WriteString("replace_allowed_ips=true\n")
	for _, ip := range allowed {
		b.WriteString("allowed_ip=")
		b.WriteString(ip)
		b.WriteByte('\n')
	}
	b.WriteString("persistent_keepalive_interval=25\n")
	return b.String(), nil
}

func b64KeyToHex(b64 string) (string, error) {
	raw, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return "", err
	}
	if len(raw) != 32 {
		return "", fmt.Errorf("want 32 bytes, got %d", len(raw))
	}
	return hex.EncodeToString(raw), nil
}
