#!/usr/bin/env bash
# Деплой партнёров/промо: бот, API, фронт, миграция.
# Использование: DEPLOY_HOST=root@your-server ./deploy/deploy-partners.sh

set -euo pipefail
HOST="${DEPLOY_HOST:-focuspay}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BOT_LOCAL="${BOT_LOCAL:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
EXCHANGE_LOCAL="${EXCHANGE_LOCAL:-/home/qwe/Desktop/exchange}"
FRONTEND_DIST="${FRONTEND_DIST:-$EXCHANGE_LOCAL/frontend/dist}"
BOT_ENV_FILE="${BOT_ENV_FILE:-$BOT_LOCAL/.env}"
BACKEND_ENV_FILE="${BACKEND_ENV_FILE:-$EXCHANGE_LOCAL/backend/.env}"

printf '==> Predeploy validation\n'
"$BOT_LOCAL/scripts/validate_env.sh" "$BOT_ENV_FILE"
"$EXCHANGE_LOCAL/backend/scripts/validate_env.sh" "$BACKEND_ENV_FILE"

run_migration() {
  local file="$1"
  [ -f "$file" ] || { echo "    skip (missing): $file"; return 0; }
  echo "    $file"
  ssh "$HOST" 'sudo -u postgres psql -d exchange_bot -v ON_ERROR_STOP=1 -f -' < "$file"
}

echo "==> Миграция БД на сервере"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_web_users.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/telegram_only_web_users.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_partner_referral.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_login_username.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_promo_ref_token.sql"
run_migration "$BOT_LOCAL/migrations/add_campaign_fixed_bonus.sql"
run_migration "$BOT_LOCAL/migrations/widen_campaign_kind.sql"
run_migration "$BOT_LOCAL/migrations/add_web_guest_sessions.sql"
run_migration "$BOT_LOCAL/migrations/add_web_order_ip.sql"
run_migration "$BOT_LOCAL/migrations/add_web_chat.sql"
run_migration "$BOT_LOCAL/migrations/add_chat_images.sql"
run_migration "$BOT_LOCAL/migrations/add_user_referral.sql"
run_migration "$BOT_LOCAL/migrations/add_payin_split_cashback.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_partner_ledger_hold_spend.sql"
run_migration "$BOT_LOCAL/migrations/add_partner_ledger_hold_spend.sql"
run_migration "$BOT_LOCAL/migrations/add_financial_safeguards.sql"
run_migration "$BOT_LOCAL/migrations/add_promo_ref_token.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_site_reviews.sql"
run_migration "$BOT_LOCAL/migrations/add_payout_tx.sql"
run_migration "$BOT_LOCAL/migrations/add_payout_tx_unique.sql"
run_migration "$BOT_LOCAL/migrations/add_withdrawal_payout_tx.sql"
run_migration "$BOT_LOCAL/migrations/add_promo_gift_redemptions.sql"
run_migration "$BOT_LOCAL/migrations/add_promo_tables.sql"
run_migration "$BOT_LOCAL/migrations/add_card_fee_pct.sql"
run_migration "$BOT_LOCAL/migrations/add_owner_stale_alerts.sql"
run_migration "$BOT_LOCAL/migrations/add_review_bonus_claims.sql"
run_migration "$BOT_LOCAL/migrations/add_admin_payroll_roles.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_accounts.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_shifts.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_id_to_orders.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_order_features.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_payout_amounts.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_avatar.sql"
run_migration "$BOT_LOCAL/migrations/add_app_settings.sql"
run_migration "$EXCHANGE_LOCAL/migrations/add_security_access_log.sql"
run_migration "$BOT_LOCAL/migrations/add_partner_telegram_bind_token.sql"
run_migration "$BOT_LOCAL/migrations/add_promo_max_activations.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_promo_max_activations.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_promo_issued_by_operator.sql"
run_migration "$BOT_LOCAL/migrations/add_promo_issued_by_operator.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/promo_created_by_nullable.sql"
run_migration "$BOT_LOCAL/migrations/promo_created_by_nullable.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/promo_deactivate_exhausted.sql"
run_migration "$BOT_LOCAL/migrations/promo_deactivate_exhausted.sql"
run_migration "$BOT_LOCAL/migrations/add_pending_ref_token.sql"
run_migration "$BOT_LOCAL/migrations/add_referral_locked.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_referral_locked.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_admin_totp.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_web_password_auth.sql"
run_migration "$BOT_LOCAL/migrations/add_web_password_auth.sql"
run_migration "$BOT_LOCAL/migrations/add_partner_tier_settings.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_partner_tier_settings.sql"
run_migration "$BOT_LOCAL/migrations/add_partner_totp.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_partner_totp.sql"
run_migration "$BOT_LOCAL/migrations/add_partner_withdrawals.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_partner_withdrawals.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_admin_weekly_salary.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_admin_salary_recipients.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_manual_expenses.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/alter_manual_expenses_fields.sql"
run_migration "$BOT_LOCAL/migrations/add_exchange_discounts.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_exchange_discounts.sql"
run_migration "$BOT_LOCAL/migrations/add_exchange_discount_min_order.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_exchange_discount_min_order.sql"
run_migration "$BOT_LOCAL/migrations/add_web_attribution_pending.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_web_attribution_pending.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_operator_shift_usdt_issued.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_operator_usdt_issuances.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_user_recovery_and_sessions.sql"
run_migration "$BOT_LOCAL/migrations/add_order_cancel_reason.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_order_cancel_reason.sql"
run_migration "$BOT_LOCAL/migrations/add_exchange_discount_operator_grant.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_exchange_discount_operator_grant.sql"
run_migration "$BOT_LOCAL/migrations/add_ops_alert_dedup.sql"
run_migration "$BOT_LOCAL/migrations/add_no_shift_requisites_blocks.sql"
run_migration "$BOT_LOCAL/migrations/add_raffle.sql"
run_migration "$BOT_LOCAL/migrations/add_raffle_admin.sql"
run_migration "$BOT_LOCAL/migrations/add_review_submissions.sql"
run_migration "$BOT_LOCAL/migrations/add_review_web_moderation.sql"
run_migration "$BOT_LOCAL/migrations/add_swap_commission_entries.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_swap_commission_entries.sql"
run_migration "$BOT_LOCAL/migrations/add_swap_commission_part_index.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_swap_commission_part_index.sql"
run_migration "$BOT_LOCAL/migrations/add_web_chat_telegram_bridge.sql"
run_migration "$BOT_LOCAL/migrations/add_web_chat_one_thread_per_user.sql"
run_migration "$BOT_LOCAL/migrations/add_chat_media_types.sql"
run_migration "$EXCHANGE_LOCAL/migrations/add_chat_media_types.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_operator_wallet_payouts.sql"
run_migration "$BOT_LOCAL/migrations/add_operator_wallet_payouts.sql"
run_migration "$BOT_LOCAL/migrations/add_network_fee_rub.sql"
run_migration "$BOT_LOCAL/migrations/add_bot_users_captcha.sql"
run_migration "$BOT_LOCAL/migrations/add_bot_start_ref_log.sql"
run_migration "$BOT_LOCAL/migrations/add_receipt_file.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_exchanges.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_payout_crypto_amount.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_payout_admin_receipt.sql"
run_migration "$BOT_LOCAL/migrations/add_external_payout_admin_receipt.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_deals_status.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_deal_operator.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_exchanger_accounts.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_exchanger_trust_flags.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_deal_payin.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_markup_mode.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_deal_receipt_type.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_operator_payroll_external_deal_per_op.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_exchanger_chat.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_exchanger_chat_escalation.sql"
run_migration "$EXCHANGE_LOCAL/backend/migrations/add_external_deal_client_is_new.sql"
run_migration "$BOT_LOCAL/migrations/add_user_ban.sql"
run_migration "$BOT_LOCAL/migrations/add_unified_ref_token.sql"

echo "==> Синхронизация бота"
rsync -avz --exclude venv --exclude __pycache__ --exclude .git --exclude .env --exclude receipts \
  "$BOT_LOCAL/" "$HOST:/opt/tg_bot_btc/"

echo "==> Права на каталоги загрузок (бот пишет от focuspay)"
ssh "$HOST" 'for d in receipts chat_uploads operator_avatars bot_user_avatars; do \
  mkdir -p "/opt/tg_bot_btc/${d}"; \
  chown focuspay:focuspay "/opt/tg_bot_btc/${d}"; \
  chmod 750 "/opt/tg_bot_btc/${d}"; \
done'

echo "==> Синхронизация exchange API"
rsync -avz --exclude venv --exclude __pycache__ --exclude .git --exclude .env \
  "$EXCHANGE_LOCAL/backend/" "$HOST:/opt/exchange-backend/"

echo "==> Сборка фронтенда"
(cd "$EXCHANGE_LOCAL/frontend" && npm run build)

echo "==> Фронтенд"
rsync -avz "$FRONTEND_DIST/" "$HOST:/var/www/focuspay.org/"

echo "==> Синхронизация .env бота из exchange-backend"
ssh "$HOST" 'bash -s' <<'REMOTE_ENV'
set -euo pipefail
BOT_ENV=/opt/tg_bot_btc/.env
EX=/opt/exchange-backend/.env
touch "$BOT_ENV"
# Не затираем .env бота — только дополняем/обновляем ключи из exchange (иначе теряются секреты)
merge_key() {
  local key="$1" line="$2"
  [ -z "$line" ] && return 0
  if grep -q "^${key}=" "$BOT_ENV" 2>/dev/null; then
    sed -i "/^${key}=/d" "$BOT_ENV"
  fi
  echo "$line" >> "$BOT_ENV"
}
[ -f "$EX" ] || exit 0
# TELEGRAM_ADMIN_GROUP_ID / TELEGRAM_OPS_GROUP_ID не мержим — у бота свои группы ops vs отчёты
for key in DATABASE_DSN TELEGRAM_BOT_TOKEN TELEGRAM_BOT_USERNAME WEBHOOK_SECRET INTERNAL_API_SECRET CALLBACK_SECRET RECEIPT_SECRET WEBHOOK_ALLOWED_IPS MERCHANT_BASE_URL MERCHANT_API_KEY MERCHANT_SECRET_KEY MERCHANT_CALLBACK_URL PUBLIC_SITE_URL SELL_WALLETS_JSON OPERATOR_AVATAR_DIR SECURITY_TELEGRAM_CHAT_ID SECURITY_TELEGRAM_USER_ID SECURITY_ALERTS_ENABLED SECURITY_ALERT_COOLDOWN_SEC SECURITY_RATE_LIMIT_PER_MIN SECURITY_LOG_FILE GEOIP_CITY_DB_PATH REDIS_URL PANEL_HTTP_ONLY_COOKIES SECURITY_IP_BAN_SCORE SECURITY_IP_BAN_SEC; do
  line=$(grep "^${key}=" "$EX" 2>/dev/null || true)
  merge_key "$key" "$line"
done
# Бот → exchange internal API (чат @focus_operator)
if ! grep -q "^EXCHANGE_API_URL=" "$BOT_ENV" 2>/dev/null; then
  echo "EXCHANGE_API_URL=http://127.0.0.1:8000" >> "$BOT_ENV"
fi
if ! grep -q "^CHAT_UPLOAD_DIR=" "$BOT_ENV" 2>/dev/null; then
  echo "CHAT_UPLOAD_DIR=/opt/tg_bot_btc/chat_uploads" >> "$BOT_ENV"
fi
# INTERNAL_API_SECRET в exchange: fallback на WEBHOOK_SECRET
if ! grep -q "^INTERNAL_API_SECRET=" "$EX" 2>/dev/null; then
  ws=$(grep "^WEBHOOK_SECRET=" "$EX" 2>/dev/null || true)
  [ -n "$ws" ] && echo "$ws" | sed 's/^WEBHOOK_SECRET=/INTERNAL_API_SECRET=/' >> "$EX"
fi
line=$(grep "^ADMIN_TELEGRAM_IDS=" "$EX" 2>/dev/null || true)
[ -n "$line" ] && merge_key "TELEGRAM_ADMIN_IDS" "TELEGRAM_ADMIN_IDS=${line#ADMIN_TELEGRAM_IDS=}"
chmod 600 "$BOT_ENV"
[ -f "$EX" ] && chmod 600 "$EX"
for unit in tg-bot tg-bot-webhook; do
  f="/etc/systemd/system/${unit}.service"
  grep -q 'EnvironmentFile=/opt/tg_bot_btc/.env' "$f" 2>/dev/null || \
    sed -i '/^\[Service\]/a EnvironmentFile=/opt/tg_bot_btc/.env' "$f"
done
systemctl daemon-reload
REMOTE_ENV

echo "==> Зависимости API (если есть venv)"
ssh "$HOST" 'if [ -x /opt/exchange-backend/venv/bin/pip ]; then \
  /opt/exchange-backend/venv/bin/pip install -q -r /opt/exchange-backend/requirements.txt; \
  else pip install -q bcrypt 2>/dev/null || true; fi'

echo "==> Права на каталоги загрузок (бот/API пишут от focuspay)"
ssh "$HOST" 'for d in receipts operator_avatars chat_uploads bot_user_avatars; do \
  mkdir -p "/opt/tg_bot_btc/${d}"; \
  chown focuspay:focuspay "/opt/tg_bot_btc/${d}"; \
  chmod 750 "/opt/tg_bot_btc/${d}"; \
done; \
chown focuspay:focuspay /opt/tg_bot_btc/.env /opt/exchange-backend/.env 2>/dev/null || true; \
chmod 600 /opt/tg_bot_btc/.env /opt/exchange-backend/.env 2>/dev/null || true'

echo "==> Перезапуск сервисов"
ssh "$HOST" 'systemctl restart focuspay-exchange-api tg-bot tg-bot-webhook'

echo "✅ Готово"
