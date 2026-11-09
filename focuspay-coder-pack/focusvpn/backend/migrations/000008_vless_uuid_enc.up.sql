-- 000008: VLESS UUID at rest is an encrypted envelope, not a plaintext uuid.
-- vless_uuid_hash is SHA-256 of the UUID (uniqueness only, not a credential).

ALTER TABLE vpn_allocations ADD COLUMN vless_uuid_enc bytea;
ALTER TABLE vpn_allocations ADD COLUMN vless_uuid_hash text;

DROP INDEX IF EXISTS uq_allocations_vless_uuid_live;
ALTER TABLE vpn_allocations DROP COLUMN IF EXISTS vless_uuid;

CREATE UNIQUE INDEX uq_allocations_vless_hash_live
    ON vpn_allocations (vless_uuid_hash)
    WHERE vless_uuid_hash IS NOT NULL AND status IN ('pending','active');
