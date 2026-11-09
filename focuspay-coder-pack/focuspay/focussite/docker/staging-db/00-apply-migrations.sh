#!/usr/bin/env bash
# Bootstrap only an empty disposable PostgreSQL database with synthetic fixtures.
set -euo pipefail

PROFILE="${1:-pvp}"
case "$PROFILE" in
  pvp|payments) ;;
  *)
    printf 'Unsupported staging bootstrap profile: %s (available: pvp, payments)\n' "$PROFILE" >&2
    exit 64
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-$REPO_ROOT/site/exchange-backend/migrations}"
BOT_MIGRATIONS_DIR="${BOT_MIGRATIONS_DIR:-$REPO_ROOT/bot/tg_bot_btc/migrations}"
FIXTURES_SQL="$SCRIPT_DIR/10-fixtures.sql"

required_artifacts=("$FIXTURES_SQL")
if [[ "$PROFILE" == "pvp" ]]; then
  required_artifacts+=(
    "$MIGRATIONS_DIR/add_casino_tables.sql"
    "$MIGRATIONS_DIR/fix_casino_backend_integrity.sql"
    "$MIGRATIONS_DIR/add_casino_durable_recovery.sql"
    "$MIGRATIONS_DIR/add_casino_weekly_cashback_tiers.sql"
    "$MIGRATIONS_DIR/add_casino_game_chat_bindings.sql"
    "$MIGRATIONS_DIR/add_casino_game_chat_binding_telegram_url.sql"
    "$MIGRATIONS_DIR/add_casino_house_bankroll.sql"
    "$MIGRATIONS_DIR/add_external_exchanges.sql"
    "$MIGRATIONS_DIR/add_external_deals_status.sql"
    "$MIGRATIONS_DIR/add_exchanger_hmac_api_and_expires.sql"
    "$MIGRATIONS_DIR/add_casino_deposit_credits.sql"
    "$MIGRATIONS_DIR/add_casino_deposit_credit_rail.sql"
    "$MIGRATIONS_DIR/add_casino_wagering_locks.sql"
    "$MIGRATIONS_DIR/add_casino_crypto_deposits.sql"
    "$MIGRATIONS_DIR/add_casino_wagering_commission_profiles.sql"
    "$MIGRATIONS_DIR/add_casino_volume_tier_grids.sql"
    "$MIGRATIONS_DIR/add_casino_settings_v2.sql"
    "$MIGRATIONS_DIR/add_casino_settings_audit.sql"
    "$MIGRATIONS_DIR/add_casino_fairness_seeds.sql"
    "$MIGRATIONS_DIR/add_web_users.sql"
    "$MIGRATIONS_DIR/add_web_telegram_bot_logins.sql"
    "$MIGRATIONS_DIR/add_captcha_challenges.sql"
    "$MIGRATIONS_DIR/add_casino_creator_accounts.sql"
    "$MIGRATIONS_DIR/add_casino_creator_withdrawal_idempotency.sql"
    "$MIGRATIONS_DIR/add_casino_multiplayer_v2.sql"
    "$MIGRATIONS_DIR/add_casino_v2_house_ledger.sql"
    "$MIGRATIONS_DIR/add_casino_pvp_dm_invitations.sql"
    "$MIGRATIONS_DIR/add_casino_v2_table_chat.sql"
    "$MIGRATIONS_DIR/add_casino_drop_sport_pvp.sql"
    "$MIGRATIONS_DIR/add_casino_poker_tables.sql"
    "$MIGRATIONS_DIR/add_casino_nardy_tables.sql"
    "$MIGRATIONS_DIR/add_casino_draughts.sql"
    "$MIGRATIONS_DIR/add_casino_chat.sql"
    "$MIGRATIONS_DIR/add_casino_jackpot.sql"
    "$MIGRATIONS_DIR/add_casino_clans.sql"
    "$MIGRATIONS_DIR/add_casino_level_bonus.sql"
    "$MIGRATIONS_DIR/seed_casino_level_reach_bonuses.sql"
    "$MIGRATIONS_DIR/add_casino_house_tables.sql"
    "$MIGRATIONS_DIR/add_casino_house_tables_solo.sql"
    "$MIGRATIONS_DIR/add_casino_player_cosmetics.sql"
    "$MIGRATIONS_DIR/add_casino_notify_open_tables.sql"
    "$MIGRATIONS_DIR/add_casino_web_inbox.sql"
    "$MIGRATIONS_DIR/add_casino_fixed_rooms.sql"
    "$MIGRATIONS_DIR/add_casino_fixed_room_bots.sql"
    "$MIGRATIONS_DIR/add_casino_live_mosaic.sql"
    "$MIGRATIONS_DIR/add_casino_clan_wars.sql"
    "$MIGRATIONS_DIR/add_casino_roulette.sql"
    "$MIGRATIONS_DIR/add_casino_roulette_table.sql"
    "$MIGRATIONS_DIR/add_casino_roulette_table_chips.sql"
    "$MIGRATIONS_DIR/add_casino_roulette_telegram_notify.sql"
    "$MIGRATIONS_DIR/add_casino_jackpot_telegram_notify.sql"
    "$MIGRATIONS_DIR/add_raffle_live_show.sql"
    "$MIGRATIONS_DIR/add_raffle_accrual_blocks.sql"
    "$MIGRATIONS_DIR/add_raffle_timed_show.sql"
    "$MIGRATIONS_DIR/add_casino_tournaments.sql"
    "$MIGRATIONS_DIR/add_withdrawal_source.sql"
    "$MIGRATIONS_DIR/add_casino_withdraw_pending_cap.sql"
    "$BOT_MIGRATIONS_DIR/add_operator_accounts.sql"
    "$MIGRATIONS_DIR/add_operator_sticker_sets_and_chat_templates.sql"
    "$MIGRATIONS_DIR/add_rbac_templates_hardening.sql"
    "$MIGRATIONS_DIR/add_casino_v2_web_client_ids.sql"
    "$MIGRATIONS_DIR/add_casino_v2_outbox_web_client_ids.sql"
    "$MIGRATIONS_DIR/add_casino_notification_delivery_policy.sql"
    "$BOT_MIGRATIONS_DIR/add_broadcast_jobs.sql"
    "$MIGRATIONS_DIR/add_broadcast_job_stickers.sql"
    "$MIGRATIONS_DIR/add_broadcast_schedule.sql"
    "$MIGRATIONS_DIR/add_requisite_retry_requests.sql"
  )
