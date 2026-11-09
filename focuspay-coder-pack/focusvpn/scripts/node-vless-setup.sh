#!/usr/bin/env bash
# Provision a VLESS traffic node: Xray terminates TLS on :443 (WS + XHTTP), Nginx serves
# the decoy site on localhost:8080 and ACME on :80. ufw, fail2ban, BBR.
# Idempotent: re-running keeps the node's UUID and secret paths from /root/focusvpn/node.env.
#
#   scripts/node-vless-setup.sh <ssh-host> <domain> [node-name]
#   scripts/node-vless-setup.sh focusvpn-de1 94-26-83-74.sslip.io DE1
#
# <domain> must already resolve to the node (A record). Secrets stay on the node;
# fetch them with: scp <ssh-host>:/root/focusvpn/node.env (chmod 600 locally).
#
# To also register the node on the control plane and install the node-agent, set:
#   FOCUSVPN_CP_URL          public API, e.g. https://api.vpn.example
#   FOCUSVPN_AGENT_URL       mTLS agent listener, e.g. https://cp.example:8443
#   FOCUSVPN_INTERNAL_TOKEN  same value as on the CP
# Optional: FOCUSVPN_NODE_COUNTRY (DE), FOCUSVPN_NODE_REGION, FOCUSVPN_NODE_CAPACITY,
#           FOCUSVPN_NODE_TRANSPORT (xhttp or ws; the other is kept as fallback).
set -euo pipefail

HOST=${1:?ssh host}
DOMAIN=${2:?domain}
XRAY_VERSION=${XRAY_VERSION:-v26.3.27}

ssh "$HOST" DOMAIN="$DOMAIN" XRAY_VERSION="$XRAY_VERSION" bash -s <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get -y -qq -o Dpkg::Options::=--force-confold upgrade >/dev/null
apt-get -y -qq install ufw fail2ban unattended-upgrades nginx certbot curl unzip jq iproute2 >/dev/null

ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
for p in 22 80 443; do ufw allow "$p/tcp" >/dev/null; done
ufw --force enable >/dev/null

cat > /etc/sysctl.d/90-focusvpn.conf <<EOF
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
EOF
sysctl -q --system
systemctl enable --now fail2ban unattended-upgrades >/dev/null 2>&1

if [ ! -x /usr/local/bin/xray ] || ! xray version | grep -q "${XRAY_VERSION#v}"; then
  curl -fsSL -o /root/install-release.sh https://github.com/XTLS/Xray-install/raw/main/install-release.sh
  bash /root/install-release.sh install --version "$XRAY_VERSION" >/tmp/xray-install.log 2>&1
fi

