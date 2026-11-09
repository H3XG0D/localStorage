-- Staging-only seed: live-like SELL/BUY amounts for the payout/payin click pass.
-- Prod traffic analog: SBP + BTC, 2.5–7k ₽, operator chips 5/7/10k, doliv 2000.
--
-- Apply against a disposable staging database:
--   docker compose --env-file .env.staging-runtime -f docker-compose.staging-runtime.yml \
--     exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
--     < scripts/staging-payout-requisites-seed.sql
--
-- Click-pass:
--   queued payin 5 000 sits in «Очередь» until confirm;
--   confirmed payin 5 000 matches BUY silently (no round-up dialog);
--   hour-old payin 5 000 + quote 3 300 → sits as 1 of 2, no offer.

DO $$
BEGIN
    IF current_setting('server_version_num')::int < 130000 THEN
        RAISE EXCEPTION 'unexpected Postgres version for staging seed';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM web_users WHERE id = 940002) THEN
        RAISE EXCEPTION 'synthetic full-panel fixtures are missing (web_users 940002)';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM operator_accounts WHERE id = 940102) THEN
        RAISE EXCEPTION 'synthetic finance operator 940102 is missing';
    END IF;
END $$;

DELETE FROM payout_requisite_allocations
WHERE order_id LIKE 'pr-seed-%'
   OR requisite_id IN (
        SELECT id FROM operator_payout_requisites WHERE COALESCE(label, '') LIKE 'pr-seed-%'
   );
DELETE FROM payout_requisite_plans
WHERE requisite_id IN (
    SELECT id FROM operator_payout_requisites WHERE COALESCE(label, '') LIKE 'pr-seed-%'
);
DELETE FROM operator_payout_requisites WHERE COALESCE(label, '') LIKE 'pr-seed-%';
DELETE FROM orders WHERE order_id LIKE 'pr-seed-%';

-- Extra PAID BUY so the fixture buyer clears payin_requisite_min_buy_paid (3).
INSERT INTO orders (
    order_id, user_id, status, crypto_amount, fiat_amount, direction, requisites, rate,
    created_at, updated_at, expires_at, crypto, sub_token, payroll_model
)
VALUES (
    'pr-seed-buy-paid-extra',
    940002,
    'PAID',
    33.00000000,
    3300.00,
    'buy',
    'fixture wallet',
    100.00,
    now() - interval '5 hours',
    now() - interval '4 hours',
    now() + interval '1 hour',
    'btc',
    'SBPRUB',
    'legacy'
);

INSERT INTO orders (
    order_id, user_id, status, crypto_amount, fiat_amount, direction, requisites, rate,
    created_at, updated_at, expires_at, crypto, sub_token, payroll_model,
    crypto_confirmed_at
)
SELECT
    seed.order_id,
    940002,
    seed.status,
    seed.fiat_amount / 100,
    seed.fiat_amount,
    'sell',
    seed.requisites,
    100.00,
    now() - seed.age,
    now() - seed.age,
    now() + interval '12 hours',
    'btc',
    seed.sub_token,
    'legacy',
    now() - seed.age
FROM (VALUES
    ('pr-seed-sbp-2500', 'PENDING',          2500.00, 'SBPRUB',  '+7 900 000-00-11', interval '40 minutes'),
    ('pr-seed-sbp-3300', 'PENDING',          3300.00, 'SBPRUB',  '+7 900 000-00-12', interval '55 minutes'),
    ('pr-seed-sbp-4900', 'PENDING',          4900.00, 'SBPRUB',  '+7 900 000-00-13', interval '25 minutes'),
    ('pr-seed-sbp-5000', 'PENDING',          5000.00, 'SBPRUB',  '+7 900 000-00-14', interval '15 minutes'),
    ('pr-seed-sbp-7000', 'OPERATOR_PENDING', 7000.00, 'SBPRUB',  '+7 900 000-00-15', interval '80 minutes'),
    ('pr-seed-card-3300','PENDING',          3300.00, 'CARDRUB', '2200 0000 0000 0011', interval '50 minutes'),
    ('pr-seed-card-4900','PENDING',          4900.00, 'CARDRUB', '2200 0000 0000 0012', interval '30 minutes'),
    ('pr-seed-card-5000','OPERATOR_PENDING', 5000.00, 'CARDRUB', '2200 0000 0000 0013', interval '70 minutes')
) AS seed(order_id, status, fiat_amount, sub_token, requisites, age);

INSERT INTO operator_payout_requisites (
    operator_id, label, direction, method, requisites, bank, holder_name,
    amount_rub, cost_pct, crypto, max_checks, doliv_limit_rub, status,
    deadline_at, created_at, updated_at, confirmed_at, confirmed_by
) VALUES
    (
        940102, 'pr-seed-payin-fresh-5000', 'payin', 'sbp', '+79001234501', 'Сбер', 'Иван П.',
        5000.00, 0, 'btc', 3, 2000, 'OPEN',
        now() + interval '180 minutes', now(), now(), now(), 940102
    ),
    (
        940102, 'pr-seed-payin-aged-5000', 'payin', 'sbp', '+79001234502', 'Т-Банк', 'Пётр С.',
        5000.00, 0, 'btc', 3, 2000, 'OPEN',
        now() + interval '110 minutes', now() - interval '70 minutes', now() - interval '70 minutes',
        now() - interval '70 minutes', 940102
    ),
    (
        940102, 'pr-seed-payin-queued-5000', 'payin', 'sbp', '+79001234505', 'Альфа', 'Очередь О.',
        5000.00, 0, 'btc', 3, 2000, 'QUEUED',
        now() + interval '180 minutes', now(), now(), NULL, NULL
    ),
    (
        940102, 'pr-seed-payout-fresh-5000', 'payout', 'sbp', '+79001234503', 'Сбер', 'Иван П.',
        5000.00, 0, 'btc', 3, 2000, 'OPEN',
        now() + interval '180 minutes', now(), now(), NULL, NULL
    ),
    (
        940102, 'pr-seed-payout-aged-5000', 'payout', 'sbp', '+79001234504', 'Т-Банк', 'Пётр С.',
        5000.00, 0, 'btc', 3, 2000, 'OPEN',
        now() + interval '110 minutes', now() - interval '70 minutes', now() - interval '70 minutes',
        NULL, NULL
    );

INSERT INTO operator_permission_grants (operator_id, permission, granted, updated_at)
VALUES (940102, 'payout.requisites.confirm', TRUE, now())
ON CONFLICT (operator_id, permission)
DO UPDATE SET granted = TRUE, updated_at = now();

SELECT 'orders' AS kind, count(*)::int AS n
FROM orders WHERE order_id LIKE 'pr-seed-%'
UNION ALL
SELECT 'requisites', count(*)::int
FROM operator_payout_requisites WHERE label LIKE 'pr-seed-%';
