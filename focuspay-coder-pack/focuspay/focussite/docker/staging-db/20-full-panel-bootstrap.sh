#!/usr/bin/env bash
# Bootstrap an empty synthetic database for the public site and panels.
set -euo pipefail

PROFILE="${1:-full-panel}"
case "$PROFILE" in
  full-panel|full-panel-pvp) ;;
  *)
    printf 'Unsupported full-panel bootstrap profile: %s\n' "$PROFILE" >&2
    exit 64
    ;;
esac
export STAGING_BOOTSTRAP_PROFILE="$PROFILE"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-$REPO_ROOT/site/exchange-backend/migrations}"
BOT_MIGRATIONS_DIR="${BOT_MIGRATIONS_DIR:-$REPO_ROOT/bot/tg_bot_btc/migrations}"
FIXTURES_SQL="$SCRIPT_DIR/20-full-panel-fixtures.sql"

run_psql() {
  psql -X -v ON_ERROR_STOP=1 "$@"
}

required_artifacts=(
  "$FIXTURES_SQL"
  "$BOT_MIGRATIONS_DIR/create_tables.sql"
  "$BOT_MIGRATIONS_DIR/add_bot_users_captcha.sql"
  "$BOT_MIGRATIONS_DIR/add_user_ban.sql"
  "$BOT_MIGRATIONS_DIR/add_account_review_and_username_history.sql"
  "$BOT_MIGRATIONS_DIR/add_pending_ref_token.sql"
  "$BOT_MIGRATIONS_DIR/add_referral_locked.sql"
  "$BOT_MIGRATIONS_DIR/add_bot_start_ref_log.sql"
  "$BOT_MIGRATIONS_DIR/add_app_settings.sql"
  "$MIGRATIONS_DIR/add_web_users.sql"
  "$MIGRATIONS_DIR/telegram_only_web_users.sql"
  "$BOT_MIGRATIONS_DIR/add_operator_accounts.sql"
  "$MIGRATIONS_DIR/add_web_password_auth.sql"
  "$MIGRATIONS_DIR/add_captcha_challenges.sql"
  "$MIGRATIONS_DIR/add_user_recovery_and_sessions.sql"
  "$MIGRATIONS_DIR/add_web_telegram_bot_logins.sql"
  "$MIGRATIONS_DIR/add_admin_totp.sql"
  "$MIGRATIONS_DIR/add_security_access_log.sql"
  "$BOT_MIGRATIONS_DIR/add_operator_shifts.sql"
  "$BOT_MIGRATIONS_DIR/add_operator_id_to_orders.sql"
  "$BOT_MIGRATIONS_DIR/add_operator_order_features.sql"
  "$BOT_MIGRATIONS_DIR/add_operator_shift_balances.sql"
  "$MIGRATIONS_DIR/add_operator_payroll_pool.sql"
  "$MIGRATIONS_DIR/add_operator_roles_payroll_split.sql"
  "$MIGRATIONS_DIR/add_operator_dual_roles.sql"
  "$MIGRATIONS_DIR/add_operator_payroll_split_v2.sql"
  "$MIGRATIONS_DIR/add_operator_sla_columns.sql"
  "$MIGRATIONS_DIR/add_order_economics_snapshot.sql"
  "$MIGRATIONS_DIR/add_payout_tx.sql"
  "$MIGRATIONS_DIR/add_operator_shift_usdt_issued.sql"
  "$MIGRATIONS_DIR/add_operator_usdt_issuances.sql"
  "$MIGRATIONS_DIR/add_operator_avatar.sql"
  "$BOT_MIGRATIONS_DIR/add_web_chat.sql"
  "$BOT_MIGRATIONS_DIR/add_web_chat_one_thread_per_user.sql"
  "$BOT_MIGRATIONS_DIR/add_web_chat_telegram_bridge.sql"
  "$MIGRATIONS_DIR/add_operator_sticker_sets_and_chat_templates.sql"
  "$BOT_MIGRATIONS_DIR/add_payin_split_cashback.sql"
  "$BOT_MIGRATIONS_DIR/add_user_referral.sql"
  "$BOT_MIGRATIONS_DIR/add_promo_tables.sql"
  "$BOT_MIGRATIONS_DIR/add_promo_ref_token.sql"
  "$BOT_MIGRATIONS_DIR/add_partner_tier_settings.sql"
  "$BOT_MIGRATIONS_DIR/add_campaign_fixed_bonus.sql"
  "$BOT_MIGRATIONS_DIR/add_promo_bonus_usage.sql"
  "$BOT_MIGRATIONS_DIR/add_promo_gift_redemptions.sql"
  "$BOT_MIGRATIONS_DIR/add_promo_max_activations.sql"
  "$BOT_MIGRATIONS_DIR/add_promo_issued_by_operator.sql"
  "$MIGRATIONS_DIR/add_partner_referral.sql"
  "$MIGRATIONS_DIR/add_partner_withdrawals.sql"
  "$BOT_MIGRATIONS_DIR/add_referral_discount_spend.sql"
  "$MIGRATIONS_DIR/add_admin_salary_recipients.sql"
  "$MIGRATIONS_DIR/add_external_exchanges.sql"
  "$MIGRATIONS_DIR/add_external_deals_status.sql"
  "$MIGRATIONS_DIR/add_owner_finance_ledger.sql"
  "$BOT_MIGRATIONS_DIR/add_review_bonus_claims.sql"
  "$BOT_MIGRATIONS_DIR/add_review_bonus_source_message.sql"
  "$BOT_MIGRATIONS_DIR/add_review_submissions.sql"
  "$BOT_MIGRATIONS_DIR/add_raffle.sql"
  "$MIGRATIONS_DIR/add_operator_wallet_payouts.sql"
  "$MIGRATIONS_DIR/add_swap_commission_entries.sql"
  "$MIGRATIONS_DIR/add_swap_commission_part_index.sql"
  "$MIGRATIONS_DIR/add_swap_commission_panel_send.sql"
  "$MIGRATIONS_DIR/add_exchange_discounts.sql"
  "$BOT_MIGRATIONS_DIR/add_exchange_discount_min_order.sql"
  "$BOT_MIGRATIONS_DIR/add_exchange_discount_operator_grant.sql"
  "$MIGRATIONS_DIR/add_manual_expenses.sql"
  "$MIGRATIONS_DIR/alter_manual_expenses_fields.sql"
  "$MIGRATIONS_DIR/add_login_username.sql"
  "$MIGRATIONS_DIR/add_site_reviews.sql"
  "$MIGRATIONS_DIR/add_payout_requisites.sql"
  "$MIGRATIONS_DIR/add_payout_requisite_queue.sql"
  "$MIGRATIONS_DIR/add_payin_open_requires_confirm.sql"
  "$MIGRATIONS_DIR/add_triangle_source_sell.sql"
  "$MIGRATIONS_DIR/add_triangle_source_withdrawal.sql"
  "$BOT_MIGRATIONS_DIR/add_order_crypto_confirmed.sql"
  "$BOT_MIGRATIONS_DIR/add_order_payin_requisite.sql"
)

