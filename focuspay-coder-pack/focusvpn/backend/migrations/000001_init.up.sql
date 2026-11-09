-- FocusVPN initial schema (Phase 2 / Milestone 2).
-- Source of truth: docs/DATABASE.md. Only the entities exercised through M2 are
-- created here; allocations/configurations/audit/telemetry arrive in later
-- migrations when their code paths land.

CREATE EXTENSION IF NOT EXISTS citext;

-- 2.1 users -----------------------------------------------------------------
CREATE TABLE users (
    id            uuid PRIMARY KEY,
    email         citext NOT NULL,
    password_hash text   NOT NULL,
    role          text   NOT NULL DEFAULT 'user'   CHECK (role IN ('user','admin')),
    status        text   NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deleted')),
    last_login_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_email UNIQUE (email)
);
CREATE INDEX idx_users_status ON users (status);

-- 2.3 plans -----------------------------------------------------------------
CREATE TABLE plans (
    id             uuid PRIMARY KEY,
    code           text   NOT NULL,
    name           text   NOT NULL,
    max_devices    int    NOT NULL,
    max_speed_mbps int,
    max_traffic_gb bigint,
    period_days    int    NOT NULL,
    price_cents    int    NOT NULL DEFAULT 0,
    features       jsonb  NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_plans_code UNIQUE (code)
);

-- 2.4 subscriptions ---------------------------------------------------------
CREATE TABLE subscriptions (
    id           uuid PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    plan_id      uuid NOT NULL REFERENCES plans (id),
    status       text NOT NULL CHECK (status IN ('trialing','active','expired','cancelled')),
    starts_at    timestamptz NOT NULL,
    ends_at      timestamptz NOT NULL,
    auto_renew   boolean NOT NULL DEFAULT false,
    provider     text,
    external_ref text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_subscriptions_user   ON subscriptions (user_id);
CREATE INDEX idx_subscriptions_status ON subscriptions (status);
CREATE INDEX idx_subscriptions_ends   ON subscriptions (ends_at);
-- At most one live subscription per user (DATABASE.md §2.4 invariant).
CREATE UNIQUE INDEX uq_subscriptions_live_user
    ON subscriptions (user_id) WHERE status IN ('trialing','active');

-- 2.5 vpn_nodes -------------------------------------------------------------
CREATE TABLE vpn_nodes (
    id                uuid PRIMARY KEY,
    name              text NOT NULL,
    country           text NOT NULL,
    region            text NOT NULL,
    state             text NOT NULL DEFAULT 'OFFLINE'
                          CHECK (state IN ('HEALTHY','DEGRADED','DRAINING','OFFLINE')),
    capacity          int  NOT NULL,
    ip                inet,
    hostname          text,
    os                text,
    kernel            text,
    agent_version     text,
    cert_serial       text,
    last_heartbeat_at timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_nodes_name UNIQUE (name)
);
CREATE INDEX idx_nodes_geo   ON vpn_nodes (country, region);
CREATE INDEX idx_nodes_state ON vpn_nodes (state);

-- 2.6 vpn_endpoints ---------------------------------------------------------
CREATE TABLE vpn_endpoints (
    id            uuid PRIMARY KEY,
    node_id       uuid NOT NULL REFERENCES vpn_nodes (id) ON DELETE CASCADE,
    protocol      text NOT NULL CHECK (protocol IN ('amneziawg','wireguard','reality')),
    port          int  NOT NULL,
    state         text NOT NULL DEFAULT 'OFFLINE'
                      CHECK (state IN ('HEALTHY','DEGRADED','DRAINING','OFFLINE')),
    public_key    bytea,
    obfuscation   jsonb,
    reality       jsonb,
    subnet        cidr NOT NULL,
    load          double precision NOT NULL DEFAULT 0,
    peer_count    int  NOT NULL DEFAULT 0,
    last_probe_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_endpoints_node_proto_port UNIQUE (node_id, protocol, port),
    -- AmneziaWG endpoints must carry Jc/Jmin/Jmax obfuscation (DECISIONS.md, API.md §7).
    CONSTRAINT ck_endpoints_awg_obfuscation
        CHECK (protocol <> 'amneziawg' OR obfuscation IS NOT NULL)
);
CREATE INDEX idx_endpoints_node        ON vpn_endpoints (node_id);
CREATE INDEX idx_endpoints_state_proto ON vpn_endpoints (state, protocol);

-- 2.2 devices ---------------------------------------------------------------
CREATE TABLE devices (
    id                uuid PRIMARY KEY,
    user_id           uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name              text NOT NULL,
    platform          text NOT NULL CHECK (platform IN ('android','ios','macos','windows','linux')),
    app_version       text,
    public_key        bytea NOT NULL,
    device_token_hash text  NOT NULL,
    status            text  NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
    last_seen_at      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    revoked_at        timestamptz,
    CONSTRAINT uq_devices_token_hash UNIQUE (device_token_hash)
);
CREATE INDEX idx_devices_user   ON devices (user_id);
CREATE INDEX idx_devices_status ON devices (status);
-- Active public keys are unique; revoked keys may be re-registered.
CREATE UNIQUE INDEX uq_devices_active_pubkey
    ON devices (public_key) WHERE status = 'active';

-- 3.1 refresh_tokens --------------------------------------------------------
CREATE TABLE refresh_tokens (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    family_id   uuid NOT NULL,
    token_hash  text NOT NULL,
    device_id   uuid REFERENCES devices (id) ON DELETE SET NULL,
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    replaced_by uuid REFERENCES refresh_tokens (id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_refresh_token_hash UNIQUE (token_hash)
);
CREATE INDEX idx_rt_user    ON refresh_tokens (user_id);
CREATE INDEX idx_rt_family  ON refresh_tokens (family_id);
CREATE INDEX idx_rt_expires ON refresh_tokens (expires_at);
