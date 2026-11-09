"""Генератор современного PNG-профиля игрока FocusPay."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

_ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_SVG = _ASSETS / "logo_f.svg"
W, H, SCALE = 1000, 640, 2
MSK = ZoneInfo("Europe/Moscow")
# systemd unit used to set PATH to the venv only; Chrome's wrapper needs coreutils.
_COREUTILS_PATH = (
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/sbin",
    "/usr/bin",
    "/sbin",
    "/bin",
)


def _work_dir() -> Path:
    """Каталог для промежуточных файлов рендера.

    Snap-сборка Chromium ограничена AppArmor и не может писать в /tmp или ~/.cache,
    но имеет доступ к ~/snap/chromium/common (snap-песочница).
    """
    for candidate in (
        os.getenv("CASINO_CARD_WORKDIR"),
        os.path.expanduser("~/snap/chromium/common/focuspay-casino-card"),
        os.path.expanduser("~/.cache/focuspay-casino-card"),
    ):
        if not candidate:
            continue
        path = Path(candidate)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f".probe_{uuid.uuid4().hex}"
            probe.write_bytes(b"")
            probe.unlink()
            return path
        except OSError:
            continue
    return Path(tempfile.gettempdir())


def _browser_env(home: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """PATH for headless Chrome: keep the caller's PATH, then append coreutils."""
    env = dict(os.environ if environ is None else environ)
    env["HOME"] = home
    parts: list[str] = []
    seen: set[str] = set()
    for raw in (*(env.get("PATH") or "").split(":"), *_COREUTILS_PATH):
        if not raw or raw in seen:
            continue
        parts.append(raw)
        seen.add(raw)
    env["PATH"] = ":".join(parts)
    return env


