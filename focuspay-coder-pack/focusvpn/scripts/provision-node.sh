#!/usr/bin/env bash
# provision-node.sh — bootstrap VPN node + node-agent (Launch-L1).
# Run as root on the VPN VPS. Requires awg/awg-quick on PATH (AmneziaWG tools).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${FOCUSVPN_PREFIX:-/opt/focusvpn}"
ETC="${FOCUSVPN_ETC:-/etc/focusvpn}"
LAUNCH="$ROOT/infra/launch"

fail() { echo "provision-node FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

[[ "$(id -u)" -eq 0 ]] || fail "run as root"

echo "==> provision-node (Launch-L1)"

if ! command -v awg >/dev/null || ! command -v awg-quick >/dev/null; then
  cat <<'EOF' >&2
Missing awg / awg-quick.
Install AmneziaWG tools for your distro (GPL — separate packages, not linked into FocusVPN):
  https://github.com/amnezia-vpn/amneziawg-tools
Then re-run this script.
EOF
  fail "awg tools required"
fi
ok "awg=$(command -v awg)"

mkdir -p "$PREFIX/bin" "$ETC/secrets"
chmod 750 "$ETC" "$ETC/secrets"

if [[ ! -x "$PREFIX/bin/node-agent" ]]; then
  if [[ -x "$ROOT/bin/node-agent" ]]; then
    install -m 0755 "$ROOT/bin/node-agent" "$PREFIX/bin/node-agent"
  elif command -v go >/dev/null; then
    echo "==> building node-agent"
    (cd "$ROOT" && CGO_ENABLED=0 go build -trimpath -o "$PREFIX/bin/node-agent" ./node-agent/cmd/agent)
  else
    fail "missing $PREFIX/bin/node-agent"
  fi
fi
ok "binary $PREFIX/bin/node-agent"

if [[ ! -f "$ETC/agent.env" ]]; then
  cp "$LAUNCH/env.node.example" "$ETC/agent.env"
  chmod 640 "$ETC/agent.env"
  echo "  EDIT $ETC/agent.env — AGENT_CP_URL, AGENT_NODE_ID, AGENT_NODE_TOKEN (first boot)"
fi
ok "env $ETC/agent.env"

# Firewall hints (ufw if present)
if command -v ufw >/dev/null; then
  ufw allow 51820/udp comment 'FocusVPN AmneziaWG' || true
  ufw allow out 443/tcp || true
  ufw allow out 8443/tcp || true
  ok "ufw rules hinted (review ufw status)"
fi

install -m 0644 "$LAUNCH/focusvpn-agent.service" /etc/systemd/system/focusvpn-agent.service
systemctl daemon-reload
ok "systemd unit installed"

# Optional: bring up empty awg interface config placeholder
AWG_CONF="${AGENT_INTERFACE_CONF:-/etc/amneziawg/awg0.conf}"
if [[ ! -f "$AWG_CONF" ]]; then
  mkdir -p "$(dirname "$AWG_CONF")"
  cat >"$AWG_CONF" <<'EOF'
# Managed largely by node-agent peer apply. Minimal listen interface — adjust keys/IP for your node.
# Generate: awg genkey | tee privatekey | awg pubkey
[Interface]
PrivateKey = REPLACE_NODE_PRIVATE_KEY
Address = 10.200.0.1/24
ListenPort = 51820
# Obfuscation must match vpn_endpoints.obfuscation in CP for this node.
Jc = 4
Jmin = 40
Jmax = 70
S1 = 15
S2 = 20
S3 = 10
S4 = 5
H1 = 100-110
H2 = 200-210
H3 = 300-310
H4 = 400-410
EOF
  chmod 600 "$AWG_CONF"
  echo "  EDIT $AWG_CONF — node PrivateKey + obfuscation matching CP seed"
fi

echo "==> next:"
echo "    1. Put CA from CP at $ETC/secrets/ca.crt (after first agent register, agent may write certs)"
echo "    2. Set AGENT_NODE_TOKEN from CP: make seed-agent-token"
echo "    3. systemctl enable --now focusvpn-agent"
echo "    4. Open UDP 51820 on cloud security group"
echo "provision-node PASS"
