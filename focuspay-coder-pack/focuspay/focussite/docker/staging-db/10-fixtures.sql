BEGIN;

\if :{?is_pvp}
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM bot_users WHERE user_id IN (100000001, 100000002, 100000003))
       OR EXISTS (SELECT 1 FROM external_exchangers WHERE id = 91001)
       OR EXISTS (SELECT 1 FROM casino_games WHERE game_id = 'fixture-e-pvp-recovery-001')
       OR EXISTS (SELECT 1 FROM casino_game_chat_bindings WHERE chat_id = -1001234567890)
       OR EXISTS (SELECT 1 FROM user_cashback_ledger WHERE order_id IN ('fixture-e-p1-credit', 'fixture-e-p2-credit')) THEN
        RAISE EXCEPTION 'synthetic pvp fixture already exists; use a new disposable database instead of replaying it';
    END IF;
END $$;

INSERT INTO bot_users (user_id, username, first_name) VALUES
    (100000001, 'fixture_pvp_player_a', 'Fixture Player A'),
    (100000002, 'fixture_pvp_player_b', 'Fixture Player B'),
    (100000003, 'fixture_casino_admin', 'Fixture Admin');

INSERT INTO external_exchangers (id, name, contact, note, net_percent) VALUES
    (91001, 'Fixture Casino Exchanger', 'synthetic-only', 'pvp profile only; no payment flow', 0.000);

INSERT INTO staging_fixture_roles (subject_kind, subject_id, fixture_role) VALUES
    ('telegram_user', 100000001, 'player'),
    ('telegram_user', 100000002, 'player'),
    ('telegram_user', 100000003, 'admin'),
    ('external_exchanger', 91001, 'test_exchanger');

UPDATE casino_settings
SET value = jsonb_set(
        jsonb_set(value, '{raffle}', 'false'::jsonb, true),
        '{pvp_dice}', 'true'::jsonb, true
    ), updated_at = now()
WHERE key = 'enabled_games';

UPDATE casino_house_accounts
SET balance_rub = 5000.00, reserved_rub = 0, is_active = TRUE, updated_at = now()
WHERE account_key = 'main';

UPDATE casino_robot_profiles
SET mode = 'pvp_robot', is_active = TRUE, allowed_games = '["pvp_dice","baccara","blackjack","fixed_room"]'::jsonb,
    min_bet_rub = 1.00, max_bet_rub = 1000.00, max_concurrent_games = 20,
    max_exposure_rub = 5000.00, updated_at = now()
WHERE profile_key = 'focuscasino-house';

INSERT INTO casino_robot_profiles (
    profile_key, display_name, mode, account_id, is_active, allowed_games,
    min_bet_rub, max_bet_rub, max_concurrent_games, max_exposure_rub
)
SELECT 'fixture-pvp-robot-' || number, 'Fixture PvP Robot ' || number, 'pvp_robot', id, TRUE,
       '["pvp_dice","baccara","blackjack","fixed_room"]'::jsonb, 1.00, 1000.00, 20, 5000.00
FROM casino_house_accounts CROSS JOIN generate_series(2, 5) AS number
WHERE account_key = 'main';

INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note) VALUES
    (100000001, 'accrual', 500.00, 'fixture-e-p1-credit', 'Synthetic staging PvP funding only'),
    (100000002, 'accrual', 500.00, 'fixture-e-p2-credit', 'Synthetic staging PvP funding only'),
    (100000001, 'hold', -100.00, 'hold-fixture-e-p1', 'Synthetic durable recovery hold'),
    (100000002, 'hold', -100.00, 'hold-fixture-e-p2', 'Synthetic durable recovery hold');

INSERT INTO casino_game_chat_bindings (
    chat_id, chat_type, chat_title, status, requested_by_telegram_id,
    confirmed_by_admin_id, confirmed_at, telegram_url
) VALUES (
    -1001234567890, 'supergroup', 'Fixture PvP Lobby', 'active', 100000001,
    100000003, now(), 'https://t.me/focuspay_fixture'
);

