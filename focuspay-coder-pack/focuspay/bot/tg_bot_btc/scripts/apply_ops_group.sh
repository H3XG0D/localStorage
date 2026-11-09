#!/usr/bin/env bash
# Прописать TELEGRAM_OPS_GROUP_ID в .env бота и перезапустить сервисы.
set -euo pipefail
CHAT_ID="${1:?usage: apply_ops_group.sh CHAT_ID}"
ENV="${BOT_ENV_FILE:-/opt/tg_bot_btc/.env}"
touch "$ENV"
grep -q "^TELEGRAM_OPS_GROUP_ID=" "$ENV" 2>/dev/null && sed -i "/^TELEGRAM_OPS_GROUP_ID=/d" "$ENV"
echo "TELEGRAM_OPS_GROUP_ID=${CHAT_ID}" >> "$ENV"
if ! grep -q "^TELEGRAM_REPORTS_GROUP_ID=" "$ENV" 2>/dev/null; then
  ADMIN=$(grep "^TELEGRAM_ADMIN_GROUP_ID=" "$ENV" 2>/dev/null | cut -d= -f2- || true)
  if [ -n "$ADMIN" ]; then
    echo "TELEGRAM_REPORTS_GROUP_ID=${ADMIN}" >> "$ENV"
  fi
fi
systemctl restart tg-bot-webhook 2>/dev/null || true
systemctl restart tg-bot 2>/dev/null || true
