-- 000007: VLESS nodes (plans/E3-android-vless).
--
-- vless_uuid: per-allocation VLESS credential. Pushed to every Xray node so the
-- client can fail over between nodes with the same credential.
-- xray: transport settings of a VLESS endpoint
--   {"transport":"ws|xhttp","path":"/...","host":"cdn.example","sni":"...","port":443,"mode":"auto"}
-- node_traffic_daily: per-node traffic counters for reporting.

ALTER TABLE vpn_allocations ADD COLUMN vless_uuid uuid;
CREATE UNIQUE INDEX uq_allocations_vless_uuid_live
    ON vpn_allocations (vless_uuid) WHERE vless_uuid IS NOT NULL AND status IN ('pending','active');

ALTER TABLE vpn_endpoints ADD COLUMN xray jsonb;

CREATE TABLE node_traffic_daily (
    node_id   uuid   NOT NULL REFERENCES vpn_nodes (id) ON DELETE CASCADE,
    day       date   NOT NULL,
    rx_bytes  bigint NOT NULL DEFAULT 0,
    tx_bytes  bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (node_id, day)
);
