#!/usr/bin/env bash
# Прописать TELEGRAM_EXTERNAL_DEALS_GROUP_ID в .env бота и перезапустить сервисы.
set -euo pipefail
CHAT_ID="${1:?usage: apply_external_deals_group.sh CHAT_ID}"
ENV="${BOT_ENV_FILE:-/opt/tg_bot_btc/.env}"
touch "$ENV"
grep -q "^TELEGRAM_EXTERNAL_DEALS_GROUP_ID=" "$ENV" 2>/dev/null && sed -i "/^TELEGRAM_EXTERNAL_DEALS_GROUP_ID=/d" "$ENV"
echo "TELEGRAM_EXTERNAL_DEALS_GROUP_ID=${CHAT_ID}" >> "$ENV"
systemctl restart tg-bot-webhook 2>/dev/null || true
systemctl restart tg-bot 2>/dev/null || true
