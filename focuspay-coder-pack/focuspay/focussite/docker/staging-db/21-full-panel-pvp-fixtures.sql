BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM bot_users WHERE user_id IN (941001, 941002))
       OR EXISTS (SELECT 1 FROM casino_games WHERE game_id IN ('fixture-full-pvp-finished-001', 'fixture-full-pvp-recovery-001'))
       OR EXISTS (SELECT 1 FROM casino_game_chat_bindings WHERE chat_id = -1001234567801) THEN
        RAISE EXCEPTION 'synthetic full-panel-pvp fixture already exists; use a new disposable database instead of replaying it';
    END IF;
END $$;

ALTER TABLE staging_fixture_roles
    DROP CONSTRAINT staging_fixture_roles_fixture_role_check;
ALTER TABLE staging_fixture_roles
    ADD CONSTRAINT staging_fixture_roles_fixture_role_check CHECK (fixture_role IN (
        'admin', 'buyer', 'client_operator', 'finance_operator', 'partner', 'external_exchanger',
        'player_a', 'player_b'
    ));

INSERT INTO bot_users (user_id, username, first_name, ref_token) VALUES
    (941001, 'fixture_full_pvp_player_a', 'Fixture PvP Player A', 'fixture-pvp-a'),
    (941002, 'fixture_full_pvp_player_b', 'Fixture PvP Player B', 'fixture-pvp-b');

INSERT INTO staging_fixture_roles (subject_kind, subject_id, fixture_role) VALUES
    ('telegram_user', 941001, 'player_a'),
    ('telegram_user', 941002, 'player_b');

UPDATE casino_settings
SET value = jsonb_set(value, '{raffle}', 'false'::jsonb, true), updated_at = now()
WHERE key = 'enabled_games';

INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note) VALUES
    (941001, 'accrual', 500.00, 'fixture-full-pvp-a-credit', 'Synthetic full-panel PvP funding only'),
    (941002, 'accrual', 500.00, 'fixture-full-pvp-b-credit', 'Synthetic full-panel PvP funding only'),
    (941001, 'hold', -100.00, 'hold-fixture-full-pvp-a', 'Synthetic full-panel PvP recovery hold'),
    (941002, 'hold', -100.00, 'hold-fixture-full-pvp-b', 'Synthetic full-panel PvP recovery hold');

INSERT INTO casino_game_chat_bindings (
    chat_id, chat_type, chat_title, status, requested_by_telegram_id,
    confirmed_by_admin_id, confirmed_at, telegram_url
) VALUES (
    -1001234567801, 'supergroup', 'Fixture Full Panel PvP Lobby', 'active', 941001,
    940001, now(), 'https://t.me/focuspay_staging_fixture'
);

INSERT INTO casino_games (
    game_id, game_type, creator_id, opponent_id, bet_rub, commission_rub,
    winner_id, status, game_data, settlement_base_rub, state_version,
    game_state, outcome, outcome_committed_at, started_at, finished_at,
    creator_hold_id, opponent_hold_id
) VALUES (
    'fixture-full-pvp-finished-001', 'pvp_dice', 941001, 941002, 100.00, 15.00,
    941001, 'finished',
    '{"pricing_snapshot":{"allocation_model":"stake_percent_v2","commission_rate":"15.00"}}'::jsonb,
    100.00, 1, '{"fixture":"full_panel_finished"}'::jsonb,
    '{"kind":"winner","source":"synthetic_fixture"}'::jsonb, now() - interval '2 hours',
    now() - interval '2 hours', now() - interval '90 minutes', NULL, NULL
), (
    'fixture-full-pvp-recovery-001', 'pvp_dice', 941001, 941002, 100.00, 15.00,
    941001, 'outcome_committed',
    '{"pricing_snapshot":{"allocation_model":"stake_percent_v2","commission_rate":"15.00"}}'::jsonb,
    100.00, 1, '{"fixture":"durable_recovery"}'::jsonb,
    '{"kind":"winner","source":"synthetic_fixture"}'::jsonb, now(), now(), NULL,
    'casino-fixture-full-pvp-recovery-creator', 'casino-fixture-full-pvp-recovery-opponent'
);

INSERT INTO casino_commission_ledger (game_id, recipient_type, recipient_id, amount_rub)
SELECT id, 'owner', NULL, 6.00
FROM casino_games
WHERE game_id = 'fixture-full-pvp-finished-001';

INSERT INTO casino_balance_holds (
    hold_id, telegram_id, game_id, amount_rub, status, expires_at, role, ledger_order_ref
) VALUES
    ('casino-fixture-full-pvp-recovery-creator', 941001, 'fixture-full-pvp-recovery-001', 100.00,
     'active', now() + interval '2 hours', 'creator', 'fixture-full-pvp-a'),
    ('casino-fixture-full-pvp-recovery-opponent', 941002, 'fixture-full-pvp-recovery-001', 100.00,
     'active', now() + interval '2 hours', 'opponent', 'fixture-full-pvp-b');

COMMIT;