if [[ "$PROFILE" == "full-panel-pvp" ]]; then
  required_artifacts+=(
    "$MIGRATIONS_DIR/add_casino_tables.sql"
    "$MIGRATIONS_DIR/fix_casino_backend_integrity.sql"
    "$MIGRATIONS_DIR/add_casino_durable_recovery.sql"
    "$MIGRATIONS_DIR/add_casino_game_chat_bindings.sql"
    "$MIGRATIONS_DIR/add_casino_game_chat_binding_telegram_url.sql"
    "$MIGRATIONS_DIR/add_casino_house_bankroll.sql"
    "$MIGRATIONS_DIR/add_casino_deposit_credits.sql"
    "$MIGRATIONS_DIR/add_casino_deposit_credit_rail.sql"
    "$MIGRATIONS_DIR/add_casino_wagering_locks.sql"
    "$MIGRATIONS_DIR/add_casino_crypto_deposits.sql"
    "$MIGRATIONS_DIR/add_casino_wagering_commission_profiles.sql"
    "$MIGRATIONS_DIR/add_casino_creator_accounts.sql"
    "$MIGRATIONS_DIR/add_casino_creator_withdrawal_idempotency.sql"
    "$MIGRATIONS_DIR/add_casino_multiplayer_v2.sql"
    "$MIGRATIONS_DIR/add_casino_v2_house_ledger.sql"
    "$MIGRATIONS_DIR/add_casino_pvp_dm_invitations.sql"
    "$MIGRATIONS_DIR/add_casino_weekly_cashback_tiers.sql"
    "$MIGRATIONS_DIR/add_casino_volume_tier_grids.sql"
    "$MIGRATIONS_DIR/add_casino_settings_v2.sql"
    "$MIGRATIONS_DIR/add_casino_settings_audit.sql"
    "$MIGRATIONS_DIR/add_casino_fairness_seeds.sql"
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
    "$MIGRATIONS_DIR/add_casino_fixed_rooms.sql"
    "$MIGRATIONS_DIR/add_casino_fixed_room_bots.sql"
    "$MIGRATIONS_DIR/add_casino_live_mosaic.sql"
    "$MIGRATIONS_DIR/add_casino_clan_wars.sql"
    "$MIGRATIONS_DIR/add_casino_house_tables.sql"
    "$MIGRATIONS_DIR/add_casino_house_tables_solo.sql"
    "$MIGRATIONS_DIR/add_casino_player_cosmetics.sql"
    "$MIGRATIONS_DIR/add_casino_notify_open_tables.sql"
    "$MIGRATIONS_DIR/add_casino_web_inbox.sql"
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
    "$MIGRATIONS_DIR/add_rbac_templates_hardening.sql"
    "$BOT_MIGRATIONS_DIR/add_network_fee_rub.sql"
    "$BOT_MIGRATIONS_DIR/add_withdrawal_payout_tx.sql"
    "$MIGRATIONS_DIR/add_withdrawal_operator_id.sql"
    "$MIGRATIONS_DIR/add_casino_v2_web_client_ids.sql"
    "$MIGRATIONS_DIR/add_casino_v2_outbox_web_client_ids.sql"
    "$MIGRATIONS_DIR/add_casino_notification_delivery_policy.sql"
    "$SCRIPT_DIR/21-full-panel-pvp-fixtures.sql"
  )
