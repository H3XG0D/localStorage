// Command focusvpn-cli is the Phase 2 CLI harness used to drive and verify the
// Control Plane vertical slice end-to-end (ROADMAP §1, DECISIONS.md "Phase 2 E2E").
// It is NOT a product client (those arrive in Phase 3).
package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/crypto/curve25519"

	"focusvpn.example/focusvpn/clients/shared/apitypes"
	"focusvpn.example/focusvpn/clients/shared/configcrypto"
	"focusvpn.example/focusvpn/clients/shared/tunnel"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	cmd := os.Args[1]
	args := os.Args[2:]

	var err error
	switch cmd {
	case "health":
		err = cmdHealth(args)
	case "register":
		err = cmdRegister(args)
	case "login":
		err = cmdLogin(args)
	case "refresh":
		err = cmdRefresh(args)
	case "me":
		err = cmdMe(args)
	case "logout":
		err = cmdLogout(args)
	case "device-add":
		err = cmdDeviceAdd(args)
	case "device-list":
		err = cmdDeviceList(args)
	case "servers":
		err = cmdServers(args)
	case "connect":
		err = cmdConnect(args)
	case "disconnect":
		err = cmdDisconnect(args)
	case "config":
		err = cmdConfig(args)
	case "keygen":
		err = cmdKeygen(args)
	case "tunnel-up":
		err = cmdTunnelUp(args)
	case "tunnel-down":
		err = cmdTunnelDown(args)
	case "handshake":
		err = cmdHandshake(args)
	case "-h", "--help", "help":
		usage()
		return
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", cmd)
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `focusvpn-cli — Phase 2 vertical-slice harness

Usage:
  focusvpn-cli health   --api URL
  focusvpn-cli register --api URL --email E --password P
  focusvpn-cli login    --api URL --email E --password P
  focusvpn-cli refresh  --api URL --refresh TOKEN
  focusvpn-cli me          --api URL --access TOKEN
  focusvpn-cli logout      --api URL --refresh TOKEN
  focusvpn-cli device-add  --api URL --access TOKEN --name N --platform P --pubkey BASE64
  focusvpn-cli device-list --api URL --access TOKEN
  focusvpn-cli servers     --api URL --access TOKEN
  focusvpn-cli connect     --api URL --access TOKEN --device-id ID [--protocol amneziawg]
  focusvpn-cli disconnect  --api URL --access TOKEN --id CONNECTION_ID
  focusvpn-cli config      --api URL --device-token TOKEN --id CONFIG_ID
  focusvpn-cli keygen      [--out-dir DIR]
  focusvpn-cli tunnel-up   --api URL --access TOKEN --device-id ID --device-token TOKEN \
                        --private-key BASE64 [--iface NAME] [--conf-dir DIR] [--dry-run] \
                        [--verify-pubkey BASE64] [--wait-handshake DUR]
  focusvpn-cli tunnel-down --api URL --access TOKEN --id CONNECTION_ID \
                        [--conf PATH] [--iface NAME] [--dry-run]
  focusvpn-cli handshake   --iface NAME [--timeout DUR]
`)
}

