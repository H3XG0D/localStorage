-- Живой джекпот-раунд должен быть один НА ОБЛАСТЬ КОШЕЛЬКА, а не один глобально.
-- Старый ux_casino_jackpot_live появился до wallet-scopes и ронял /casino/jackpot
-- в 500, когда игрок с турнирными фишками открывал экран при живом рублёвом раунде.
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.casino_jackpot_rounds') IS NULL THEN
        RETURN;
    END IF;

    DROP INDEX IF EXISTS ux_casino_jackpot_live;

    CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_jackpot_live_scope
        ON casino_jackpot_rounds (wallet_kind, COALESCE(tournament_id, 0))
        WHERE status IN ('open', 'locked');
END
$$;

COMMIT;
