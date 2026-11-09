DROP TABLE IF EXISTS allocation_pauses;

ALTER TABLE vpn_nodes
    DROP COLUMN IF EXISTS status_reason,
    DROP COLUMN IF EXISTS health_fails,
    DROP COLUMN IF EXISTS probe_fails;
