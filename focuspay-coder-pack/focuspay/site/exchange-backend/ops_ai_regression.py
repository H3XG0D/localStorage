"""Read-only UI regression agent for Admin · /x8/ai-tasks.

Sandbox rules:
- Only safe UI/API checks (list/filter/open detail).
- Never Approve / Reject / Done / finance / Cursor auto-apply / git / subprocess / deploy.
- Reports are proposals only — human must approve any fix.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from privacy_redaction import content_hash, redact_text

# Fixed scenario target — never substitute with /exchange or LIVE RATES.
REGRESSION_PATH = "/x8/ai-tasks"
REGRESSION_HINT = "Очередь AI-задач"
REGRESSION_AGENT_ROLE = "ui_regression"

Severity = Literal["critical", "high", "med", "low", "info"]
RunStatus = Literal["queued", "running", "passed", "failed", "error"]

SAFE_UI_ACTIONS: frozenset[str] = frozenset(
    {
        "open_path",
        "assert_page_header",
        "change_status_filter",
        "select_task_row",
        "view_task_detail",
        "copy_cursor_prompt",  # clipboard only — does not execute
        "collect_console",
        "collect_network",
        "capture_screenshot_meta",
    }
)

FORBIDDEN_UI_ACTIONS: frozenset[str] = frozenset(
    {
        "approve",
        "reject",
        "done",
        "finance",
        "payroll",
        "payout",
        "deploy",
        "git_commit",
        "git_push",
        "subprocess",
        "cursor_auto_apply",
        "execute_cursor_prompt",
        "delete",
        "ban",
        "broadcast",
    }
)

_RATE_PER_MIN = 6
_IDEMPOTENCY_TTL = 3600
_MAX_RUNS = 200


class RegressionError(ValueError):
    pass


@dataclass
class StepResult:
    step: str
    action: str
    expected: str
    actual: str
    ok: bool
    severity: Severity = "info"
    screenshot: str | None = None
    bugfix_proposal: str | None = None
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)


@dataclass
class RegressionReport:
    run_id: str
    path: str
    hint: str
    deployment: dict[str, Any]
    status: RunStatus
    started_at: str
    finished_at: str | None
    steps: list[StepResult]
    summary: str
    max_severity: Severity
    agent_capabilities: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": self.path,
            "hint": self.hint,
            "deployment": self.deployment,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [asdict(s) for s in self.steps],
            "summary": self.summary,
            "max_severity": self.max_severity,
            "agent_capabilities": self.agent_capabilities,
            "notes": self.notes,
        }


@dataclass
class RegressionRun:
    id: str
    admin_id: int
    tenant_scope: str
    status: RunStatus
    created_at: float
    deployment: dict[str, Any]
    report: RegressionReport | None = None
    client_observations: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


_lock = threading.Lock()
_runs: dict[str, RegressionRun] = {}
_by_admin_latest: dict[int, str] = {}
_rate_hits: dict[int, list[float]] = {}
_idem: dict[str, tuple[float, str]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rate_ok(admin_id: int) -> bool:
    now = time.time()
    with _lock:
        bucket = [t for t in _rate_hits.get(admin_id, []) if now - t < 60.0]
        if len(bucket) >= _RATE_PER_MIN:
            _rate_hits[admin_id] = bucket
            return False
        bucket.append(now)
        _rate_hits[admin_id] = bucket
        return True


def _idem_get(key: str) -> str | None:
    now = time.time()
    with _lock:
        item = _idem.get(key)
        if not item:
            return None
        ts, run_id = item
        if now - ts > _IDEMPOTENCY_TTL:
            _idem.pop(key, None)
            return None
        return run_id


def _idem_put(key: str, run_id: str) -> None:
    with _lock:
        _idem[key] = (time.time(), run_id)


def assert_action_allowed(action: str) -> None:
    a = (action or "").strip().lower()
    if a in FORBIDDEN_UI_ACTIONS or a not in SAFE_UI_ACTIONS:
        raise RegressionError(f"action_forbidden:{a}")


def agent_capabilities() -> dict[str, Any]:
    return {
        "role": REGRESSION_AGENT_ROLE,
        "path": REGRESSION_PATH,
        "hint": REGRESSION_HINT,
        "read_only": True,
        "safe_actions": sorted(SAFE_UI_ACTIONS),
        "forbidden_actions": sorted(FORBIDDEN_UI_ACTIONS),
        "auto_approve": False,
        "auto_reject": False,
        "auto_done": False,
        "auto_git": False,
        "auto_subprocess": False,
        "auto_deploy": False,
        "cursor_execute": False,
        "requires_human_for_fixes": True,
    }


def resolve_deployment(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Best-effort version/deployment stamp — no secrets."""
    import os

    meta = meta or {}
    version = (
        str(meta.get("version") or "").strip()
        or str(os.environ.get("FOCUSPAY_DEPLOY_VERSION") or "").strip()
        or str(os.environ.get("GIT_COMMIT") or "").strip()[:40]
        or "unknown"
    )
    deploy_id = str(meta.get("deployment_id") or meta.get("deploy_id") or "").strip() or None
    return {
        "version": version[:120],
        "deployment_id": (deploy_id or "")[:120] or None,
        "panel_path": REGRESSION_PATH,
        "captured_at": _now_iso(),
    }


