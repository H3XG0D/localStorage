"""Telegram handlers for the FocusVPN bot.

Screens edit one message: home -> plans -> confirm -> result, devices -> unbind.
Money and gates are FocusPay's (fp_*); days and devices are the control plane's (mv_*).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot import api, config, reviews, ui

log = logging.getLogger("focusvpn-tg")

MSK = ZoneInfo("Europe/Moscow")
BAR_WIDTH = 10
PLATFORMS = {
    "android": "Android",
    "ios": "iOS",
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
    "link": "ссылка",
}


def download_url(st: dict | None = None) -> str:
    """Public APK link from the admin field; env is only the fallback when that field is empty."""
    url = str((st or {}).get("app_url") or "").strip()
    return url or config.VPN_CLIENT_DOWNLOAD_URL


def subscription_active(st: dict | None) -> bool:
    sub = (st or {}).get("subscription") or {}
    return bool(sub.get("active"))


def apk_button() -> InlineKeyboardButton:
    """Sends the APK into the chat. A URL button opens Telegram's browser, which does not save APKs."""
    return ui.button("Получить APK", "apk", "download", "success")


def apk_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_apk_file_id(cache_path: Path, sha: str) -> str:
    try:
        raw = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(raw, dict) or raw.get("sha256") != sha:
        return ""
    return str(raw.get("file_id") or "")


def store_apk_file_id(cache_path: Path, sha: str, file_id: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"sha256": sha, "file_id": file_id}))


_apk_lock = asyncio.Lock()


async def send_apk(message, st: dict | None = None) -> None:
    """Put FocusVPN.apk in the chat. The first send uploads it; later ones reuse Telegram's file id."""
    url = download_url(st)
    path = Path(config.VPN_APK_PATH)
    if message is None:
        return
    if not path.is_file():
        await ui.reply_html(
            message,
            ui.screen(
                "Не получилось",
                "<blockquote>Файл приложения сейчас недоступен. Откройте ссылку в Chrome:\n"
                f"{html.escape(url)}</blockquote>",
                "download",
            ),
        )
        return
    caption = (
        "FocusVPN для Android. Откройте файл и разрешите установку.\n\n"
        "Если файл не сохранился, откройте ссылку в Chrome:\n" + url
    )
    timeouts = {"read_timeout": 60, "write_timeout": 180, "connect_timeout": 30, "pool_timeout": 30}
    try:
        async with _apk_lock:
            sha = await asyncio.to_thread(apk_sha256, path)
            cache_path = Path(config.VPN_APK_FILE_ID_PATH)
            file_id = load_apk_file_id(cache_path, sha)
            sent = None
            if file_id:
                try:
                    sent = await message.reply_document(document=file_id, filename="FocusVPN.apk", caption=caption, **timeouts)
                except TelegramError:
                    log.warning("cached apk file_id rejected, uploading again")
                    sent = None
            if sent is None:
                sent = await message.reply_document(document=path, filename="FocusVPN.apk", caption=caption, **timeouts)
                new_id = sent.document.file_id if sent.document else ""
                if new_id:
                    try:
                        store_apk_file_id(cache_path, sha, new_id)
                    except OSError:
                        log.warning("could not store apk file_id")
    except (TelegramError, OSError):
        log.exception("apk send failed")
        await ui.reply_html(
            message,
            ui.screen(
                "Не получилось",
                "<blockquote>Не удалось отправить файл в чат. Откройте ссылку в Chrome:\n"
                f"{html.escape(url)}</blockquote>",
                "download",
            ),
        )


# --- formatting -----------------------------------------------------------------


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_date(value: Any) -> str:
    dt = _parse(value)
    return dt.astimezone(MSK).strftime("%d.%m.%Y · %H:%M МСК") if dt else "—"


def fmt_rub(value: Any) -> str:
    v = float(value or 0)
    text = f"{v:,.2f}".replace(",", " ")
    return text[:-3] if text.endswith(".00") else text


def plural_days(n: int) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


def plural_invited(n: int) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} приглашённый"
    return f"{n} приглашённых"


def plural_exchanges(n: int) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} обмен"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} обмена"
    return f"{n} обменов"


