-- FocusVPN Phase 2 · M3: allocations + configurations (docs/plans/M3.md, DATABASE.md §2.7–2.8).

CREATE TABLE vpn_allocations (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    device_id       uuid NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    endpoint_id     uuid NOT NULL REFERENCES vpn_endpoints (id),
    ip              inet NOT NULL,
    peer_public_key bytea NOT NULL,
    status          text NOT NULL CHECK (status IN ('pending','active','revoked','failed')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz
);
CREATE INDEX idx_allocations_user   ON vpn_allocations (user_id);
CREATE INDEX idx_allocations_device ON vpn_allocations (device_id);
CREATE UNIQUE INDEX uq_allocations_endpoint_ip_live
    ON vpn_allocations (endpoint_id, ip) WHERE status IN ('pending','active');
CREATE UNIQUE INDEX uq_allocations_device_endpoint_active
    ON vpn_allocations (device_id, endpoint_id) WHERE status = 'active';

CREATE TABLE vpn_configurations (
    id                uuid PRIMARY KEY,
    allocation_id     uuid NOT NULL REFERENCES vpn_allocations (id) ON DELETE CASCADE,
    device_id         uuid NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    version           int  NOT NULL,
    content_encrypted bytea NOT NULL,
    content_hash      bytea NOT NULL,
    signature         bytea NOT NULL,
    status            text  NOT NULL CHECK (status IN ('active','revoked')),
    rotated_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_configurations_allocation_version UNIQUE (allocation_id, version)
);
CREATE INDEX idx_configs_device  ON vpn_configurations (device_id);
CREATE INDEX idx_configs_status ON vpn_configurations (status);
-- At most one active config per allocation.
CREATE UNIQUE INDEX uq_configurations_allocation_active
    ON vpn_configurations (allocation_id) WHERE status = 'active';