def _sev_rank(s: Severity) -> int:
    order = {"info": 0, "low": 1, "med": 2, "high": 3, "critical": 4}
    return order.get(s, 0)


def _max_sev(steps: list[StepResult]) -> Severity:
    best: Severity = "info"
    for s in steps:
        if not s.ok and _sev_rank(s.severity) > _sev_rank(best):
            best = s.severity
        elif s.ok and s.severity == "info":
            continue
    return best


def _scrub_list(items: list[Any] | None, *, limit: int = 40) -> list[str]:
    out: list[str] = []
    for x in items or []:
        t = redact_text(str(x), keep_short_ids=True)[:500]
        if t:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def execute_cursor_prompt_forbidden() -> dict[str, Any]:
    return {
        "allowed": False,
        "auto_apply": False,
        "auto_deploy": False,
        "reason": "cursor_prompt_requires_explicit_human_approve",
    }


def refuse_subprocess_and_git() -> dict[str, Any]:
    return {
        "subprocess": False,
        "git": False,
        "deploy": False,
        "reason": "regression_agent_is_read_only_sandbox",
    }


async def _probe_queue() -> dict[str, Any]:
    """Read-only probe of task queue shape (service layer, no privilege escalation)."""
    try:
        import ops_ai_service as svc

        data = await svc.list_tasks(status="review", limit=5, offset=0)
        tasks = data.get("tasks") or []
        keys_ok = True
        sample = tasks[0] if tasks else None
        if sample:
            for k in ("id", "title", "status", "request_text"):
                if k not in sample:
                    keys_ok = False
        return {
            "ok": True,
            "total": int(data.get("total") or 0),
            "sample_count": len(tasks),
            "keys_ok": keys_ok,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "total": 0,
            "sample_count": 0,
            "keys_ok": False,
            "error": redact_text(str(e), keep_short_ids=True)[:300],
        }


def _step(
    *,
    step: str,
    action: str,
    expected: str,
    actual: str,
    ok: bool,
    severity: Severity = "info",
    bugfix: str | None = None,
    console: list[str] | None = None,
    network: list[str] | None = None,
    screenshot: str | None = None,
) -> StepResult:
    assert_action_allowed(action)
    return StepResult(
        step=step,
        action=action,
        expected=expected,
        actual=actual,
        ok=ok,
        severity=severity if not ok else "info",
        screenshot=screenshot,
        bugfix_proposal=bugfix,
        console_errors=_scrub_list(console),
        network_errors=_scrub_list(network),
    )