def progress_bar(have: int, need: int, width: int = BAR_WIDTH) -> str:
    if need <= 0:
        return "▰" * width
    filled = min(width, max(0, have) * width // need)
    return "▰" * filled + "▱" * (width - filled)


def gate_text(need: int, have: int, invited_need: int = 30, invited_have: int = 0) -> str:
    left = max(0, need - have)
    return (
        "<b>Покупка откроется так</b>\n"
        f"Либо {plural_exchanges(need)} в FocusPay, либо {plural_invited(invited_need)}.\n"
        f"Обмены: <b>{have} из {need}</b> · осталось {left}\n"
        f"Приглашённые: <b>{invited_have} из {invited_need}</b>"
    )


def _exchanges(st: dict) -> tuple[int, int]:
    ex = st.get("exchanges") or {}
    return int(ex.get("have", 0)), int(ex.get("need", 0))


def _invited(st: dict) -> tuple[int, int]:
    inv = st.get("invited") or {}
    return int(inv.get("have", 0)), int(inv.get("need", 30))


def _gate(st: dict) -> str:
    have, need = _exchanges(st)
    invited_have, invited_need = _invited(st)
    return gate_text(need, have, invited_need, invited_have)


def _slots(st: dict) -> int | None:
    raw = (st.get("devices_limit") or {}).get("max_devices")
    if raw is None:
        return None
    return int(raw)


def home_text(st: dict, first_name: str | None = None, device_count: int | None = None) -> str:
    sub = st.get("subscription") or {}
    who = html.escape(first_name) if first_name else "друг"
    lines = [f"Привет, <b>{who}</b>!", "Ваш личный кабинет подключения.", ""]
    if sub.get("active"):
        trialing = sub.get("status") == "trialing"
        title = "Пробный период" if trialing else "Подписка активна"
        kind = "" if trialing else f" · {_plan_title(st, sub.get('plan'))}"
        lines.append(
            "<blockquote>"
            f"{ui.emoji('check')} <b>{title}</b>{kind}\n"
            f"До {fmt_date(sub.get('ends_at'))}\n"
            f"Осталось дней: <b>{int(sub.get('days_left', 0))}</b></blockquote>"
        )
    else:
        lines.append(
            "<blockquote>⏸ <b>Подписки нет</b>\n"
            "VPN в приложении не подключится.</blockquote>"
        )
    lines.append("")
    lines.append(f"{ui.emoji('wallet')} Баланс <b>{fmt_rub(st.get('available_rub'))} ₽</b>")
    if device_count is not None:
        slots = _slots(st)
        shown = f"{device_count} / {slots}" if slots else str(device_count)
        lines.append(f"{ui.emoji('device')} Устройства <b>{shown}</b>")
    lines.append("")
    if sub.get("active") and st.get("purchase_open"):
        lines.append("<i>Продлевайте в любой момент — оставшиеся дни сохранятся.</i>")
    elif not sub.get("active"):
        lines.append("<i>Скачать приложение можно после активации подписки или пробного периода.</i>")
    extra = reviews.home_line(st)
    if extra:
        lines.append("")
        lines.append(extra)
    return ui.screen("FocusVPN", "\n".join(lines))


def _plan_title(st: dict, code: str | None) -> str:
    for p in st.get("plans") or []:
        if p.get("code") == code:
            return str(p.get("title") or code)
    return str(code or "тариф")


def home_keyboard(st: dict) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if st.get("trial_available"):
        days = int((st.get("trial") or {}).get("days", 1))
        rows.append([ui.button(f"Попробовать бесплатно · {plural_days(days)}", "trial", style="success")])
    rows.append([ui.button("Продлить подписку", "plans", "card", "success")])
    rows.append([ui.button("Устройства", "devices", "device")])
    rows.append([
        ui.button("Код входа", "app_code", "key"),
        ui.button("Ключ ссылкой", "sub_link", "key"),
    ])
    rows.append([ui.button("Скачать приложение", "download", "download")])
    rows.append([
        ui.button("Как подключиться", "guide", "info"),
        ui.button("Баланс", "balance", "wallet"),
    ])
    rows.append([ui.button("Отзывы", "reviews", "review")])
    rows.append([ui.button("Обновить", "home", "refresh", style=None)])
    return InlineKeyboardMarkup(rows)


def guide_text(platform: str = "android") -> str:
    if platform in {"windows", "macos"}:
        name = "Windows" if platform == "windows" else "macOS"
        body = (
            f"<b>{name}</b>\n\n"
            "В FocusVPN входите кодом из «Код входа». Файл для этой платформы бот пока не присылает.\n\n"
            "<blockquote>Happ и похожие клиенты берут ключ ссылкой — кнопка ниже.</blockquote>"
        )
    elif platform == "iphone":
        body = (
            "<b>iPhone</b>\n\n"
            "<b>01 · Поставьте клиент</b>\n"
            "Happ, INCY или другое приложение, которое добавляет подписку по ссылке.\n\n"
            "<b>02 · Вставьте ключ</b>\n"
            "Откройте «Ключ ссылкой» и вставьте ссылку в клиент.\n\n"
            "<b>03 · Подключитесь</b>\n"
            "Нажмите подключить.\n\n"
            "<blockquote>В FocusVPN входите кодом. "
            "В Happ и похожих клиентах ключ — ссылка.</blockquote>"
        )
    else:
        body = (
            "<b>Android</b> · три шага\n\n"
            "<b>01 · Установите приложение</b>\n"
            "Когда подписка или пробный период активны, откройте «Скачать приложение» — бот пришлёт файл FocusVPN.apk. "
            "Разрешите установку.\n\n"
            "<b>02 · Войдите в аккаунт</b>\n"
            "Откройте приложение и войдите: «Войти через Telegram» или кодом из кнопки «Код входа».\n\n"
            "<b>03 · Подключитесь</b>\n"
            "На вкладке «Подключение» выберите локацию и нажмите «Подключить».\n\n"
            "<blockquote><b>Как идёт трафик</b>\n"
            "Нужна живая подписка или пробный период. Российские сайты открываются с IP телефона, "
            "зарубежные — через VPN.</blockquote>"
        )
    return ui.screen("Подключение без лишних шагов", body, "info")


def _platform_tab(label: str, key: str, selected: str) -> InlineKeyboardButton:
    return ui.button(label, f"guide:{key}", style="primary" if selected == key else None)


def guide_keyboard(_st: dict | None = None, platform: str = "android") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_platform_tab("Android", "android", platform), _platform_tab("iPhone", "iphone", platform)],
        [_platform_tab("Windows", "windows", platform), _platform_tab("macOS", "macos", platform)],
        [ui.button("Скачать приложение", "download", "download")],
    ]
    if platform == "iphone":
        rows.append([ui.button("Ключ ссылкой", "sub_link", "key")])
    elif platform in {"windows", "macos"}:
        rows.append([
            ui.button("Код входа", "app_code", "key"),
            ui.button("Ключ ссылкой", "sub_link", "key"),
        ])
    else:
        rows.append([ui.button("Код входа", "app_code", "key")])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def back_row(target: str = "home", label: str | None = None) -> list[InlineKeyboardButton]:
    return ui.back_row(target, label)


