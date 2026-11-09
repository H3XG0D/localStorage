-- 000006: allow Xray/VLESS endpoint protocols.
--
-- 000001 restricted vpn_endpoints.protocol to ('amneziawg','wireguard','reality'),
-- but connections.Service defaults to 'vless-ws' and accepts 'vless'/'xray' too.
-- The in-memory store has no constraint, so this only surfaced against Postgres
-- (seed failed with vpn_endpoints_protocol_check).

ALTER TABLE vpn_endpoints DROP CONSTRAINT IF EXISTS vpn_endpoints_protocol_check;

ALTER TABLE vpn_endpoints
    ADD CONSTRAINT vpn_endpoints_protocol_check
    CHECK (protocol IN ('amneziawg', 'wireguard', 'reality', 'vless-ws', 'vless', 'xray'));