func cmdHealth(args []string) error {
	fs := flag.NewFlagSet("health", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	_ = fs.Parse(args)
	return doJSON(http.MethodGet, *api+"/v1/health", nil, "")
}

func cmdRegister(args []string) error {
	fs := flag.NewFlagSet("register", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	email := fs.String("email", "", "email")
	password := fs.String("password", "", "password")
	_ = fs.Parse(args)
	body := map[string]string{"email": *email, "password": *password}
	return doJSON(http.MethodPost, *api+"/v1/auth/register", body, "")
}

func cmdLogin(args []string) error {
	fs := flag.NewFlagSet("login", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	email := fs.String("email", "", "email")
	password := fs.String("password", "", "password")
	_ = fs.Parse(args)
	body := map[string]string{"email": *email, "password": *password}
	return doJSON(http.MethodPost, *api+"/v1/auth/login", body, "")
}

func cmdRefresh(args []string) error {
	fs := flag.NewFlagSet("refresh", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	refresh := fs.String("refresh", "", "refresh token")
	_ = fs.Parse(args)
	// API.md §2: refresh token is sent as Authorization: Bearer.
	return doJSON(http.MethodPost, *api+"/v1/auth/refresh", nil, *refresh)
}

func cmdMe(args []string) error {
	fs := flag.NewFlagSet("me", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	_ = fs.Parse(args)
	return doJSON(http.MethodGet, *api+"/v1/me", nil, *access)
}

func cmdLogout(args []string) error {
	fs := flag.NewFlagSet("logout", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	refresh := fs.String("refresh", "", "refresh token")
	_ = fs.Parse(args)
	body := map[string]string{"refresh_token": *refresh}
	return doJSON(http.MethodPost, *api+"/v1/auth/logout", body, "")
}

func cmdDeviceAdd(args []string) error {
	fs := flag.NewFlagSet("device-add", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	name := fs.String("name", "cli", "device name")
	platform := fs.String("platform", "linux", "platform")
	pubkey := fs.String("pubkey", "", "base64 x25519 public key")
	_ = fs.Parse(args)
	body := map[string]string{"name": *name, "platform": *platform, "public_key": *pubkey}
	return doJSON(http.MethodPost, *api+"/v1/devices", body, *access)
}

func cmdDeviceList(args []string) error {
	fs := flag.NewFlagSet("device-list", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	_ = fs.Parse(args)
	return doJSON(http.MethodGet, *api+"/v1/devices", nil, *access)
}

func cmdServers(args []string) error {
	fs := flag.NewFlagSet("servers", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	_ = fs.Parse(args)
	return doJSON(http.MethodGet, *api+"/v1/servers", nil, *access)
}

func cmdConnect(args []string) error {
	fs := flag.NewFlagSet("connect", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	deviceID := fs.String("device-id", "", "device id")
	protocol := fs.String("protocol", "amneziawg", "protocol")
	_ = fs.Parse(args)
	body := map[string]string{"device_id": *deviceID, "protocol": *protocol}
	return doJSON(http.MethodPost, *api+"/v1/connections", body, *access)
}

func cmdDisconnect(args []string) error {
	fs := flag.NewFlagSet("disconnect", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	id := fs.String("id", "", "connection id")
	_ = fs.Parse(args)
	return doJSON(http.MethodDelete, *api+"/v1/connections/"+*id, nil, *access)
}

func cmdConfig(args []string) error {
	fs := flag.NewFlagSet("config", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	deviceToken := fs.String("device-token", "", "device token")
	id := fs.String("id", "", "config id")
	_ = fs.Parse(args)
	raw, status, err := doRaw(http.MethodGet, *api+"/v1/configurations/"+*id, nil, "", *deviceToken)
	if err != nil {
		return err
	}
	os.Stdout.Write(raw)
	if len(raw) == 0 || raw[len(raw)-1] != '\n' {
		fmt.Println()
	}
	if status < 200 || status >= 300 {
		return fmt.Errorf("HTTP %d", status)
	}
	return nil
}

// cmdKeygen generates an x25519 keypair. Private key never leaves the device.
func cmdKeygen(args []string) error {
	fs := flag.NewFlagSet("keygen", flag.ExitOnError)
	outDir := fs.String("out-dir", "", "optional directory to write private.key / public.key")
	_ = fs.Parse(args)

	var priv [32]byte
	if _, err := rand.Read(priv[:]); err != nil {
		return err
	}
	// Clamp per X25519 (RFC 7748).
	priv[0] &= 248
	priv[31] &= 127
	priv[31] |= 64
	var pub [32]byte
	curve25519.ScalarBaseMult(&pub, &priv)

	privB64 := base64.StdEncoding.EncodeToString(priv[:])
	pubB64 := base64.StdEncoding.EncodeToString(pub[:])

	if *outDir != "" {
		if err := os.MkdirAll(*outDir, 0700); err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(*outDir, "private.key"), []byte(privB64+"\n"), 0600); err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(*outDir, "public.key"), []byte(pubB64+"\n"), 0644); err != nil {
			return err
		}
	}
	enc := json.NewEncoder(os.Stdout)
	return enc.Encode(map[string]string{
		"private_key": privB64,
		"public_key":  pubB64,
	})
}

// cmdTunnelUp: POST /connections → GET /configurations → write .conf → awg-quick up.
func cmdTunnelUp(args []string) error {
	fs := flag.NewFlagSet("tunnel-up", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	deviceID := fs.String("device-id", "", "device id")
	deviceToken := fs.String("device-token", "", "device token")
	privKey := fs.String("private-key", "", "base64 client private key")
	iface := fs.String("iface", "focusvpn0", "interface name")
	confDir := fs.String("conf-dir", "", "directory for .conf (default: temp)")
	dryRun := fs.Bool("dry-run", false, "write .conf only; do not call awg-quick")
	verifyPub := fs.String("verify-pubkey", "", "optional Ed25519 config-signing public key (base64)")
	waitHS := fs.Duration("wait-handshake", 0, "if >0 and not dry-run, wait for handshake")
	protocol := fs.String("protocol", "amneziawg", "protocol")
	_ = fs.Parse(args)

	if *access == "" || *deviceID == "" || *deviceToken == "" || *privKey == "" {
		return fmt.Errorf("tunnel-up requires --access --device-id --device-token --private-key")
	}
	if err := tunnel.MustDecodeKey(*privKey); err != nil {
		return err
	}

	connBody := map[string]string{"device_id": *deviceID, "protocol": *protocol}
	connRaw, status, err := doRaw(http.MethodPost, *api+"/v1/connections", connBody, *access, "")
	if err != nil {
		return err
	}
	if status < 200 || status >= 300 {
		os.Stdout.Write(connRaw)
		return fmt.Errorf("connect HTTP %d", status)
	}
	var connResp apitypes.CreateConnectionResponse
	if err := json.Unmarshal(connRaw, &connResp); err != nil {
		return fmt.Errorf("decode connect: %w", err)
	}
	if connResp.ConfigID == "" {
		return fmt.Errorf("connect response missing config_id")
	}

	cfgRaw, status, err := doRaw(http.MethodGet, *api+"/v1/configurations/"+connResp.ConfigID, nil, "", *deviceToken)
	if err != nil {
		return err
	}
	if status < 200 || status >= 300 {
		os.Stdout.Write(cfgRaw)
		return fmt.Errorf("config HTTP %d", status)
	}
	var partsResp apitypes.ConfigPartsResponse
	if err := json.Unmarshal(cfgRaw, &partsResp); err != nil {
		return fmt.Errorf("decode config: %w", err)
	}

	if *verifyPub != "" {
		pubRaw, err := base64.StdEncoding.DecodeString(*verifyPub)
		if err != nil || len(pubRaw) != ed25519.PublicKeySize {
			return fmt.Errorf("invalid --verify-pubkey")
		}
		sig, err := base64.StdEncoding.DecodeString(partsResp.Signature)
		if err != nil {
			return fmt.Errorf("signature base64: %w", err)
		}
		if err := configcrypto.VerifyParts(ed25519.PublicKey(pubRaw), partsResp.ConfigVersion, partsResp.Parts, sig); err != nil {
			return fmt.Errorf("config signature verify: %w", err)
		}
	}

	tc, err := tunnel.FromParts(partsResp.Parts, *privKey, *iface)
	if err != nil {
		return err
	}
	dir := *confDir
	if dir == "" {
		dir, err = os.MkdirTemp("", "focusvpn-conf-*")
		if err != nil {
			return err
		}
	}
	confPath, err := tunnel.WriteConf(dir, tc)
	if err != nil {
		return err
	}

	out := map[string]any{
		"connection_id": connResp.Connection.ID,
		"status":        connResp.Connection.Status,
		"config_id":     connResp.ConfigID,
		"conf_path":     confPath,
		"iface":         *iface,
		"dry_run":       *dryRun,
	}

	if *dryRun {
		out["message"] = "conf written; awg-quick skipped (--dry-run)"
		return json.NewEncoder(os.Stdout).Encode(out)
	}
	if !tunnel.Available() {
		out["message"] = "conf written; awg/awg-quick not on PATH — install AmneziaWG tools for real tunnel"
		_ = json.NewEncoder(os.Stdout).Encode(out)
		return fmt.Errorf("awg/awg-quick not available")
	}
	ctx := context.Background()
	if err := tunnel.Up(ctx, confPath); err != nil {
		return err
	}
	out["tunnel"] = "up"
	if *waitHS > 0 {
		ts, err := tunnel.Handshake(ctx, *iface, *waitHS)
		if err != nil {
			_ = json.NewEncoder(os.Stdout).Encode(out)
			return err
		}
		out["handshake_at"] = ts.Format(time.RFC3339)
	}
	return json.NewEncoder(os.Stdout).Encode(out)
}

func cmdTunnelDown(args []string) error {
	fs := flag.NewFlagSet("tunnel-down", flag.ExitOnError)
	api := fs.String("api", "http://localhost:8080", "control plane base URL")
	access := fs.String("access", "", "access token")
	id := fs.String("id", "", "connection id")
	conf := fs.String("conf", "", "path to .conf for awg-quick down")
	dryRun := fs.Bool("dry-run", false, "skip awg-quick; only DELETE connection")
	_ = fs.Parse(args)

	if *access == "" || *id == "" {
		return fmt.Errorf("tunnel-down requires --access --id")
	}
	if !*dryRun && *conf != "" {
		if tunnel.Available() {
			if err := tunnel.Down(context.Background(), *conf); err != nil {
				fmt.Fprintf(os.Stderr, "warn: awg-quick down: %v\n", err)
			}
		}
	}
	return doJSON(http.MethodDelete, *api+"/v1/connections/"+*id, nil, *access)
}

func cmdHandshake(args []string) error {
	fs := flag.NewFlagSet("handshake", flag.ExitOnError)
	iface := fs.String("iface", "focusvpn0", "interface name")
	timeout := fs.Duration("timeout", 15*time.Second, "wait timeout")
	_ = fs.Parse(args)
	if !tunnel.Available() {
		return fmt.Errorf("awg not on PATH")
	}
	ts, err := tunnel.Handshake(context.Background(), *iface, *timeout)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{
		"iface":        *iface,
		"handshake_at": ts.Format(time.RFC3339),
		"status":       "ok",
	})
}

func doJSON(method, url string, body any, bearer string) error {
	raw, status, err := doRaw(method, url, body, bearer, "")
	if err != nil {
		return err
	}
	os.Stdout.Write(raw)
	if len(raw) == 0 || raw[len(raw)-1] != '\n' {
		fmt.Println()
	}
	if status < 200 || status >= 300 {
		return fmt.Errorf("HTTP %d", status)
	}
	return nil
}

func doRaw(method, url string, body any, bearer, deviceToken string) ([]byte, int, error) {
	var rdr io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		if err != nil {
			return nil, 0, err
		}
		rdr = bytes.NewReader(buf)
	}
	req, err := http.NewRequest(method, url, rdr)
	if err != nil {
		return nil, 0, err
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
	client := &http.Client{Timeout: 35 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	return raw, resp.StatusCode, nil
}