def download_text(st: dict) -> str:
    if subscription_active(st):
        android = "Бот пришлёт файл FocusVPN.apk. Разрешите установку."
    else:
        android = "Файл откроется после активации подписки или пробного периода."
    body = (
        f"<blockquote><b>Android</b>\n{android}</blockquote>\n\n"
        "<b>Ключ ссылкой</b>\n"
        "Для Happ и похожих клиентов. Кнопка «Ключ ссылкой» в меню.\n\n"
        "<b>Windows · macOS</b>\n"
        "<i>В FocusVPN входите кодом. Файл для них бот пока не присылает. "
        "Вкладки — в «Как подключиться».</i>"
    )
    return ui.screen("Приложение", body, "download")


def download_keyboard(st: dict) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if subscription_active(st):
        rows.append([apk_button()])
    elif st.get("trial_available"):
        days = int((st.get("trial") or {}).get("days", 1))
        rows.append([ui.button(f"Попробовать бесплатно · {plural_days(days)}", "trial", style="success")])
    rows.append([ui.button("Как подключиться", "guide", "info")])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def balance_text(st: dict) -> str:
    body = (
        "<blockquote>Доступно на балансе FocusPay\n"
        f"<b>{fmt_rub(st.get('available_rub'))} ₽</b></blockquote>\n\n"
        "С этого баланса оплачиваются подписка и дополнительные устройства.\n\n"
        "<i>Пополнение — в боте FocusPay.</i>"
    )
    return ui.screen("Ваш баланс", body, "wallet")


def balance_keyboard(st: dict | None = None) -> InlineKeyboardMarkup:
    del st
    rows = [[ui.button("Пополнить в FocusPay", url=config.FOCUSPAY_BOT_URL, icon="wallet", style="success")]]
    rows.append([ui.button("Продлить подписку", "plans", "card")])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def locked_text(st: dict) -> str:
    lines = [f"<blockquote>{_gate(st)}</blockquote>", "", "<b>Что откроется:</b>", ""]
    lines += [plan_card(p) for p in st.get("plans") or []]
    if st.get("trial_available"):
        lines.append("<i>Пока можно пользоваться пробным периодом.</i>")
    return ui.screen("Тарифы пока закрыты", "\n".join(lines), "card")


def locked_keyboard(st: dict) -> InlineKeyboardMarkup:
    rows = [[ui.button("Обмен в FocusPay", url=config.FOCUSPAY_BOT_URL, icon="wallet")]]
    if st.get("trial_available"):
        rows.append([ui.button("Попробовать бесплатно", "trial", style="success")])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def highlighted_code(plans: list[dict]) -> str | None:
    """Green button goes to the plan with the largest admin discount."""
    best = None
    best_discount = 0
    for p in plans:
        discount = int(p.get("discount_pct") or 0)
        if discount > best_discount:
            best = p.get("code")
            best_discount = discount
    return str(best) if best else None


def plan_card(p: dict, star: bool = False) -> str:
    discount = int(p.get("discount_pct") or 0)
    title = html.escape(str(p["title"]))
    head = f"{ui.emoji('star')} <b>{title}</b>" if star else f"<b>{title}</b>"
    mark = f" · <b>−{discount}%</b>" if discount > 0 else ""
    return (
        f"{head}{mark}\n"
        f"<blockquote><b>{fmt_rub(p['price_rub'])} ₽</b> · {plural_days(int(p['days']))}\n"
        f"{fmt_rub(p.get('per_day_rub'))} ₽ в день</blockquote>"
    )


def plans_text(st: dict) -> str:
    plans = st.get("plans") or []
    star = highlighted_code(plans)
    body = (
        f"На балансе <b>{fmt_rub(st.get('available_rub'))} ₽</b>\n"
        "В тариф включено одно устройство.\n\n"
        + "\n".join(plan_card(p, p.get("code") == star) for p in plans)
        + "\n<i>Дни добавятся к текущему сроку. Сначала покажем подтверждение.</i>"
    )
    return ui.screen("Выберите свой ритм", body, "card")