umask 077
mkdir -p /root/focusvpn
ENV=/root/focusvpn/node.env
rand() { head -c 9 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
[ -f "$ENV" ] || printf 'UUID=%s\nWS_PATH=/api/v2/%s\nXHTTP_PATH=/cdn/%s\nDOMAIN=%s\n' \
  "$(xray uuid)" "$(rand)" "$(rand)" "$DOMAIN" > "$ENV"
grep -q '^XHTTP_PATH=' "$ENV" || echo "XHTTP_PATH=/cdn/$(rand)" >> "$ENV"
sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" "$ENV"
# shellcheck disable=SC1090
. "$ENV"
umask 022

# Port 80 must serve the ACME webroot before the TLS site exists.
mkdir -p /var/www/html /var/www/focus
cat > /etc/nginx/sites-available/focusvpn <<EOF
server {
    listen 80; listen [::]:80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/focusvpn /etc/nginx/sites-enabled/focusvpn
systemctl reload nginx || systemctl restart nginx

[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ] || certbot certonly --webroot -w /var/www/html \
  -d "$DOMAIN" --agree-tos --register-unsafely-without-email --non-interactive -q
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
# Certbot renews the live symlink; Xray reads a copy it is allowed to open.
cat > /etc/letsencrypt/renewal-hooks/deploy/focusvpn-xray.sh <<HOOK
#!/bin/sh
set -eu
user=\$(systemctl show xray -p User --value 2>/dev/null || true)
[ -n "\$user" ] || user=nobody
group=\$(id -gn "\$user" 2>/dev/null || echo "\$user")
install -d -o "\$user" -g "\$group" -m 750 /usr/local/etc/xray/certs
cp -L "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" /usr/local/etc/xray/certs/fullchain.pem
cp -L "/etc/letsencrypt/live/$DOMAIN/privkey.pem" /usr/local/etc/xray/certs/privkey.pem
chown "\$user:\$group" /usr/local/etc/xray/certs/fullchain.pem /usr/local/etc/xray/certs/privkey.pem
chmod 640 /usr/local/etc/xray/certs/fullchain.pem /usr/local/etc/xray/certs/privkey.pem
systemctl restart xray
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/focusvpn-xray.sh
rm -f /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

cat > /var/www/focus/index.html <<EOF
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Focus Cloud</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:sans-serif;max-width:640px;margin:80px auto;color:#222">
<h1>Focus Cloud</h1><p>Internal file sync service. Authorized clients only.</p></body></html>
EOF

# Xray owns :443 so the online-IP stat is the client address, not Nginx's bind address.
# Inner inbounds accept PROXY protocol (fallback xver 1). Nginx only serves ACME and the decoy.
install_xray_certs() {
  local user group
  user=$(systemctl show xray -p User --value 2>/dev/null || true)
  [ -n "$user" ] || user=nobody
  group=$(id -gn "$user" 2>/dev/null || echo "$user")
  install -d -o "$user" -g "$group" -m 750 /usr/local/etc/xray/certs
  cp -L "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" /usr/local/etc/xray/certs/fullchain.pem
  cp -L "/etc/letsencrypt/live/$DOMAIN/privkey.pem" /usr/local/etc/xray/certs/privkey.pem
  chown "$user:$group" /usr/local/etc/xray/certs/fullchain.pem /usr/local/etc/xray/certs/privkey.pem
  chmod 640 /usr/local/etc/xray/certs/fullchain.pem /usr/local/etc/xray/certs/privkey.pem
}
install_xray_certs
CERT=/usr/local/etc/xray/certs/fullchain.pem
KEY=/usr/local/etc/xray/certs/privkey.pem

# Xray picks the config format from the file extension, so the staging file ends in .json.
jq -n --arg id "$UUID" --arg ws "$WS_PATH" --arg xh "$XHTTP_PATH" --arg cert "$CERT" --arg key "$KEY" '{
  log: {loglevel: "warning", access: "none"},
  stats: {},
  api: {tag: "api", services: ["HandlerService", "StatsService"]},
  policy: {
    levels: {"0": {statsUserUplink: true, statsUserDownlink: true, statsUserOnline: true, handshake: 4, connIdle: 300}},
    system: {statsInboundUplink: true, statsInboundDownlink: true}
  },
  inbounds: [
    {tag: "tls-in", listen: "0.0.0.0", port: 443, protocol: "vless",
     settings: {clients: [], decryption: "none", fallbacks: [
       {path: $ws, dest: 10000, xver: 1},
       {path: $xh, dest: 10001, xver: 1},
       {dest: 8080}
     ]},
     streamSettings: {network: "tcp", security: "tls",
       tlsSettings: {alpn: ["http/1.1"], certificates: [{certificateFile: $cert, keyFile: $key}]}}},
    {tag: "vless-ws", listen: "127.0.0.1", port: 10000, protocol: "vless",
     settings: {clients: [{id: $id, email: "test-1@focusvpn", level: 0}], decryption: "none"},
     streamSettings: {network: "ws", security: "none", wsSettings: {path: $ws, acceptProxyProtocol: true}},
     sniffing: {enabled: true, destOverride: ["http", "tls", "quic"], routeOnly: true}},
    {tag: "vless-xhttp", listen: "127.0.0.1", port: 10001, protocol: "vless",
     settings: {clients: [{id: $id, email: "test-1x@focusvpn", level: 0}], decryption: "none"},
     streamSettings: {network: "xhttp", security: "none", sockopt: {acceptProxyProtocol: true},
       xhttpSettings: {path: $xh, mode: "auto"}},
     sniffing: {enabled: true, destOverride: ["http", "tls", "quic"], routeOnly: true}},
    {tag: "api", listen: "127.0.0.1", port: 10085, protocol: "dokodemo-door", settings: {address: "127.0.0.1"}}
  ],
  outbounds: [
    {tag: "direct", protocol: "freedom", settings: {domainStrategy: "UseIPv4"}},
    {tag: "block", protocol: "blackhole"}
  ],
  routing: {rules: [
    {type: "field", inboundTag: ["api"], outboundTag: "api"},
    {type: "field", ip: ["geoip:private"], outboundTag: "block"},
    {type: "field", protocol: ["bittorrent"], outboundTag: "block"}
  ]}
}' > /usr/local/etc/xray/next.json
xray run -test -config /usr/local/etc/xray/next.json >/dev/null
mv /usr/local/etc/xray/next.json /usr/local/etc/xray/config.json
chmod 644 /usr/local/etc/xray/config.json

cat > /etc/nginx/sites-available/focusvpn <<EOF
server {
    listen 80; listen [::]:80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 127.0.0.1:8080;
    server_name $DOMAIN;
    server_tokens off;
    root /var/www/focus;
    access_log off;
    location / { try_files \$uri /index.html; }
}
EOF
rm -f /etc/systemd/system/nginx.service.d/focusvpn-proxy-bind.conf
ip addr del 10.66.0.1/32 dev lo 2>/dev/null || true
nginx -t -q
systemctl daemon-reload
systemctl enable xray nginx >/dev/null 2>&1
systemctl reload nginx || systemctl restart nginx
for _ in 1 2 3 4 5 6 7 8 9 10; do
  ss -ltn | awk '{print $4}' | grep -Eq ':443$' || break
  sleep 0.3
done
systemctl restart xray
sleep 1
if ! ss -ltn | awk '{print $4}' | grep -Eq ':443$'; then
  echo "xray did not bind 443; retrying as root" >&2
  mkdir -p /etc/systemd/system/xray.service.d
  printf '[Service]\nUser=\nGroup=\n' > /etc/systemd/system/xray.service.d/focusvpn-bind.conf
  systemctl daemon-reload
  systemctl restart xray
  sleep 1
fi
if [ -f /root/focusvpn/agent.env ]; then
  if grep -q '^AGENT_PUBLIC_HOST=' /root/focusvpn/agent.env; then
    sed -i "s|^AGENT_PUBLIC_HOST=.*|AGENT_PUBLIC_HOST=$DOMAIN|" /root/focusvpn/agent.env
  else
    echo "AGENT_PUBLIC_HOST=$DOMAIN" >> /root/focusvpn/agent.env
  fi
fi

echo "xray=$(systemctl is-active xray) nginx=$(systemctl is-active nginx) ufw=$(ufw status | head -1 | cut -d' ' -f2)"
echo "decoy=$(curl -fsS -o /dev/null -w '%{http_code}' "https://$DOMAIN/")"
echo "decoy_local=$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/)"
[ -f /var/run/reboot-required ] && echo "NOTE: reboot required (kernel update)" || true
REMOTE

# Optional: register the node and install the agent. Skipped unless the CP is configured,
# so a plain re-run only refreshes Xray/Nginx.
if [[ -z "${FOCUSVPN_CP_URL:-}" ]]; then
  exit 0
fi
: "${FOCUSVPN_INTERNAL_TOKEN:?set FOCUSVPN_INTERNAL_TOKEN together with FOCUSVPN_CP_URL}"
: "${FOCUSVPN_AGENT_URL:?set FOCUSVPN_AGENT_URL to the mTLS agent listener}"

ROOT=$(cd "$(dirname "$0")/.." && pwd)
NAME=${3:-$HOST}
COUNTRY=${FOCUSVPN_NODE_COUNTRY:-DE}
REGION=${FOCUSVPN_NODE_REGION:-eu-central}
CAPACITY=${FOCUSVPN_NODE_CAPACITY:-500}
TRANSPORT=${FOCUSVPN_NODE_TRANSPORT:-xhttp}

eval "$(ssh "$HOST" 'grep -E "^(WS_PATH|XHTTP_PATH|DOMAIN)=" /root/focusvpn/node.env')"
if [[ "$TRANSPORT" == "ws" ]]; then
  PRIMARY=$WS_PATH
  ALT_TRANSPORT=xhttp
  ALT_PATH=$XHTTP_PATH
  ALT_MODE=auto
else
  TRANSPORT=xhttp
  PRIMARY=$XHTTP_PATH
  ALT_TRANSPORT=ws
  ALT_PATH=$WS_PATH
  ALT_MODE=
fi

ISSUE=true
if ssh "$HOST" 'test -f /root/focusvpn/agent.crt'; then
  ISSUE=false
fi

BODY=$(NAME="$NAME" COUNTRY="$COUNTRY" REGION="$REGION" DOMAIN="$DOMAIN" CAPACITY="$CAPACITY" \
  ISSUE="$ISSUE" TRANSPORT="$TRANSPORT" PRIMARY="$PRIMARY" ALT_TRANSPORT="$ALT_TRANSPORT" \
  ALT_PATH="$ALT_PATH" ALT_MODE="$ALT_MODE" python3 - <<'PY'
import json, os
transport = os.environ["TRANSPORT"]
alt_mode = os.environ["ALT_MODE"] or None
print(json.dumps({
    "name": os.environ["NAME"],
    "country": os.environ["COUNTRY"],
    "region": os.environ["REGION"],
    "hostname": os.environ["DOMAIN"],
    "capacity": int(os.environ["CAPACITY"]),
    "issue_token": os.environ["ISSUE"] == "true",
    "xray": {
        "transport": transport,
        "path": os.environ["PRIMARY"],
        "host": os.environ["DOMAIN"],
        "sni": os.environ["DOMAIN"],
        "port": 443,
        "mode": "packet-up" if transport == "xhttp" else "",
        "alt": {"transport": os.environ["ALT_TRANSPORT"], "path": os.environ["ALT_PATH"], "mode": alt_mode},
    },
}))
PY
)

RESP=$(curl -fsS -H "X-Internal-Token: $FOCUSVPN_INTERNAL_TOKEN" -H 'Content-Type: application/json' \
  -d "$BODY" "${FOCUSVPN_CP_URL%/}/v1/internal/nodes")
NODE_ID=$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("node_id") or "")')
AGENT_TOKEN=$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("agent_token") or "")')
if [[ -z "$NODE_ID" || "$NODE_ID" == "null" ]]; then
  echo "CP did not return a node id" >&2
  exit 1
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
(cd "$ROOT" && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o "$TMP" ./node-agent/cmd/agent)
scp -q "$TMP" "$HOST:/usr/local/bin/node-agent"
ssh "$HOST" 'chmod 755 /usr/local/bin/node-agent'

