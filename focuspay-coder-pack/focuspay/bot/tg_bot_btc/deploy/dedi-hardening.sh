#!/usr/bin/env bash
# Максимальная защита на VPS без Cloudflare (пока NS на Njalla).
# Запуск на сервере: sudo bash /opt/tg_bot_btc/deploy/dedi-hardening.sh

set -euo pipefail

echo "==> UFW: только 22, 80, 443"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
for p in 8000 8080 8081 5432; do
  ufw delete allow "$p/tcp" 2>/dev/null || true
done
ufw --force enable

echo "==> fail2ban"
apt-get install -y -qq fail2ban 2>/dev/null || true
cp /opt/tg_bot_btc/deploy/fail2ban/nginx-focuspay-filter.conf /etc/fail2ban/filter.d/nginx-focuspay.conf
cat > /etc/fail2ban/jail.d/focuspay.conf <<'JAIL'
[nginx-focuspay]
enabled = true
port = http,https
filter = nginx-focuspay
logpath = /var/log/nginx/access.log
maxretry = 15
findtime = 300
bantime = 7200
JAIL
cp /opt/tg_bot_btc/deploy/fail2ban/jail.d-focuspay-ssh.conf /etc/fail2ban/jail.d/focuspay-ssh.conf
systemctl enable fail2ban
systemctl restart fail2ban

echo "==> SSH: только ключи"
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-focuspay-hardening.conf <<'SSH'
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 4
LoginGraceTime 30
SSH
systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true

echo "==> sysctl anti-flood"
cat > /etc/sysctl.d/99-focuspay-net.conf <<'SYS'
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
SYS
sysctl --system >/dev/null 2>&1 || true

echo "==> nginx: усиленные лимиты"
cp /opt/tg_bot_btc/deploy/nginx-cloudflare-real-ip.conf /etc/nginx/cloudflare-real-ip.conf
cp /opt/tg_bot_btc/deploy/nginx-focuspay.org.conf /etc/nginx/sites-available/focuspay.org
# Доп. лимит на корень и панели
if ! grep -q 'zone=general_limit' /etc/nginx/nginx.conf 2>/dev/null; then
  sed -i '/http {/a \    limit_req_zone $binary_remote_addr zone=general_limit:10m rate=15r/s;' /etc/nginx/nginx.conf
fi
nginx -t
systemctl reload nginx

echo "==> Redis + сервисы"
systemctl enable redis-server 2>/dev/null || true
systemctl start redis-server 2>/dev/null || true
systemctl restart focuspay-exchange-api tg-bot tg-bot-webhook

echo "==> Cron: чистка security логов старше 90 дней"
cat > /etc/cron.daily/focuspay-security-prune <<'CRON'
#!/bin/sh
sudo -u postgres psql -d exchange_bot -c "DELETE FROM security_access_log WHERE created_at < now() - interval '90 days';" 2>/dev/null || true
sudo -u postgres psql -d exchange_bot -c "DELETE FROM web_order_ip_log WHERE created_at < now() - interval '90 days';" 2>/dev/null || true
CRON
chmod +x /etc/cron.daily/focuspay-security-prune

echo "==> Проверка"
systemctl is-active nginx focuspay-exchange-api tg-bot tg-bot-webhook redis-server fail2ban
curl -sf http://127.0.0.1:8000/api/health
echo ""
fail2ban-client status 2>/dev/null | head -3
echo "✅ dedi-hardening готов (без Cloudflare — IP сервера всё ещё виден в DNS)"
