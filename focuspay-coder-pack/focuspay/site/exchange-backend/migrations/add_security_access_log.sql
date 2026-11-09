CREATE TABLE IF NOT EXISTS security_access_log (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address INET NOT NULL,
    method VARCHAR(10) NOT NULL,
    path VARCHAR(512) NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    zone VARCHAR(20) NOT NULL,
    user_id BIGINT,
    operator_id BIGINT,
    scope VARCHAR(20),
    country_code VARCHAR(2),
    city VARCHAR(128),
    user_agent VARCHAR(2000),
    threat_type VARCHAR(40),
    threat_score INTEGER NOT NULL DEFAULT 0,
    extra JSONB
);

CREATE INDEX IF NOT EXISTS idx_security_access_log_created_at
    ON security_access_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_access_log_ip_address
    ON security_access_log (ip_address);
CREATE INDEX IF NOT EXISTS idx_security_access_log_threat_type
    ON security_access_log (threat_type)
    WHERE threat_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_security_access_log_zone
    ON security_access_log (zone, created_at DESC);

GRANT ALL PRIVILEGES ON TABLE security_access_log TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE security_access_log_id_seq TO exchange_bot;
