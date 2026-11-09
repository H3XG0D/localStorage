# FocusPay SAST self-check

Nightly **fail-closed** bandit + pip-audit. Results are stored in Postgres and shown on `/x8/ai-tasks`.

HTTP origin smoke stays in `focuspay-selfcheck.service`
(`bot/tg_bot_btc/deploy/security/focuspay-selfcheck.py`, ~15m, UA `FocusPay-SelfCheck/1.0`).
Set `SELFCHECK_SAST=0` on that unit so SAST is not PATH-looked-up there.

## Layout

| Path | Role |
|---|---|
| `/opt/focuspay-security-tools` | pinned venv (`bandit`, `pip-audit`) |
| `/opt/exchange-backend/scripts/security_selfcheck.py` | orchestrator |
| `/var/lib/focuspay/selfcheck` | WorkingDirectory + artifacts |
| `focuspay-sast-selfcheck.timer` | `OnCalendar=04:15 UTC` |

Bins are **absolute** (`BANDIT_BIN`, `PIP_AUDIT_BIN`). Missing executable → `unavailable`, job exit 2, alarm on `/x8/ai-tasks`. No PATH lookup, no silent skip.

Each tree may ship `bandit.yaml` (passed as `-c` when present). Current skip: **B608** only — asyncpg `$N` binds; the f-string SQL heuristic is a known FP. Do not skip B311/B105/B108/B310/B404. `exclude_dirs` covers tests/scripts/deploy/tmp.

## Install (prod)

```bash
python3 -m venv /opt/focuspay-security-tools
/opt/focuspay-security-tools/bin/pip install -U pip
/opt/focuspay-security-tools/bin/pip install -r /opt/exchange-backend/deploy/security/requirements-security.txt
install -d -o focuspay -g focuspay /var/lib/focuspay/selfcheck
install -m 644 focuspay-sast-selfcheck.service /etc/systemd/system/
install -m 644 focuspay-sast-selfcheck.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now focuspay-sast-selfcheck.timer
systemctl start focuspay-sast-selfcheck.service
```

Apply migration `migrations/add_ops_ai_selfcheck_runs.sql` before the first run.

## API

- `GET /api/admin/ai-tasks/selfcheck/latest`
- `GET /api/admin/ai-tasks/selfcheck/{id}`

`agents_json.selfcheck` holds check statuses. `agents.merged` is only real vulnerability findings.
Failed runs open/update a `review` task; the Cursor prompt fences scanner output as
`<<<UNTRUSTED_DATA` (not instructions) and splits Bandit exchange/bot + pip-audit sections.
No Cursor/git/subprocess/deploy from the SAST job. Full reports required — do not invent CVE.
