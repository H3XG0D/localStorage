#!/usr/bin/env python3
"""FocusPay defensive self-check: origin smoke + optional nightly SAST.

HTTP probe is fail-visible (Telegram on regression). SAST is fail-closed via
ops_ai_selfcheck (absolute bins, persist to API). No exploit payloads.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [selfcheck] %(levelname)s %(message)s",
)
log = logging.getLogger("selfcheck")

STATE_PATH = Path(os.environ.get("SELFCHECK_STATE", "/var/lib/focuspay/selfcheck-state.json"))
BASE_URL = (os.environ.get("SELFCHECK_BASE_URL") or "https://focuspay.org").rstrip("/")
INTERVAL = int(os.environ.get("SELFCHECK_INTERVAL_SEC") or "900")
NIGHTLY_HOUR = int(os.environ.get("SELFCHECK_NIGHTLY_HOUR") or "3")
TG_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
TG_CHAT = int(os.environ.get("TELEGRAM_REPORTS_GROUP_ID") or os.environ.get("SELFCHECK_TG_CHAT_ID") or "0")
RUN_SAST = (os.environ.get("SELFCHECK_SAST", "0") or "0").lower() in ("1", "true", "yes")


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"fails": {}, "last_nightly": "", "last_digest": ""}


def save_state(st: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def tg(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        log.warning("tg skip: no token/chat")
        return
    body = json.dumps(
        {"chat_id": TG_CHAT, "text": text[:3500], "disable_web_page_preview": True}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except Exception as e:
        log.warning("tg failed: %s", e)


def http_check(path: str, *, expect: set[int], name: str) -> tuple[str, bool, str]:
    url = f"{BASE_URL}{path}"
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "FocusPay-SelfCheck/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            raw = resp.read(2048)
        if code not in expect:
            return name, False, f"{path} → HTTP {code} (want {sorted(expect)})"
        low = raw.lower()
        if b"database_dsn=" in low or b"secret_key=" in low or b"api_key=sk-" in low:
            return name, False, f"{path} body looks like leaked secrets"
        return name, True, f"{path} → {code}"
    except urllib.error.HTTPError as e:
        code = e.code
        if code in expect:
            return name, True, f"{path} → {code}"
        return name, False, f"{path} → HTTP {code}"
    except Exception as e:
        return name, False, f"{path} → {e}"


def run_smoke() -> list[tuple[str, bool, str]]:
    return [
        http_check("/", expect={200, 301, 302}, name="home"),
        http_check("/api/public/rates", expect={200}, name="rates"),
        http_check("/ops", expect={200, 301, 302}, name="ops"),
        http_check("/x8", expect={200, 301, 302}, name="x8"),
        http_check("/api/admin/dashboard", expect={401, 403}, name="admin_auth"),
        http_check("/api/operator/orders", expect={401, 403}, name="ops_auth"),
        http_check("/.env", expect={403, 404}, name="dot_env"),
    ]


def run_sast() -> list[str]:
    """Fail-closed SAST via ops_ai_selfcheck. Never PATH-lookup bandit/pip-audit."""
    if not RUN_SAST:
        return ["SAST delegated to focuspay-sast-selfcheck.timer"]
    import operator as _stdlib_operator

    sys.modules["operator"] = _stdlib_operator
    backend = Path("/opt/exchange-backend")
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    import asyncio
    import subprocess

    import ops_ai_selfcheck as sc

    def _exec(argv: list[str], *, timeout: int = 600, cwd: str | None = None) -> sc.ExecResult:
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
            )
        except FileNotFoundError:
            return sc.ExecResult(exit_code=127, stdout="", stderr="not_installed")
        except subprocess.TimeoutExpired:
            return sc.ExecResult(exit_code=124, stdout="", stderr="timeout")
        return sc.ExecResult(int(proc.returncode), proc.stdout or "", proc.stderr or "")

    cfg = sc.config_from_env()
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    run = sc.run_selfcheck(cfg, exec_fn=_exec)
    run_id, task_id = 0, None
    dsn = (os.environ.get("DATABASE_DSN") or "").strip()
    if dsn:
        try:
            import asyncpg

            async def _persist() -> tuple[int, int | None]:
                conn = await asyncpg.connect(dsn)
                try:
                    rid = await sc.persist_run(conn, run)
                    tid = await sc.upsert_review_task(conn, run, run_id=rid)
                    if tid:
                        await sc.attach_task(conn, rid, tid)
                    return rid, tid
                finally:
                    await conn.close()

            run_id, task_id = asyncio.run(_persist())
        except Exception as e:
            log.exception("sast persist failed: %s", e)
            if int(run.get("exit_code") or 0) == 0:
                run["job_status"] = "error"
                run["exit_code"] = sc.JOB_EXIT_UNAVAILABLE
    else:
        log.error("DATABASE_DSN missing — SAST not saved to API")
        run["job_status"] = "error"
        run["exit_code"] = sc.JOB_EXIT_UNAVAILABLE

    lines = [
        f"job={run.get('job_status')} exit={run.get('exit_code')} run=#{run_id} task={task_id or '—'}",
    ]
    for c in run.get("checks") or []:
        if not isinstance(c, dict):
            continue
        lines.append(
            f"{c.get('tool')}[{c.get('target')}]: {c.get('status')} "
            f"reason={c.get('reason') or '—'} exit={c.get('exit_code')}"
        )
    return lines


def main() -> None:
    st = load_state()
    log.info("start interval=%ss base=%s sast=%s", INTERVAL, BASE_URL, RUN_SAST)
    while True:
        results = run_smoke()
        new_fails = []
        prev = st.get("fails") or {}
        cur_fails = {}
        for name, ok, msg in results:
            if ok:
                log.info("OK %s", msg)
                continue
            log.warning("FAIL %s", msg)
            low = msg.lower()
            if "timed out" in low or "timeout" in low or "http 502" in low or "http 503" in low:
                continue
            cur_fails[name] = msg
            if prev.get(name) != msg:
                new_fails.append(msg)
        st["fails"] = cur_fails
        if new_fails:
            tg("FocusPay self-check FAIL:\n" + "\n".join(f"• {x}" for x in new_fails))
        elif prev and not cur_fails:
            tg("FocusPay self-check: all clear (previous fails recovered)")

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if RUN_SAST and now.hour == NIGHTLY_HOUR and st.get("last_nightly") != today:
            log.info("nightly SAST")
            sast = run_sast()
            st["last_nightly"] = today
            body = "FocusPay SAST self-check:\n" + "\n".join(sast)[:3000]
            tg(body)
            st["last_digest"] = today

        save_state(st)
        time.sleep(max(60, INTERVAL))


if __name__ == "__main__":
    main()