else
  required_artifacts+=(
    "$MIGRATIONS_DIR/add_external_exchanges.sql"
    "$MIGRATIONS_DIR/add_external_deals_status.sql"
    "$MIGRATIONS_DIR/add_external_deal_payin.sql"
    "$MIGRATIONS_DIR/add_external_exchanger_accounts.sql"
    "$MIGRATIONS_DIR/add_exchanger_hmac_api_and_expires.sql"
    "$MIGRATIONS_DIR/add_external_deal_receipt_type.sql"
    "$MIGRATIONS_DIR/add_external_deal_client_is_new.sql"
    "$MIGRATIONS_DIR/add_external_exchanger_trust_flags.sql"
    "$MIGRATIONS_DIR/add_external_markup_mode.sql"
    "$MIGRATIONS_DIR/add_external_deal_operator.sql"
    "$MIGRATIONS_DIR/add_operator_dual_roles.sql"
    "$MIGRATIONS_DIR/add_external_deal_payout_on_credit.sql"
    "$MIGRATIONS_DIR/add_external_deal_payfast_reviews.sql"
    "$MIGRATIONS_DIR/add_web_users.sql"
    "$MIGRATIONS_DIR/add_web_telegram_bot_logins.sql"
    "$MIGRATIONS_DIR/add_captcha_challenges.sql"
    "$MIGRATIONS_DIR/add_login_username.sql"
    "$MIGRATIONS_DIR/add_admin_totp.sql"
    "$MIGRATIONS_DIR/add_site_reviews.sql"
    "$BOT_MIGRATIONS_DIR/add_review_submissions.sql"
    "$MIGRATIONS_DIR/add_security_access_log.sql"
    "$BOT_MIGRATIONS_DIR/add_web_chat.sql"
    "$BOT_MIGRATIONS_DIR/add_web_chat_telegram_bridge.sql"
    "$BOT_MIGRATIONS_DIR/add_operator_shift_balances.sql"
    "$MIGRATIONS_DIR/add_payout_requisites.sql"
    "$MIGRATIONS_DIR/add_payout_requisite_queue.sql"
    "$MIGRATIONS_DIR/add_payin_open_requires_confirm.sql"
    "$MIGRATIONS_DIR/add_triangle_source_sell.sql"
    "$MIGRATIONS_DIR/add_triangle_source_withdrawal.sql"
    "$BOT_MIGRATIONS_DIR/add_order_crypto_confirmed.sql"
    "$BOT_MIGRATIONS_DIR/add_order_payin_requisite.sql"
  )
