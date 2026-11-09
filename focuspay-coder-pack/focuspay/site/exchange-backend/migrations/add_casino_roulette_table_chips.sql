-- Shared roulette table: one player may stack chips on many spots in the same round.
-- Apply after add_casino_roulette_table.sql. Repeat is a no-op.
BEGIN;

ALTER TABLE casino_roulette_bets
    DROP CONSTRAINT IF EXISTS casino_roulette_bets_round_pk_user_id_key;

DROP INDEX IF EXISTS casino_roulette_bets_round_pk_user_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_roulette_bets_spot
    ON casino_roulette_bets (round_pk, user_id, bet);

COMMENT ON INDEX ux_casino_roulette_bets_spot IS
    'One stacked chip pile per player per felt spot; red and 22 are separate rows.';

COMMIT;
