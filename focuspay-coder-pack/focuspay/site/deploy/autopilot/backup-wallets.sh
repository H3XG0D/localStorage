#!/bin/bash
# Снимает ключи горячего кошелька и копию sqlite подписанта.
# Пароль RPC не попадает в командную строку: пишется во временный conf и сразу удаляется.
# Живую signer.sqlite3 этот скрипт не затирает.
#
# Установка на подписант (после «выкати»):
#   install -m 755 site/deploy/autopilot/backup-wallets.sh /usr/local/sbin/focuspay-backup-wallets
#   cp site/deploy/autopilot/focuspay-wallet-backup.service /etc/systemd/system/
#   cp site/deploy/autopilot/focuspay-wallet-backup.timer /etc/systemd/system/
#   cp site/deploy/autopilot/focuspay-wallet-backup.path /etc/systemd/system/
#   systemctl daemon-reload
#   systemctl enable --now focuspay-wallet-backup.timer focuspay-wallet-backup.path
set -u

ENV_FILE=/etc/focuspay/signer.env
ROOT=/var/backups/focuspay-wallets
SQLITE=/var/lib/focuspay-signer/signer.sqlite3
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$ROOT/$STAMP"
fail=0

if [[ ! -r "$ENV_FILE" ]]; then
  echo "focuspay-backup-wallets: no $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

install -d -m 700 "$ROOT" "$DEST"

write_conf() {
  local path="$1" user="$2" password="$3" port="$4"
  umask 077
  cat >"$path" <<EOF
rpcuser=${user}
rpcpassword=${password}
rpcport=${port}
EOF
}

backup_coin() {
  local bin="$1" user="$2" password="$3" port="$4" wallet="$5" out="$6"
  local conf
  conf=$(mktemp)
  write_conf "$conf" "$user" "$password" "$port"
  if "$bin" -conf="$conf" -rpcwallet="$wallet" backupwallet "$out"; then
    chmod 600 "$out"
  else
    echo "focuspay-backup-wallets: $bin backupwallet failed" >&2
    fail=1
  fi
  rm -f "$conf"
}

port_of() {
  local url="$1" fallback="$2" port
  port=$(printf '%s' "$url" | sed -n 's#.*:\([0-9][0-9]*\).*#\1#p')
  if [[ -n "$port" ]]; then
    printf '%s' "$port"
  else
    printf '%s' "$fallback"
  fi
}

if [[ -n "${BTC_RPC_USER:-}" && -n "${BTC_RPC_PASSWORD:-}" ]]; then
  backup_coin bitcoin-cli "$BTC_RPC_USER" "$BTC_RPC_PASSWORD" \
    "$(port_of "${BTC_RPC_URL:-}" 8332)" "${BTC_RPC_WALLET:-hot}" "$DEST/btc-hot.dat"
else
  echo "focuspay-backup-wallets: BTC rpc is not configured" >&2
  fail=1
fi

if [[ -n "${LTC_RPC_USER:-}" && -n "${LTC_RPC_PASSWORD:-}" ]]; then
  backup_coin litecoin-cli "$LTC_RPC_USER" "$LTC_RPC_PASSWORD" \
    "$(port_of "${LTC_RPC_URL:-}" 9332)" "${LTC_RPC_WALLET:-hot}" "$DEST/ltc-hot.dat"
else
  echo "focuspay-backup-wallets: LTC rpc is not configured" >&2
  fail=1
fi

if [[ -f "$SQLITE" ]]; then
  cp -a "$SQLITE" "$DEST/signer.sqlite3"
  chmod 600 "$DEST/signer.sqlite3"
else
  echo "focuspay-backup-wallets: no $SQLITE" >&2
  fail=1
fi

find "$ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
exit "$fail"
