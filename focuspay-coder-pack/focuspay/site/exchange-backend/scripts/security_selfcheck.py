#!/usr/bin/env python3
"""Nightly SAST orchestrator (systemd). Fail-closed. Does not run inside uvicorn.

WorkingDirectory must NOT be /opt/exchange-backend (operator.py shadows stdlib).
Uses absolute BANDIT_BIN / PIP_AUDIT_BIN — never PATH lookup.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import traceback
from pathlib import Path

# Pin stdlib operator before any backend import (prod tree has operator.py).
import operator as _stdlib_operator

sys.modules["operator"] = _stdlib_operator

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import ops_ai_selfcheck as sc  # noqa: E402


def _exec(argv: list[str], *, timeout: int = 600, cwd: str | None = None) -> sc.ExecResult:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else "timeout"
        return sc.ExecResult(exit_code=124, stdout=out, stderr=err or "timeout")
    except FileNotFoundError:
        return sc.ExecResult(exit_code=127, stdout="", stderr="not_installed")
    return sc.ExecResult(
        exit_code=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def _notify_telegram(run: dict, run_id: int, task_id: int | None) -> None:
    """Best-effort; never changes job exit code. No secrets in text."""
    if str(run.get("job_status") or "") == "passed":
        return
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (
        os.environ.get("SECURITY_TELEGRAM_CHAT_ID")
        or os.environ.get("TELEGRAM_REPORTS_GROUP_ID")
        or os.environ.get("OPS_AI_DEV_TELEGRAM_CHAT_ID")
        or ""
    ).strip()
    if not token or not chat:
        return
    site = (os.environ.get("PUBLIC_SITE_URL") or "https://focuspay.org").rstrip("/")
    lines = [
        "<b>Ops AI · SAST self-check</b>",
        f"job=<b>{run.get('job_status')}</b> exit={run.get('exit_code')} run=#{run_id}",
    ]
    for c in run.get("checks") or []:
        if not isinstance(c, dict):
            continue
        lines.append(
            f"• {c.get('tool')}[{c.get('target')}] {c.get('status')}"
            f" ({c.get('reason') or '—'}, exit={c.get('exit_code')})"
        )
    lines.append(f'<a href="{site}/x8/ai-tasks">Открыть /x8/ai-tasks</a>')
    if task_id:
        lines.append(f'<a href="{site}/x8/ai-tasks?id={task_id}">Задача #{task_id}</a>')
    text = "\n".join(lines)[:3500]
    try:
        import urllib.parse
        import urllib.request

        body = urllib.parse.urlencode(
            {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except Exception:
        # Notify must not mask the SAST result.
        traceback.print_exc(file=sys.stderr)


async def _persist(run: dict) -> tuple[int, int | None]:
    dsn = (os.environ.get("DATABASE_DSN") or "").strip()
    if not dsn:
        print("DATABASE_DSN missing — result not saved to API", file=sys.stderr)
        return 0, None
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        run_id = await sc.persist_run(conn, run)
        task_id = await sc.upsert_review_task(conn, run, run_id=run_id)
        if task_id:
            await sc.attach_task(conn, run_id, task_id)
        return run_id, task_id
    finally:
        await conn.close()


def main() -> int:
    cfg = sc.config_from_env()
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    run = sc.run_selfcheck(cfg, exec_fn=_exec)
    try:
        run_id, task_id = asyncio.run(_persist(run))
    except Exception:
        traceback.print_exc()
        run_id, task_id = 0, None
        # Persist failure is itself a failed job.
        if int(run.get("exit_code") or 0) == 0:
            run["job_status"] = "error"
            run["exit_code"] = sc.JOB_EXIT_UNAVAILABLE
    try:
        _notify_telegram(run, run_id, task_id)
    except Exception:
        traceback.print_exc(file=sys.stderr)
    print(
        json_line(run, run_id, task_id),
        flush=True,
    )
    return int(run.get("exit_code") if run.get("exit_code") is not None else sc.JOB_EXIT_UNAVAILABLE)


def json_line(run: dict, run_id: int, task_id: int | None) -> str:
    import json

    return json.dumps(
        {
            "run_id": run_id,
            "task_id": task_id,
            "job_status": run.get("job_status"),
            "exit_code": run.get("exit_code"),
            "checks": [
                {
                    "tool": c.get("tool"),
                    "target": c.get("target"),
                    "status": c.get("status"),
                    "reason": c.get("reason"),
                    "exit_code": c.get("exit_code"),
                }
                for c in (run.get("checks") or [])
                if isinstance(c, dict)
            ],
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