def plans_keyboard(plans: list[dict], nonce: str | None = None) -> InlineKeyboardMarkup:
    """One nonce per rendered menu: repeated taps on the same menu are one purchase."""
    nonce = nonce or secrets.token_hex(6)
    star = highlighted_code(plans)
    rows = []
    for p in plans:
        discount = int(p.get("discount_pct") or 0)
        label = f"{p['title']} · {fmt_rub(p['price_rub'])} ₽" + (f" · −{discount}%" if discount > 0 else "")
        picked = p.get("code") == star
        rows.append([ui.button(
            label,
            f"pick:{p['code']}:{nonce}",
            "star" if picked else None,
            "success" if picked else "primary",
        )])
    rows.append([ui.button("Баланс", "balance", "wallet")])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def new_end(sub: dict, days: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    ends = _parse(sub.get("ends_at")) if sub.get("active") else None
    base = ends if ends and ends > now else now
    return base + timedelta(days=days)


def confirm_text(st: dict, plan: dict) -> str:
    price = float(plan["price_rub"])
    avail = float(st.get("available_rub") or 0)
    body = (
        "<blockquote>"
        f"Тариф <b>{html.escape(str(plan['title']))}</b> · {plural_days(int(plan['days']))}\n"
        f"Спишем с баланса FocusPay: <b>{fmt_rub(price)} ₽</b>\n"
        f"Доступно: {fmt_rub(avail)} ₽\n"
        f"Подписка будет до: <b>{fmt_date(new_end(st.get('subscription') or {}, int(plan['days'])).isoformat())}</b>"
        "</blockquote>\n\n"
        "<i>Проверьте условия перед подтверждением.</i>"
    )
    if avail < price:
        body += f"\n\n⚠️ Не хватает {fmt_rub(price - avail)} ₽ — пополните баланс в FocusPay."
    return ui.screen("Подтвердите действие", body, "info")


def confirm_keyboard(st: dict, plan: dict, nonce: str) -> InlineKeyboardMarkup:
    rows = []
    if float(st.get("available_rub") or 0) >= float(plan["price_rub"]):
        rows.append([ui.button("Подтвердить", f"buy:{plan['code']}:{nonce}", "check", "success")])
    else:
        rows.append([ui.button("Пополнить в FocusPay", url=config.FOCUSPAY_BOT_URL, icon="wallet", style="success")])
    rows.append(ui.back_row("plans", "К тарифам"))
    return InlineKeyboardMarkup(rows)


def device_line(i: int, d: dict) -> str:
    del i
    name = html.escape(str(d.get("name") or "Устройство"))
    platform = PLATFORMS.get(str(d.get("platform") or "").lower(), str(d.get("platform") or ""))
    state = "подключено" if d.get("connected") else "не подключено"
    return (
        f"<blockquote>{ui.emoji('device')} <b>{name}</b> · {platform}\n"
        f"{state}\n"
        f"Добавлено {fmt_date(d.get('created_at'))}</blockquote>"
    )


def _addons(st: dict) -> list[dict]:
    return list(st.get("device_addons") or [])


def _limit(st: dict) -> dict:
    return st.get("devices_limit") or {}


def device_offer_open(st: dict) -> bool:
    """Buy button: a live subscription and at least one priced term."""
    sub = st.get("subscription") or {}
    return bool(sub.get("active")) and bool(_addons(st))


def _addon_title(st: dict, code: str | None) -> str:
    for p in _addons(st):
        if p.get("code") == code:
            return str(p.get("title") or code)
    return str(code or "доп. место")


def seats_line(st: dict) -> str:
    sub = st.get("subscription") or {}
    if not sub.get("active"):
        return ""
    lim = _limit(st)
    extra = list(lim.get("extra_slots") or [])
    base = int(lim.get("base_devices") or 1)
    total = int(lim.get("max_devices") or base + len(extra))
    if not extra:
        return "В подписке одно устройство. Можно докупить ещё — на свой срок, подписка при этом не продлевается."
    bits = [f"{html.escape(_addon_title(st, s.get('plan_code')))} до {fmt_date(s.get('ends_at'))}" for s in extra]
    return f"Мест: <b>{total}</b> (подписка {base} + доп. {len(extra)}). {'; '.join(bits)}."


def devices_text(devices: list[dict], st: dict | None = None) -> str:
    st = st or {}
    if not devices:
        body = (
            "Пока ни одного. Установите приложение FocusVPN и войдите через Telegram "
            "или кодом из этого бота."
        )
    else:
        used = _slots(st)
        head = f"Использовано мест: <b>{len(devices)}" + (f" из {used}" if used else "") + "</b>\n\n"
        body = head + "\n".join(device_line(i, d) for i, d in enumerate(devices, 1))
        body += "\n\n<b>Меняете устройство?</b>\nОтвяжите старое и используйте свободное место."
    seat = seats_line(st)
    if seat:
        body += "\n\n" + seat
    return ui.screen("Ваши устройства", body, "device")


def devices_keyboard(devices: list[dict], st: dict | None = None) -> InlineKeyboardMarkup:
    st = st or {}
    rows = [
        [ui.button(f"Отвязать {str(d.get('name') or 'устройство')[:24]}", f"unbind:{d['id']}", style="danger")]
        for d in devices
    ]
    rows.append([ui.button("Новое устройство", "guide:android", "device", "success")])
    if device_offer_open(st):
        rows.append([ui.button("Ещё устройство", "device_plans", "device")])
    rows.append([
        ui.button("Код входа", "app_code", "key"),
        ui.button("Ключ ссылкой", "sub_link", "key"),
    ])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def device_plans_text(st: dict) -> str:
    sub = st.get("subscription") or {}
    if not sub.get("active"):
        return ui.screen(
            "Ещё одно устройство",
            "Сначала нужна живая подписка. Место само по себе VPN не включает.",
            "device",
        )
    addons = _addons(st)
    if not st.get("purchase_open"):
        lines = [f"<blockquote>{_gate(st)}</blockquote>", "", "<b>Дополнительное устройство:</b>", ""]
        lines += [plan_card(p) for p in addons]
        return ui.screen("Ещё одно устройство", "\n".join(lines), "device")
    star = highlighted_code(addons)
    body = (
        "Срок считается с оплаты и не зависит от конца подписки. Подписка не продлевается.\n"
        f"Баланс FocusPay: <b>{fmt_rub(st.get('available_rub'))} ₽</b>\n\n"
        + "\n".join(plan_card(p, p.get("code") == star) for p in addons)
    )
    return ui.screen("Ещё одно устройство", body, "device")


def device_plans_keyboard(st: dict, nonce: str | None = None) -> InlineKeyboardMarkup:
    if not device_offer_open(st) or not st.get("purchase_open"):
        rows = []
        if not st.get("purchase_open"):
            rows.append([ui.button("Обмен в FocusPay", url=config.FOCUSPAY_BOT_URL, icon="wallet")])
        rows.append(ui.back_row("devices", "К устройствам"))
        return InlineKeyboardMarkup(rows)
    nonce = nonce or secrets.token_hex(6)
    addons = _addons(st)
    star = highlighted_code(addons)
    rows = []
    for p in addons:
        label = f"{p['title']} · {fmt_rub(p['price_rub'])} ₽"
        picked = p.get("code") == star
        rows.append([ui.button(
            label,
            f"dpick:{p['code']}:{nonce}",
            "star" if picked else None,
            "success" if picked else "primary",
        )])
    rows.append(ui.back_row("devices", "К устройствам"))
    return InlineKeyboardMarkup(rows)


def device_seat_end(days: int, now: datetime | None = None) -> datetime:
    """Extra seats start at payment time. They do not stack on the subscription."""
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=days)


