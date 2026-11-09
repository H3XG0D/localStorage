BEGIN;

CREATE TABLE staging_fixture_roles (
    subject_kind VARCHAR(32) NOT NULL CHECK (subject_kind IN ('telegram_user', 'web_user', 'operator', 'partner', 'external_exchanger')),
    subject_id BIGINT NOT NULL,
    fixture_role VARCHAR(32) NOT NULL CHECK (fixture_role IN ('admin', 'buyer', 'client_operator', 'finance_operator', 'partner', 'external_exchanger')),
    PRIMARY KEY (subject_kind, subject_id),
    UNIQUE (fixture_role)
);

INSERT INTO bot_users (user_id, username, first_name, ref_token) VALUES
    (940001, 'fixture_full_admin', 'Fixture Admin', 'fixture-admin'),
    (940002, 'fixture_full_buyer', 'Fixture Buyer', 'fixture-buyer'),
    (940003, 'fixture_full_referrer', 'Fixture Referrer', 'fixture-referrer');

INSERT INTO web_users (id, email, password_hash, telegram_user_id, display_name, is_admin, username) VALUES
    (940001, 'admin@fixture.invalid', 'synthetic-managed-on-staging', 940001, 'Fixture Admin', TRUE, 'fixture_admin'),
    (940002, 'buyer@fixture.invalid', 'synthetic-disabled-login', 940002, 'Fixture Buyer', FALSE, 'fixture_buyer');

INSERT INTO operator_accounts (
    id, username, display_name, password_hash, percent, operator_role, operator_roles
) VALUES
    (940101, 'fixture_full_client_ops', 'Fixture Client Operator', 'synthetic-disabled-login', 10.000, 'client', ARRAY['client']::TEXT[]),
    (940102, 'fixture_full_finance_ops', 'Fixture Finance Operator', 'synthetic-disabled-login', 10.000, 'finance', ARRAY['finance']::TEXT[]);

INSERT INTO operator_shifts (id, operator_id, started_at, note) VALUES
    (940101, 940101, now() - interval '4 hours', 'Synthetic full-panel client shift'),
    (940102, 940102, now() - interval '4 hours', 'Synthetic full-panel finance shift');

INSERT INTO operator_shift_balances (shift_id, crypto, balance_start) VALUES
    (940101, 'usdt', 100.00000000),
    (940101, 'btc', 0.01000000),
    (940101, 'trx', 500.00000000),
    (940101, 'ltc', 5.00000000),
    (940102, 'usdt', 150.00000000),
    (940102, 'btc', 0.02000000),
    (940102, 'trx', 750.00000000),
    (940102, 'ltc', 8.00000000);

INSERT INTO orders (
    order_id, user_id, status, crypto_amount, fiat_amount, direction, requisites, rate,
    created_at, updated_at, expires_at, crypto, sub_token, operator_id, intake_operator_id,
    finance_operator_id, cashback_applied_rub, economics_snapshot, payout_confirmed_at, payroll_model
) VALUES
    ('fixture-full-paid-001', 940002, 'PAID', 100.00000000, 10000.00, 'buy', 'fixture wallet', 100.00,
     now() - interval '3 hours', now() - interval '2 hours', now() + interval '1 hour', 'usdt', 'SBPRUB', 940101, NULL,
     NULL, 0.00, '{"service_profit_rub":500}'::jsonb, now() - interval '2 hours', 'legacy'),
    ('fixture-full-completed-001', 940002, 'COMPLETED', 200.00000000, 20000.00, 'buy', 'fixture wallet', 100.00,
     now() - interval '2 hours', now() - interval '1 hour', now() + interval '1 hour', 'usdt', 'SBPRUB', NULL, 940101,
     940102, 0.00, '{"service_profit_rub":1000}'::jsonb, now() - interval '1 hour', 'role_split'),
    ('fixture-full-pending-001', 940002, 'PENDING', 150.00000000, 15000.00, 'buy', 'fixture wallet', 100.00,
     now() - interval '30 minutes', now() - interval '30 minutes', now() + interval '1 hour', 'usdt', 'SBPRUB', 940101, NULL,
     NULL, 0.00, '{"service_profit_rub":750}'::jsonb, NULL, 'legacy');

INSERT INTO order_payroll_splits (
    id, order_id, profit_rub, operator_pool_percent, pool_rub, client_pool_rub, finance_pool_rub, source
) VALUES (940001, 'fixture-full-completed-001', 1000.00, 30.000, 300.00, 90.00, 210.00, 'fixture');

INSERT INTO order_payroll_split_lines (split_id, operator_id, role, amount_rub) VALUES
    (940001, 940101, 'client', 90.00),
    (940001, 940102, 'finance', 210.00);

