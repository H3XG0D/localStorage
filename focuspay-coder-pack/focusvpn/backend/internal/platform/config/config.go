// Package config loads Control Plane configuration from environment variables.
// Secrets policy (SECURITY.md §4.2, DECISIONS.md): in dev, keys may be file-backed
// or ephemeral; in prod they must come from a Secret Manager. This package supports
// explicit seed/file and, for local dev only, ephemeral generation with a warning.
package config

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"strconv"
	"time"
)

// Config is the fully-resolved server configuration.
type Config struct {
	HTTPAddr    string
	Store       string // "memory" (tests/smoke) | "postgres" (real app path)
	DatabaseURL string // required when Store == "postgres"

	AccessTTL  time.Duration
	RefreshTTL time.Duration

	JWTPrivateKey ed25519.PrivateKey
	JWTPublicKey  ed25519.PublicKey
	TokenHMACKey  []byte

	// Config signing (distinct from JWT) — ADR-005 / plans/M3.
	ConfigSigningPrivateKey ed25519.PrivateKey
	ConfigSigningPublicKey  ed25519.PublicKey

	// Envelope KEK (file-backed in Phase 2).
	KEKID  string
	KEKKey []byte // 32 bytes

	// AllocationAutoActive is the approved A1 DEV stub: pending→active without agent.
	// Must stay false in production / once M4 agent confirm exists.
	AllocationAutoActive bool

	// Config TTL rotation (P4-M5 scheduler).
	SchedulerEnabled  bool
	SchedulerInterval time.Duration
	ConfigTTL         time.Duration

	// Internal service token for VPN bot / FocusPay federation (ADR-007).
	InternalToken string

	// Telegram bot @username for app deep links (without @).
	TelegramBotUsername string
	AppLoginTTL         time.Duration

	// PublicBase is the HTTPS origin of this API, without a trailing slash.
	// Subscription links for Happ are PublicBase + /v1/sub/<token>.
	PublicBase string

	// M4: node-agent mTLS listener.
	AgentAddr   string // default ":8443"; empty = disabled
	AgentCACert string // path to CA cert PEM (dev: secrets/ca.crt)
	AgentCAKey  string // path to CA key PEM (dev: secrets/ca.key)

	RateLimits RateLimits
}

// RateLimits are the approved MVP defaults (DECISIONS.md, SECURITY.md §6).
type RateLimits struct {
	RegisterPerHourPerIP     int
	LoginPerMinutePerIP      int
	LoginPerMinutePerAcct    int
	GeneralPerMinutePerToken int
}

