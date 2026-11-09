#!/usr/bin/env bash
# provision-cp.sh — bootstrap Control Plane on a Debian/Ubuntu VPS (Launch-L1).
# Run as root on the CP host after copying release binaries + infra/launch templates.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${FOCUSVPN_PREFIX:-/opt/focusvpn}"
ETC="${FOCUSVPN_ETC:-/etc/focusvpn}"
LAUNCH="$ROOT/infra/launch"

fail() { echo "provision-cp FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

[[ "$(id -u)" -eq 0 ]] || fail "run as root"

echo "==> provision-cp (Launch-L1)"

command -v curl >/dev/null || { apt-get update -qq; apt-get install -y -qq curl ca-certificates; }

id focusvpn >/dev/null 2>&1 || useradd --system --home /var/lib/focusvpn --shell /usr/sbin/nologin focusvpn
mkdir -p "$PREFIX/bin" "$ETC/secrets" /var/lib/focusvpn
chown -R focusvpn:focusvpn /var/lib/focusvpn "$ETC/secrets"
chmod 750 "$ETC" "$ETC/secrets"

# Binaries: expect pre-built or build on host with Go.
if [[ ! -x "$PREFIX/bin/focusvpn-server" ]]; then
  if [[ -x "$ROOT/bin/focusvpn-server" ]]; then
    install -m 0755 "$ROOT/bin/focusvpn-server" "$PREFIX/bin/focusvpn-server"
  elif command -v go >/dev/null; then
    echo "==> building focusvpn-server"
    (cd "$ROOT" && CGO_ENABLED=0 go build -trimpath -o "$PREFIX/bin/focusvpn-server" ./backend/cmd/server)
  else
    fail "missing $PREFIX/bin/focusvpn-server (build on a machine with Go and copy here)"
  fi
fi
ok "binary $PREFIX/bin/focusvpn-server"

if [[ ! -f "$ETC/env" ]]; then
  [[ -f "$LAUNCH/env.cp.example" ]] || fail "missing env.cp.example"
  cp "$LAUNCH/env.cp.example" "$ETC/env"
  chmod 640 "$ETC/env"
  chown root:focusvpn "$ETC/env"
  warn_env=1
else
  warn_env=0
fi
ok "env $ETC/env"

# Generate secrets if missing (dev-friendly; rotate for real prod).
gen_b64() { openssl rand -base64 32 | tr -d '\n'; }
if [[ ! -f "$ETC/secrets/config_signing_seed" ]]; then
  gen_b64 >"$ETC/secrets/config_signing_seed"
  chown focusvpn:focusvpn "$ETC/secrets/config_signing_seed"
  chmod 600 "$ETC/secrets/config_signing_seed"
  ok "generated config_signing_seed"
fi
if [[ ! -f "$ETC/secrets/kek" ]]; then
  openssl rand -out "$ETC/secrets/kek" 32
  chown focusvpn:focusvpn "$ETC/secrets/kek"
  chmod 600 "$ETC/secrets/kek"
  ok "generated kek"
fi

# CA for agent mTLS — backend generates ephemeral if missing; prefer persistent.
if [[ ! -f "$ETC/secrets/ca.crt" || ! -f "$ETC/secrets/ca.key" ]]; then
  echo "==> note: place CA at $ETC/secrets/ca.{crt,key} or let server create ephemeral (not ideal for prod)"
fi

install -m 0644 "$LAUNCH/focusvpn-backend.service" /etc/systemd/system/focusvpn-backend.service
systemctl daemon-reload
ok "systemd unit installed"

if command -v podman >/dev/null || command -v docker >/dev/null; then
  ENGINE=podman
  command -v podman >/dev/null || ENGINE=docker
  if [[ -n "${FOCUSVPN_PG_PASSWORD:-}" ]]; then
    echo "==> starting Postgres+Redis via $ENGINE"
    export FOCUSVPN_PG_PASSWORD
    (cd "$LAUNCH" && $ENGINE compose -f docker-compose.cp.yml up -d)
    ok "compose up"
  else
    echo "  note: set FOCUSVPN_PG_PASSWORD and re-run to start local Postgres/Redis"
  fi
fi

# Optional Caddy
if [[ "${FOCUSVPN_INSTALL_CADDY:-0}" == "1" ]]; then
  if ! command -v caddy >/dev/null; then
    apt-get update -qq
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
  fi
  HOST="${FOCUSVPN_API_HOST:-api.example.com}"
  sed "s/api.example.com/$HOST/g" "$LAUNCH/Caddyfile.example" >/etc/caddy/Caddyfile
  systemctl enable --now caddy
  ok "caddy for $HOST"
fi

echo "==> migrate + seed (manual next steps)"
echo "    FOCUSVPN_DATABASE_URL=... $PREFIX/bin/focusvpn-server  # or make migrate from repo"
echo "    make seed / make seed-agent-token on a trusted host with DB access"
if [[ "$warn_env" -eq 1 ]]; then
  echo "    EDIT $ETC/env — set database URL, JWT seeds, disable AUTO_ACTIVE"
fi
echo "    systemctl enable --now focusvpn-backend"
echo "provision-cp PASS (unit installed; start after env + DB ready)"