# Token and node id are expanded into the script body sent over SSH, not into the
# remote command line, and the script does not print them.
# Values below are expanded on this machine before the script is sent.
ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
umask 077
install -d -m 700 /root/focusvpn
cat > /root/focusvpn/agent.env <<EOF
AGENT_NODE_ID=${NODE_ID}
AGENT_CP_URL=${FOCUSVPN_AGENT_URL}
AGENT_ENGINE=xray
AGENT_CERT_FILE=/root/focusvpn/agent.crt
AGENT_KEY_FILE=/root/focusvpn/agent.key
AGENT_CA_FILE=/root/focusvpn/ca.crt
AGENT_XRAY_API=127.0.0.1:10085
AGENT_XRAY_TAGS=vless-ws:10000,vless-xhttp:10001
AGENT_PUBLIC_HOST=${DOMAIN}
AGENT_NODE_TOKEN=${AGENT_TOKEN}
EOF
chmod 600 /root/focusvpn/agent.env
cat > /etc/systemd/system/focusvpn-agent.service <<'UNIT'
[Unit]
Description=FocusVPN node agent
After=network-online.target xray.service
Wants=xray.service

[Service]
EnvironmentFile=/root/focusvpn/agent.env
ExecStart=/usr/local/bin/node-agent
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now focusvpn-agent
echo "agent=$(systemctl is-active focusvpn-agent)"
REMOTE
echo "node $NAME registered ($NODE_ID)"