fi

for required in "${required_artifacts[@]}"; do
  if [[ ! -r "$required" ]]; then
    printf 'Required full-panel bootstrap artifact is unavailable: %s\n' "$required" >&2
    exit 66
  fi
done

existing_state="$(run_psql -Atqc "
  SELECT string_agg(name, ', ' ORDER BY name)
  FROM (
    SELECT 'orders' AS name WHERE to_regclass('public.orders') IS NOT NULL
    UNION ALL SELECT 'staging_fixture_roles' WHERE to_regclass('public.staging_fixture_roles') IS NOT NULL
    UNION ALL SELECT 'casino_games' WHERE to_regclass('public.casino_games') IS NOT NULL
  ) state;
")"
if [[ -n "$existing_state" ]]; then
  existing_fixture_roles="$(run_psql -Atqc "
    SELECT string_agg(fixture_role, ',' ORDER BY fixture_role)
    FROM staging_fixture_roles;
  " 2>/dev/null || true)"
  expected_state="orders, staging_fixture_roles"
  expected_roles="admin,buyer,client_operator,external_exchanger,finance_operator,partner"
  if [[ "$PROFILE" == "full-panel-pvp" ]]; then
    expected_state="casino_games, orders, staging_fixture_roles"
    expected_roles="admin,buyer,client_operator,external_exchanger,finance_operator,partner,player_a,player_b"
  fi
  if [[ "$existing_state" == "$expected_state" && "$existing_fixture_roles" == "$expected_roles" ]] \
    && [[ "$(run_psql -Atqc "
      SELECT COUNT(*)
      FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'bot_users'
        AND column_name IN (
          'captcha_passed_at', 'is_banned', 'ban_type', 'ban_reason', 'banned_at', 'banned_by_op_id',
          'previous_username', 'username_changed_at', 'account_review_status',
          'account_review_reason', 'account_reviewed_at', 'account_reviewed_by',
          'pending_ref_token', 'referral_locked', 'ref_token', 'use_cashback_on_next_order'
        );
    ")" == "16" ]] \
    && [[ "$(run_psql -Atqc "
      SELECT COUNT(*)
      FROM pg_tables
      WHERE schemaname = 'public'
        AND tablename IN (
          'app_settings', 'bot_start_ref_log', 'promo_bonus_usages', 'promo_gift_redemptions',
          'user_cashback_ledger', 'user_referral_attributions', 'user_referral_ledger',
          'user_referral_withdrawals', 'partner_accounts', 'partner_ledger',
          'partner_withdrawals', 'user_exchange_discounts'
        );
    ")" == "12" ]] \
    && [[ "$(run_psql -Atqc "
      SELECT COUNT(*)
      FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'promo_campaigns'
        AND column_name IN (
          'ref_token', 'campaign_kind', 'client_fixed_bonus_rub', 'max_activations',
          'partner_tier_base_percent', 'partner_tier_step_percent',
          'partner_tier_every_n', 'partner_tier_max_percent'
        );
    ")" == "8" ]] \
    && [[ "$(run_psql -Atqc "
      SELECT COUNT(*) FROM pg_tables
      WHERE schemaname = 'public' AND tablename = 'app_settings';
    ")" == "1" ]]; then
    printf 'Synthetic staging PostgreSQL %s bootstrap already completed.\n' "$PROFILE"
    # Idempotent casino settings inserts. Fresh bootstrap never reaches here;
    # without this, staging-sync would skip add_casino_settings_v2.sql forever.
    if [[ "$PROFILE" == "full-panel-pvp" ]]; then
      run_psql -f "$MIGRATIONS_DIR/add_payout_requisites.sql"
      run_psql -f "$MIGRATIONS_DIR/add_payout_requisite_queue.sql"
      run_psql -f "$MIGRATIONS_DIR/add_payin_open_requires_confirm.sql"
      run_psql -f "$MIGRATIONS_DIR/add_triangle_source_sell.sql"
      run_psql -f "$MIGRATIONS_DIR/add_triangle_source_withdrawal.sql"
      run_psql -f "$BOT_MIGRATIONS_DIR/add_order_crypto_confirmed.sql"
      run_psql -f "$BOT_MIGRATIONS_DIR/add_order_payin_requisite.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_deposit_credit_rail.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_volume_tier_grids.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_settings_v2.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_settings_audit.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_fairness_seeds.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_drop_sport_pvp.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_poker_tables.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_nardy_tables.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_draughts.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_chat.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_jackpot.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_clans.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_level_bonus.sql"
      run_psql -f "$MIGRATIONS_DIR/seed_casino_level_reach_bonuses.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_fixed_rooms.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_fixed_room_bots.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_live_mosaic.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_clan_wars.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_house_tables.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_house_tables_solo.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_player_cosmetics.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_notify_open_tables.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_web_inbox.sql"
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
      run_psql -f "$MIGRATIONS_DIR/add_rbac_templates_hardening.sql"
      run_psql -f "$BOT_MIGRATIONS_DIR/add_network_fee_rub.sql"
      run_psql -f "$BOT_MIGRATIONS_DIR/add_withdrawal_payout_tx.sql"
      run_psql -f "$MIGRATIONS_DIR/add_withdrawal_operator_id.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_v2_web_client_ids.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_v2_outbox_web_client_ids.sql"
      run_psql -f "$MIGRATIONS_DIR/add_casino_notification_delivery_policy.sql"
    fi
    exit 0
  fi
  printf 'Refusing %s bootstrap: database is not empty (%s). Create a new disposable volume.\n' "$PROFILE" "$existing_state" >&2
  exit 65