// Load resolves configuration from the environment, applying documented defaults.
func Load() (Config, error) {
	c := Config{
		HTTPAddr:    getenv("FOCUSVPN_HTTP_ADDR", ":8080"),
		Store:       getenv("FOCUSVPN_STORE", "memory"),
		DatabaseURL: envLookup("FOCUSVPN_DATABASE_URL"),
		AccessTTL:   getdur("FOCUSVPN_ACCESS_TTL", 15*time.Minute),
		RefreshTTL:  getdur("FOCUSVPN_REFRESH_TTL", 30*24*time.Hour),
		RateLimits: RateLimits{
			RegisterPerHourPerIP:     getint("FOCUSVPN_RL_REGISTER_HOUR_IP", 5),
			LoginPerMinutePerIP:      getint("FOCUSVPN_RL_LOGIN_MIN_IP", 10),
			LoginPerMinutePerAcct:    getint("FOCUSVPN_RL_LOGIN_MIN_ACCT", 5),
			GeneralPerMinutePerToken: getint("FOCUSVPN_RL_GENERAL_MIN_TOKEN", 120),
		},
	}

	priv, pub, err := loadEd25519()
	if err != nil {
		return Config{}, fmt.Errorf("load jwt key: %w", err)
	}
	c.JWTPrivateKey = priv
	c.JWTPublicKey = pub

	c.TokenHMACKey, err = loadHMACKey()
	if err != nil {
		return Config{}, fmt.Errorf("load token hmac key: %w", err)
	}

	c.ConfigSigningPrivateKey, c.ConfigSigningPublicKey, err = loadConfigSigningKey()
	if err != nil {
		return Config{}, fmt.Errorf("load config signing key: %w", err)
	}

	c.KEKID, c.KEKKey, err = loadKEK()
	if err != nil {
		return Config{}, fmt.Errorf("load KEK: %w", err)
	}

	c.AllocationAutoActive = getbool("FOCUSVPN_ALLOCATION_AUTO_ACTIVE", false)
	if c.AllocationAutoActive {
		log.Println("WARN: FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true (DEV stub A1: allocations skip agent confirm)")
	}
	c.SchedulerEnabled = getbool("FOCUSVPN_SCHEDULER", true)
	c.SchedulerInterval = getdur("FOCUSVPN_SCHEDULER_INTERVAL", time.Minute)
	c.ConfigTTL = getdur("FOCUSVPN_CONFIG_TTL", 24*time.Hour)
	c.InternalToken = envLookup("FOCUSVPN_INTERNAL_TOKEN")
	if c.InternalToken == "" {
		log.Println("WARN: FOCUSVPN_INTERNAL_TOKEN unset — /v1/internal/* disabled")
	}
	c.TelegramBotUsername = getenv("FOCUSVPN_TELEGRAM_BOT_USERNAME", "FocusVPNBot")
	c.AppLoginTTL = getdur("FOCUSVPN_APP_LOGIN_TTL", 5*time.Minute)
	c.PublicBase = getenv("FOCUSVPN_PUBLIC_BASE", "https://focuspay.org/vpn-api")

	c.AgentAddr = getenv("FOCUSVPN_AGENT_ADDR", ":8443")
	if c.AgentAddr == "off" || c.AgentAddr == "-" || c.AgentAddr == "disabled" {
		c.AgentAddr = ""
	}
	c.AgentCACert = getenv("FOCUSVPN_AGENT_CA_CERT", "secrets/ca.crt")
	c.AgentCAKey = getenv("FOCUSVPN_AGENT_CA_KEY", "secrets/ca.key")

	return c, nil
}

func loadConfigSigningKey() (ed25519.PrivateKey, ed25519.PublicKey, error) {
	if seedB64 := envLookup("FOCUSVPN_CONFIG_SIGNING_SEED"); seedB64 != "" {
		seed, err := base64.StdEncoding.DecodeString(seedB64)
		if err != nil {
			return nil, nil, fmt.Errorf("decode FOCUSVPN_CONFIG_SIGNING_SEED: %w", err)
		}
		if len(seed) != ed25519.SeedSize {
			return nil, nil, fmt.Errorf("FOCUSVPN_CONFIG_SIGNING_SEED must be %d bytes", ed25519.SeedSize)
		}
		priv := ed25519.NewKeyFromSeed(seed)
		return priv, priv.Public().(ed25519.PublicKey), nil
	}
	path := getenv("FOCUSVPN_CONFIG_SIGNING_KEY_PATH", "secrets/config_signing_seed")
	if raw, err := os.ReadFile(path); err == nil {
		seed := bytesTrim(raw)
		if decoded, derr := base64.StdEncoding.DecodeString(string(seed)); derr == nil && len(decoded) == ed25519.SeedSize {
			seed = decoded
		}
		if len(seed) == ed25519.SeedSize {
			priv := ed25519.NewKeyFromSeed(seed)
			return priv, priv.Public().(ed25519.PublicKey), nil
		}
		return nil, nil, fmt.Errorf("%s must contain a %d-byte seed (raw or base64)", path, ed25519.SeedSize)
	}
	log.Println("WARN: config signing key not set; generating EPHEMERAL dev config signing key (do NOT use in production)")
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, nil, err
	}
	return priv, pub, nil
}

func loadKEK() (id string, key []byte, err error) {
	id = getenv("FOCUSVPN_KEK_ID", "kek-v1")
	if b64 := envLookup("FOCUSVPN_KEK"); b64 != "" {
		key, err = base64.StdEncoding.DecodeString(b64)
		if err != nil {
			return "", nil, fmt.Errorf("decode FOCUSVPN_KEK: %w", err)
		}
		if len(key) != 32 {
			return "", nil, fmt.Errorf("FOCUSVPN_KEK must be 32 bytes")
		}
		return id, key, nil
	}
	path := getenv("FOCUSVPN_KEK_PATH", "secrets/kek")
	if raw, rerr := os.ReadFile(path); rerr == nil {
		key = bytesTrim(raw)
		if decoded, derr := base64.StdEncoding.DecodeString(string(key)); derr == nil && len(decoded) == 32 {
			key = decoded
		}
		if len(key) != 32 {
			return "", nil, fmt.Errorf("%s must contain 32 raw bytes or base64", path)
		}
		return id, key, nil
	}
	log.Println("WARN: KEK not set; generating EPHEMERAL dev KEK (do NOT use in production)")
	key = make([]byte, 32)
	if _, err = rand.Read(key); err != nil {
		return "", nil, err
	}
	return id, key, nil
}