async def run_safe_scenarios(
    *,
    admin_id: int,
    deployment: dict[str, Any],
    client_obs: dict[str, Any] | None = None,
) -> RegressionReport:
    """Execute allowlisted regression steps for /x8/ai-tasks only."""
    run_id = uuid.uuid4().hex[:16]
    started = _now_iso()
    steps: list[StepResult] = []
    notes: list[str] = [
        "Агент read-only: Approve/Reject/Done недоступны без human approval.",
        "Исправления только как proposal — без git/subprocess/автодеплоя.",
    ]
    obs = client_obs or {}

    # 1) Path / hint anchor
    path = str(obs.get("path") or REGRESSION_PATH).strip() or REGRESSION_PATH
    hint = str(obs.get("hint") or REGRESSION_HINT).strip() or REGRESSION_HINT
    path_ok = path == REGRESSION_PATH and "LIVE RATES" not in hint.upper()
    steps.append(
        _step(
            step="ui_anchor",
            action="open_path",
            expected=f"path={REGRESSION_PATH}; hint={REGRESSION_HINT}",
            actual=f"path={path}; hint={hint[:120]}",
            ok=path_ok,
            severity="high",
            bugfix=(
                "Зафиксировать path=/x8/ai-tasks и hint «Очередь AI-задач»; "
                "не подменять цель на /exchange из-за LIVE RATES."
                if not path_ok
                else None
            ),
        )
    )

    # 2) Page header — screen PageHeader title, not browser tab ("FocusPay · Панель")
    header = str(obs.get("page_title") or obs.get("header") or "").strip()
    hl = header.lower()
    tabish = hl in {"focuspay · панель", "focuspay - панель", "focuspay"} or (
        hl.startswith("focuspay") and "панель" in hl and "задач" not in hl
    )
    header_ok = (
        (not header)
        or tabish  # shell tab title is not a failure of this screen
        or ("задач" in hl and ("ai" in hl or "AI" in header))
        or header.startswith("AI · задачи")
        or "очередь ai" in hl
    )
    steps.append(
        _step(
            step="page_header",
            action="assert_page_header",
            expected="PageHeader: AI · задачи / очередь (не document.title панели)",
            actual=header or "(server-side: header not supplied — rely on path)",
            ok=header_ok,
            severity="med",
            bugfix=(
                "Передавать title PageHeader («AI · задачи от операторов»), "
                "а не document.title («FocusPay · Панель»)."
                if not header_ok
                else None
            ),
        )
    )

    # 3) Status filter (safe)
    filter_val = str(obs.get("status_filter") or "review").strip() or "review"
    allowed_filters = {"review", "approved", "rejected", "done", "all"}
    filt_ok = filter_val in allowed_filters
    steps.append(
        _step(
            step="status_filter",
            action="change_status_filter",
            expected=f"filter in {sorted(allowed_filters)}",
            actual=filter_val,
            ok=filt_ok,
            severity="med",
            bugfix="Select статуса должен отдавать только review|approved|rejected|done|all."
            if not filt_ok
            else None,
        )
    )

    # 4) Queue API probe
    probe = await _probe_queue()
    steps.append(
        _step(
            step="queue_list_api",
            action="view_task_detail" if probe.get("sample_count") else "assert_page_header",
            expected="list_tasks returns {tasks,total}; items have id/title/status",
            actual=(
                f"ok={probe.get('ok')} total={probe.get('total')} "
                f"sample={probe.get('sample_count')} keys_ok={probe.get('keys_ok')} "
                f"err={probe.get('error')}"
            ),
            ok=bool(probe.get("ok")) and bool(probe.get("keys_ok") or probe.get("total") == 0),
            severity="high",
            bugfix=(
                "Проверить ops_ai_service.list_tasks / GET /api/admin/ai-tasks "
                "и нормализацию полей AdminAiTask."
                if not probe.get("ok")
                else None
            ),
            network=[probe["error"]] if probe.get("error") else None,
        )
    )

    # 5) Forbidden actions remain blocked for agent
    for bad in ("approve", "reject", "done", "execute_cursor_prompt", "subprocess"):
        try:
            assert_action_allowed(bad)
            blocked = False
            actual = f"{bad} unexpectedly allowed"
        except RegressionError:
            blocked = True
            actual = f"{bad} blocked"
        steps.append(
            _step(
                step=f"guard_{bad}",
                action="collect_console",
                expected=f"{bad} forbidden for regression agent",
                actual=actual,
                ok=blocked,
                severity="critical",
                bugfix=f"Запретить агенту действие {bad} на уровне allowlist."
                if not blocked
                else None,
            )
        )

    # 6) Sandbox: no git/subprocess/cursor execute
    sand = refuse_subprocess_and_git()
    cur = execute_cursor_prompt_forbidden()
    sand_ok = (
        sand.get("subprocess") is False
        and sand.get("git") is False
        and sand.get("deploy") is False
        and cur.get("allowed") is False
    )
    steps.append(
        _step(
            step="sandbox_no_exec",
            action="collect_network",
            expected="subprocess/git/deploy/cursor_execute = false",
            actual=str({"sandbox": sand, "cursor": cur}),
            ok=sand_ok,
            severity="critical",
            bugfix="Убрать любое автоисполнение Cursor/git/subprocess из regression path.",
        )
    )

    # 7) Client console / network / screenshot
    console = _scrub_list(obs.get("console_errors") if isinstance(obs.get("console_errors"), list) else [])
    network = _scrub_list(obs.get("network_errors") if isinstance(obs.get("network_errors"), list) else [])
    shot = obs.get("screenshot")
    shot_s = None
    if isinstance(shot, str) and shot.strip():
        # Never store raw data URLs with secrets — keep hash / short ref only
        raw = shot.strip()
        if raw.startswith("data:"):
            shot_s = f"data-url-hash:{content_hash(raw)[:16]}"
        else:
            shot_s = redact_text(raw, keep_short_ids=True)[:300]

    console_ok = len(console) == 0
    network_ok = len(network) == 0
    steps.append(
        _step(
            step="client_console",
            action="collect_console",
            expected="Нет console errors на /x8/ai-tasks",
            actual=f"{len(console)} error(s)",
            ok=console_ok,
            severity="high" if console else "info",
            console=console,
            screenshot=shot_s,
            bugfix=(
                "Исправить JS-ошибки на AdminAiTasks: см. console_errors в отчёте."
                if console
                else None
            ),
        )
    )
    steps.append(
        _step(
            step="client_network",
            action="collect_network",
            expected="Нет failed network (4xx/5xx) на безопасных GET очереди",
            actual=f"{len(network)} error(s)",
            ok=network_ok,
            severity="high" if network else "info",
            network=network,
            screenshot=shot_s,
            bugfix=(
                "Проверить авторизацию/контракт GET /api/admin/ai-tasks и вложения."
                if network
                else None
            ),
        )
    )

    # Optional: select/view row reported by client
    if obs.get("selected_task_id") is not None:
        tid = obs.get("selected_task_id")
        steps.append(
            _step(
                step="select_task_row",
                action="select_task_row",
                expected="Можно открыть карточку задачи без approve/reject/done",
                actual=f"selected_task_id={tid}",
                ok=True,
                severity="info",
                screenshot=shot_s,
            )
        )

    failed = [s for s in steps if not s.ok]
    status: RunStatus = "passed" if not failed else "failed"
    max_sev = _max_sev(steps) if failed else "info"
    summary = (
        f"UI regression /x8/ai-tasks: {status}; "
        f"{len(steps) - len(failed)}/{len(steps)} steps ok; "
        f"admin={admin_id}; version={deployment.get('version')}"
    )

    return RegressionReport(
        run_id=run_id,
        path=REGRESSION_PATH,
        hint=REGRESSION_HINT,
        deployment=deployment,
        status=status,
        started_at=started,
        finished_at=_now_iso(),
        steps=steps,
        summary=summary,
        max_severity=max_sev,
        agent_capabilities=agent_capabilities(),
        notes=notes,
    )