fi

run_psql <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        CREATE ROLE exchange_bot NOLOGIN;
    END IF;
END $$;
SQL

run_psql -f "$BOT_MIGRATIONS_DIR/create_tables.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_bot_users_captcha.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_user_ban.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_account_review_and_username_history.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_pending_ref_token.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_bot_start_ref_log.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_app_settings.sql"
run_psql -f "$MIGRATIONS_DIR/add_web_users.sql"
run_psql -f "$MIGRATIONS_DIR/telegram_only_web_users.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_accounts.sql"
run_psql -f "$MIGRATIONS_DIR/add_web_password_auth.sql"
run_psql -f "$MIGRATIONS_DIR/add_captcha_challenges.sql"
run_psql -f "$MIGRATIONS_DIR/add_user_recovery_and_sessions.sql"
run_psql -f "$MIGRATIONS_DIR/add_web_telegram_bot_logins.sql"
run_psql -f "$MIGRATIONS_DIR/add_admin_totp.sql"
run_psql -f "$MIGRATIONS_DIR/add_security_access_log.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_shifts.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_id_to_orders.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_order_features.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_operator_shift_balances.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_payroll_pool.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_roles_payroll_split.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_dual_roles.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_payroll_split_v2.sql"
# orders.claimed_at / operator_completed_at; confirm_sell_paid writes claimed_at.
run_psql -f "$MIGRATIONS_DIR/add_operator_sla_columns.sql"
run_psql -f "$MIGRATIONS_DIR/add_order_economics_snapshot.sql"
run_psql <<'SQL'
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS card_fee_pct NUMERIC(6, 4) NOT NULL DEFAULT 0;
SQL
run_psql -f "$MIGRATIONS_DIR/add_payout_tx.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_shift_usdt_issued.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_usdt_issuances.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_avatar.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_web_chat.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_web_chat_one_thread_per_user.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_web_chat_telegram_bridge.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_sticker_sets_and_chat_templates.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_payin_split_cashback.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_user_referral.sql"
# Backfills referral_locked from user_referral_attributions, so it must follow add_user_referral.
run_psql -f "$BOT_MIGRATIONS_DIR/add_referral_locked.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_promo_tables.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_promo_ref_token.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_partner_tier_settings.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_promo_bonus_usage.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_promo_gift_redemptions.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_promo_max_activations.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_promo_issued_by_operator.sql"
run_psql -f "$MIGRATIONS_DIR/add_partner_referral.sql"
run_psql -f "$MIGRATIONS_DIR/add_partner_withdrawals.sql"
# Touches partner_accounts and promo_bonus_usages, so it must follow both of their migrations.
run_psql -f "$BOT_MIGRATIONS_DIR/add_campaign_fixed_bonus.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_referral_discount_spend.sql"
run_psql -f "$MIGRATIONS_DIR/add_admin_salary_recipients.sql"
run_psql -f "$MIGRATIONS_DIR/add_external_exchanges.sql"
run_psql -f "$MIGRATIONS_DIR/add_external_deals_status.sql"
run_psql -f "$MIGRATIONS_DIR/add_owner_finance_ledger.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_review_bonus_claims.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_review_bonus_source_message.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_raffle.sql"
run_psql -f "$MIGRATIONS_DIR/add_operator_wallet_payouts.sql"
run_psql -f "$MIGRATIONS_DIR/add_swap_commission_entries.sql"
run_psql -f "$MIGRATIONS_DIR/add_swap_commission_part_index.sql"
run_psql -f "$MIGRATIONS_DIR/add_swap_commission_panel_send.sql"
run_psql -f "$MIGRATIONS_DIR/add_exchange_discounts.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_exchange_discount_min_order.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_exchange_discount_operator_grant.sql"
run_psql -f "$MIGRATIONS_DIR/add_manual_expenses.sql"
run_psql -f "$MIGRATIONS_DIR/alter_manual_expenses_fields.sql"
run_psql -f "$MIGRATIONS_DIR/add_login_username.sql"
run_psql -f "$MIGRATIONS_DIR/add_site_reviews.sql"
# Adds columns to site_reviews, so it must follow add_site_reviews.
run_psql -f "$BOT_MIGRATIONS_DIR/add_review_submissions.sql"
run_psql -f "$MIGRATIONS_DIR/add_payout_requisites.sql"
run_psql -f "$MIGRATIONS_DIR/add_payout_requisite_queue.sql"
run_psql -f "$MIGRATIONS_DIR/add_payin_open_requires_confirm.sql"
run_psql -f "$MIGRATIONS_DIR/add_triangle_source_sell.sql"
run_psql -f "$MIGRATIONS_DIR/add_triangle_source_withdrawal.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_order_crypto_confirmed.sql"
run_psql -f "$BOT_MIGRATIONS_DIR/add_order_payin_requisite.sql"

