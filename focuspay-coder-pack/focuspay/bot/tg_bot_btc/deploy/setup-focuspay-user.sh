#!/usr/bin/env bash
# Создать системного пользователя focuspay для systemd-сервисов. Запускать на сервере от root.

set -euo pipefail

if ! id focuspay &>/dev/null; then
  useradd --system --home-dir /opt/tg_bot_btc --shell /usr/sbin/nologin focuspay
  echo "Created user focuspay"
fi

chown -R focuspay:focuspay /opt/tg_bot_btc /opt/exchange-backend /var/www/focuspay.org 2>/dev/null || true
chmod 600 /opt/tg_bot_btc/.env /opt/exchange-backend/.env 2>/dev/null || true

# Каталоги загрузок (API пишет от пользователя focuspay)
for d in operator_avatars chat_uploads bot_user_avatars receipts; do
  mkdir -p "/opt/tg_bot_btc/${d}"
  chown focuspay:focuspay "/opt/tg_bot_btc/${d}"
  chmod 750 "/opt/tg_bot_btc/${d}"
done

echo "✅ User focuspay ready. Install systemd units and restart services."