INSERT INTO casino_games (
    game_id, game_type, creator_id, opponent_id, bet_rub, commission_rub,
    winner_id, status, game_data, creator_hold_id, opponent_hold_id,
    settlement_base_rub, state_version, game_state, outcome, outcome_committed_at,
    started_at
) VALUES (
    'fixture-e-pvp-recovery-001', 'pvp_dice', 100000001, 100000002, 100.00, 15.00,
    100000001, 'outcome_committed',
    '{"pricing_snapshot":{"allocation_model":"stake_percent_v2","commission_rate":"15.00","creator_cut_percent":"5.00","referral_l1_percent":"2.00","referral_l2_percent":"2.00"}}'::jsonb,
    'casino-fixture-e-pvp-recovery-001-creator',
    'casino-fixture-e-pvp-recovery-001-opponent',
    100.00, 1, '{"fixture":"durable_recovery"}'::jsonb,
    '{"kind":"winner","source":"synthetic_fixture"}'::jsonb, now(), now()
);

INSERT INTO casino_balance_holds (
    hold_id, telegram_id, game_id, amount_rub, status, expires_at, role, ledger_order_ref
) VALUES
    ('casino-fixture-e-pvp-recovery-001-creator', 100000001, 'fixture-e-pvp-recovery-001', 100.00,
     'active', now() + interval '2 hours', 'creator', 'fixture-e-p1'),
    ('casino-fixture-e-pvp-recovery-001-opponent', 100000002, 'fixture-e-pvp-recovery-001', 100.00,
     'active', now() + interval '2 hours', 'opponent', 'fixture-e-p2');
\else
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM external_exchangers WHERE id = 92001)
       OR EXISTS (SELECT 1 FROM external_deals WHERE client_transaction_id = 'fixture-payments-deal-001')
       OR EXISTS (SELECT 1 FROM external_exchanger_api_keys WHERE api_key = 'fixture-payments-api-key')
       OR EXISTS (SELECT 1 FROM owner_finance_ledger WHERE reference = 'fixture-payments-finance-001') THEN
        RAISE EXCEPTION 'synthetic payments fixture already exists; use a new disposable database instead of replaying it';
    END IF;
END $$;

INSERT INTO external_exchangers (id, name, contact, note, net_percent, markup_pct) VALUES
    (92001, 'Fixture Payments Exchanger', 'synthetic-only', 'payments profile only; no external integrations', 0.000, 10.000);

INSERT INTO external_exchanger_accounts (
    external_exchanger_id, username, password_hash, is_active
) VALUES (
    92001, 'fixture_payments_exchanger', 'synthetic-disabled-login', TRUE
);

INSERT INTO external_exchanger_api_keys (
    exchanger_id, api_key, secret, secret_hash, secret_hint, is_active
) VALUES (
    92001, 'fixture-payments-api-key', 'fixture-payments-hmac-secret',
    'f8fe1bd4995e9551527a369b1c1ab5b6c21f27d7c2547fe1b0c85187ab1f48ce', 'fixt…', TRUE
);

INSERT INTO operator_accounts (
    id, telegram_user_id, username, display_name, password_hash, percent, operator_role, operator_roles
) VALUES
    (93001, 199000001, 'fixture_payments_client_ops', 'Fixture Client Operator', 'synthetic-disabled-login', 0.000, 'client', ARRAY['client']::TEXT[]),
    (93002, 199000002, 'fixture_payments_finance_ops', 'Fixture Finance Operator', 'synthetic-disabled-login', 0.000, 'finance', ARRAY['finance']::TEXT[]);

INSERT INTO operator_shifts (operator_id, note) VALUES
    (93001, 'Synthetic payments client shift'),
    (93002, 'Synthetic payments finance shift');

