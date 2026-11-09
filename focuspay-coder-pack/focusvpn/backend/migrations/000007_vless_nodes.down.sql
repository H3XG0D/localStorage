DROP TABLE IF EXISTS node_traffic_daily;
ALTER TABLE vpn_endpoints DROP COLUMN IF EXISTS xray;
DROP INDEX IF EXISTS uq_allocations_vless_uuid_live;
ALTER TABLE vpn_allocations DROP COLUMN IF EXISTS vless_uuid;