fi
for required in "${required_artifacts[@]}"; do
  if [[ ! -r "$required" ]]; then
    printf 'Required bootstrap artifact is unavailable: %s\n' "$required" >&2
    exit 66
  fi
done

run_psql() {
  psql -X -v ON_ERROR_STOP=1 "$@"
}

# Every profile is intentionally single-use. A marker from either profile can be a
# partial/unknown state, so rerunning must fail instead of replaying any ledger entries.
existing_state="$(run_psql -Atqc "
  SELECT string_agg(name, ', ' ORDER BY name)
  FROM (
    SELECT 'casino_games' AS name WHERE to_regclass('public.casino_games') IS NOT NULL
    UNION ALL SELECT 'casino_v2_tables' WHERE to_regclass('public.casino_v2_tables') IS NOT NULL
    UNION ALL SELECT 'external_deals' WHERE to_regclass('public.external_deals') IS NOT NULL
    UNION ALL SELECT 'staging_fixture_roles' WHERE to_regclass('public.staging_fixture_roles') IS NOT NULL
    UNION ALL SELECT 'bot_users' WHERE to_regclass('public.bot_users') IS NOT NULL
    UNION ALL SELECT 'user_cashback_ledger' WHERE to_regclass('public.user_cashback_ledger') IS NOT NULL
    UNION ALL SELECT 'external_ledger' WHERE to_regclass('public.external_ledger') IS NOT NULL
    UNION ALL SELECT 'owner_finance_ledger' WHERE to_regclass('public.owner_finance_ledger') IS NOT NULL
  ) state;
")"
if [[ -n "$existing_state" ]]; then
  printf 'Refusing bootstrap: database is not empty for profile %s (%s). Create a new disposable volume.\n' "$PROFILE" "$existing_state" >&2
  exit 65
fi

# Minimal shared schema needed by the existing unified-balance implementation.
# All player funding is cashback-only; referral and partner tables deliberately stay empty.
run_psql <<'SQL'
BEGIN;

CREATE TABLE bot_users (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    use_cashback_on_next_order BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_cashback_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('accrual', 'spend', 'adjustment', 'remainder_credit', 'hold')),
    amount_rub NUMERIC(14, 2) NOT NULL,
    order_id VARCHAR(64) UNIQUE,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_staging_cashback_user_created ON user_cashback_ledger (user_id, created_at DESC);

