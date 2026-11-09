-- Follow-up integrity for the casino financial/internal slice.
-- Safe to run repeatedly after migrations/add_casino_tables.sql.

BEGIN;

ALTER TABLE casino_games
    ADD COLUMN IF NOT EXISTS settlement_base_rub NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS payout_rub NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS creator_hold_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS opponent_hold_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS settlement_key VARCHAR(128);

UPDATE casino_games
SET settlement_base_rub = bet_rub
WHERE settlement_base_rub IS NULL;

COMMENT ON COLUMN casino_games.settlement_base_rub IS
    'Equal stake of one player and the losing-stake base used for commission';
COMMENT ON COLUMN casino_games.payout_rub IS
    'Persisted winner payout (two equal stakes minus commission)';
COMMENT ON COLUMN casino_games.creator_hold_id IS
    'Casino balance hold consumed for creator stake';
COMMENT ON COLUMN casino_games.opponent_hold_id IS
    'Casino balance hold consumed for opponent stake';
COMMENT ON COLUMN casino_games.settlement_key IS
    'Idempotency key for the atomic internal settlement';

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_games_settlement_key
    ON casino_games (settlement_key)
    WHERE settlement_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_games_creator_hold
    ON casino_games (creator_hold_id)
    WHERE creator_hold_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_games_opponent_hold
    ON casino_games (opponent_hold_id)
    WHERE opponent_hold_id IS NOT NULL;

ALTER TABLE casino_games DROP CONSTRAINT IF EXISTS casino_games_settlement_base_positive;
ALTER TABLE casino_games ADD CONSTRAINT casino_games_settlement_base_positive
    CHECK (settlement_base_rub IS NULL OR settlement_base_rub > 0) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_settlement_base_positive;

ALTER TABLE casino_games DROP CONSTRAINT IF EXISTS casino_games_payout_nonnegative;
ALTER TABLE casino_games ADD CONSTRAINT casino_games_payout_nonnegative
    CHECK (payout_rub IS NULL OR payout_rub >= 0) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_payout_nonnegative;

ALTER TABLE casino_balance_holds
    ADD COLUMN IF NOT EXISTS role VARCHAR(20),
    ADD COLUMN IF NOT EXISTS ledger_order_ref VARCHAR(64),
    ADD COLUMN IF NOT EXISTS operation_key VARCHAR(128);

COMMENT ON COLUMN casino_balance_holds.ledger_order_ref IS
    'Base order reference for cashback/referral/partner ledger hold rows';
COMMENT ON COLUMN casino_balance_holds.operation_key IS
    'Optional caller idempotency key for compatibility hold operations';

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_holds_ledger_order_ref
    ON casino_balance_holds (ledger_order_ref)
    WHERE ledger_order_ref IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_holds_operation_key
    ON casino_balance_holds (operation_key)
    WHERE operation_key IS NOT NULL;

ALTER TABLE casino_balance_holds DROP CONSTRAINT IF EXISTS casino_balance_holds_role_check;
ALTER TABLE casino_balance_holds ADD CONSTRAINT casino_balance_holds_role_check
    CHECK (role IS NULL OR role IN ('player', 'creator', 'opponent')) NOT VALID;
ALTER TABLE casino_balance_holds VALIDATE CONSTRAINT casino_balance_holds_role_check;

-- Financial history must never be silently removed. Existing duplicates require
-- a separately approved reconciliation before this integrity migration is run.
DO $block$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM casino_commission_ledger
        GROUP BY game_id, recipient_type
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'casino_commission_ledger contains duplicate (game_id, recipient_type) rows; reconcile them before applying this migration';
    END IF;
END
$block$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_commission_game_recipient_type
    ON casino_commission_ledger (game_id, recipient_type);

-- The proven unified-balance hold path needs hold/spend in every backing ledger.
DO $block$
BEGIN
    IF to_regclass('public.user_cashback_ledger') IS NOT NULL THEN
        ALTER TABLE user_cashback_ledger
            DROP CONSTRAINT IF EXISTS user_cashback_ledger_type_check;
        ALTER TABLE user_cashback_ledger
            ADD CONSTRAINT user_cashback_ledger_type_check
            CHECK (type IN ('accrual', 'spend', 'adjustment', 'remainder_credit', 'hold'));
    END IF;

    IF to_regclass('public.user_referral_ledger') IS NOT NULL THEN
        ALTER TABLE user_referral_ledger
            DROP CONSTRAINT IF EXISTS user_referral_ledger_type_check;
        ALTER TABLE user_referral_ledger
            ADD CONSTRAINT user_referral_ledger_type_check
            CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend'));
    END IF;

    IF to_regclass('public.partner_ledger') IS NOT NULL THEN
        ALTER TABLE partner_ledger
            DROP CONSTRAINT IF EXISTS partner_ledger_type_check;
        ALTER TABLE partner_ledger
            ADD CONSTRAINT partner_ledger_type_check
            CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend'));
    END IF;
END
$block$;

COMMIT;
