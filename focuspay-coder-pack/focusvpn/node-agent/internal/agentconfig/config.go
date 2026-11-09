// Package agentconfig loads node-agent configuration from environment variables.
package agentconfig

import (
	"errors"
	"os"
	"strconv"
	"time"
)

// Config is the fully resolved agent configuration.
type Config struct {
	// NodeToken is the one-time registration token (used only on first start).
	NodeToken string
	// NodeID is the UUID of this node in the Control Plane.
	NodeID string
	// CPURL is the base URL of the CP agent listener, e.g. https://cp.focusvpn.internal:8443
	CPURL string

	// mTLS cert/key paths. After registration the agent writes cert/key here.
	CertFile string
	KeyFile  string
	// CAFile is the CP CA cert used to verify the agent listener's TLS cert.
	CAFile string

	// Interface is the AmneziaWG network interface name, e.g. "awg0".
	Interface string

	// Engine is "awg" (AmneziaWG subprocess) or "xray" (Xray API on localhost).
	Engine string
	// XrayAPI is the Xray API listen address, e.g. 127.0.0.1:10085.
	XrayAPI string
	// XrayBin is the xray executable.
	XrayBin string
	// XrayTags are the VLESS inbound tags, comma-separated.
	XrayTags string
	// XrayResyncInterval re-applies the last desired user set to Xray.
	XrayResyncInterval time.Duration
	// PublicHost is the TLS name of this node (certificate and local probe).
	PublicHost string
	// LimitMbps is the per-UUID ceiling. LimitEvery is how often it is refreshed.
	LimitMbps  int
	LimitEvery time.Duration
	// MaxShareIPs is how many public addresses one UUID may use at once.
	MaxShareIPs int

	// PollInterval controls how quickly the agent re-polls after a state response.
	PollInterval time.Duration
	// TelemetryInterval controls how often the agent sends heartbeats.
	TelemetryInterval time.Duration
}

// Load resolves config from environment variables.
func Load() (Config, error) {
	c := Config{
		NodeToken:          os.Getenv("AGENT_NODE_TOKEN"),
		NodeID:             os.Getenv("AGENT_NODE_ID"),
		CPURL:              getenv("AGENT_CP_URL", "https://localhost:8443"),
		CertFile:           getenv("AGENT_CERT_FILE", "secrets/agent.crt"),
		KeyFile:            getenv("AGENT_KEY_FILE", "secrets/agent.key"),
		CAFile:             getenv("AGENT_CA_FILE", "secrets/ca.crt"),
		Interface:          getenv("AGENT_INTERFACE", "awg0"),
		Engine:             getenv("AGENT_ENGINE", "awg"),
		XrayAPI:            getenv("AGENT_XRAY_API", "127.0.0.1:10085"),
		XrayBin:            getenv("AGENT_XRAY_BIN", "xray"),
		XrayTags:           getenv("AGENT_XRAY_TAGS", "vless-ws,vless-xhttp"),
		XrayResyncInterval: getdur("AGENT_XRAY_RESYNC_INTERVAL", 60*time.Second),
		PublicHost:         os.Getenv("AGENT_PUBLIC_HOST"),
		LimitMbps:          getint("AGENT_LIMIT_MBPS", 100),
		LimitEvery:         getdur("AGENT_LIMIT_INTERVAL", 2*time.Second),
		MaxShareIPs:        getint("AGENT_MAX_SHARE_IPS", 3),
		PollInterval:       getdur("AGENT_POLL_INTERVAL", 5*time.Second),
		TelemetryInterval:  getdur("AGENT_TELEMETRY_INTERVAL", 15*time.Second),
	}
	if c.NodeID == "" {
		return Config{}, errors.New("AGENT_NODE_ID is required")
	}
	if c.CPURL == "" {
		return Config{}, errors.New("AGENT_CP_URL is required")
	}
	return c, nil
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getint(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return def
}

func getdur(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if secs, err := strconv.ParseFloat(v, 64); err == nil {
			return time.Duration(secs * float64(time.Second))
		}
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}