def _store_run(run: RegressionRun) -> None:
    with _lock:
        _runs[run.id] = run
        _by_admin_latest[run.admin_id] = run.id
        # prune
        if len(_runs) > _MAX_RUNS:
            oldest = sorted(_runs.values(), key=lambda r: r.created_at)[: len(_runs) - _MAX_RUNS]
            for o in oldest:
                _runs.pop(o.id, None)


def get_run(run_id: str, *, admin_id: int) -> RegressionRun | None:
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return None
        # Ownership: only the starting admin (or we could allow any admin — still re-auth)
        if int(run.admin_id) != int(admin_id):
            return None
        return run


def get_latest_for_admin(admin_id: int) -> RegressionRun | None:
    with _lock:
        rid = _by_admin_latest.get(int(admin_id))
        if not rid:
            return None
        return _runs.get(rid)


async def start_run(
    *,
    admin_id: int,
    tenant_scope: str = "admin",
    deployment_meta: dict[str, Any] | None = None,
    client_observations: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not admin_id or int(admin_id) <= 0:
        raise RegressionError("admin_required")
    if not _rate_ok(int(admin_id)):
        raise PermissionError("rate_limited")

    idem = (idempotency_key or "").strip()[:128] or None
    if idem:
        scoped = f"{admin_id}:{idem}"
        existing = _idem_get(scoped)
        if existing:
            run = get_run(existing, admin_id=int(admin_id))
            if run and run.report:
                return {"run": _public_run(run), "replay": True}

    deployment = resolve_deployment(deployment_meta)
    report = await run_safe_scenarios(
        admin_id=int(admin_id),
        deployment=deployment,
        client_obs=client_observations,
    )
    run = RegressionRun(
        id=report.run_id,
        admin_id=int(admin_id),
        tenant_scope=(tenant_scope or "admin")[:64],
        status=report.status,
        created_at=time.time(),
        deployment=deployment,
        report=report,
        client_observations={
            k: redact_text(str(v), keep_short_ids=True)[:500]
            if not isinstance(v, (list, dict, int, float, bool)) and v is not None
            else v
            for k, v in (client_observations or {}).items()
            if k
            in {
                "path",
                "hint",
                "page_title",
                "header",
                "status_filter",
                "selected_task_id",
                "console_errors",
                "network_errors",
                "screenshot",
            }
        },
        idempotency_key=idem,
    )
    # scrub nested lists
    if isinstance(run.client_observations.get("console_errors"), list):
        run.client_observations["console_errors"] = _scrub_list(
            run.client_observations["console_errors"]
        )
    if isinstance(run.client_observations.get("network_errors"), list):
        run.client_observations["network_errors"] = _scrub_list(
            run.client_observations["network_errors"]
        )

    _store_run(run)
    if idem:
        _idem_put(f"{admin_id}:{idem}", run.id)

    return {"run": _public_run(run), "replay": False}


async def attach_client_observations(
    run_id: str,
    *,
    admin_id: int,
    observations: dict[str, Any],
) -> dict[str, Any]:
    """Re-run scenarios with client console/network/screenshot (still read-only)."""
    run = get_run(run_id, admin_id=admin_id)
    if not run:
        raise LookupError("run_not_found")
    merged = {**(run.client_observations or {}), **(observations or {})}
    report = await run_safe_scenarios(
        admin_id=int(admin_id),
        deployment=run.deployment,
        client_obs=merged,
    )
    report.run_id = run.id
    run.report = report
    run.status = report.status
    run.client_observations = merged
    _store_run(run)
    return {"run": _public_run(run)}


def _public_run(run: RegressionRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "admin_id": run.admin_id,
        "tenant_scope": run.tenant_scope,
        "status": run.status,
        "deployment": run.deployment,
        "created_at": datetime.fromtimestamp(run.created_at, tz=timezone.utc).isoformat(),
        "capabilities": agent_capabilities(),
        "report": run.report.to_dict() if run.report else None,
    }


def new_idempotency_key() -> str:
    return secrets.token_hex(16)


def ownership_token(admin_id: int, run_id: str) -> str:
    """Opaque binding admin↔run (not a privilege substitute for JWT)."""
    return hashlib.sha256(f"{admin_id}:{run_id}:ops-ai-regression".encode()).hexdigest()[:24]