def device_confirm_text(st: dict, addon: dict, now: datetime | None = None) -> str:
    price = float(addon["price_rub"])
    avail = float(st.get("available_rub") or 0)
    days = int(addon["days"])
    seats = int(_limit(st).get("max_devices") or 1)
    body = (
        "<blockquote>"
        f"Ещё устройство · <b>{html.escape(str(addon['title']))}</b> · {plural_days(days)}\n"
        f"Спишем с баланса FocusPay: <b>{fmt_rub(price)} ₽</b>\n"
        f"Доступно: {fmt_rub(avail)} ₽\n"
        f"Новое место до: <b>{fmt_date(device_seat_end(days, now).isoformat())}</b>\n"
        f"Станет мест: <b>{seats + 1}</b>\n"
        "Подписка VPN при этом не продлевается."
        "</blockquote>\n\n"
        "<i>Проверьте условия перед подтверждением.</i>"
    )
    if avail < price:
        body += f"\n\n⚠️ Не хватает {fmt_rub(price - avail)} ₽ — пополните баланс в FocusPay."
    return ui.screen("Подтвердите действие", body, "info")


def device_confirm_keyboard(st: dict, addon: dict, nonce: str) -> InlineKeyboardMarkup:
    rows = []
    if float(st.get("available_rub") or 0) >= float(addon["price_rub"]):
        rows.append([ui.button("Подтвердить", f"dbuy:{addon['code']}:{nonce}", "check", "success")])
    else:
        rows.append([ui.button("Пополнить в FocusPay", url=config.FOCUSPAY_BOT_URL, icon="wallet", style="success")])
    rows.append(ui.back_row("device_plans", "К срокам"))
    return InlineKeyboardMarkup(rows)


def device_done_text(res: dict) -> str:
    status = res.get("status")
    if status == "paid":
        body = (
            "Место для ещё одного устройства оплачено.\n"
            f"Оно доступно до <b>{fmt_date(res.get('ends_at'))}</b>.\n"
            "Подписка VPN не продлевалась.\n\n"
            "Войдите в приложении на новом устройстве."
        )
        return ui.screen("Готово", f"<blockquote>{body}</blockquote>", "check")
    if status == "pending":
        body = "Платёж обрабатывается. Место появится в течение пары минут — откройте «Устройства» ещё раз."
        return ui.screen("Готово", f"<blockquote>{body}</blockquote>", "info")
    if status == "released":
        body = "Не удалось выдать место, деньги возвращены на баланс."
    else:
        body = "Не удалось оформить. Попробуйте позже."
    return ui.screen("Не получилось", f"<blockquote>{body}</blockquote>", "info")


def refusal_text(e: api.APIError) -> str:
    d = e.detail
    code = d.get("code")
    if code in ("exchange_gate", "deposit_gate"):
        inner = gate_text(
            int(d.get("need", 0)),
            int(d.get("have", 0)),
            int(d.get("invited_need", 30)),
            int(d.get("invited_have", 0)),
        )
    elif code == "insufficient_funds":
        inner = "Недостаточно средств на балансе FocusPay. Пополните баланс и попробуйте снова."
    elif code == "trial_used":
        inner = "Пробный период уже был использован."
    elif code == "trial_disabled":
        inner = "Пробный период сейчас недоступен."
    elif code == "unknown_plan":
        inner = "Этот срок больше не продаётся. Откройте список ещё раз."
    elif code == "subscription_required":
        inner = "Дополнительное устройство можно докупить только при живой подписке."
    elif e.status == 404 and code == "not_found":
        inner = "Устройство уже отвязано."
    else:
        inner = f"Ошибка: {html.escape(str(d.get('message') or e))}"
    return ui.screen("Не получилось", f"<blockquote>{inner}</blockquote>", "info")


