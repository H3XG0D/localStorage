-- Reverse of 000001_init. Drops in FK-safe order. The citext extension is left
-- in place intentionally (it may be shared by other objects).

DROP TABLE IF EXISTS refresh_tokens;
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS vpn_endpoints;
DROP TABLE IF EXISTS vpn_nodes;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS plans;
DROP TABLE IF EXISTS users;
