"""
Генерация PNG-карточки профиля FocusPay через HTML/CSS → headless Chromium.

render_profile_card(user: dict, avatar_bytes: bytes | None = None) -> bytes
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess  # nosec B404
import tempfile
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
LOGO_SVG = _ASSETS / "logo_f.svg"
W, H = 1000, 640
SCALE = 2


def _find_browser() -> Optional[str]:
    env = os.getenv("CHROME_PATH")
    if env and os.path.exists(env):
        return env

    # Google Chrome (.deb) предпочтительнее snap-wrapper и «голого» chrome из snap
    # (у того нет системных .so без snap-окружения).
    candidates: list[str] = [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/chromium/current/usr/lib/chromium-browser/chrome",
        "/snap/bin/chromium",
    ]
    which = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if which:
        candidates.insert(0, which)
    # Не предпочитаем /snap/bin/chromium (wrapper) — только если нет реального chrome.
    which_cr = shutil.which("chromium") or shutil.which("chromium-browser")
    if which_cr and "/snap/bin/" not in which_cr:
        candidates.insert(0, which_cr)

    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    candidates.extend(
        [
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
        ]
    )
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def browser_available() -> bool:
    return _find_browser() is not None


def _logo_data_uri() -> Optional[str]:
    if not LOGO_SVG.exists():
        return None
    try:
        svg = LOGO_SVG.read_text(encoding="utf-8")
    except OSError:
        return None
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _avatar_data_uri(
    avatar_bytes: Optional[bytes], photo_path: Optional[str]
) -> Optional[str]:
    data = avatar_bytes
    if data is None and photo_path and os.path.exists(photo_path):
        with open(photo_path, "rb") as f:
            data = f.read()
    if not data:
        return None
    # Telegram отдаёт JPEG; если байты — PNG/WebP, браузер всё равно отрисует
    # при image/jpeg в большинстве случаев. Определяем по сигнатуре.
    mime = "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_html(
    user: dict, avatar_uri: Optional[str], logo_uri: Optional[str]
) -> str:
    name = _esc(user.get("name", "Пользователь"))
    initial = _esc((str(user.get("name", "F")).strip()[:1] or "F").upper())
    uid = _esc(user.get("user_id", "—"))
    balance = _esc(f"{user.get('balance', 0):,.2f}".replace(",", " "))
    cashback = _esc(user.get("cashback_percent", 5))
    tickets = _esc(user.get("tickets", 0))
    deals = _esc(user.get("deals_done", 0))

    logo_html = (
        f'<img class="logo" src="{logo_uri}" alt="F">'
        if logo_uri
        else '<div class="logo logo--txt">F</div>'
    )
    avatar_html = (
        f'<img class="ava" src="{avatar_uri}" alt="">'
        if avatar_uri
        else f'<div class="ava ava--initial">{initial}</div>'
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  :root {{
    --text:#f5f5f7; --muted:#a1a1aa;
    --glass:rgba(255,255,255,.07);
    --glass-strong:rgba(255,255,255,.12);
    --stroke:rgba(255,255,255,.16);
    --stroke-hi:rgba(255,255,255,.30);
  }}
  html,body {{ width:{W}px; height:{H}px; }}
  body {{
    position:relative; overflow:hidden;
    background:
      linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px) 0 0 / 48px 48px,
      linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px) 0 0 / 48px 48px,
      #0a0a0c;
    font-family:"SF Pro Display","SF Pro Text",-apple-system,
                "Inter","Segoe UI",system-ui,sans-serif;
    color:var(--text);
    -webkit-font-smoothing:antialiased;
    letter-spacing:-0.01em;
  }}
  body::before, body::after {{
    content:""; position:absolute; border-radius:50%; filter:blur(90px);
  }}
  body::before {{
    width:560px; height:560px; top:-220px; left:-160px;
    background:radial-gradient(circle,rgba(255,255,255,.22),transparent 70%);
  }}
  body::after {{
    width:520px; height:520px; bottom:-240px; right:-140px;
    background:radial-gradient(circle,rgba(255,255,255,.14),transparent 70%);
  }}
  .wrap {{
    position:relative; z-index:1; height:100%;
    padding:52px 56px;
    display:flex; flex-direction:column; justify-content:space-between;
  }}
  .brand {{ display:flex; align-items:center; gap:16px; }}
  .logo {{ width:44px; height:44px; display:block; }}
  .logo--txt {{
    font-size:40px; font-weight:800; line-height:44px; text-align:center;
  }}
  .brand .name {{ font-size:30px; font-weight:700; }}
  .brand .sub {{ font-size:15px; color:var(--muted); margin-top:2px;
                 letter-spacing:.04em; text-transform:uppercase; }}
  .profile {{ display:flex; align-items:center; gap:28px; }}
  .ava {{
    width:132px; height:132px; border-radius:50%;
    object-fit:cover; flex:none;
    border:1px solid var(--stroke-hi);
    box-shadow:0 12px 40px rgba(0,0,0,.5),
               inset 0 1px 0 rgba(255,255,255,.25);
    background:var(--glass-strong);
    -webkit-backdrop-filter:blur(30px) saturate(180%);
    backdrop-filter:blur(30px) saturate(180%);
  }}
  .ava--initial {{
    display:flex; align-items:center; justify-content:center;
    font-size:58px; font-weight:700;
  }}
  .who .pname {{ font-size:46px; font-weight:700; line-height:1.05; }}
  .who .pid {{ font-size:23px; color:var(--muted); margin-top:8px; }}
  .pill {{
    display:inline-flex; align-items:center; gap:8px; margin-top:16px;
    padding:9px 18px; border-radius:100px;
    background:var(--glass-strong); border:1px solid var(--stroke);
    -webkit-backdrop-filter:blur(20px) saturate(180%);
    backdrop-filter:blur(20px) saturate(180%);
    font-size:18px; font-weight:500;
  }}
  .pill .dot {{ width:9px; height:9px; border-radius:50%; background:#fff;
                box-shadow:0 0 10px rgba(255,255,255,.9); }}
  .grid {{
    display:grid; grid-template-columns:1fr 1fr;
    gap:22px;
  }}
  .tile {{
    padding:22px 26px; border-radius:26px;
    background:var(--glass); border:1px solid var(--stroke);
    -webkit-backdrop-filter:blur(30px) saturate(180%);
    backdrop-filter:blur(30px) saturate(180%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.14),
               0 10px 30px rgba(0,0,0,.35);
  }}
  .tile .lbl {{ font-size:15px; color:var(--muted);
                text-transform:uppercase; letter-spacing:.09em;
                font-weight:500; }}
  .tile .val {{ font-size:38px; font-weight:700; margin-top:8px;
                letter-spacing:-0.02em; }}
  .tile .val .cur {{ font-size:26px; font-weight:600; color:var(--muted);
                     margin-left:4px; }}
  .foot {{
    display:flex; align-items:baseline; justify-content:space-between;
    padding-top:16px; border-top:1px solid var(--stroke);
  }}
  .foot .fitem {{ display:flex; align-items:baseline; gap:10px; }}
  .foot .flbl {{
    font-size:14px; color:var(--muted);
    text-transform:uppercase; letter-spacing:.10em; font-weight:500;
  }}
  .foot .fval {{ font-size:20px; color:var(--text); font-weight:600; }}
</style></head>
<body>
  <div class="wrap">
    <div class="brand">
      {logo_html}
      <div>
        <div class="name">FocusPay</div>
        <div class="sub">crypto&nbsp;exchange</div>
      </div>
    </div>

    <div class="profile">
      {avatar_html}
      <div class="who">
        <div class="pname">{name}</div>
        <div class="pid">ID&nbsp;{uid}</div>
        <div class="pill"><span class="dot"></span>FocusPay&nbsp;client</div>
      </div>
    </div>

    <div class="grid">
      <div class="tile"><div class="lbl">Баланс</div>
        <div class="val">{balance}<span class="cur">₽</span></div></div>
      <div class="tile"><div class="lbl">Кешбэк</div>
        <div class="val">{cashback}<span class="cur">%</span></div></div>
      <div class="tile"><div class="lbl">Билеты</div>
        <div class="val">{tickets}</div></div>
      <div class="tile"><div class="lbl">Обмены</div>
        <div class="val">{deals}</div></div>
    </div>

    <div class="foot">
      <div class="fitem">
        <span class="flbl">Сайт</span>
        <span class="fval">focuspay.org</span>
      </div>
      <div class="fitem">
        <span class="flbl">Оператор</span>
        <span class="fval">@focus_operator</span>
      </div>
    </div>
  </div>
</body></html>"""


