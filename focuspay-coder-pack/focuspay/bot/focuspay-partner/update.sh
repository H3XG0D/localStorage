#!/bin/bash
# Обновление бота на сервере новым архивом (настройки и база сохраняются).
# Запуск: bash /opt/focuspay/update.sh /root/focuspay_update.zip
set -e
ZIP="${1:-$(ls -t /root/focuspay*.zip | head -1)}"
[ -f "$ZIP" ] || { echo "Архив не найден: $ZIP"; exit 1; }
echo "▶ Обновляю из $ZIP"
cp /opt/focuspay/focuspay.db "/opt/focuspay/backups/before_update_$(date +%F_%H%M).db" 2>/dev/null || true
rm -rf /tmp/fp_upd && mkdir /tmp/fp_upd && unzip -q -o "$ZIP" -d /tmp/fp_upd
SRC=$(dirname "$(find /tmp/fp_upd -name bot.py | head -1)")
rsync -a --exclude '.env' --exclude 'focuspay.db' --exclude 'backups' --exclude '.venv' "$SRC"/ /opt/focuspay/ 2>/dev/null || \
  (cd "$SRC" && tar cf - --exclude=.env --exclude=focuspay.db . | (cd /opt/focuspay && tar xf -))
cd /opt/focuspay
while IFS= read -r l; do k=${l%%=*}; [[ -z "$l" || "$l" == \#* ]] && continue; grep -q "^$k=" .env || echo "$l" >> .env; done < .env.example
.venv/bin/pip install -q -r requirements.txt
rm -rf cache && chown -R focuspay:focuspay /opt/focuspay
systemctl restart focuspay && sleep 5
systemctl is-active -q focuspay && echo "✅ Обновлено и запущено" || journalctl -u focuspay -n 30 --no-pager