INSERT INTO operator_payroll_ledger (type, amount_rub, shift_id, operator_id, note) VALUES
    ('accrual', 50.00, 940101, 940101, 'Synthetic full-panel payroll liability');

INSERT INTO operator_payout_requests (operator_id, amount_rub, requisites, status) VALUES
    (940102, 40.00, 'Synthetic payment requisites', 'pending');

INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note) VALUES
    (940002, 'accrual', 125.00, 'fixture-full-cashback-001', 'Synthetic full-panel cashback liability');

INSERT INTO user_referral_attributions (user_id, referrer_user_id) VALUES (940002, 940003);
INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, order_id, note) VALUES
    (940003, 'accrual', 75.00, 'fixture-full-referral-001', 'Synthetic full-panel referral liability');
INSERT INTO user_referral_withdrawals (referrer_user_id, amount_rub, method, requisites, status) VALUES
    (940003, 50.00, 'card', 'Synthetic payment requisites', 'pending');

INSERT INTO promo_campaigns (id, code, name, bonus_percent, ad_spend_rub, created_by, partner_commission_percent, ref_token) VALUES
    (940001, 'FIXTURE', 'Fixture campaign', 5.00, 0.00, 940001, 10.00, 'fixturefullpanel01');
INSERT INTO promo_attributions (user_id, promo_code) VALUES (940002, 'FIXTURE');
INSERT INTO partner_accounts (id, promo_campaign_id, username, password_hash, display_name) VALUES
    (940001, 940001, 'fixture_full_partner', 'synthetic-disabled-login', 'Fixture Partner');
INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note, created_by_web_user_id) VALUES
    (940001, 'accrual', 110.00, 'fixture-full-partner-001', 'Synthetic full-panel partner liability', 940001);
INSERT INTO partner_withdrawals (campaign_id, partner_account_id, amount_rub, method, requisites, status) VALUES
    (940001, 940001, 60.00, 'card', 'Synthetic payment requisites', 'pending');
INSERT INTO admin_salary_recipients (partner_account_id, label, daily_salary_rub) VALUES
    (940001, 'Fixture administrator', 1000.00);

INSERT INTO external_exchangers (id, name, contact, net_percent, note) VALUES
    (940001, 'Fixture External Exchanger', 'synthetic-only', 20.000, 'full-panel profile only');
INSERT INTO external_payouts (id, exchanger_id, gross_usd, fee_usd, net_usd, crypto, status, note, created_by) VALUES
    (940001, 940001, 15.000000, 3.000000, 12.000000, 'usdt', 'pending', 'Synthetic full-panel external payout', 'fixture');
INSERT INTO external_ledger (exchanger_id, type, amount_usd, payout_id, note) VALUES
    (940001, 'principal', 25.000000, NULL, 'Synthetic full-panel external liability'),
    (940001, 'payout', -15.000000, 940001, 'Synthetic pending external payout');

INSERT INTO manual_expenses (
    category, amount_rub, operation_type, title, comment, expense_date, created_by_web_user_id
) VALUES
    ('work', 350.00, 'operations', 'Synthetic staging expense',
     'Fixture for full-panel finance analytics', CURRENT_DATE, 940001);

INSERT INTO site_reviews (telegram_message_id, channel_username, text, author_name, published_at) VALUES
    (940001, 'focuspayr', 'Synthetic full-panel review', 'Fixture Buyer', now());

INSERT INTO web_chat_threads (session_token, telegram_user_id, order_id, admin_unread, last_message_at) VALUES
    ('00000000-0000-4000-8000-000000940001', 940002, 'fixture-full-pending-001', 1, now());
INSERT INTO web_chat_messages (thread_id, sender_role, body)
SELECT id, 'buyer', 'Synthetic full-panel chat message'
FROM web_chat_threads
WHERE session_token = '00000000-0000-4000-8000-000000940001';

INSERT INTO security_access_log (ip_address, method, path, status_code, latency_ms, zone, threat_score, extra) VALUES
    ('198.51.100.2', 'GET', '/api/health', 200, 1, 'api', 0, '{"fixture":"full-panel"}'::jsonb);

INSERT INTO staging_fixture_roles (subject_kind, subject_id, fixture_role) VALUES
    ('web_user', 940001, 'admin'),
    ('telegram_user', 940002, 'buyer'),
    ('operator', 940101, 'client_operator'),
    ('operator', 940102, 'finance_operator'),
    ('partner', 940001, 'partner'),
    ('external_exchanger', 940001, 'external_exchanger');

COMMIT;
