#!/usr/bin/env bash
# Разрешить HTTPS только с IP Cloudflare. Запускать ПОСЛЕ включения прокси (cf-ray в ответе).
# Иначе сайт станет недоступен!

set -euo pipefail

CF_IPS_V4=(
  173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22
  141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 188.114.96.0/20
  197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13
  104.24.0.0/14 172.64.0.0/13 131.0.72.0/22
)

echo "==> Проверка Cloudflare proxy"
if ! curl -sfI https://focuspay.org/ 2>/dev/null | grep -qi cf-ray; then
  echo "ОШИБКА: cf-ray не найден — сначала включите Cloudflare proxy!"
  echo "См. deploy/CLOUDFLARE_NJALLA.md"
  exit 1
fi

echo "==> UFW: 443 только для Cloudflare"
ufw delete allow 443/tcp 2>/dev/null || true
for cidr in "${CF_IPS_V4[@]}"; do
  ufw allow from "$cidr" to any port 443 proto tcp comment 'Cloudflare'
done
ufw status verbose | head -40
echo "✅ Готово. SSH 22 и HTTP 80 без изменений."
