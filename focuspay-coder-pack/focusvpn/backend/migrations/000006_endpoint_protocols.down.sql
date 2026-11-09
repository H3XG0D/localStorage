-- Revert to the 000001 protocol whitelist. Rows using Xray/VLESS protocols must be
-- removed first, otherwise the narrower constraint cannot be validated.

DELETE FROM vpn_endpoints WHERE protocol IN ('vless-ws', 'vless', 'xray');

ALTER TABLE vpn_endpoints DROP CONSTRAINT IF EXISTS vpn_endpoints_protocol_check;

ALTER TABLE vpn_endpoints
    ADD CONSTRAINT vpn_endpoints_protocol_check
    CHECK (protocol IN ('amneziawg', 'wireguard', 'reality'));
