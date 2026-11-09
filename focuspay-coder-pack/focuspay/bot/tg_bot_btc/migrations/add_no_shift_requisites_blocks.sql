-- Учёт попыток обмена, заблокированных из-за отсутствия операторов на смене.

CREATE TABLE IF NOT EXISTS no_shift_requisites_blocks (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    direction  VARCHAR(8) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_no_shift_blocks_created
    ON no_shift_requisites_blocks (created_at DESC);

GRANT SELECT, INSERT ON no_shift_requisites_blocks TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE no_shift_requisites_blocks_id_seq TO exchange_bot;
