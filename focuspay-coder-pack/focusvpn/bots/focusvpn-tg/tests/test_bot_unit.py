"""Pure unit tests for bot screens (no network)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from bot import api, handlers, reminders, reviews, ui
from bot.handlers import (
    _after_trial_keyboard,
    apk_button,
    balance_keyboard,
    balance_text,
    confirm_keyboard,
    confirm_text,
    device_confirm_keyboard,
    device_confirm_text,
    device_done_text,
    device_plans_keyboard,
    device_plans_text,
    devices_keyboard,
    devices_text,
    download_keyboard,
    download_text,
    download_url,
    extract_vpnauth_start,
    gate_text,
    home_keyboard,
    home_text,
    load_apk_file_id,
    new_end,
    plans_keyboard,
    plans_text,
    plural_days,
    refusal_text,
    store_apk_file_id,
)

ui.premium = True

PLANS = [
    {"code": "week", "title": "Неделя", "days": 7, "price_rub": 300.0, "per_day_rub": 42.86, "discount_pct": 0},
    {"code": "month", "title": "Месяц", "days": 30, "price_rub": 990.0, "per_day_rub": 33.0, "discount_pct": 23},
]


def status(**kw):
    base = {
        "available_rub": 1250.0,
        "exchanges": {"have": 3, "need": 10},
        "purchase_open": False,
        "trial": {"enabled": True, "days": 1, "min_exchanges": 0, "used": False},
        "trial_available": True,
        "plans": PLANS,
        "app_url": "https://focuspay.org/vpn.apk",
        "subscription": {"active": False, "days_left": 0},
    }
    base.update(kw)
    return base


def _buttons(kb):
    return [b for row in kb.inline_keyboard for b in row]


def test_home_new_user_sees_trial_and_progress():
    st = status()
    text = home_text(st, "Ann")
    assert "Привет, <b>Ann</b>" in text
    assert "Подписки нет" in text
    assert "личный кабинет" in text
    assert "1 250 ₽" in text
    assert "Скачать приложение можно после активации" in text
    assert "3 из 10" not in text
    locked = handlers.locked_text(st)
    assert "3 из 10" in locked
    assert "▰" not in locked
    buttons = _buttons(home_keyboard(st))
    labels = [b.text for b in buttons]
    assert labels[0] == "Попробовать бесплатно · 1 день"
    assert buttons[0].style == "success"
    assert "Продлить подписку" in labels
    assert buttons[1].style == "success"
    assert any(b.callback_data == "download" for b in buttons)
    assert not any(b.callback_data == "apk" for b in buttons)
    assert apk_button().callback_data == "apk"


def test_download_url_falls_back_when_admin_field_empty(monkeypatch):
    monkeypatch.setattr(handlers.config, "VPN_CLIENT_DOWNLOAD_URL", "https://focuspay.org/vpn.apk")
    assert download_url(status(app_url="")) == "https://focuspay.org/vpn.apk"
    assert download_url(None) == "https://focuspay.org/vpn.apk"
    inactive = _buttons(_after_trial_keyboard(status()))
    assert not any(b.callback_data == "apk" for b in inactive)
    live = status(subscription={"active": True, "status": "trialing", "days_left": 1})
    assert _after_trial_keyboard(live).inline_keyboard[0][0].callback_data == "apk"


def test_apk_file_id_cache_is_kept_only_for_the_same_file(tmp_path):
    cache = tmp_path / "apk.file_id.json"
    store_apk_file_id(cache, "abc", "file-1")
    assert load_apk_file_id(cache, "abc") == "file-1"
    assert load_apk_file_id(cache, "other") == ""


def test_home_active_subscription_open_gate():
    st = status(
        purchase_open=True,
        trial_available=False,
        subscription={"active": True, "plan": "month", "status": "active", "ends_at": "2026-10-14T15:00:00+00:00", "days_left": 6},
        devices_limit={"max_devices": 1},
    )
    text = home_text(st, device_count=1)
    assert "Подписка активна</b> · Месяц" in text
    assert "14.10.2026 · 18:00 МСК" in text and "Осталось дней: <b>6</b>" in text
    assert "Продлевайте в любой момент" in text
    assert "Устройства <b>1 / 1</b>" in text
    labels = [b.text for b in _buttons(home_keyboard(st))]
    assert "Продлить подписку" in labels
    assert not any("Попробовать" in x for x in labels)
    assert any(b.callback_data == "download" for b in _buttons(home_keyboard(st)))
    assert not any(b.callback_data == "apk" for b in _buttons(home_keyboard(st)))


def test_home_trusted_account_skips_the_gate_copy():
    st = status(purchase_open=True, trusted=True)
    text = home_text(st)
    assert "3 из 10" not in text
    assert "Продлевайте в любой момент" not in text
    labels = [b.text for b in _buttons(home_keyboard(st))]
    assert "Продлить подписку" in labels


def test_plans_screen_and_one_nonce_per_menu():
    text = plans_text(status(purchase_open=True))
    assert "−23%" in text and "33 ₽ в день" in text
    buttons = _buttons(plans_keyboard(PLANS, nonce="abc123"))
    data = [b.callback_data for b in buttons]
    assert data[:2] == ["pick:week:abc123", "pick:month:abc123"]
    assert buttons[1].style == "success"
    assert buttons[1].icon_custom_emoji_id == ui.EMOJI["star"][0]
    assert buttons[0].style == "primary"
    assert all(len(d.encode()) <= 64 for d in data)
    a = _buttons(plans_keyboard(PLANS))[0].callback_data
    b = _buttons(plans_keyboard(PLANS))[0].callback_data
    assert a != b


def test_confirm_keeps_nonce_and_blocks_without_funds():
    st = status(purchase_open=True)
    kb = confirm_keyboard(st, PLANS[1], "n1")
    pay = _buttons(kb)[0]
    assert pay.callback_data == "buy:month:n1"
    assert pay.style == "success"
    assert pay.text == "Подтвердить"
    poor = status(purchase_open=True, available_rub=100.0)
    assert "Не хватает 890 ₽" in confirm_text(poor, PLANS[1])
    assert not any((b.callback_data or "").startswith("buy:") for b in _buttons(confirm_keyboard(poor, PLANS[1], "n1")))


def test_new_end_stacks_on_live_subscription():
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    live = {"active": True, "ends_at": "2026-10-10T00:00:00+00:00"}
    assert new_end(live, 30, now) == datetime(2026, 11, 9, tzinfo=timezone.utc)
    assert new_end({"active": False}, 7, now) == now + timedelta(days=7)


def test_devices_screen_and_unbind_buttons():
    devs = [{"id": "11111111-2222-4333-8444-555555555555", "name": "Pixel 8", "platform": "android",
             "created_at": "2026-10-05T10:00:00Z", "connected": True}]
    text = devices_text(devs)
    assert "Pixel 8</b> · Android" in text and "подключено" in text
    buttons = _buttons(devices_keyboard(devs))
    assert buttons[0].callback_data == "unbind:11111111-2222-4333-8444-555555555555"
    assert buttons[0].style == "danger"
    assert len(("unbind_ok:" + devs[0]["id"]).encode()) <= 64
    assert "Пока ни одного" in devices_text([])


ADDONS = [
    {"code": "week", "title": "Неделя", "days": 7, "price_rub": 300.0, "per_day_rub": 42.86, "discount_pct": 0},
    {"code": "month", "title": "Месяц", "days": 30, "price_rub": 990.0, "per_day_rub": 33.0, "discount_pct": 23},
]


def _live(**kw):
    base = status(
        purchase_open=True,
        trial_available=False,
        subscription={"active": True, "plan": "week", "status": "active", "ends_at": "2026-10-15T00:00:00+00:00", "days_left": 7},
        device_addons=ADDONS,
        devices_limit={"max_devices": 1, "base_devices": 1, "extra_slots": []},
    )
    base.update(kw)
    return base


def test_device_seat_screen_is_independent_of_subscription_end():
    st = _live()
    text = devices_text([], st)
    assert "одно устройство" in text
    labels = [b.text for b in _buttons(devices_keyboard([], st))]
    assert "Ещё устройство" in labels
    assert "Ещё устройство" not in devices_text([], status())
    assert not any("Ещё устройство" in b.text for b in _buttons(devices_keyboard([], status())))

    plans = device_plans_text(st)
    assert "не продлевается" in plans and "Месяц" in plans
    data = [b.callback_data for b in _buttons(device_plans_keyboard(st, nonce="abc123"))]
    assert data[0] == "dpick:week:abc123"
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    confirm = device_confirm_text(st, ADDONS[1], now)
    assert "07.11.2026" in confirm
    assert "не продлевается" in confirm
    assert "Станет мест: <b>2</b>" in confirm
    assert "Подписка будет до" not in confirm
    pay = _buttons(device_confirm_keyboard(st, ADDONS[1], "n1"))[0]
    assert pay.callback_data == "dbuy:month:n1"
    done = device_done_text({"status": "paid", "ends_at": "2026-11-07T00:00:00+00:00"})
    assert "не продлевалась" in done and "07.11.2026" in done

    gated = _live(purchase_open=False)
    assert "обменов" in device_plans_text(gated)
    assert not any((b.callback_data or "").startswith("dpick:") for b in _buttons(device_plans_keyboard(gated)))


def test_refusal_texts():
    gate = api.APIError(403, json.dumps({"detail": {"code": "exchange_gate", "need": 10, "have": 3}}))
    assert "10 обменов" in refusal_text(gate) and "осталось 7" in refusal_text(gate)
    funds = api.APIError(402, json.dumps({"detail": {"code": "insufficient_funds"}}))
    assert "Недостаточно" in refusal_text(funds)
    missing = api.APIError(400, json.dumps({"detail": {"code": "subscription_required"}}))
    assert "живой подписке" in refusal_text(missing)
    assert "Ошибка" in refusal_text(api.APIError(500, "oops"))


def test_gate_text_and_plurals():
    assert "2 из 10" in gate_text(10, 2) and "осталось 8" in gate_text(10, 2)
    assert "▰" not in gate_text(10, 2)
    assert [plural_days(n) for n in (1, 2, 5, 11, 21, 30)] == ["1 день", "2 дня", "5 дней", "11 дней", "21 день", "30 дней"]


def test_vpnauth_start_payload():
    assert extract_vpnauth_start(["vpnauth_abc"]) == "vpnauth_abc"
    assert extract_vpnauth_start(["fp"]) is None
    assert extract_vpnauth_start([]) is None


def test_reminders_record_before_send_and_skip_duplicates():
    rem = [
        {"telegram_id": 1, "kind": "soon", "status": "trialing", "plan_code": "trial",
         "ends_at": (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()},
        {"telegram_id": 2, "kind": "ended", "status": "expired", "plan_code": "week", "ends_at": "2026-10-07T09:00:00+00:00"},
    ]
    bot = MagicMock()
    bot.send_message = AsyncMock()
    with patch.object(api, "fp_expiring", AsyncMock(return_value=rem)), \
         patch.object(api, "fp_notified", AsyncMock(side_effect=[True, False])), \
         patch.object(api, "fp_status", AsyncMock(return_value=status())), \
         patch.object(api, "fp_review_reminders", AsyncMock(return_value=[])):
        sent = asyncio.run(reminders.send_due(bot))
    assert sent == 1
    text = bot.send_message.await_args.args[1]
    assert "Пробный период закончится через 5 ч" in text
    assert "3 из 10" in text


def test_guide_screen_from_home():
    labels = [b.text for b in _buttons(home_keyboard(status()))]
    assert "Как подключиться" in labels
    android = handlers.guide_text("android")
    iphone = handlers.guide_text("iphone")
    assert "<b>Android</b>" in android
    assert "Войти через Telegram" in android
    assert "Когда подписка или пробный период активны" in android
    assert "<b>iPhone</b>" in iphone
    assert "Ключ ссылкой" in iphone
    assert "Happ" in iphone
    assert "пока не выдаёт" not in iphone
    data = [b.callback_data for b in _buttons(handlers.guide_keyboard(status()))]
    assert data == ["guide:android", "guide:iphone", "guide:windows", "guide:macos", "download", "app_code", "home"]
    assert "ключ ссылкой" in handlers.guide_text("windows")
    assert "Код входа" in handlers.guide_text("windows")
    assert "Новое устройство" in [b.text for b in _buttons(devices_keyboard([], _live()))]
    iphone_kb = _buttons(handlers.guide_keyboard(status(), "iphone"))
    assert iphone_kb[0].style is None
    assert iphone_kb[1].style == "primary"
    assert "sub_link" in [b.callback_data for b in iphone_kb]
    link = handlers.sub_link_text("https://focuspay.org/vpn-api/v1/sub/abc", "2026-10-14T15:00:00+00:00")
    assert "https://focuspay.org/vpn-api/v1/sub/abc" in link
    assert "Happ" in link
    assert _buttons(handlers.sub_link_keyboard())[0].callback_data == "sub_new"
    seat = handlers.sub_link_error_text(api.APIError(409, '{"error":{"code":"too_many_devices"}}'))
    assert "Свободного места нет" in seat
    macos_kb = _buttons(handlers.guide_keyboard(status(), "macos"))
    assert macos_kb[3].style == "primary"


def test_reviews_tab_is_always_on_the_home_screen():
    closed = status()
    home = _buttons(home_keyboard(closed))
    assert any(b.callback_data == "reviews" for b in home)
    assert not any((b.callback_data or "") == "review:start" for b in home)
    assert reviews.home_line(closed) is None
    assert "живой подписке" in reviews.hub_text(closed)
    closed_hub = _buttons(reviews.hub_keyboard(closed))
    assert not any(b.callback_data == "review:start" for b in closed_hub)
    assert closed_hub[0].url == reviews.config.REVIEWS_CHANNEL_URL == "https://t.me/focuspayr"

    open_week = status(
        subscription={"active": True, "status": "active", "plan": "month", "days_left": 12},
        review={"eligible": True, "text_rub": 25, "photo_rub": 50},
    )
    assert any(b.callback_data == "reviews" for b in _buttons(home_keyboard(open_week)))
    assert "25 ₽ за текст" in home_text(open_week, "Ann")
    write = next(b for b in _buttons(reviews.hub_keyboard(open_week)) if b.callback_data == "review:start")
    assert write.text == "Написать отзыв · до 50 ₽"
    assert write.style == "success"
    assert "боте FocusPay" in reviews.hub_text(open_week)

    cooling = status(review={"eligible": False, "reason": "cooldown", "next_at": "2099-01-08T00:00:00+00:00"})
    assert "снова можно оставить" in home_text(cooling)
    assert "Следующий отзыв" in reviews.hub_text(cooling)
    pending = status(review={"pending": True, "reason": "pending", "text_rub": 25, "photo_rub": 50})
    assert "на проверке" in reviews.hub_text(pending).lower()


def test_review_reminder_offers_the_bonus():
    text = reviews.reminder_text({"text_rub": 25, "photo_rub": 50})
    assert "бонус" in text and "25" in text and "50" in text and "недел" in text
    assert reviews.reminder_keyboard().inline_keyboard[0][0].callback_data == "review:start"
    assert "10 минут" in reviews.text_accepted_prompt(25, 50)
    assert "скрин приложения" in reviews.start_prompt(25, 50)


def test_review_reminders_record_before_send():
    rem = [{"telegram_id": 7, "window_at": "2026-10-05T00:00:00+00:00", "text_rub": 25, "photo_rub": 50}]
    bot = MagicMock()
    bot.send_message = AsyncMock()
    with patch.object(api, "fp_review_reminders", AsyncMock(return_value=rem)), \
         patch.object(api, "fp_review_notified", AsyncMock(return_value=True)):
        sent = asyncio.run(reminders.send_review_due(bot))
    assert sent == 1
    assert "Можно оставить отзыв" in bot.send_message.await_args.args[1]


def test_deliver_retries_without_premium_emoji():
    previous = ui.premium
    ui.premium = True
    calls = []

    async def sender(text, markup):
        calls.append((text, markup))
        if len(calls) == 1:
            raise BadRequest("Bad Request: can't parse entities: Custom_emoji_id")

    try:
        asyncio.run(ui.deliver(sender, ui.screen("FocusVPN", "кабинет"), None))
        assert ui.premium is False
        assert len(calls) == 2
        assert "<tg-emoji" in calls[0][0]
        assert calls[1][0].startswith("🌐 <b>FocusVPN</b>")
    finally:
        ui.premium = previous


def test_reminder_text_ended_open_gate():
    rem = {"kind": "ended", "plan_code": "week", "ends_at": "2026-10-07T09:00:00+00:00"}
    text = handlers.reminder_text(rem, status(purchase_open=True))
    assert "Подписка FocusVPN закончилась" in text and "Продлите" in text


def test_download_and_balance_screens():
    closed = status()
    assert "после активации" in download_text(closed)
    closed_data = [b.callback_data for b in _buttons(download_keyboard(closed))]
    assert "apk" not in closed_data
    assert closed_data[0] == "trial"
    live = status(subscription={"active": True, "status": "trialing", "days_left": 2}, trial_available=False)
    assert _buttons(download_keyboard(live))[0].callback_data == "apk"
    assert "1 250 ₽" in balance_text(closed)
    topup = _buttons(balance_keyboard(closed))[0]
    assert topup.url == handlers.config.FOCUSPAY_BOT_URL
    assert topup.callback_data is None
    assert "1 000" not in balance_text(closed)


def test_premium_emoji_falls_back_to_unicode():
    previous = ui.premium
    try:
        ui.premium = True
        kb = home_keyboard(status(purchase_open=True, trial_available=False))
        extend = _buttons(kb)[0]
        assert extend.icon_custom_emoji_id == ui.EMOJI["card"][0]
        assert extend.text == "Продлить подписку"
        plain = ui.plain_markup(kb)
        stripped = _buttons(plain)[0]
        assert stripped.icon_custom_emoji_id is None
        assert stripped.text == "💳 Продлить подписку"
        assert stripped.style == "success"
        sample = ui.screen("FocusVPN", "кабинет")
        assert "<tg-emoji" in sample
        assert ui.plain_text(sample).startswith("🌐 <b>FocusVPN</b>")
        ui.premium = False
        off = _buttons(home_keyboard(status(purchase_open=True, trial_available=False)))[0]
        assert off.icon_custom_emoji_id is None
        assert off.text == "💳 Продлить подписку"
    finally:
        ui.premium = previous
