DROP INDEX IF EXISTS uq_allocations_vless_hash_live;
ALTER TABLE vpn_allocations DROP COLUMN IF EXISTS vless_uuid_hash;
ALTER TABLE vpn_allocations DROP COLUMN IF EXISTS vless_uuid_enc;

ALTER TABLE vpn_allocations ADD COLUMN vless_uuid uuid;
CREATE UNIQUE INDEX uq_allocations_vless_uuid_live
    ON vpn_allocations (vless_uuid) WHERE vless_uuid IS NOT NULL AND status IN ('pending','active');
