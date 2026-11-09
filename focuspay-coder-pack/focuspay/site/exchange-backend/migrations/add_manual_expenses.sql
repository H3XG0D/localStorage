-- Ручные расходы админки: обязательные / рабочие / непредвиденные

CREATE TABLE IF NOT EXISTS manual_expenses (
    id                     BIGSERIAL PRIMARY KEY,
    category               TEXT NOT NULL
        CHECK (category IN ('mandatory', 'work', 'unexpected')),
    amount_rub             NUMERIC(14, 2) NOT NULL
        CHECK (amount_rub > 0),
    operation_type         TEXT NOT NULL,
    created_by_web_user_id BIGINT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_manual_expenses_category_created
    ON manual_expenses (category, created_at DESC);

COMMENT ON TABLE manual_expenses IS 'Ручные расходы админки по категориям';

GRANT SELECT, INSERT, UPDATE, DELETE ON manual_expenses TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE manual_expenses_id_seq TO exchange_bot;