def render_profile_card(
    user: dict,
    avatar_bytes: Optional[bytes] = None,
    photo_path: Optional[str] = None,
) -> bytes:
    """Рендерит карточку профиля (HTML→Chrome) и возвращает PNG bytes."""
    browser = _find_browser()
    if browser is None:
        raise RuntimeError(
            "Не найден Chrome/Chromium для рендера карточки. "
            "Укажите путь в CHROME_PATH."
        )

    html = _build_html(
        user,
        _avatar_data_uri(avatar_bytes, photo_path),
        _logo_data_uri(),
    )

    tmp = tempfile.gettempdir()
    tag = uuid.uuid4().hex
    html_path = os.path.join(tmp, f"fp_card_{tag}.html")
    png_path = os.path.join(tmp, f"fp_card_{tag}.png")
    profile_dir = os.path.join(tmp, f"fp_chrome_profile_{tag}")
    os.makedirs(profile_dir, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-component-update",
        "--disable-features=Translate,OptimizationHints,MediaRouter",
        "--metrics-recording-only",
        "--mute-audio",
        f"--user-data-dir={profile_dir}",
        f"--force-device-scale-factor={SCALE}",
        f"--window-size={W},{H}",
        f"--screenshot={png_path}",
        f"file:///{html_path.replace(os.sep, '/')}",
    ]

    # Snap Chromium пишет в $HOME/snap — у сервиса focuspay HOME может
    # указывать на каталог без прав записи. Даём временный HOME.
    env = os.environ.copy()
    env["HOME"] = profile_dir
    env["XDG_CONFIG_HOME"] = os.path.join(profile_dir, ".config")
    env["XDG_CACHE_HOME"] = os.path.join(profile_dir, ".cache")
    os.makedirs(env["XDG_CONFIG_HOME"], exist_ok=True)
    os.makedirs(env["XDG_CACHE_HOME"], exist_ok=True)

    try:
        proc = subprocess.run(  # nosec B603
            cmd,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            cwd=tmp,
        )
        if not os.path.exists(png_path):
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"Chrome не создал карточку (exit {proc.returncode}). "
                f"Вывод: {err[-500:] or '—'}"
            )
        with open(png_path, "rb") as f:
            return f.read()
    finally:
        for p in (html_path, png_path):
            try:
                os.remove(p)
            except OSError:
                pass
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    demo = {
        "name": "Барсег",
        "user_id": 100500,
        "balance": 1240.50,
        "cashback_percent": 7,
        "tickets": 4,
        "deals_done": 7,
    }
    out = Path(__file__).resolve().parent.parent / "assets" / "profile_demo.png"
    out.write_bytes(render_profile_card(demo))
    print(f"Сохранено: {out}")
