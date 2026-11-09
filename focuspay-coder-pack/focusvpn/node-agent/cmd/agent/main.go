// Command agent is the FocusVPN Node Agent (ADR-004).
//
// On first start: AGENT_NODE_TOKEN must be set. The agent registers with the
// Control Plane (POST /v1/agent/register) to obtain a mTLS certificate, then
// enters the main loop.
//
// Main loop:
//  1. Long-poll GET /v1/agent/state?since=N (30s server timeout).
//  2. On state change: diff and apply peers via `awg` subprocess.
//  3. Every AGENT_TELEMETRY_INTERVAL: POST /v1/agent/telemetry with applied
//     peer confirmations → CP transitions allocations pending→active.
//
// Required environment variables:
//
//	AGENT_NODE_ID    UUID of this node in the Control Plane
//	AGENT_CP_URL     Agent listener URL, e.g. https://cp.focusvpn.internal:8443
//
// Optional:
//
//	AGENT_NODE_TOKEN      One-time registration token (required on first start only)
//	AGENT_CERT_FILE       Path to store/load mTLS cert (default: secrets/agent.crt)
//	AGENT_KEY_FILE        Path to store/load mTLS key  (default: secrets/agent.key)
//	AGENT_CA_FILE         Path to CP CA cert           (default: secrets/ca.crt)
//	AGENT_INTERFACE       AmneziaWG interface name     (default: awg0)
//	AGENT_POLL_INTERVAL   Re-poll delay after state    (default: 5s)
//	AGENT_TELEMETRY_INTERVAL  Heartbeat interval       (default: 15s)
//	AGENT_XRAY_RESYNC_INTERVAL  Xray user re-apply     (default: 60s)
package main

import (
	"context"
	"errors"
	"log"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"

	"focusvpn.example/focusvpn/node-agent/internal/agentconfig"
	"focusvpn.example/focusvpn/node-agent/internal/applier"
	"focusvpn.example/focusvpn/node-agent/internal/mtls"
	"focusvpn.example/focusvpn/node-agent/internal/poller"
	"focusvpn.example/focusvpn/node-agent/internal/probe"
	"focusvpn.example/focusvpn/node-agent/internal/shaper"
	"focusvpn.example/focusvpn/node-agent/internal/telemetry"
	"focusvpn.example/focusvpn/node-agent/internal/xrayapplier"
)

func main() {
	cfg, err := agentconfig.Load()
	if err != nil {
		log.Fatalf("agent config: %v", err)
	}

	// --- Registration (first start) ------------------------------------------
	if needsRegistration(cfg) {
		if cfg.NodeToken == "" {
			log.Fatal("no mTLS cert found and AGENT_NODE_TOKEN not set; cannot register")
		}
		log.Printf("registering with CP at %s...", cfg.CPURL)
		if err := mtls.Register(cfg.CPURL, cfg.NodeToken, cfg.CertFile, cfg.KeyFile, cfg.CAFile); err != nil {
			log.Fatalf("registration: %v", err)
		}
		log.Println("registration complete")
	}

	// --- mTLS client ---------------------------------------------------------
	client, err := mtls.NewClient(cfg.CPURL, cfg.CertFile, cfg.KeyFile, cfg.CAFile)
	if err != nil {
		log.Fatalf("mtls client: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// --- Applier + Telemetry -------------------------------------------------
	telem := telemetry.New(client, cfg.NodeID, cfg.TelemetryInterval)
	var apply func(context.Context, poller.StateResponse) ([]string, error)
	switch cfg.Engine {
	case "xray":
		cli := xrayapplier.CLI{Bin: cfg.XrayBin, API: cfg.XrayAPI}
		xa := xrayapplier.New(cli, xrayTags(cfg.XrayTags))
		apply = xa.Apply
		go xa.Resync(ctx, cfg.XrayResyncInterval, telem.MarkApplied)
		iface := os.Getenv("AGENT_EGRESS_IFACE")
		if iface == "" {
			found, err := shaper.DefaultIface(ctx)
			if err != nil {
				log.Printf("shaper: egress device: %v", err)
			}
			iface = found
		}
		loop := &shaper.Loop{
			Source: cli,
			Apply:  shaper.NewApplier(shaper.ExecCommand, iface, "ifb-fvpn", cfg.LimitMbps),
			Max:    cfg.MaxShareIPs,
			Every:  cfg.LimitEvery,
		}
		go loop.Run(ctx)
		checks := probe.Live(cli.Ping, cfg.PublicHost)
		telem.SetCollector(func(ctx context.Context) (telemetry.Sample, error) {
			health := checks.Run(ctx)
			var shares []telemetry.Share
			for _, s := range loop.Shares() {
				shares = append(shares, telemetry.Share{AllocationID: s.Email, IPCount: s.Count})
			}
			online, down, up, err := xa.Sample(ctx)
			return telemetry.Sample{
				Online: online, Downlink: down, Uplink: up,
				Health: &telemetry.Health{OK: health.OK, Degraded: health.Degraded, Reason: health.Reason},
				Shares: shares,
			}, err
		})
	default:
		awg := applier.New(cfg.Interface)
		apply = awg.Apply
	}

	onState := func(ctx context.Context, state poller.StateResponse) error {
		applied, err := apply(ctx, state)
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Printf("applier: %v", err)
		}
		if len(applied) > 0 {
			telem.MarkApplied(applied)
		}
		return nil
	}

	// --- Poll loop -----------------------------------------------------------
	poll := poller.New(client, cfg.NodeID, cfg.PollInterval, onState)

	go telem.Run(ctx)
	log.Printf("node-agent started (node_id=%s, engine=%s, cp=%s)", cfg.NodeID, cfg.Engine, cfg.CPURL)
	poll.Run(ctx) // blocks until ctx cancelled
	log.Println("node-agent stopped")
}

// needsRegistration returns true if the mTLS cert file does not yet exist.
// xrayTags parses "name:port,name:port" or "name,name" (ports default to the
// localhost inbounds from scripts/node-vless-setup.sh).
func xrayTags(raw string) []xrayapplier.Tag {
	defaults := map[string]int{"vless-ws": 10000, "vless-xhttp": 10001}
	var tags []xrayapplier.Tag
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		name, portStr, hasPort := strings.Cut(part, ":")
		port := defaults[name]
		if hasPort {
			if p, err := strconv.Atoi(portStr); err == nil {
				port = p
			}
		}
		if port == 0 {
			port = 1
		}
		tags = append(tags, xrayapplier.Tag{Name: name, Port: port})
	}
	return tags
}

func needsRegistration(cfg agentconfig.Config) bool {
	_, err := os.Stat(cfg.CertFile)
	return os.IsNotExist(err)
}
