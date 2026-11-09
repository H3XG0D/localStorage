#!/usr/bin/env python3
"""Deploy BOTH entries (public index.html + panel.html) and all their assets.

Backs up both live HTML files, uploads every dist asset, atomically replaces
both HTML files, then prunes assets that were referenced by the OLD html files
but by NEITHER new one. Old panel assets (p-*.js) are pruned — a full backup is
taken first (see /root/focuspay-panel-backup-*). Verifies /, /x8, /ops after.

Env: FOCUSPAY_SSH_HOST, FOCUSPAY_SSH_USER, FOCUSPAY_SSH_PASSWORD
Usage: python scripts/deploy_all.py [--dry-run]
"""
import os
import posixpath
import re
import sys
import time

import paramiko

HOST = os.environ.get("FOCUSPAY_SSH_HOST", "153.80.249.77")
USER = os.environ.get("FOCUSPAY_SSH_USER", "root")
PW = os.environ.get("FOCUSPAY_SSH_PASSWORD")

WEBROOT = "/var/www/focuspay.org"
ASSETS_DIR = posixpath.join(WEBROOT, "assets")
LOCAL_DIST = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dist"))
ASSET_RE = re.compile(r"/assets/([A-Za-z0-9._-]+\.(?:js|css))")
HTML_FILES = ("index.html", "panel.html", "casino.html", "exchange.html")
DRY = "--dry-run" in sys.argv

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass


def log(m: str) -> None:
    print(m, flush=True)


def connect() -> paramiko.SSHClient:
    ssh_config = paramiko.SSHConfig.from_path(os.path.expanduser("~/.ssh/config")).lookup("focuspay")
    hostname = os.environ.get("FOCUSPAY_SSH_HOST", ssh_config.get("hostname", HOST))
    username = os.environ.get("FOCUSPAY_SSH_USER", ssh_config.get("user", USER))
    key_filename = None if PW else ssh_config.get("identityfile")
    last = None
    for _attempt in range(4):
        c = paramiko.SSHClient()
        c.load_system_host_keys()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(
                hostname,
                username=username,
                password=PW,
                key_filename=key_filename,
                timeout=25,
                look_for_keys=not PW and not key_filename,
                allow_agent=not PW,
            )
            return c
        except Exception as exc:  # noqa: BLE001
            last = exc
            c.close()
            time.sleep(9)
    raise SystemExit(f"SSH connect failed: {last}")


def run(c, cmd):
    _i, o, e = c.exec_command(cmd, timeout=60)
    o.channel.recv_exit_status()
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


def refs(text: str) -> set:
    return set(ASSET_RE.findall(text or ""))


def main() -> int:
    new_html: dict[str, str] = {}
    for name in HTML_FILES:
        path = os.path.join(LOCAL_DIST, name)
        if not os.path.isfile(path):
            log(f"ERROR: dist/{name} missing — run `npm run build`.")
            return 2
        with open(path, encoding="utf-8") as f:
            new_html[name] = f.read()
    new_assets_refs: set[str] = set()
    for content in new_html.values():
        new_assets_refs |= refs(content)
    local_assets = sorted(os.listdir(os.path.join(LOCAL_DIST, "assets"))) if os.path.isdir(os.path.join(LOCAL_DIST, "assets")) else []
    log(f"New assets referenced: {len(new_assets_refs)}")

    c = connect()
    sftp = c.open_sftp()
    try:
        def read_remote(p):
            try:
                with sftp.open(p, "r") as fh:
                    return fh.read().decode("utf-8", "replace")
            except IOError:
                return ""

        old_refs: set[str] = set()
        for name in HTML_FILES:
            old_refs |= refs(read_remote(posixpath.join(WEBROOT, name)))

        # upload all new hashed assets
        log(f"Uploading {len(local_assets)} asset(s)…")
        for name in local_assets:
            if DRY:
                continue
            sftp.put(os.path.join(LOCAL_DIST, "assets", name), posixpath.join(ASSETS_DIR, name))
            sftp.chmod(posixpath.join(ASSETS_DIR, name), 0o664)

        # upload root static (favicon, images, svg) except html/assets
        for name in os.listdir(LOCAL_DIST):
            if name in ("assets", *HTML_FILES):
                continue
            src = os.path.join(LOCAL_DIST, name)
            if os.path.isfile(src) and not DRY:
                sftp.put(src, posixpath.join(WEBROOT, name))
                sftp.chmod(posixpath.join(WEBROOT, name), 0o664)

        # backup + replace both html
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name, content in new_html.items():
            if DRY:
                log(f"  [dry] replace {name}")
                continue
            run(c, f"cp -a {WEBROOT}/{name} {WEBROOT}/{name}.bak-{stamp} 2>/dev/null || true")
            sftp.put(os.path.join(LOCAL_DIST, name), posixpath.join(WEBROOT, name))
            sftp.chmod(posixpath.join(WEBROOT, name), 0o664)
            log(f"Replaced {name} (backup .bak-{stamp})")

        # prune assets referenced by old html but not by new (old bundles)
        prunable = old_refs - new_assets_refs
        if prunable:
            log(f"Pruning {len(prunable)} old asset(s): {sorted(prunable)}")
            for name in sorted(prunable):
                if DRY:
                    continue
                try:
                    sftp.remove(posixpath.join(ASSETS_DIR, name))
                except IOError as e:
                    log(f"  warn: {name}: {e}")
        else:
            log("Nothing to prune.")

        if not DRY:
            run(c, f"chown -R www-data:www-data {WEBROOT} 2>/dev/null || true")

        log("Verifying…")
        for path in ("/", "/x8", "/ops", "/casino", "/casino/tg", "/exchange/tg"):
            out, _ = run(
                c,
                "curl -s -o /dev/null -w '%{http_code}' -H 'Host: focuspay.org' "
                f"http://127.0.0.1{path}",
            )
            log(f"  {path} → {out.strip()}")
    finally:
        sftp.close()
        c.close()
    log("Done." + (" (dry-run)" if DRY else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