if [[ "$PROFILE" == "full-panel-pvp" ]]; then
  run_psql -f "$MIGRATIONS_DIR/add_casino_tables.sql"
  run_psql -f "$MIGRATIONS_DIR/fix_casino_backend_integrity.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_durable_recovery.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_weekly_cashback_tiers.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_game_chat_bindings.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_game_chat_binding_telegram_url.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_house_bankroll.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_deposit_credits.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_deposit_credit_rail.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_wagering_locks.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_crypto_deposits.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_wagering_commission_profiles.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_creator_accounts.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_creator_withdrawal_idempotency.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_multiplayer_v2.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_v2_house_ledger.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_pvp_dm_invitations.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_v2_table_chat.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_drop_sport_pvp.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_volume_tier_grids.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_settings_v2.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_settings_audit.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_fairness_seeds.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_poker_tables.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_nardy_tables.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_draughts.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_chat.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_jackpot.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_clans.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_level_bonus.sql"
  run_psql -f "$MIGRATIONS_DIR/seed_casino_level_reach_bonuses.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_fixed_rooms.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_fixed_room_bots.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_live_mosaic.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_clan_wars.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_house_tables.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_house_tables_solo.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_player_cosmetics.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_notify_open_tables.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_web_inbox.sql"
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
  run_psql -f "$MIGRATIONS_DIR/add_rbac_templates_hardening.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_network_fee_rub.sql"
  run_psql -f "$BOT_MIGRATIONS_DIR/add_withdrawal_payout_tx.sql"
  run_psql -f "$MIGRATIONS_DIR/add_withdrawal_operator_id.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_v2_web_client_ids.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_v2_outbox_web_client_ids.sql"
  run_psql -f "$MIGRATIONS_DIR/add_casino_notification_delivery_policy.sql"
