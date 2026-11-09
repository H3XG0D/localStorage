#!/usr/bin/env bash
# Применить chat_id группы для алертов безопасности. Вызывается ботом после /sec123.
set -euo pipefail
CHAT_ID="${1:?usage: apply_security_chat.sh CHAT_ID}"
EX=/opt/exchange-backend/.env
touch "$EX"
grep -q "^SECURITY_TELEGRAM_CHAT_ID=" "$EX" 2>/dev/null && sed -i "/^SECURITY_TELEGRAM_CHAT_ID=/d" "$EX"
grep -q "^SECURITY_TELEGRAM_USER_ID=" "$EX" 2>/dev/null && sed -i "/^SECURITY_TELEGRAM_USER_ID=/d" "$EX"
echo "SECURITY_TELEGRAM_CHAT_ID=${CHAT_ID}" >> "$EX"
systemctl restart focuspay-exchange-api

source "$EX"
TOKEN="${TELEGRAM_BOT_TOKEN:-}"
if [ -n "$TOKEN" ]; then
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "{\"chat_id\":${CHAT_ID},\"text\":\"🔐 Алерты безопасности FocusPay подключены к этой группе.\",\"parse_mode\":\"HTML\"}" \
    >/dev/null || true
fi
