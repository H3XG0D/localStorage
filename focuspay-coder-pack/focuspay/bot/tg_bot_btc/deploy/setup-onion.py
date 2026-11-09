"""Idempotent Tor hidden services: FocusPay exchange + Doliv/traders.

Copies nginx/tor snippets, installs tor, writes PUBLIC_ONION_URL / DOLIV_ONION_URL
into backend and bot .env. Does not restart API/bot — caller does after code sync.
"""
from __future__ import annotations

import os
import pathlib
import re
import time

DEPLOY = pathlib.Path(__file__).resolve().parent
NGINX_EXCHANGE = DEPLOY / "nginx-focuspay-onion.conf"
NGINX_DOLIV = DEPLOY / "nginx-traders-onion.conf"
NGINX_ZONES = DEPLOY / "nginx-focuspay-onion-zones.conf"
TORRC = DEPLOY / "tor-focuspay-onion.conf"

EXCHANGE_ENV = "/opt/exchange-backend/.env"
BOT_ENV = "/opt/tg_bot_btc/.env"
TOR_INCLUDE = "%include /etc/tor/torrc.d/*.conf"
TOR_MARKER_BEGIN = "# BEGIN focuspay-onion"
TOR_MARKER_END = "# END focuspay-onion"


def upsert_env(path: str, key: str, value: str) -> None:
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=", text, flags=re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n{line}\n"
    p.write_text(text, encoding="utf-8")


def write_selfsigned_onion_cert(hostname: str, dest_stem: str) -> None:
    """Self-signed cert so Tor Browser HTTPS-Only Mode can connect on :443."""
    cert_dir = pathlib.Path("/etc/nginx/onion-certs")
    cert_dir.mkdir(mode=0o750, exist_ok=True)
    key = cert_dir / f"{dest_stem}.key"
    crt = cert_dir / f"{dest_stem}.crt"
    host = hostname.strip()
    rc = os.system(
        "openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes "
        f"-keyout {key} -out {crt} "
        f'-subj "/CN={host}" '
        f'-addext "subjectAltName=DNS:{host}" '
        ">/dev/null 2>&1"
    )
    if rc != 0:
        raise SystemExit(f"openssl cert failed for {host}")
    os.chmod(key, 0o640)
    os.chmod(crt, 0o644)


def read_hostname(path: str) -> str:
    deadline = time.time() + 90
    while time.time() < deadline:
        if os.path.isfile(path):
            host = pathlib.Path(path).read_text(encoding="utf-8").strip()
            if host.endswith(".onion"):
                return host
        time.sleep(1)
    raise SystemExit(f"hidden service hostname missing: {path}")


def apply_torrc() -> None:
    torrc = pathlib.Path("/etc/tor/torrc")
    body = torrc.read_text(encoding="utf-8") if torrc.exists() else ""
    body = body.replace(f"\n{TOR_INCLUDE}\n", "\n").replace(TOR_INCLUDE + "\n", "")
    hs = TORRC.read_text(encoding="utf-8").strip()
    block = f"{TOR_MARKER_BEGIN}\n{hs}\n{TOR_MARKER_END}\n"
    if TOR_MARKER_BEGIN in body and TOR_MARKER_END in body:
        body = re.sub(
            re.escape(TOR_MARKER_BEGIN) + r".*?" + re.escape(TOR_MARKER_END),
            block.strip(),
            body,
            count=1,
            flags=re.S,
        )
    else:
        if body and not body.endswith("\n"):
            body += "\n"
        body += f"\n{block}"
    torrc.write_text(body, encoding="utf-8")


def write_nginx_sites() -> None:
    os.makedirs("/etc/nginx/conf.d", exist_ok=True)
    pathlib.Path("/etc/nginx/conf.d/focuspay-onion-zones.conf").write_text(
        NGINX_ZONES.read_text(encoding="utf-8"), encoding="utf-8"
    )
    pathlib.Path("/etc/nginx/sites-available/focuspay-onion").write_text(
        NGINX_EXCHANGE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    pathlib.Path("/etc/nginx/sites-available/traders-onion").write_text(
        NGINX_DOLIV.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in ("focuspay-onion", "traders-onion"):
        link = pathlib.Path(f"/etc/nginx/sites-enabled/{name}")
        target = f"/etc/nginx/sites-available/{name}"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("run as root on the production box")
    os.system("apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y tor")
    os.makedirs("/etc/nginx/conf.d", exist_ok=True)
    pathlib.Path("/etc/nginx/conf.d/focuspay-onion-zones.conf").write_text(
        NGINX_ZONES.read_text(encoding="utf-8"), encoding="utf-8"
    )
    apply_torrc()
    os.system("systemctl enable tor")
    os.system("systemctl reset-failed tor@default")
    rc = os.system("systemctl restart tor@default")
    if rc != 0:
        raise SystemExit("tor@default failed to start")
    exchange = read_hostname("/var/lib/tor/hidden_service_focuspay/hostname")
    doliv = read_hostname("/var/lib/tor/hidden_service_doliv/hostname")
    write_selfsigned_onion_cert(exchange, "focuspay")
    write_selfsigned_onion_cert(doliv, "doliv")
    write_nginx_sites()
    rc = os.system("nginx -t")
    if rc != 0:
        raise SystemExit("nginx -t failed")
    os.system("systemctl reload nginx")
    exchange_url = f"http://{exchange}"
    doliv_url = f"http://{doliv}"
    for env_path in (EXCHANGE_ENV, BOT_ENV):
        if os.path.isfile(env_path):
            upsert_env(env_path, "PUBLIC_ONION_URL", exchange_url)
            upsert_env(env_path, "DOLIV_ONION_URL", doliv_url)
    print(f"PUBLIC_ONION_URL={exchange_url}")
    print(f"DOLIV_ONION_URL={doliv_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
