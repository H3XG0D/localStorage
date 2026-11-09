-- Player seed-pair sessions for provably fair cards (task 7).
-- Rotation reveals the previous server seed. Repeat-safe on existing staging.

BEGIN;

CREATE TABLE IF NOT EXISTS casino_fairness_seeds (
    telegram_id BIGINT PRIMARY KEY,
    server_seed VARCHAR(128) NOT NULL,
    commit_hash VARCHAR(128) NOT NULL,
    client_seed VARCHAR(64) NOT NULL DEFAULT 'focuspay',
    nonce BIGINT NOT NULL DEFAULT 0,
    previous_server_seed VARCHAR(128),
    previous_commit VARCHAR(128),
    rotated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_fairness_seeds_nonce_nonneg CHECK (nonce >= 0)
);

ALTER TABLE casino_house_rng_commits
    ADD COLUMN IF NOT EXISTS client_seed VARCHAR(64) NOT NULL DEFAULT 'focuspay';

COMMIT;
