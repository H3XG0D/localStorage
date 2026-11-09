#!/bin/bash
# Забирает каталог бэкапов с подписанта на основной сервер по WireGuard.
# Ключи в git не кладутся. Каталог назначения не в webroot.
#
# Один раз на подписанте, в authorized_keys ключа с прода (только чтение каталога):
#   from="10.8.0.1",restrict,command="/usr/bin/rrsync -ro /var/backups/focuspay-wallets"
# Ключ прода: /root/.ssh/focuspay_wallet_backup (ed25519, без пароля).
# Пока ключа нет, скрипт выходит тихо: таймер можно поставить до настройки доступа.
set -u

KEY=/root/.ssh/focuspay_wallet_backup
DEST=/opt/backups/signer-wallets
REMOTE=root@10.8.0.2
SRC=/var/backups/focuspay-wallets/

if [[ ! -f "$KEY" ]]; then
  logger -t focuspay-wallet-backup "pull skipped: no $KEY"
  exit 0
fi

install -d -m 700 -o root -g root "$DEST"
rsync -a \
  -e "ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$REMOTE:$SRC" "$DEST/"
status=$?
find "$DEST" -type d -exec chmod 700 {} +
find "$DEST" -type f -exec chmod 600 {} +
exit "$status"