fi

run_psql -f "$FIXTURES_SQL"
if [[ "$PROFILE" == "full-panel-pvp" ]]; then
  run_psql -f "$SCRIPT_DIR/21-full-panel-pvp-fixtures.sql"
fi

: "${STAGING_SYNTHETIC_ADMIN_USERNAME:?STAGING_SYNTHETIC_ADMIN_USERNAME must be set}"
: "${STAGING_SYNTHETIC_ADMIN_PASSWORD:?STAGING_SYNTHETIC_ADMIN_PASSWORD must be set}"
if [[ "$PROFILE" == "full-panel-pvp" ]]; then
  : "${STAGING_SYNTHETIC_CLIENT_OPERATOR_PASSWORD:?STAGING_SYNTHETIC_CLIENT_OPERATOR_PASSWORD must be set}"
  : "${STAGING_SYNTHETIC_FINANCE_OPERATOR_PASSWORD:?STAGING_SYNTHETIC_FINANCE_OPERATOR_PASSWORD must be set}"
fi
password_hashes="$(python - <<'PY'
import bcrypt
import os

keys = ["STAGING_SYNTHETIC_ADMIN_PASSWORD"]
if os.environ.get("STAGING_BOOTSTRAP_PROFILE") == "full-panel-pvp":
    keys.extend((
        "STAGING_SYNTHETIC_CLIENT_OPERATOR_PASSWORD",
        "STAGING_SYNTHETIC_FINANCE_OPERATOR_PASSWORD",
    ))