def done_text(res: dict, what: str) -> str:
    status = res.get("status")
    if status == "paid":
        body = (
            f"{what}\nПодписка до <b>{fmt_date(res.get('ends_at'))}</b>\n\n"
            "Откройте приложение и нажмите «Подключить»."
        )
        return ui.screen("Готово", f"<blockquote>{body}</blockquote>", "check")
    if status == "pending":
        body = "Платёж обрабатывается. Дни придут автоматически в течение пары минут — нажмите «Обновить»."
        return ui.screen("Готово", f"<blockquote>{body}</blockquote>", "info")
    if status == "released":
        body = "Не удалось выдать дни, деньги возвращены на баланс."
    else:
        body = "Не удалось оформить. Попробуйте позже."
    return ui.screen("Не получилось", f"<blockquote>{body}</blockquote>", "info")


def reminder_text(rem: dict, st: dict) -> str:
    if rem.get("kind") == "soon":
        ends = _parse(rem.get("ends_at"))
        hours = max(1, int(((ends - datetime.now(timezone.utc)).total_seconds() + 3599) // 3600)) if ends else 0
        what = "Пробный период" if rem.get("status") == "trialing" else "Подписка FocusVPN"
        text = f"{what} закончится через {hours} ч — {fmt_date(rem.get('ends_at'))}."
    else:
        what = "Пробный период закончился" if rem.get("plan_code") == "trial" else "Подписка FocusVPN закончилась"
        text = f"{what}."
    if st.get("purchase_open"):
        text += "\n\nПродлите подписку — дни добавятся сразу."
    else:
        text += "\n\n" + _gate(st)
    return ui.screen("Подписка", f"<blockquote>{text}</blockquote>", "info")


def reminder_keyboard(st: dict) -> InlineKeyboardMarkup:
    if st.get("purchase_open"):
        rows = [[ui.button("Продлить подписку", "plans", "card", "success")]]
    else:
        rows = [[ui.button("Обмен в FocusPay", url=config.FOCUSPAY_BOT_URL, icon="wallet")]]
    rows.append(ui.back_row("home", "В меню"))
    return InlineKeyboardMarkup(rows)


def sub_link_text(url: str, ends_at: Any) -> str:
    body = (
        f"<code>{html.escape(url)}</code>\n\n"
        "<i>Нажмите на ссылку, чтобы скопировать.</i>\n\n"
        "В Happ, INCY, v2rayNG и других клиентах добавьте подписку и вставьте эту ссылку.\n\n"
        f"<blockquote>Действует до {fmt_date(ends_at)}. "
        "Ключ занимает одно место. Отвязка в «Устройства» гасит ссылку. "
        "В FocusVPN входите кодом из «Код входа».</blockquote>"
    )
    return ui.screen("Ключ ссылкой", body, "key")


def sub_link_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [ui.button("Новый ключ", "sub_new", "refresh")],
        [ui.button("Устройства", "devices", "device")],
        ui.back_row(),
    ])


def sub_link_confirm_text() -> str:
    return ui.screen(
        "Новый ключ",
        "<blockquote>Старая ссылка в Happ перестанет открывать VPN. "
        "Нужно будет вставить новую.</blockquote>",
        "key",
    )


def sub_link_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [ui.button("Выдать новый", "sub_new_ok", "check", "success")],
        ui.back_row("sub_link", "Отмена"),
    ])


def _cp_code(e: api.APIError) -> str:
    try:
        body = json.loads(e.body)
    except ValueError:
        return ""
    err = body.get("error")
    if isinstance(err, dict) and err.get("code"):
        return str(err["code"])
    return str((e.detail or {}).get("code") or "")


def sub_link_error_text(e: api.APIError) -> str:
    code = _cp_code(e)
    if code == "no_subscription":
        inner = "Сначала включите пробный период или оплатите подписку."
    elif code == "too_many_devices":
        inner = "Свободного места нет. Ключ занимает одно место, как телефон. Отвяжите устройство или докупите место."
    elif code == "no_nodes":
        inner = "Сейчас нет свободной локации. Попробуйте через минуту."
    else:
        return refusal_text(e)
    return ui.screen("Не получилось", f"<blockquote>{inner}</blockquote>", "info")


def sub_link_error_keyboard(e: api.APIError) -> InlineKeyboardMarkup:
    code = _cp_code(e)
    if code == "too_many_devices":
        return InlineKeyboardMarkup([
            [ui.button("Устройства", "devices", "device")],
            ui.back_row(),
        ])
    if code == "no_subscription":
        return InlineKeyboardMarkup([
            [ui.button("Продлить подписку", "plans", "card", "success")],
            ui.back_row(),
        ])
    return InlineKeyboardMarkup([ui.back_row()])


def app_code_text(code: str, ttl: int) -> str:
    minutes = max(1, ttl // 60)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    body = (
        f"<code>{code}</code>\n\n"
        "<i>Нажмите на код, чтобы скопировать.</i>\n\n"
        "<blockquote><b>Срок действия</b>\n"
        f"{minutes} мин · до {fmt_date(expires.isoformat())}</blockquote>\n\n"
        "Введите его на экране входа приложения FocusVPN."
    )
    return ui.screen("Ваш код входа", body, "key")


def app_code_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [ui.button("Новый код", "app_code", "refresh")],
        [ui.button("Как подключиться", "guide", "info")],
        ui.back_row(),
    ])


def extract_vpnauth_start(args: list[str]) -> str | None:
    if not args:
        return None
    payload = args[0].strip()
    return payload if payload.startswith("vpnauth_") else None


# --- handlers -------------------------------------------------------------------


