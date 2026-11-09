-- Tiered weekly casino cashback. Apply after add_casino_tables.sql.
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.casino_player_cashback') IS NULL THEN
        RAISE EXCEPTION 'casino_player_cashback is required before weekly cashback tiers migration';
    END IF;
END $$;

-- NULL means the record predates the tiered policy. Existing rows are untouched.
ALTER TABLE casino_player_cashback
    ADD COLUMN IF NOT EXISTS eligible_loss_rub NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS cashback_percent NUMERIC(5, 2);

ALTER TABLE casino_player_cashback
    ALTER COLUMN cashback_percent DROP DEFAULT,
    ALTER COLUMN cashback_percent DROP NOT NULL;

ALTER TABLE casino_player_cashback
    DROP CONSTRAINT IF EXISTS casino_player_cashback_percent_check;
ALTER TABLE casino_player_cashback
    ADD CONSTRAINT casino_player_cashback_percent_check
    CHECK (cashback_percent IS NULL OR cashback_percent IN (5, 7, 9, 10, 15)) NOT VALID;
ALTER TABLE casino_player_cashback
    VALIDATE CONSTRAINT casino_player_cashback_percent_check;

ALTER TABLE casino_player_cashback
    DROP CONSTRAINT IF EXISTS casino_player_cashback_eligible_loss_check;
ALTER TABLE casino_player_cashback
    ADD CONSTRAINT casino_player_cashback_eligible_loss_check
    CHECK (eligible_loss_rub IS NULL OR eligible_loss_rub >= 0) NOT VALID;
ALTER TABLE casino_player_cashback
    VALIDATE CONSTRAINT casino_player_cashback_eligible_loss_check;

COMMENT ON COLUMN casino_player_cashback.eligible_loss_rub IS
    'Валовой eligible-проигрыш, использованный для tiered-кешбека; NULL для записей до политики';
COMMENT ON COLUMN casino_player_cashback.cashback_percent IS
    'Процент tiered-кешбека: <5000=5, <15000=7, <50000=9, <150000=10, >=150000=15; NULL до политики';
COMMENT ON TABLE casino_player_cashback IS
    'Недельный tiered-кешбек от проигранных ставок завершённых канонических игр казино';

COMMIT;