def _find_browser() -> Optional[str]:
    for path in (
        os.getenv("CHROMIUM_PATH"),
        os.getenv("CHROME_PATH"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
    ):
        if path and os.path.exists(path):
            return path
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    for path in (
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
    ):
        if os.path.exists(path):
            return path
    return None


def _data_uri(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def _avatar_uri(data: Optional[bytes], path: Optional[str]) -> Optional[str]:
    if data is None and path and os.path.exists(path):
        data = Path(path).read_bytes()
    if not data:
        return None
    mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _esc(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _value(player: dict, key: str, *aliases, default=0):
    for name in (key, *aliases):
        if player.get(name) is not None:
            return player[name]
    return default


def _number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(" ", "").replace("₽", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _rub(value) -> str:
    amount = _number(value)
    sign = "−" if amount < 0 else ""
    amount = abs(amount)
    result = f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"
    return sign + result.replace(",", " ").replace(".", ",")


def _percent(value) -> str:
    amount = _number(value)
    return str(int(amount)) if amount.is_integer() else f"{amount:.2f}".rstrip("0").rstrip(".")


def _progress(value) -> tuple[float, str]:
    amount = _number(value)
    if 0 <= amount <= 1:
        amount *= 100
    amount = float(max(0.0, min(100.0, amount)))
    return amount, (str(int(amount)) if amount.is_integer() else f"{amount:.1f}")


def _next_cashback_at(now: Optional[datetime] = None) -> datetime:
    current = (datetime.now(MSK) if now is None else
               (now.replace(tzinfo=MSK) if now.tzinfo is None else now.astimezone(MSK)))
    candidate = current.replace(hour=6, minute=0, second=0, microsecond=0)
    candidate += timedelta(days=(7 - current.weekday()) % 7)
    return candidate if candidate > current else candidate + timedelta(days=7)


def _countdown(now: Optional[datetime] = None) -> str:
    current = datetime.now(MSK) if now is None else now.astimezone(MSK)
    seconds = max(0, int((_next_cashback_at(current) - current).total_seconds()))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return f"{days} д · {hours:02d} ч · {minutes:02d} мин"


def _build_html(player: dict, avatar_uri: Optional[str], logo_uri: Optional[str]) -> str:
    name_raw = _value(player, "name", "player_name", default="Игрок")
    name, initial = _esc(name_raw), _esc(str(name_raw).strip()[:1].upper() or "F")
    username_raw = _value(player, "username", "user_name", default="")
    username = str(username_raw)
    username = username if username.startswith("@") else ("@" + username if username else "")
    username_html = f'<div class="username">{_esc(username)}</div>' if username else ""
    balance = _rub(_value(player, "balance_rub", "balance"))
    turnover = _rub(_value(player, "weekly_bet_turnover_rub", "weekly_turnover_rub"))
    loss = _rub(_value(player, "weekly_eligible_loss_rub", "eligible_loss_rub"))
    level = _esc(_value(player, "cashback_level", default="—"))
    rate = _percent(_value(player, "cashback_percent"))
    cashback = _rub(_value(player, "expected_cashback_rub", "cashback_rub"))
    rollover = _rub(_value(player, "rollover_remaining_rub", "required_rollover_rub"))
    progress, progress_label = _progress(_value(player, "progress_to_next_level", "next_level_progress_percent"))
    next_level = _esc(_value(player, "next_cashback_level", default="следующего уровня"))
    countdown = _countdown()
    logo = f'<img class="logo" src="{logo_uri}" alt="FocusPay">' if logo_uri else '<b class="logo-fallback">F</b>'
    avatar = f'<img class="avatar" src="{avatar_uri}" alt="">' if avatar_uri else f'<div class="avatar avatar-fallback">{initial}</div>'

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}:root{{--white:#f7f7f5;--muted:#a2a2a0;--dim:#686866;--line:rgba(255,255,255,.07);--glass:rgba(42,42,41,.68);--glass-hi:rgba(58,58,56,.72);--cyan:#66e6dc;--orange:#ff9d55;--radius:24px}}
html,body{{width:{W}px;height:{H}px}}body{{overflow:hidden;color:var(--white);background:#050505;font-family:Inter,Arial,sans-serif;letter-spacing:-.015em}}
body:before{{content:"";position:absolute;inset:-120px;background:radial-gradient(circle at 86% 0,rgba(255,255,255,.12),transparent 25%),radial-gradient(circle at 12% 45%,rgba(255,255,255,.055),transparent 27%),radial-gradient(circle at 80% 100%,rgba(255,255,255,.07),transparent 30%);filter:blur(38px)}}
body:after{{content:"";position:absolute;inset:0;opacity:.085;background:linear-gradient(rgba(255,255,255,.16) 1px,transparent 1px) 0 0/64px 64px,linear-gradient(90deg,rgba(255,255,255,.16) 1px,transparent 1px) 0 0/64px 64px;mask-image:radial-gradient(ellipse at center,#000 0%,rgba(0,0,0,.8) 55%,transparent 94%);-webkit-mask-image:radial-gradient(ellipse at center,#000 0%,rgba(0,0,0,.8) 55%,transparent 94%)}}
.wrap{{position:relative;z-index:1;height:100%;padding:36px 42px 30px;display:flex;flex-direction:column;gap:20px}}
.header{{display:flex;justify-content:space-between;align-items:center;padding-bottom:16px;border-bottom:1px solid var(--line)}}.brand{{display:flex;align-items:center;gap:13px}}.logo{{width:38px;height:38px;filter:drop-shadow(0 0 10px rgba(255,255,255,.25))}}.logo-fallback{{font-size:34px}}.brand-name{{font-size:23px;font-weight:700}}.brand-sub{{color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase;margin-top:2px}}.edition{{color:var(--dim);font-size:10px;letter-spacing:.12em;text-transform:uppercase;text-align:right}}.edition strong{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}
.hero{{display:grid;grid-template-columns:1fr 340px;gap:20px}}.profile,.tier,.metric,.payout{{border:1px solid var(--line);background:var(--glass);-webkit-backdrop-filter:blur(30px) saturate(150%);backdrop-filter:blur(30px) saturate(150%);box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 18px 48px rgba(0,0,0,.36)}}.profile{{display:flex;align-items:center;gap:18px;padding:22px 4px;border:0;background:transparent;box-shadow:none;backdrop-filter:none;-webkit-backdrop-filter:none}}.avatar{{width:82px;height:82px;flex:none;object-fit:cover;border-radius:50%;border:1px solid rgba(255,255,255,.28);background:rgba(255,255,255,.08);box-shadow:0 10px 28px rgba(0,0,0,.42),0 0 0 5px rgba(255,255,255,.025)}}.avatar-fallback{{display:flex;align-items:center;justify-content:center;font-size:38px;font-weight:600;background:radial-gradient(circle at 35% 25%,rgba(255,255,255,.22),rgba(255,255,255,.04) 65%)}}.eyebrow,.metric-label,.tier-label,.payout-label{{color:var(--muted);font-size:10px;letter-spacing:.10em;text-transform:uppercase}}.pname{{font-size:34px;font-weight:650;line-height:1;margin-top:6px}}.username{{color:#b8b8b4;font-size:15px;margin-top:7px}}.status{{color:var(--muted);font-size:11px;margin-top:9px}}.status i{{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 9px var(--cyan);margin-right:6px}}
 .tier{{padding:20px;border-radius:var(--radius);background:linear-gradient(145deg,rgba(255,255,255,.10),rgba(255,255,255,.025))}}.tier-value{{font-size:27px;font-weight:700;margin:9px 0 12px}}.tier-value small{{color:var(--cyan);font-size:16px;font-weight:600;margin-left:5px}}.progress{{height:6px;border-radius:99px;background:rgba(255,255,255,.10);overflow:hidden}}.progress span{{display:block;height:100%;width:{progress:.2f}%;background:linear-gradient(90deg,var(--cyan),#fff);box-shadow:0 0 13px rgba(102,230,220,.65)}}.progress-meta{{display:flex;justify-content:space-between;color:var(--dim);font-size:10px;margin-top:7px}}.progress-meta b{{color:var(--muted);font-weight:500}}
 .section{{display:flex;align-items:center;gap:10px;color:var(--dim);font-size:10px;letter-spacing:.13em;text-transform:uppercase}}.section:after{{content:"";height:1px;flex:1;background:var(--line)}}.metrics{{display:grid;grid-template-columns:1.35fr 1fr 1fr 1fr;gap:12px}}.metric{{min-width:0;padding:16px;border-radius:18px}}.metric:first-child{{background:linear-gradient(135deg,rgba(255,255,255,.11),rgba(255,255,255,.035))}}.metric-value{{font-size:24px;font-weight:650;margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}}.metric:first-child .metric-value{{font-size:31px}}.currency{{color:var(--muted);font-size:15px;font-weight:500;margin-left:3px}}
 .payout{{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:20px 24px;border-radius:24px;background:linear-gradient(105deg,rgba(255,255,255,.16),rgba(255,255,255,.045) 60%,rgba(255,255,255,.11));border-color:rgba(255,255,255,.20);box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 22px 60px rgba(0,0,0,.42),0 0 50px rgba(255,255,255,.07)}}.payout-main{{font-size:38px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}}.payout-main .currency{{font-size:19px}}.payout-right{{text-align:right}}.countdown{{font-size:27px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}}.payout-note{{color:var(--muted);font-size:11px;margin-top:4px}}
</style></head><body><div class="wrap">
<div class="header"><div class="brand">{logo}<div><div class="brand-name">FocusPay</div><div class="brand-sub">Профиль игрока</div></div></div><div class="edition">Расчётный период<strong>МСК · понедельник 06:00</strong></div></div>
<div class="hero"><div class="profile">{avatar}<div><div class="eyebrow">Личный профиль</div><div class="pname">{name}</div>{username_html}<div class="status"><i></i>Аккаунт активен</div></div></div><div class="tier"><div class="tier-label">Уровень кешбэка</div><div class="tier-value">{level}<small>{_esc(rate)}%</small></div><div class="progress"><span></span></div><div class="progress-meta"><span>До {next_level}</span><b>{_esc(progress_label)}%</b></div></div></div>
<div class="section">Показатели за неделю</div><div class="metrics"><div class="metric"><div class="metric-label">Доступный баланс</div><div class="metric-value">{_esc(balance)}<span class="currency">₽</span></div></div><div class="metric"><div class="metric-label">Оборот ставок</div><div class="metric-value">{_esc(turnover)}<span class="currency">₽</span></div></div><div class="metric"><div class="metric-label">Учтённый проигрыш</div><div class="metric-value">{_esc(loss)}<span class="currency">₽</span></div></div><div class="metric"><div class="metric-label">Нужно поставить</div><div class="metric-value">{_esc(rollover)}<span class="currency">₽</span></div></div></div>
<div class="payout"><div><div class="payout-label">Ожидаемый кешбэк</div><div class="payout-main">{_esc(cashback)}<span class="currency">₽</span></div></div><div class="payout-right"><div class="payout-label">Начисление через</div><div class="countdown">{_esc(countdown)}</div><div class="payout-note">Ближайший понедельник · 06:00 МСК</div></div></div>
</div></body></html>"""


def render_profile_card(player: dict, avatar_bytes: Optional[bytes] = None, photo_path: Optional[str] = None) -> bytes:
    browser = _find_browser()
    if browser is None:
        raise RuntimeError("Не найден Chrome/Chromium. Укажите CHROME_PATH.")
    html = _build_html(player, _avatar_uri(avatar_bytes, photo_path), _data_uri(LOGO_SVG))
    work_dir, tag = _work_dir(), uuid.uuid4().hex
    html_path, png_path, profile_dir = (work_dir / f"fp_{tag}.{ext}" for ext in ("html", "png", "profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    cmd = [browser,"--headless=new","--disable-gpu","--disable-dev-shm-usage","--hide-scrollbars","--no-sandbox","--no-first-run","--disable-extensions",f"--user-data-dir={profile_dir}",f"--force-device-scale-factor={SCALE}",f"--window-size={W},{H}",f"--screenshot={png_path}",f"file:///{str(html_path).replace(os.sep,'/')}"]
    env = _browser_env(str(profile_dir))
    try:
        proc = subprocess.run(cmd, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, cwd=str(work_dir))
        if not png_path.exists():
            raise RuntimeError(f"Chrome не создал карточку (exit {proc.returncode}). {(proc.stderr or b'').decode(errors='replace')[-500:]}")
        return png_path.read_bytes()
    finally:
        for path in (html_path, png_path):
            try: path.unlink()
            except OSError: pass
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    demo = {"name":"Барсег","username":"@barseg","balance_rub":1240.50,"weekly_bet_turnover_rub":18750,"weekly_eligible_loss_rub":3400,"cashback_level":"Gold","cashback_percent":7,"next_cashback_level":"Platinum","expected_cashback_rub":238,"rollover_remaining_rub":12600,"progress_to_next_level":.68}
    out = Path(__file__).resolve().parent / "profile_demo.png"
    out.write_bytes(render_profile_card(demo))
    print(f"Сохранено: {out}")