async def _device_count(tid: int) -> int | None:
    try:
        return len(await api.mv_devices(tid))
    except api.APIError:
        return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    reviews.abandon(context.user_data)
    vpnauth = extract_vpnauth_start(context.args or [])
    if vpnauth:
        try:
            await api.mv_attach_login(vpnauth, user.id)
            await ui.reply_html(
                update.message,
                ui.screen(
                    "Готово",
                    "<blockquote>Вход в приложение FocusVPN подтверждён.\n"
                    "Вернитесь в приложение — оно подключится автоматически.</blockquote>",
                    "check",
                ),
            )
        except api.APIError as e:
            await ui.reply_html(
                update.message,
                ui.screen(
                    "Не получилось",
                    f"<blockquote>Не удалось подтвердить вход: {html.escape(str(e.detail.get('message') or e.status))}</blockquote>",
                    "info",
                ),
            )
        return
    await cmd_menu(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    reviews.abandon(context.user_data)
    await ui.reply_html(update.message, guide_text("android"), guide_keyboard(None, "android"))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    reviews.abandon(context.user_data)
    await ui.reply_html(
        update.message,
        ui.screen("Готово", "<blockquote>Отзыв отменён.</blockquote>", "info"),
        InlineKeyboardMarkup([ui.back_row()]),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    reviews.abandon(context.user_data)
    try:
        await api.mv_upsert(user.id)
        st = await api.fp_status(user.id)
    except api.APIError as e:
        log.warning("start: api error %s", e.status)
        await ui.reply_html(
            update.message,
            ui.screen("Не получилось", "<blockquote>Сервис временно недоступен. Попробуйте через минуту.</blockquote>", "info"),
        )
        return
    count = await _device_count(user.id)
    await ui.reply_html(update.message, home_text(st, user.first_name, count), home_keyboard(st))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.from_user:
        return
    data = q.data or ""
    if data.startswith("review:"):
        await reviews.on_callback(update, context)
        return
    if data != "apk":
        await q.answer()
    tid = q.from_user.id
    try:
        if data == "apk":
            st = await _status_or_none(tid)
            if st is None:
                await q.answer("Сервис временно недоступен. Попробуйте через минуту.", show_alert=True)
                return
            if not subscription_active(st):
                await q.answer("Скачать приложение можно после активации подписки.", show_alert=True)
                return
            await q.answer("Отправляю приложение…")
            await send_apk(q.message, st)
        elif data == "home":
            st = await api.fp_status(tid)
            count = await _device_count(tid)
            await _edit(q, home_text(st, q.from_user.first_name, count), home_keyboard(st))
        elif data == "plans":
            await _show_plans(q, tid)
        elif data == "reviews":
            st = await api.fp_status(tid)
            await _edit(q, reviews.hub_text(st), reviews.hub_keyboard(st))
        elif data == "balance":
            st = await api.fp_status(tid)
            await _edit(q, balance_text(st), balance_keyboard(st))
        elif data == "download":
            st = await api.fp_status(tid)
            await _edit(q, download_text(st), download_keyboard(st))
        elif data.startswith("pick:"):
            _, code, nonce = (data.split(":", 2) + [""])[:3]
            await _confirm(q, tid, code, nonce or q.id)
        elif data.startswith("buy:"):
            _, code, nonce = (data.split(":", 2) + [""])[:3]
            res = await api.fp_purchase(tid, code, f"tg-{tid}-{code}-{nonce or q.id}")
            await _edit(q, done_text(res, "Оплачено с баланса FocusPay"), InlineKeyboardMarkup([ui.back_row()]))
        elif data == "trial":
            res = await api.fp_trial(tid, f"tg-trial-{tid}")
            await _edit(q, done_text(res, "Пробный период включён"), _after_trial_keyboard(await _status_or_none(tid)))
        elif data == "devices":
            await _show_devices(q, tid)
        elif data == "device_plans":
            await _show_device_plans(q, tid)
        elif data.startswith("dpick:"):
            _, code, nonce = (data.split(":", 2) + [""])[:3]
            await _confirm_device(q, tid, code, nonce or q.id)
        elif data.startswith("dbuy:"):
            _, code, nonce = (data.split(":", 2) + [""])[:3]
            res = await api.fp_device(tid, code, f"tg-dev-{tid}-{code}-{nonce or q.id}")
            await _edit(q, device_done_text(res), InlineKeyboardMarkup([ui.back_row("devices", "К устройствам")]))
        elif data.startswith("unbind:"):
            await _confirm_unbind(q, tid, data.split(":", 1)[1])
        elif data.startswith("unbind_ok:"):
            await api.mv_revoke_device(tid, data.split(":", 1)[1])
            st = await _status_or_none(tid)
            rows: list[list[InlineKeyboardButton]] = [
                [
                    ui.button("Код входа", "app_code", "key"),
                    ui.button("Ключ ссылкой", "sub_link", "key"),
                ],
            ]
            if subscription_active(st):
                rows.append([apk_button()])
            rows.append(ui.back_row())
            await _edit(
                q,
                ui.screen(
                    "Готово",
                    "<blockquote>Устройство отвязано, VPN на нём отключён.\n\n"
                    "Чтобы подключить новый телефон: установите приложение и войдите через Telegram "
                    "или кодом для входа.</blockquote>",
                    "check",
                ),
                InlineKeyboardMarkup(rows),
            )
        elif data == "guide" or data.startswith("guide:"):
            platform = data.split(":", 1)[1] if ":" in data else "android"
            if platform not in {"android", "iphone", "windows", "macos"}:
                platform = "android"
            await _edit(q, guide_text(platform), guide_keyboard(None, platform))
        elif data == "app_code":
            await _show_app_code(q, tid)
        elif data == "sub_link":
            await _show_sub_link(q, tid, rotate=False)
        elif data == "sub_new":
            await _edit(q, sub_link_confirm_text(), sub_link_confirm_keyboard())
        elif data == "sub_new_ok":
            await _show_sub_link(q, tid, rotate=True)
        else:
            await _edit(
                q,
                ui.screen("Не получилось", "<blockquote>Неизвестная команда</blockquote>", "info"),
                InlineKeyboardMarkup([ui.back_row()]),
            )
    except api.APIError as e:
        log.warning("api error %s", e.status)
        await _edit(q, refusal_text(e), InlineKeyboardMarkup([ui.back_row()]))


async def _edit(q, text: str, markup: InlineKeyboardMarkup) -> None:
    await ui.edit_query(q, text, markup)


async def _status_or_none(tid: int) -> dict | None:
    try:
        return await api.fp_status(tid)
    except api.APIError:
        return None


def _after_trial_keyboard(st: dict | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if subscription_active(st):
        rows.append([apk_button()])
    rows.append([
        ui.button("Код входа", "app_code", "key"),
        ui.button("Ключ ссылкой", "sub_link", "key"),
    ])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


async def _show_plans(q, tid: int) -> None:
    st = await api.fp_status(tid)
    if not st.get("purchase_open"):
        await _edit(q, locked_text(st), locked_keyboard(st))
        return
    await _edit(q, plans_text(st), plans_keyboard(st.get("plans") or []))


async def _confirm(q, tid: int, code: str, nonce: str) -> None:
    st = await api.fp_status(tid)
    plan = next((p for p in st.get("plans") or [] if p.get("code") == code), None)
    if plan is None:
        await _edit(
            q,
            ui.screen(
                "Не получилось",
                "<blockquote>Тариф больше не продаётся. Откройте «Тарифы» ещё раз.</blockquote>",
                "info",
            ),
            InlineKeyboardMarkup([ui.back_row("plans", "К тарифам")]),
        )
        return
    if not st.get("purchase_open"):
        await _edit(q, locked_text(st), locked_keyboard(st))
        return
    await _edit(q, confirm_text(st, plan), confirm_keyboard(st, plan, nonce))


async def _show_devices(q, tid: int) -> None:
    st = await api.fp_status(tid)
    devices = await api.mv_devices(tid)
    await _edit(q, devices_text(devices, st), devices_keyboard(devices, st))


async def _show_device_plans(q, tid: int) -> None:
    st = await api.fp_status(tid)
    await _edit(q, device_plans_text(st), device_plans_keyboard(st))


async def _confirm_device(q, tid: int, code: str, nonce: str) -> None:
    st = await api.fp_status(tid)
    addon = next((p for p in _addons(st) if p.get("code") == code), None)
    if addon is None:
        await _edit(
            q,
            ui.screen("Не получилось", "<blockquote>Этот срок больше не продаётся.</blockquote>", "info"),
            InlineKeyboardMarkup([ui.back_row("device_plans", "К срокам")]),
        )
        return
    if not (st.get("subscription") or {}).get("active"):
        await _edit(q, device_plans_text(st), device_plans_keyboard(st))
        return
    if not st.get("purchase_open"):
        await _edit(q, device_plans_text(st), device_plans_keyboard(st))
        return
    await _edit(q, device_confirm_text(st, addon), device_confirm_keyboard(st, addon, nonce))


async def _confirm_unbind(q, tid: int, device_id: str) -> None:
    devices = await api.mv_devices(tid)
    dev = next((d for d in devices if d.get("id") == device_id), None)
    if dev is None:
        await _edit(
            q,
            ui.screen("Не получилось", "<blockquote>Устройство уже отвязано.</blockquote>", "info"),
            devices_keyboard(devices),
        )
        return
    name = html.escape(str(dev.get("name") or "устройство"))
    await _edit(
        q,
        ui.screen(
            "Подтвердите действие",
            f"<blockquote>Отвязать <b>{name}</b>?\n"
            "VPN на нём сразу отключится. Подписка останется — "
            "войдите в приложении на другом устройстве.</blockquote>\n\n"
            "<i>Проверьте условия перед подтверждением.</i>",
            "info",
        ),
        InlineKeyboardMarkup([
            [ui.button("Подтвердить", f"unbind_ok:{device_id}", "check", "danger")],
            ui.back_row("devices", "Отмена"),
        ]),
    )


async def _show_app_code(q, tid: int) -> None:
    res = await api.mv_login_code(tid)
    code = html.escape(str(res.get("code", "")))
    ttl = int(res.get("expires_in", 300))
    await _edit(q, app_code_text(code, ttl), app_code_keyboard())


async def _show_sub_link(q, tid: int, rotate: bool) -> None:
    try:
        await api.mv_upsert(tid)
        res = await api.mv_sub_link(tid, rotate=rotate)
    except api.APIError as e:
        await _edit(q, sub_link_error_text(e), sub_link_error_keyboard(e))
        return
    url = str(res.get("url") or "")
    if not url.startswith(("https://", "http://")):
        await _edit(
            q,
            ui.screen("Не получилось", "<blockquote>Сервис не вернул ссылку. Попробуйте через минуту.</blockquote>", "info"),
            InlineKeyboardMarkup([ui.back_row()]),
        )
        return
    await _edit(q, sub_link_text(url, res.get("ends_at")), sub_link_keyboard())
