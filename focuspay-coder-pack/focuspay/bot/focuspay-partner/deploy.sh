#!/bin/bash
# Установка партнёрского бота Focus Pay на сервер Ubuntu 22.04 / 24.04.
# Запуск (от root):  bash deploy.sh [домен]
# Без домена бот получит бесплатный адрес вида 1.2.3.4.sslip.io с https.
set -e
APP=/opt/focuspay
SRC="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="$1"

echo "▶ 1/7 Ставлю системные пакеты…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ffmpeg unzip curl sqlite3 ufw rsync openssl >/dev/null
if ! command -v caddy >/dev/null; then
  apt-get install -y -qq caddy >/dev/null 2>&1 || {
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy >/dev/null; }
fi

if [ -z "$DOMAIN" ]; then
  IP=$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')
  DOMAIN="$IP.sslip.io"
fi
echo "▶ 2/7 Адрес приложения: https://$DOMAIN"

echo "▶ 3/7 Копирую файлы в $APP…"
id focuspay >/dev/null 2>&1 || useradd -r -m -d $APP -s /usr/sbin/nologin focuspay
mkdir -p $APP
rsync_copy() { cp -r "$SRC"/. $APP/; }
if [ "$SRC" != "$APP" ]; then
  [ -f $APP/.env ] && cp $APP/.env /tmp/focuspay.env.keep
  [ -f $APP/focuspay.db ] && cp $APP/focuspay.db /tmp/focuspay.db.keep
  rsync_copy
  [ -f /tmp/focuspay.env.keep ] && mv /tmp/focuspay.env.keep $APP/.env
  [ -f /tmp/focuspay.db.keep ] && mv /tmp/focuspay.db.keep $APP/focuspay.db
fi
# настройки и база, перенесённые с Мака в /root
[ -f /root/.env ] && [ ! -f $APP/.env ] && cp /root/.env $APP/.env
[ -f /root/focuspay.db ] && [ ! -f $APP/focuspay.db ] && cp /root/focuspay.db $APP/focuspay.db
[ -f $APP/.env ] || cp $APP/.env.example $APP/.env
# новые параметры из .env.example, которых нет в .env
while IFS= read -r l; do k=${l%%=*}; [[ -z "$l" || "$l" == \#* ]] && continue; grep -q "^$k=" $APP/.env || echo "$l" >> $APP/.env; done < $APP/.env.example
setkv() { grep -q "^$1=" $APP/.env && sed -i "s|^$1=.*|$1=$2|" $APP/.env || echo "$1=$2" >> $APP/.env; }
setkv WEBAPP_URL "https://$DOMAIN"
setkv DEV_MODE 0
setkv WEB_HOST 127.0.0.1
setkv WEB_PORT 8080
grep -q "^TRACK_SECRET=.\+" $APP/.env || setkv TRACK_SECRET "$(openssl rand -hex 16)"
rm -rf $APP/cache $APP/__pycache__ 2>/dev/null || true

echo "▶ 4/7 Ставлю Python-библиотеки…"
[ -x $APP/.venv/bin/python ] && $APP/.venv/bin/python -c "import sys" 2>/dev/null || { rm -rf $APP/.venv; python3 -m venv $APP/.venv; }
$APP/.venv/bin/pip install -q --upgrade pip
$APP/.venv/bin/pip install -q -r $APP/requirements.txt
chown -R focuspay:focuspay $APP
chmod 600 $APP/.env

echo "▶ 5/7 Автозапуск (systemd)…"
cat > /etc/systemd/system/focuspay.service <<UNIT
[Unit]
Description=Focus Pay partner bot
After=network-online.target
Wants=network-online.target

[Service]
User=focuspay
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q focuspay

echo "▶ 6/7 HTTPS (Caddy) и фаервол…"
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:8080
}
CADDY
systemctl enable -q caddy
systemctl restart caddy
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# ежедневная копия базы, храним 14 дней
mkdir -p $APP/backups && chown focuspay:focuspay $APP/backups
cat > /etc/cron.daily/focuspay-backup <<CRON
#!/bin/sh
sqlite3 $APP/focuspay.db ".backup '$APP/backups/focuspay_\$(date +%F).db'" && find $APP/backups -name '*.db' -mtime +14 -delete
CRON
chmod +x /etc/cron.daily/focuspay-backup

echo "▶ 7/7 Запускаю бота…"
systemctl restart focuspay
sleep 6
if systemctl is-active -q focuspay; then
  echo ""
  echo "✅ Готово! Бот работает 24/7."
  echo "   Приложение: https://$DOMAIN"
  echo "   Админка:    https://$DOMAIN/admin  (или /admin в боте)"
  echo "   Логи:       journalctl -u focuspay -f"
  echo ""
  journalctl -u focuspay -n 6 --no-pager | grep -E "ИИ|polling" || true
else
  echo "❌ Бот не запустился. Последние строки лога:"
  journalctl -u focuspay -n 30 --no-pager
  exit 1
fi
if ! ls $APP/materials/*.mp4 >/dev/null 2>&1; then
  echo "▶ Собираю общие видео-баннеры (несколько минут)…"
  EX=$(grep '^EXCHANGE_TG=' $APP/.env | cut -d= -f2)
  sudo -u focuspay $APP/.venv/bin/python $APP/animate.py "$EX" && echo "✅ Баннеры готовы"
fi