for key in keys:
    print(bcrypt.hashpw(os.environ[key].encode(), bcrypt.gensalt()).decode())
PY
)"
mapfile -t password_hashes <<<"$password_hashes"
run_psql \
  -v admin_username="$STAGING_SYNTHETIC_ADMIN_USERNAME" \
  -v admin_password_hash="${password_hashes[0]}" <<'SQL'
UPDATE web_users
SET username = :'admin_username',
    password_hash = :'admin_password_hash',
    totp_enabled = FALSE,
    totp_secret = NULL
WHERE id = 940001 AND is_admin = TRUE;
SQL

if [[ "$PROFILE" == "full-panel-pvp" ]]; then
  run_psql \
    -v client_operator_password_hash="${password_hashes[1]}" \
    -v finance_operator_password_hash="${password_hashes[2]}" <<'SQL'
UPDATE operator_accounts
SET password_hash = :'client_operator_password_hash',
    totp_enabled = FALSE,
    totp_secret = NULL,
    is_active = TRUE
WHERE id = 940101 AND username = 'fixture_full_client_ops';

UPDATE operator_accounts
SET password_hash = :'finance_operator_password_hash',
    totp_enabled = FALSE,
    is_active = TRUE
WHERE id = 940102 AND username = 'fixture_full_finance_ops';
SQL
fi

if [[ "$(run_psql -Atq -v admin_username="$STAGING_SYNTHETIC_ADMIN_USERNAME" <<'SQL'
SELECT COUNT(*)
FROM web_users
WHERE id = 940001 AND is_admin = TRUE AND username = :'admin_username'
  AND password_hash <> 'synthetic-managed-on-staging'
  AND totp_enabled = FALSE AND totp_secret IS NULL;
SQL
)" != "1" ]]; then
  printf 'full-panel synthetic admin login fixture is missing\n' >&2
  exit 67
fi

if [[ "$(run_psql -Atq <<'SQL'
SELECT COUNT(*)
FROM operator_accounts
WHERE (id, username) IN ((940101, 'fixture_full_client_ops'), (940102, 'fixture_full_finance_ops'))
  AND password_hash <> 'synthetic-disabled-login'
  AND is_active = TRUE
  AND totp_enabled = FALSE AND totp_secret IS NULL;
SQL
)" != "2" ]]; then
  printf 'full-panel synthetic operator login fixtures are incomplete\n' >&2
  exit 67
fi

run_psql <<'SQL'
DO $$
DECLARE
    required_name TEXT;
BEGIN
    FOREACH required_name IN ARRAY ARRAY[
        'web_users', 'captcha_challenges', 'operator_accounts', 'operator_shifts',
        'operator_shift_balances', 'operator_payroll_ledger', 'operator_payout_requests',
        'web_chat_threads', 'web_chat_messages', 'telegram_business_connections',
        'site_reviews', 'security_access_log', 'user_cashback_ledger',
        'user_referral_ledger', 'user_referral_withdrawals', 'promo_campaigns',
        'partner_accounts', 'partner_ledger', 'partner_withdrawals',
        'admin_salary_recipients', 'external_exchangers', 'external_ledger', 'external_payouts',
        'owner_finance_ledger', 'review_bonus_claims', 'raffle_winners',
        'operator_wallet_payouts', 'swap_commission_entries', 'user_exchange_discounts',
        'promo_bonus_usages', 'promo_gift_redemptions', 'bot_start_ref_log',
        'manual_expenses'
    ] LOOP
        IF to_regclass('public.' || required_name) IS NULL THEN
            RAISE EXCEPTION 'missing full-panel bootstrap table: %', required_name;
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bot_users' AND column_name = 'captcha_passed_at'
    ) OR EXISTS (
        SELECT 1
        FROM unnest(ARRAY[
            'is_banned', 'ban_type', 'ban_reason', 'banned_at', 'banned_by_op_id',
            'previous_username', 'username_changed_at', 'account_review_status',
            'account_review_reason', 'account_reviewed_at', 'account_reviewed_by',
            'pending_ref_token', 'referral_locked', 'ref_token', 'use_cashback_on_next_order'
        ]) AS required_column
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'bot_users'
              AND column_name = required_column
        )
    ) THEN
        RAISE EXCEPTION 'full-panel bot_users schema is missing start-handler fields';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(ARRAY[
            'ref_token', 'campaign_kind', 'client_fixed_bonus_rub', 'max_activations',
            'exchange_discount_min_order_rub', 'partner_tier_base_percent',
            'partner_tier_step_percent', 'partner_tier_every_n', 'partner_tier_max_percent'
        ]) AS required_column
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'promo_campaigns'
              AND column_name = required_column
        )
    ) THEN
        RAISE EXCEPTION 'full-panel promo_campaigns schema is missing start/menu fields';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(ARRAY['min_order_rub', 'issued_by_operator_id']) AS required_column
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'user_exchange_discounts'
              AND column_name = required_column
        )
    ) OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'promo_bonus_usages'
          AND column_name = 'bonus_fixed_rub'
    ) THEN
        RAISE EXCEPTION 'full-panel promo and discount schema is incomplete';
    END IF;

    PERFORM 1 FROM bot_start_ref_log LIMIT 1;
    PERFORM 1 FROM promo_gift_redemptions LIMIT 1;
    PERFORM 1 FROM user_cashback_ledger LIMIT 1;
    PERFORM 1 FROM user_exchange_discounts LIMIT 1;

    IF (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'admin') <> 1
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'buyer') <> 1
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'client_operator') <> 1
       OR (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role = 'finance_operator') <> 1 THEN
        RAISE EXCEPTION 'full-panel synthetic fixture roles are incomplete or duplicated';
    END IF;
