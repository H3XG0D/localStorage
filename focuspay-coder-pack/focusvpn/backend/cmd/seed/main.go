// Command seed populates deterministic development data: plans, DE/NL/US nodes
// and AmneziaWG endpoints (unique Jc/Jmin/Jmax per node from API.md §7), and
// a DEV-ONLY admin user + subscription. It is idempotent: fixed UUIDs + upserts
// mean repeated runs never create duplicates.
//
//	seed -url postgres://user:pass@host:5432/db?sslmode=disable
//
// SECURITY: the admin credential here is a DEVELOPMENT-ONLY default. Override it
// with FOCUSVPN_SEED_ADMIN_PASSWORD; never use this seed against production.
package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/jackc/pgx/v5"

	"focusvpn.example/focusvpn/backend/internal/auth"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
)

// Deterministic identifiers (stable across runs => idempotent).
const (
	planFreeID      = "11111111-1111-1111-1111-111111111111"
	planProID       = "22222222-2222-2222-2222-222222222222"
	planBusinessID  = "33333333-3333-3333-3333-333333333333"
	nodeDE01ID      = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
	nodeNL01ID      = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
	nodeUS01ID      = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3"
	endpointAWGID   = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
	endpointNLID    = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"
	endpointUSID    = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3"
	endpointVLESSID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbc1"
	adminUserID     = "cccccccc-cccc-cccc-cccc-cccccccccccc"
	adminSubID      = "dddddddd-dddd-dddd-dddd-dddddddddddd"

	adminEmail = "admin@focusvpn.local" // reserved dev identity

	// Approved AmneziaWG obfuscation per node (API.md §7): Jc/Jmin/Jmax + H1–H4 + S1–S4 (+ optional I1).
	// Unique sets; H ranges must not overlap within a node.
	awgObfuscation   = `{"junk_packet_count":4,"junk_min_size":40,"junk_max_size":70,"init_packet_junk_size":15,"response_packet_junk_size":20,"cookie_reply_junk_size":10,"transport_packet_junk_size":5,"init_packet_magic_header":"100-110","response_packet_magic_header":"200-210","underload_packet_magic_header":"300-310","transport_packet_magic_header":"400-410","special_junk_i1":"<b 0xde01>"}`
	awgObfuscationNL = `{"junk_packet_count":5,"junk_min_size":50,"junk_max_size":80,"init_packet_junk_size":12,"response_packet_junk_size":18,"cookie_reply_junk_size":8,"transport_packet_junk_size":4,"init_packet_magic_header":"1000-1010","response_packet_magic_header":"1100-1110","underload_packet_magic_header":"1200-1210","transport_packet_magic_header":"1300-1310","special_junk_i1":"<b 0x4e4c01>"}`
	awgObfuscationUS = `{"junk_packet_count":3,"junk_min_size":30,"junk_max_size":60,"init_packet_junk_size":10,"response_packet_junk_size":16,"cookie_reply_junk_size":6,"transport_packet_junk_size":3,"init_packet_magic_header":"2000-2010","response_packet_magic_header":"2100-2110","underload_packet_magic_header":"2200-2210","transport_packet_magic_header":"2300-2310","special_junk_i1":"<b 0x555301>"}`
)

