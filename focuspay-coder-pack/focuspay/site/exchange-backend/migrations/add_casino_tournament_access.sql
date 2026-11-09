-- Персональный доступ в турнир: белый список юзеров, которым вход открыт
-- без истории обменов (взнос/промокод турнира при этом остаются как настроены).

CREATE TABLE IF NOT EXISTS casino_tournament_access (
    id BIGSERIAL PRIMARY KEY,
    tournament_id BIGINT NOT NULL REFERENCES casino_tournaments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    note VARCHAR(300) NOT NULL DEFAULT '',
    granted_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_tournament_access_uniq UNIQUE (tournament_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_tournament_access_user
    ON casino_tournament_access (user_id, tournament_id DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT ALL PRIVILEGES ON TABLE casino_tournament_access TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE casino_tournament_access_id_seq TO exchange_bot;
    END IF;
END $$;