END $$;
SQL

if [[ "$PROFILE" == "full-panel" ]]; then
  if [[ "$(run_psql -Atqc "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'casino_%';")" != "0" ]]; then
    printf 'full-panel profile must not install casino tables\n' >&2
    exit 67
  fi
else
  run_psql <<'SQL'
DO $$
DECLARE
    required_name TEXT;
BEGIN
    FOREACH required_name IN ARRAY ARRAY[
        'casino_games', 'casino_balance_holds', 'casino_settings',
        'casino_settings_audit',
        'casino_commission_ledger', 'casino_notification_outbox',
        'casino_game_chat_bindings', 'casino_house_accounts', 'casino_house_ledger',
        'casino_creator_accounts',
        'casino_poker_tables', 'casino_chat_rooms', 'casino_jackpot_rounds',
        'casino_roulette_rounds', 'casino_roulette_bets',
        'casino_level_bonus_grants',
        'casino_house_tables', 'casino_house_table_seats'
    ] LOOP
        IF to_regclass('public.' || required_name) IS NULL THEN
            RAISE EXCEPTION 'missing full-panel-pvp bootstrap table: %', required_name;
        END IF;
    END LOOP;

    IF (SELECT COUNT(*) FROM staging_fixture_roles WHERE fixture_role IN ('player_a', 'player_b')) <> 2
       OR (SELECT COUNT(*) FROM casino_game_chat_bindings WHERE status = 'active') <> 1
       OR (SELECT COUNT(*) FROM casino_games WHERE game_id = 'fixture-full-pvp-finished-001' AND status = 'finished') <> 1
       OR (SELECT COUNT(*) FROM casino_games WHERE game_id = 'fixture-full-pvp-recovery-001' AND status = 'outcome_committed') <> 1 THEN
        RAISE EXCEPTION 'full-panel-pvp casino fixtures are incomplete';
    END IF;
END $$;
SQL
fi

printf 'Synthetic staging PostgreSQL %s bootstrap completed.\n' "$PROFILE"