INSERT INTO operator_shift_balances (shift_id, crypto, balance_start)
SELECT shift.id, balance.crypto, balance.amount
FROM operator_shifts AS shift
JOIN (VALUES
    ('usdt'::VARCHAR(16), 100.00000000::NUMERIC(20, 8)),
    ('btc'::VARCHAR(16), 0.01000000::NUMERIC(20, 8)),
    ('trx'::VARCHAR(16), 500.00000000::NUMERIC(20, 8)),
    ('ltc'::VARCHAR(16), 5.00000000::NUMERIC(20, 8))
) AS balance(crypto, amount) ON TRUE
WHERE shift.operator_id IN (93001, 93002);

INSERT INTO staging_fixture_roles (subject_kind, subject_id, fixture_role) VALUES
    ('external_exchanger', 92001, 'payments_exchanger'),
    ('operator', 93001, 'client_operator'),
    ('operator', 93002, 'finance_operator');

INSERT INTO external_deals (
    exchanger_id, amount_rub, crypto, markup_pct, card_fee_pct, usdt_rate_rub,
    client_pays_rub, payfast_fee_rub, net_profit_rub, principal_usdt, reward_usdt,
    receive_fee_usd, house_profit_usd, note, created_by, status, merchant_order_id,
    payment_snapshot, sub_token, paid_confirmed_at, client_transaction_id, expires_at,
    required_receipt_type, client_is_new, markup_mode, operator_id, operator_earnings_rub,
    payout_on_credit, payout_wallet, payout_id
) VALUES (
    92001, 1000.00, 'usdt', 10.000, 0.0000, 100.0000,
    1100.00, 0.00, 100.00, 10.000000, 0.000000,
    0.000000, 1.000000, 'Synthetic payments deal only', 'fixture-bootstrap', 'confirmed',
    'fixture-payments-merchant-001', '{"provider":"synthetic","state":"confirmed"}'::jsonb,
    'SBPRUB', now(), 'fixture-payments-deal-001', now() + interval '20 minutes',
    2, TRUE, 'on_deal', 93002, 0.00, FALSE, NULL, NULL
);

INSERT INTO external_ledger (exchanger_id, type, amount_usd, deal_id, note)
SELECT 92001, entry.type, entry.amount_usd, deal.id, entry.note
FROM external_deals deal
CROSS JOIN (VALUES
    ('principal'::VARCHAR(20), 10.000000::NUMERIC(14, 6), 'Synthetic payments principal'),
    ('reward'::VARCHAR(20), 0.000000::NUMERIC(14, 6), 'Synthetic payments reward')
) AS entry(type, amount_usd, note)
WHERE deal.client_transaction_id = 'fixture-payments-deal-001';

INSERT INTO owner_finance_ledger (
    occurred_at, entry_type, amount, currency, source, reference, status, note
) VALUES (
    now(), 'commission', 100.00, 'RUB', 'synthetic-payments',
    'fixture-payments-finance-001', 'confirmed', 'Synthetic payments finance entry'
);

INSERT INTO site_reviews (
    telegram_message_id, channel_username, text, author_name, published_at
) VALUES (
    920001, 'focuspayr', 'Synthetic staging review', 'Fixture Customer', now()
);

INSERT INTO web_chat_threads (
    session_token, telegram_user_id, order_id, admin_unread, last_message_at
) VALUES (
    '00000000-0000-4000-8000-000000092001', 199000001, NULL, 1, now()
);

INSERT INTO web_chat_messages (thread_id, sender_role, body)
SELECT id, 'buyer', 'Synthetic staging chat message'
FROM web_chat_threads
WHERE session_token = '00000000-0000-4000-8000-000000092001';

INSERT INTO security_access_log (
    ip_address, method, path, status_code, latency_ms, zone, threat_score, extra
) VALUES (
    '198.51.100.1', 'GET', '/api/health', 200, 1, 'api', 0,
    '{"fixture":"payments"}'::jsonb
);
\endif

COMMIT;