CREATE TABLE user_referral_attributions (
    user_id BIGINT PRIMARY KEY,
    referrer_user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_referral_attr_referrer
    ON user_referral_attributions (referrer_user_id);

CREATE TABLE user_referral_ledger (
    id BIGSERIAL PRIMARY KEY,
    referrer_user_id BIGINT NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend')),
    amount_rub NUMERIC(14, 2) NOT NULL,
    order_id VARCHAR(64) UNIQUE,
    withdrawal_id BIGINT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_referral_withdrawals (
    id BIGSERIAL PRIMARY KEY,
    referrer_user_id BIGINT NOT NULL,
    amount_rub NUMERIC(14, 2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE promo_campaigns (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE partner_accounts (
    id SERIAL PRIMARY KEY,
    promo_campaign_id INTEGER NOT NULL REFERENCES promo_campaigns(id),
    telegram_user_id BIGINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (promo_campaign_id, telegram_user_id)
);

CREATE TABLE partner_ledger (
    id BIGSERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES promo_campaigns(id),
    type VARCHAR(20) NOT NULL CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend')),
    amount_rub NUMERIC(14, 2) NOT NULL,
    order_id VARCHAR(64) UNIQUE,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE partner_withdrawals (
    id BIGSERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES promo_campaigns(id),
    amount_rub NUMERIC(14, 2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE promo_gift_redemptions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE external_exchangers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    contact VARCHAR(512),
    net_percent NUMERIC(6, 3) NOT NULL DEFAULT 20.0 CHECK (net_percent >= 0 AND net_percent <= 100),
    note TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE staging_fixture_roles (
    subject_kind VARCHAR(32) NOT NULL CHECK (subject_kind IN ('telegram_user', 'external_exchanger', 'operator')),
    subject_id BIGINT NOT NULL,
    fixture_role VARCHAR(32) NOT NULL CHECK (fixture_role IN (
        'player', 'admin', 'test_exchanger', 'payments_exchanger',
        'client_operator', 'finance_operator'
    )),
    PRIMARY KEY (subject_kind, subject_id)
);

COMMIT;
SQL

if [[ "$PROFILE" == "pvp" ]]; then
# The production migration grants to this application role. The disposable database
# is intentionally empty, so provide a no-login placeholder before applying it.
run_psql <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        CREATE ROLE exchange_bot NOLOGIN;
    END IF;
END $$;
SQL

# The order is a schema dependency chain: base tables -> integrity columns/indexes
# -> durable state/outbox -> PVP chat binding -> its navigation URL -> house-game columns
# -> web creator account dependencies -> casino deposit and wagering schema.
run_psql -f "$MIGRATIONS_DIR/add_casino_tables.sql"
run_psql -f "$MIGRATIONS_DIR/fix_casino_backend_integrity.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_durable_recovery.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_weekly_cashback_tiers.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_game_chat_bindings.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_game_chat_binding_telegram_url.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_house_bankroll.sql"
run_psql -f "$MIGRATIONS_DIR/add_external_exchanges.sql"
run_psql -f "$MIGRATIONS_DIR/add_external_deals_status.sql"
run_psql -f "$MIGRATIONS_DIR/add_exchanger_hmac_api_and_expires.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_deposit_credits.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_deposit_credit_rail.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_wagering_locks.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_crypto_deposits.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_wagering_commission_profiles.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_volume_tier_grids.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_settings_v2.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_settings_audit.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_fairness_seeds.sql"
run_psql -f "$MIGRATIONS_DIR/add_web_users.sql"
run_psql -f "$MIGRATIONS_DIR/add_web_telegram_bot_logins.sql"
run_psql -f "$MIGRATIONS_DIR/add_captcha_challenges.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_creator_accounts.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_creator_withdrawal_idempotency.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_multiplayer_v2.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_v2_house_ledger.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_pvp_dm_invitations.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_v2_table_chat.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_drop_sport_pvp.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_poker_tables.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_nardy_tables.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_draughts.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_chat.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_jackpot.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_clans.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_level_bonus.sql"
run_psql -f "$MIGRATIONS_DIR/seed_casino_level_reach_bonuses.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_house_tables.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_house_tables_solo.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_player_cosmetics.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_notify_open_tables.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_web_inbox.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_fixed_rooms.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_fixed_room_bots.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_live_mosaic.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_clan_wars.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_roulette.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_roulette_table.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_roulette_table_chips.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_roulette_telegram_notify.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_jackpot_telegram_notify.sql"
run_psql -f "$MIGRATIONS_DIR/add_raffle_live_show.sql"
run_psql -f "$MIGRATIONS_DIR/add_raffle_accrual_blocks.sql"
run_psql -f "$MIGRATIONS_DIR/add_raffle_timed_show.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_tournaments.sql"
run_psql -f "$MIGRATIONS_DIR/add_withdrawal_source.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_withdraw_pending_cap.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_accounts.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_sticker_sets_and_chat_templates.sql"
run_psql -f "$MIGRATIONS_DIR/add_rbac_templates_hardening.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_v2_web_client_ids.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_v2_outbox_web_client_ids.sql"
run_psql -f "$MIGRATIONS_DIR/add_casino_notification_delivery_policy.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_broadcast_jobs.sql"
run_psql -f "$MIGRATIONS_DIR/add_broadcast_job_stickers.sql"
run_psql -f "$MIGRATIONS_DIR/add_broadcast_schedule.sql"
run_psql -f "$MIGRATIONS_DIR/add_requisite_retry_requests.sql"

run_psql <<'SQL'
DO $$
DECLARE
    required_name TEXT;
BEGIN
    FOREACH required_name IN ARRAY ARRAY[
        'casino_games', 'casino_balance_holds', 'casino_settings',
        'casino_settings_audit',
        'casino_fairness_seeds',
        'casino_commission_ledger', 'casino_notification_outbox',
        'casino_game_chat_bindings', 'casino_house_accounts', 'casino_wagering_locks',
        'casino_deposit_credits', 'bot_users', 'user_cashback_ledger',
        'user_referral_attributions', 'user_referral_ledger', 'partner_ledger', 'external_exchangers',
        'web_users', 'captcha_challenges', 'casino_creator_accounts', 'casino_v2_tables', 'casino_v2_table_seats',
        'casino_v2_house_reservations', 'casino_v2_settlements', 'casino_v2_lifecycle_idempotency',
        'casino_v2_notification_outbox', 'casino_v2_house_ledger', 'casino_pvp_invitation_outbox',
        'casino_poker_tables', 'casino_poker_seats', 'casino_poker_hands',
        'casino_chat_rooms', 'casino_chat_messages', 'casino_chat_presence',
        'casino_jackpot_rounds', 'casino_jackpot_bets',
        'casino_roulette_rounds', 'casino_roulette_bets',
        'casino_clans', 'casino_clan_members',
        'casino_level_bonus_grants',
        'casino_house_tables', 'casino_house_table_seats',
        'casino_player_cosmetics',
        'casino_web_inbox'
    ] LOOP
        IF to_regclass('public.' || required_name) IS NULL THEN
            RAISE EXCEPTION 'missing required bootstrap table: %', required_name;
        END IF;
    END LOOP;

    FOREACH required_name IN ARRAY ARRAY[
        'ux_casino_games_settlement_key', 'ux_casino_games_creator_hold',
        'ux_casino_games_opponent_hold', 'idx_casino_games_recovery',
        'ux_casino_holds_ledger_order_ref', 'ux_casino_holds_operation_key',
        'idx_casino_notification_outbox_claim', 'ux_casino_game_chat_bindings_one_active',
        'idx_casino_v2_tables_recovery', 'idx_casino_v2_outbox_claim', 'idx_casino_v2_house_ledger_table',
        'idx_casino_pvp_invitation_outbox_claim'
    ] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = required_name) THEN
            RAISE EXCEPTION 'missing required bootstrap index: %', required_name;
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'casino_games' AND column_name = 'game_chat_id'
    ) THEN
        RAISE EXCEPTION 'DM PVP pinned chat column casino_games.game_chat_id is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'casino_jackpot_bets' AND column_name = 'notify_chat_id'
    ) THEN
        RAISE EXCEPTION 'casino_jackpot_bets.notify_chat_id is missing';
    END IF;
END $$;
SQL

run_psql -v profile="$PROFILE" -v is_pvp=true -f "$FIXTURES_SQL"

run_psql <<'SQL'
DO $$
DECLARE
    active_bindings INTEGER;
BEGIN
    IF (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'player') <> 2
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'admin') <> 1
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'test_exchanger') <> 1 THEN
        RAISE EXCEPTION 'synthetic fixture roles are incomplete or duplicated';
    END IF;

    SELECT COUNT(*) INTO active_bindings FROM casino_game_chat_bindings WHERE status = 'active';
    IF active_bindings <> 1 THEN
        RAISE EXCEPTION 'expected exactly one active game chat binding, got %', active_bindings;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM casino_settings
        WHERE key = 'enabled_games' AND value ->> 'raffle' = 'false'
    ) THEN
        RAISE EXCEPTION 'raffle must be disabled in the pvp fixture profile';
    END IF;

    IF EXISTS (
        SELECT order_id FROM user_cashback_ledger
        WHERE order_id IN ('fixture-e-p1-credit', 'fixture-e-p2-credit')
        GROUP BY order_id HAVING COUNT(*) <> 1
    ) OR (SELECT COUNT(*) FROM user_cashback_ledger
          WHERE order_id IN ('fixture-e-p1-credit', 'fixture-e-p2-credit')) <> 2 THEN
        RAISE EXCEPTION 'fixture funding ledger entries are missing or duplicated';
    END IF;

    IF EXISTS (
        SELECT 1 FROM (
            SELECT user_id, SUM(amount_rub) AS available_rub
            FROM user_cashback_ledger
            WHERE user_id IN (100000001, 100000002)
            GROUP BY user_id
        ) balances
        WHERE available_rub <> 400.00
    ) OR (SELECT COUNT(DISTINCT user_id) FROM user_cashback_ledger
          WHERE user_id IN (100000001, 100000002)) <> 2 THEN
        RAISE EXCEPTION 'synthetic PvP balances must each be 400.00 RUB after their active hold';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM casino_games g
        JOIN casino_balance_holds creator_hold ON creator_hold.hold_id = g.creator_hold_id
        JOIN casino_balance_holds opponent_hold ON opponent_hold.hold_id = g.opponent_hold_id
        WHERE g.game_id = 'fixture-e-pvp-recovery-001'
          AND g.status = 'outcome_committed'
          AND g.creator_id = 100000001 AND g.opponent_id = 100000002
          AND g.winner_id = 100000001 AND g.bet_rub = 100.00
          AND g.recovery_completed_at IS NULL
          AND creator_hold.status = 'active' AND opponent_hold.status = 'active'
          AND creator_hold.amount_rub = 100.00 AND opponent_hold.amount_rub = 100.00
    ) THEN
        RAISE EXCEPTION 'durable recovery fixture game or holds are invalid';
    END IF;

    IF EXISTS (SELECT 1 FROM casino_notification_outbox WHERE game_id = 'fixture-e-pvp-recovery-001') THEN
        RAISE EXCEPTION 'unsettled recovery fixture must not have notification intents';
    END IF;
END $$;
SQL
else
  # Migrations grant privileges to this disposable non-login application role.
  # Do not alter a pre-existing role or grant it membership.
  run_psql <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        CREATE ROLE exchange_bot NOLOGIN;
    END IF;
END $$;

BEGIN;

-- add_external_deal_operator.sql requires these production-compatible base tables.
CREATE TABLE operator_accounts (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE,
    username VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128),
    password_hash TEXT NOT NULL,
    percent NUMERIC(6, 3) NOT NULL DEFAULT 10.0 CHECK (percent >= 0 AND percent <= 100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    operator_role TEXT NOT NULL CHECK (operator_role IN ('client', 'finance')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE operator_shifts (
    id SERIAL PRIMARY KEY,
    operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    note TEXT
);
CREATE UNIQUE INDEX ux_staging_payments_active_operator_shift
    ON operator_shifts (operator_id) WHERE ended_at IS NULL;

CREATE TABLE operator_payroll_ledger (
    id SERIAL PRIMARY KEY,
    type VARCHAR(20) NOT NULL CHECK (type IN ('accrual', 'hold', 'payout', 'release')),
    amount_rub NUMERIC(14, 2) NOT NULL,
    shift_id INT REFERENCES operator_shifts(id),
    operator_id INT REFERENCES operator_accounts(id),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE operator_shift_balances (
    id SERIAL PRIMARY KEY,
    shift_id INT NOT NULL REFERENCES operator_shifts(id) ON DELETE CASCADE,
    crypto VARCHAR(16) NOT NULL,
    balance_start NUMERIC(20, 8),
    balance_end NUMERIC(20, 8),
    UNIQUE (shift_id, crypto)
);

COMMIT;
SQL

  # Exact payments dependency chain. Casino migrations are excluded.
  run_psql -f "$MIGRATIONS_DIR/add_external_exchanges.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deals_status.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deal_payin.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_exchanger_accounts.sql"
  run_psql -f "$MIGRATIONS_DIR/add_exchanger_hmac_api_and_expires.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deal_receipt_type.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deal_client_is_new.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_exchanger_trust_flags.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_markup_mode.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deal_operator.sql"
  run_psql -f "$MIGRATIONS_DIR/add_operator_dual_roles.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deal_payout_on_credit.sql"
  run_psql -f "$MIGRATIONS_DIR/add_external_deal_payfast_reviews.sql"
  run_psql -f "$MIGRATIONS_DIR/add_web_users.sql"
  run_psql -f "$MIGRATIONS_DIR/add_web_telegram_bot_logins.sql"
  run_psql -f "$MIGRATIONS_DIR/add_captcha_challenges.sql"
  run_psql -f "$MIGRATIONS_DIR/add_login_username.sql"
  run_psql -f "$MIGRATIONS_DIR/add_admin_totp.sql"
  run_psql -f "$MIGRATIONS_DIR/add_site_reviews.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_review_submissions.sql"
  run_psql -f "$MIGRATIONS_DIR/add_security_access_log.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_web_chat.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_web_chat_telegram_bridge.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_shift_balances.sql"
  run_psql -f "$MIGRATIONS_DIR/add_payout_requisites.sql"
  run_psql -f "$MIGRATIONS_DIR/add_payout_requisite_queue.sql"
  run_psql -f "$MIGRATIONS_DIR/add_payin_open_requires_confirm.sql"
  run_psql -f "$MIGRATIONS_DIR/add_triangle_source_sell.sql"
  run_psql -f "$MIGRATIONS_DIR/add_triangle_source_withdrawal.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_order_crypto_confirmed.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_order_payin_requisite.sql"
  run_psql -f "$MIGRATIONS_DIR/add_requisite_retry_requests.sql"

  run_psql <<'SQL'
BEGIN;

CREATE TABLE owner_finance_ledger (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('commission', 'refund', 'expense', 'adjustment', 'payroll', 'transfer', 'other')),
    amount NUMERIC(14, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'RUB',
    source TEXT,
    reference TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'pending', 'void')),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
SQL

  run_psql -v profile="$PROFILE" -f "$FIXTURES_SQL"

  run_psql <<'SQL'
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'payments_exchanger') <> 1
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'client_operator') <> 1
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'finance_operator') <> 1 THEN
        RAISE EXCEPTION 'synthetic payments fixture roles are incomplete or duplicated';
    END IF;

    IF (SELECT COUNT(*) FROM external_exchangers WHERE id = 92001 AND is_active
                 AND is_trusted_client = FALSE AND auto_credit_on_payfast = FALSE
                 AND markup_mode = 'on_deal') <> 1
       OR (SELECT COUNT(*) FROM external_exchanger_accounts
           WHERE external_exchanger_id = 92001 AND username = 'fixture_payments_exchanger' AND is_active) <> 1
       OR (SELECT COUNT(*) FROM external_exchanger_api_keys WHERE exchanger_id = 92001 AND is_active) <> 1 THEN
        RAISE EXCEPTION 'synthetic payments exchanger or HMAC credential is missing';
    END IF;

    IF (SELECT COUNT(*) FROM operator_accounts
        WHERE (username = 'fixture_payments_client_ops' AND is_active AND operator_roles = ARRAY['client']::TEXT[])
           OR (username = 'fixture_payments_finance_ops' AND is_active AND operator_roles = ARRAY['finance']::TEXT[])) <> 2
       OR (SELECT COUNT(*) FROM operator_shifts WHERE ended_at IS NULL) <> 2 THEN
        RAISE EXCEPTION 'synthetic payments operators must be active with open shifts';
    END IF;

    IF (SELECT COUNT(*) FROM external_deals WHERE client_transaction_id = 'fixture-payments-deal-001'
                 AND status = 'confirmed' AND required_receipt_type = 2
                 AND client_is_new = TRUE AND markup_mode = 'on_deal'
                 AND operator_id = 93002 AND payout_on_credit = FALSE
                 AND payout_wallet IS NULL AND payout_id IS NULL) <> 1
       OR (SELECT COUNT(*) FROM external_ledger WHERE deal_id = (SELECT id FROM external_deals WHERE client_transaction_id = 'fixture-payments-deal-001')) <> 2
       OR (SELECT COUNT(*) FROM external_ledger WHERE deal_id = (SELECT id FROM external_deals WHERE client_transaction_id = 'fixture-payments-deal-001') AND type = 'principal') <> 1 THEN
        RAISE EXCEPTION 'synthetic payments deal ledger entries are missing or duplicated';
    END IF;

    IF (SELECT COUNT(*) FROM owner_finance_ledger WHERE reference = 'fixture-payments-finance-001') <> 1 THEN
        RAISE EXCEPTION 'synthetic payments finance entry is missing or duplicated';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'casino_%') THEN
        RAISE EXCEPTION 'payments profile must not install casino tables';
    END IF;
END $$;
SQL
fi

printf 'Synthetic staging PostgreSQL bootstrap completed for profile: %s\n' "$PROFILE"
