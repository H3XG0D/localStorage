-- Why a node was taken out of the pool, and a short pause when one UUID
-- is seen from too many public addresses at once.

ALTER TABLE vpn_nodes
    ADD COLUMN status_reason text,
    ADD COLUMN health_fails integer NOT NULL DEFAULT 0,
    ADD COLUMN probe_fails integer NOT NULL DEFAULT 0;

CREATE TABLE allocation_pauses (
    allocation_id uuid PRIMARY KEY REFERENCES vpn_allocations (id) ON DELETE CASCADE,
    ip_count      integer NOT NULL,
    reason        text NOT NULL,
    until_at      timestamptz NOT NULL,
    node_id       uuid REFERENCES vpn_nodes (id) ON DELETE SET NULL,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_allocation_pauses_until ON allocation_pauses (until_at);