func bytesTrim(b []byte) []byte {
	for len(b) > 0 && (b[len(b)-1] == '\n' || b[len(b)-1] == '\r' || b[len(b)-1] == ' ') {
		b = b[:len(b)-1]
	}
	return b
}

func getbool(key string, def bool) bool {
	v := envLookup(key)
	if v == "" {
		return def
	}
	switch v {
	case "1", "true", "TRUE", "yes", "YES", "on", "ON":
		return true
	case "0", "false", "FALSE", "no", "NO", "off", "OFF":
		return false
	default:
		return def
	}
}

// loadEd25519 resolves the JWT signing key from (in order): base64 seed env,
// key file, or ephemeral dev key.
func loadEd25519() (ed25519.PrivateKey, ed25519.PublicKey, error) {
	if seedB64 := envLookup("FOCUSVPN_JWT_ED25519_SEED"); seedB64 != "" {
		seed, err := base64.StdEncoding.DecodeString(seedB64)
		if err != nil {
			return nil, nil, fmt.Errorf("decode FOCUSVPN_JWT_ED25519_SEED: %w", err)
		}
		if len(seed) != ed25519.SeedSize {
			return nil, nil, fmt.Errorf("FOCUSVPN_JWT_ED25519_SEED must be %d bytes", ed25519.SeedSize)
		}
		priv := ed25519.NewKeyFromSeed(seed)
		return priv, priv.Public().(ed25519.PublicKey), nil
	}
	if path := envLookup("FOCUSVPN_JWT_KEY_FILE"); path != "" {
		raw, err := os.ReadFile(path)
		if err != nil {
			return nil, nil, fmt.Errorf("read FOCUSVPN_JWT_KEY_FILE: %w", err)
		}
		seed := raw
		if decoded, derr := base64.StdEncoding.DecodeString(string(raw)); derr == nil && len(decoded) == ed25519.SeedSize {
			seed = decoded
		}
		if len(seed) != ed25519.SeedSize {
			return nil, nil, fmt.Errorf("key file must contain a %d-byte seed (raw or base64)", ed25519.SeedSize)
		}
		priv := ed25519.NewKeyFromSeed(seed)
		return priv, priv.Public().(ed25519.PublicKey), nil
	}
	log.Println("WARN: FOCUSVPN_JWT_ED25519_SEED/FOCUSVPN_JWT_KEY_FILE not set; generating EPHEMERAL dev JWT key (do NOT use in production)")
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, nil, err
	}
	return priv, pub, nil
}

func loadHMACKey() ([]byte, error) {
	if b64 := envLookup("FOCUSVPN_TOKEN_HMAC_KEY"); b64 != "" {
		key, err := base64.StdEncoding.DecodeString(b64)
		if err != nil {
			return nil, fmt.Errorf("decode FOCUSVPN_TOKEN_HMAC_KEY: %w", err)
		}
		if len(key) < 32 {
			return nil, fmt.Errorf("FOCUSVPN_TOKEN_HMAC_KEY must be >= 32 bytes")
		}
		return key, nil
	}
	log.Println("WARN: FOCUSVPN_TOKEN_HMAC_KEY not set; generating EPHEMERAL dev token HMAC key (do NOT use in production)")
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, err
	}
	return key, nil
}

func getenv(key, def string) string {
	if v := envLookup(key); v != "" {
		return v
	}
	return def
}

func getint(key string, def int) int {
	if v := envLookup(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func getdur(key string, def time.Duration) time.Duration {
	if v := envLookup(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

// envLookup reads FOCUSVPN_* and falls back to legacy MYVPN_* during rename.
func envLookup(key string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	if len(key) > 9 && key[:9] == "FOCUSVPN_" {
		return os.Getenv("MYVPN_" + key[9:])
	}
	return ""
}