func main() {
	url := flag.String("url", os.Getenv("FOCUSVPN_DATABASE_URL"), "PostgreSQL URL (or FOCUSVPN_DATABASE_URL)")
	agentToken := flag.Bool("agent-token", false, "Generate and seed a one-time node agent registration token for DE-01 and print it")
	flag.Parse()
	if *url == "" {
		log.Fatal("missing -url (or FOCUSVPN_DATABASE_URL)")
	}

	adminPassword := os.Getenv("FOCUSVPN_SEED_ADMIN_PASSWORD")
	if adminPassword == "" {
		adminPassword = "dev-admin-change-me" // DEV-ONLY default
		log.Println("WARN: using DEV-ONLY default admin password; set FOCUSVPN_SEED_ADMIN_PASSWORD to override")
	}
	adminHash, err := auth.HashPassword(adminPassword)
	if err != nil {
		log.Fatalf("hash admin password: %v", err)
	}

	ctx := context.Background()
	conn, err := pgx.Connect(ctx, *url)
	if err != nil {
		log.Fatalf("connect: %v", err)
	}
	defer conn.Close(ctx)

	tx, err := conn.Begin(ctx)
	if err != nil {
		log.Fatalf("begin: %v", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	// --- plans (public configuration; DO UPDATE keeps them current) ----------
	const upsertPlan = `
	INSERT INTO plans (id, code, name, max_devices, max_speed_mbps, max_traffic_gb, period_days, price_cents, features)
	VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'{}'::jsonb)
	ON CONFLICT (id) DO UPDATE SET
	  code=EXCLUDED.code, name=EXCLUDED.name, max_devices=EXCLUDED.max_devices,
	  max_speed_mbps=EXCLUDED.max_speed_mbps, max_traffic_gb=EXCLUDED.max_traffic_gb,
	  period_days=EXCLUDED.period_days, price_cents=EXCLUDED.price_cents, updated_at=now()`
	mustExec(ctx, tx, upsertPlan, planFreeID, "free", "Free", 1, 10, int64(10), 36500, 0)
	mustExec(ctx, tx, upsertPlan, planProID, "pro", "Pro", 5, nil, nil, 30, 999)
	mustExec(ctx, tx, upsertPlan, planBusinessID, "business", "Business", 25, nil, nil, 30, 4999)
	mustExec(ctx, tx, upsertPlan, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4", "week", "Week", 1, nil, nil, 7, 30000)

	// --- nodes DE-01 / NL-01 / US-01 (P4-M4 multi-node seed) -----------------
	mustExec(ctx, tx, `
	INSERT INTO vpn_nodes (id, name, country, region, state, capacity, hostname)
	VALUES ($1,$2,$3,$4,'HEALTHY',$5,$6)
	ON CONFLICT (id) DO UPDATE SET
	  name=EXCLUDED.name, country=EXCLUDED.country, region=EXCLUDED.region,
	  capacity=EXCLUDED.capacity, hostname=EXCLUDED.hostname, updated_at=now()`,
		nodeDE01ID, "DE-01", "DE", "eu-central", 1000, "de-01.focusvpn.example")
	mustExec(ctx, tx, `
	INSERT INTO vpn_nodes (id, name, country, region, state, capacity, hostname)
	VALUES ($1,$2,$3,$4,'HEALTHY',$5,$6)
	ON CONFLICT (id) DO UPDATE SET
	  name=EXCLUDED.name, country=EXCLUDED.country, region=EXCLUDED.region,
	  capacity=EXCLUDED.capacity, hostname=EXCLUDED.hostname, updated_at=now()`,
		nodeNL01ID, "NL-01", "NL", "eu-west", 800, "nl-01.focusvpn.example")
	mustExec(ctx, tx, `
	INSERT INTO vpn_nodes (id, name, country, region, state, capacity, hostname)
	VALUES ($1,$2,$3,$4,'HEALTHY',$5,$6)
	ON CONFLICT (id) DO UPDATE SET
	  name=EXCLUDED.name, country=EXCLUDED.country, region=EXCLUDED.region,
	  capacity=EXCLUDED.capacity, hostname=EXCLUDED.hostname, updated_at=now()`,
		nodeUS01ID, "US-01", "US", "us-east", 900, "us-01.focusvpn.example")

	// --- AmneziaWG endpoints (distinct DEV pubkeys + subnets; unique Jc/Jmin/Jmax) ---
	// Approved A1 (plans/M3 §17): DEV-ONLY server public keys + HEALTHY so harnesses can
	// issue ConfigParts without a node-agent. Private keys are NEVER stored on CP.
	devServerPub := devPubKey(0x01)
	devServerPubNL := devPubKey(0x02)
	devServerPubUS := devPubKey(0x03)
	log.Println("WARN: seeding DEV-ONLY AmneziaWG server public keys + HEALTHY (A1 stub; not for production)")

	mustExec(ctx, tx, `
	INSERT INTO vpn_endpoints (id, node_id, protocol, port, state, public_key, obfuscation, subnet)
	VALUES ($1,$2,'amneziawg',$3,'HEALTHY',$4,$5::jsonb,$6::cidr)
	ON CONFLICT (id) DO UPDATE SET
	  node_id=EXCLUDED.node_id, protocol=EXCLUDED.protocol, port=EXCLUDED.port,
	  state=EXCLUDED.state, public_key=EXCLUDED.public_key,
	  obfuscation=EXCLUDED.obfuscation, subnet=EXCLUDED.subnet, updated_at=now()`,
		endpointAWGID, nodeDE01ID, 51820, devServerPub, awgObfuscation, "10.200.0.0/24")
	mustExec(ctx, tx, `
	INSERT INTO vpn_endpoints (id, node_id, protocol, port, state, public_key, obfuscation, subnet)
	VALUES ($1,$2,'amneziawg',$3,'HEALTHY',$4,$5::jsonb,$6::cidr)
	ON CONFLICT (id) DO UPDATE SET
	  node_id=EXCLUDED.node_id, protocol=EXCLUDED.protocol, port=EXCLUDED.port,
	  state=EXCLUDED.state, public_key=EXCLUDED.public_key,
	  obfuscation=EXCLUDED.obfuscation, subnet=EXCLUDED.subnet, updated_at=now()`,
		endpointNLID, nodeNL01ID, 51820, devServerPubNL, awgObfuscationNL, "10.201.0.0/24")
	mustExec(ctx, tx, `
	INSERT INTO vpn_endpoints (id, node_id, protocol, port, state, public_key, obfuscation, subnet)
	VALUES ($1,$2,'amneziawg',$3,'HEALTHY',$4,$5::jsonb,$6::cidr)
	ON CONFLICT (id) DO UPDATE SET
	  node_id=EXCLUDED.node_id, protocol=EXCLUDED.protocol, port=EXCLUDED.port,
	  state=EXCLUDED.state, public_key=EXCLUDED.public_key,
	  obfuscation=EXCLUDED.obfuscation, subnet=EXCLUDED.subnet, updated_at=now()`,
		endpointUSID, nodeUS01ID, 51820, devServerPubUS, awgObfuscationUS, "10.202.0.0/24")

	// --- VLESS+WS endpoint (default protocol; TLS on 443 via Nginx, Xray on 127.0.0.1:10000) ---
	mustExec(ctx, tx, `
	INSERT INTO vpn_endpoints (id, node_id, protocol, port, state, public_key, obfuscation, subnet, xray)
	VALUES ($1,$2,'vless',$3,'HEALTHY',$4,$5::jsonb,$6::cidr,$7::jsonb)
	ON CONFLICT (id) DO UPDATE SET
	  node_id=EXCLUDED.node_id, protocol=EXCLUDED.protocol, port=EXCLUDED.port,
	  state=EXCLUDED.state, public_key=EXCLUDED.public_key, xray=EXCLUDED.xray, updated_at=now()`,
		endpointVLESSID, nodeDE01ID, 443, devServerPub, "{}", "10.203.0.0/24", `{"transport":"ws","path":"/vpn"}`)

	// --- DEV-ONLY admin user (password never reset on re-run) ----------------
	mustExec(ctx, tx, `
	INSERT INTO users (id, email, password_hash, role, status)
	VALUES ($1,$2,$3,'admin','active')
	ON CONFLICT (id) DO NOTHING`,
		adminUserID, adminEmail, adminHash)

	// --- admin subscription (Business, live) ---------------------------------
	now := time.Now().UTC()
	mustExec(ctx, tx, `
	INSERT INTO subscriptions (id, user_id, plan_id, status, starts_at, ends_at, auto_renew)
	VALUES ($1,$2,$3,'active',$4,$5,true)
	ON CONFLICT (id) DO NOTHING`,
		adminSubID, adminUserID, planBusinessID, now, now.AddDate(1, 0, 0))

	// M4: Optionally generate a one-time node token for DE-01 agent registration.
	if *agentToken {
		rawToken := make([]byte, 32)
		if _, err := rand.Read(rawToken); err != nil {
			log.Fatalf("generate token: %v", err)
		}
		tokenStr := hex.EncodeToString(rawToken)
		hash := sha256.Sum256([]byte(tokenStr))
		tokenHash := hex.EncodeToString(hash[:])
		tokenID := id.NewUUID()
		mustExec(ctx, tx, `
		INSERT INTO node_tokens (id, node_id, token_hash, expires_at, created_at)
		VALUES ($1,$2,$3,$4,$5)
		ON CONFLICT DO NOTHING`,
			tokenID, nodeDE01ID, tokenHash, now.Add(24*time.Hour), now)
		if err := tx.Commit(ctx); err != nil {
			log.Fatalf("commit: %v", err)
		}
		fmt.Printf("\nAGENT_NODE_TOKEN=%s\n", tokenStr)
		fmt.Printf("(valid 24h, for node %s)\n", nodeDE01ID)
		return
	}

	if err := tx.Commit(ctx); err != nil {
		log.Fatalf("commit: %v", err)
	}
	log.Printf("seed applied: plans(free,pro,business), nodes DE/NL/US HEALTHY amneziawg (DEV pubkeys), admin=%s", adminEmail)
}

// devPubKey builds a distinct DEV-ONLY key of exactly 32 bytes (the WireGuard key
// size). nodeselector.Rank skips endpoints whose public_key is not 32 bytes, so a
// wrong length silently makes every node unselectable.
func devPubKey(tag byte) []byte {
	b := make([]byte, 32)
	for i := range b {
		b[i] = tag
	}
	return b
}

func mustExec(ctx context.Context, tx pgx.Tx, sql string, args ...any) {
	if _, err := tx.Exec(ctx, sql, args...); err != nil {
		log.Fatalf("seed exec failed: %v\nSQL: %s", err, sql)
	}
}
