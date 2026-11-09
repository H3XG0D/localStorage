#!/usr/bin/env python3
"""Deploy the FocusPay public site to the live server WITHOUT touching the
admin/operator panel (panel.html + p-*.js).

Steps:
  1. Read local dist/ (must be freshly built: `npm run build`).
  2. Parse asset filenames referenced by the NEW dist/index.html.
  3. Parse asset filenames referenced by the LIVE index.html (old public site)
     and by the LIVE panel.html (admin/operator — must be preserved).
  4. Upload every new asset into /var/www/focuspay.org/assets/.
  5. Back up the live index.html, then atomically replace it.
  6. Delete ONLY old public-site assets that (a) were referenced by the old
     index.html, (b) are not referenced by the new index.html, and
     (c) are NOT referenced by panel.html. Never deletes p-*.js / panel assets.
  7. Verify `/`, `/x8`, `/ops` still respond.

Usage:  python scripts/deploy.py [--dry-run]
"""

import posixpath
import re
import stat
import sys
import time

import os

import paramiko

# Credentials come from the environment, never hardcoded:
#   FOCUSPAY_SSH_HOST, FOCUSPAY_SSH_USER, FOCUSPAY_SSH_PASSWORD
HOST = os.environ.get("FOCUSPAY_SSH_HOST", "153.80.249.77")
USER = os.environ.get("FOCUSPAY_SSH_USER", "root")
PW = os.environ.get("FOCUSPAY_SSH_PASSWORD")

WEBROOT = "/var/www/focuspay.org"
ASSETS_DIR = posixpath.join(WEBROOT, "assets")
LOCAL_DIST = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dist"))

ASSET_RE = re.compile(r'/assets/([A-Za-z0-9._-]+\.(?:js|css))')

DRY_RUN = "--dry-run" in sys.argv


try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def connect() -> paramiko.SSHClient:
    if not PW:
        raise SystemExit("Set FOCUSPAY_SSH_PASSWORD in the environment before deploying.")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)
    return c


def run(c: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    _in, out, err = c.exec_command(cmd, timeout=60)
    code = out.channel.recv_exit_status()
    return code, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def refs_in(text: str) -> set[str]:
    return set(ASSET_RE.findall(text or ""))


def main() -> int:
    if not os.path.isdir(LOCAL_DIST):
        log(f"ERROR: build output not found: {LOCAL_DIST}\nRun `npm run build` first.")
        return 2

    local_index = os.path.join(LOCAL_DIST, "index.html")
    with open(local_index, "r", encoding="utf-8") as f:
        new_index_html = f.read()
    new_assets = refs_in(new_index_html)
    log(f"New index.html references {len(new_assets)} asset(s): {sorted(new_assets)}")

    local_assets_dir = os.path.join(LOCAL_DIST, "assets")
    local_asset_files = sorted(os.listdir(local_assets_dir)) if os.path.isdir(local_assets_dir) else []
    local_extra = os.listdir(LOCAL_DIST)  # favicon etc. at dist root

    c = connect()
    sftp = c.open_sftp()
    try:
        # --- read live files ---
        def read_remote(path: str) -> str:
            try:
                with sftp.open(path, "r") as fh:
                    return fh.read().decode("utf-8", "replace")
            except IOError:
                return ""

        old_index_html = read_remote(posixpath.join(WEBROOT, "index.html"))
        panel_html = read_remote(posixpath.join(WEBROOT, "panel.html"))
        old_public_assets = refs_in(old_index_html)
        panel_assets = refs_in(panel_html)
        log(f"Live public index references: {sorted(old_public_assets)}")
        log(f"panel.html references (PROTECTED): {sorted(panel_assets)}")

        # --- upload new hashed assets ---
        log(f"Uploading {len(local_asset_files)} asset file(s) → {ASSETS_DIR}")
        for name in local_asset_files:
            src = os.path.join(local_assets_dir, name)
            dst = posixpath.join(ASSETS_DIR, name)
            if DRY_RUN:
                log(f"  [dry] put {name}")
            else:
                sftp.put(src, dst)
                sftp.chmod(dst, 0o664)

        # --- upload root static (favicon.svg, logo.svg, images, etc.) ---
        for name in local_extra:
            if name in ("assets", "index.html"):
                continue
            src = os.path.join(LOCAL_DIST, name)
            if not os.path.isfile(src):
                continue
            dst = posixpath.join(WEBROOT, name)
            if DRY_RUN:
                log(f"  [dry] put root {name}")
            else:
                sftp.put(src, dst)
                sftp.chmod(dst, 0o664)

        # --- backup + replace index.html ---
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = posixpath.join(WEBROOT, f"index.html.bak-{stamp}")
        if not DRY_RUN and old_index_html:
            run(c, f"cp -a {WEBROOT}/index.html {backup}")
            log(f"Backed up live index.html → {backup}")
        if DRY_RUN:
            log("  [dry] replace index.html")
        else:
            sftp.put(local_index, posixpath.join(WEBROOT, "index.html"))
            sftp.chmod(posixpath.join(WEBROOT, "index.html"), 0o664)
            log("Replaced index.html")

        # --- prune ONLY superseded public assets, never panel assets ---
        prunable = (old_public_assets - new_assets) - panel_assets
        if prunable:
            log(f"Pruning {len(prunable)} superseded public asset(s): {sorted(prunable)}")
            for name in sorted(prunable):
                if DRY_RUN:
                    log(f"  [dry] rm {name}")
                else:
                    try:
                        sftp.remove(posixpath.join(ASSETS_DIR, name))
                    except IOError as e:
                        log(f"  warn: could not remove {name}: {e}")
        else:
            log("Nothing to prune.")

        if not DRY_RUN:
            run(c, "chown -R www-data:www-data " + WEBROOT + " 2>/dev/null || true")

        # --- verify ---
        log("Verifying endpoints...")
        for path in ("/", "/x8", "/ops"):
            code, out, _ = run(c, f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1{path}")
            log(f"  {path} → HTTP {out.strip()}")
    finally:
        sftp.close()
        c.close()

    log("Done." + (" (dry-run, no changes)" if DRY_RUN else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
