#!/usr/bin/env bash
# Настройка UFW для FocusPay. Запускать на сервере от root.
# Открыты только SSH, HTTP, HTTPS. Backend-порты закрыты снаружи.

set -euo pipefail

echo "==> UFW: разрешить SSH, HTTP, HTTPS"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP redirect'
ufw allow 443/tcp comment 'HTTPS nginx'

echo "==> Закрыть прямой доступ к backend (если были открыты)"
ufw delete allow 8080/tcp 2>/dev/null || true
ufw delete allow 8081/tcp 2>/dev/null || true
ufw delete allow 8000/tcp 2>/dev/null || true
ufw delete allow 5432/tcp 2>/dev/null || true

echo "==> Включить UFW"
ufw --force enable
ufw status verbose

echo "✅ Готово. Webhook и API доступны только через nginx (443)."
