"""Отстук в ops-чат о блокировках реквизитов при отсутствии смены."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta
from typing import Any

from services import config_rates
from services.db import (
    count_no_shift_blocks_since,
    count_no_shift_blocks_since_empty_shift,
    record_no_shift_requisites_block,
)
from services.operator_availability import ROLE_LABELS
from services.operator_shift_store import read_operator_shift_target

logger = logging.getLogger("no_shift_block_notify")

_DEBOUNCE_SEC = 30.0
_STATE_KEY = "no_shift_block_notify"


def _notify_target() -> tuple[int, int | None]:
    target = read_operator_shift_target()
    if target and target.get("chat_id"):
        topic = target.get("topic_id")
        return int(target["chat_id"]), int(topic) if topic is not None else None
    gid = config_rates.ops_group_id()
    return int(gid) if gid else 0, None


def _state(bot_data: dict) -> dict[str, Any]:
    raw = bot_data.get(_STATE_KEY)
    if raw is None:
        raw = {"events": [], "task": None}
        bot_data[_STATE_KEY] = raw
    return raw


def _direction_label(direction: str) -> str:
    return "продажа" if (direction or "").lower() == "sell" else "покупка"


async def _reki_summary() -> str | None:
    """Что показывал /reki в момент отказа — видно расхождение с выдачей."""
    try:
        from services.reki_poll import load_snapshot, snapshot_ttl_seconds
        from services.reki_snapshot import ops_summary_line

        return ops_summary_line(await load_snapshot(), ttl_seconds=snapshot_ttl_seconds())
    except Exception:
        logger.warning("reki summary skipped", exc_info=True)
        return None


def _reason_label(reason: str, missing_roles: tuple[str, ...]) -> str:
    if reason == "all_busy":
        return "реки заняты"
    if missing_roles and set(str(role) for role in missing_roles) < {"client", "finance"}:
        return "неполная смена"
    return "нет смены"


def _fmt_coin(value) -> str:
    try:
        text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
    return text or "0"


def block_why(reason: str | None, detail: dict | None = None) -> str:
    """Короткая причина, почему реквизиты не выданы. Пустая строка — строку в отстук не пишем."""
    info = detail or {}
    code = (reason or "").strip()
    if code == "insufficient_paid_buys":
        paid = info.get("paid_buys")
        need = info.get("min_paid_buys")
        if paid is not None and need is not None:
            return f"оплаченных покупок {int(paid)} из {int(need)}"
        return "мало оплаченных покупок для автопилота"
    if code == "amount_over_cap":
        fiat = info.get("fiat_amount")
        limit = info.get("max_rub")
        if fiat is not None and limit is not None:
            return f"сумма {int(fiat)} ₽ выше лимита автопилота {int(limit)} ₽"
        return "сумма выше лимита автопилота"
    if code == "not_whitelisted":
        return "клиента нет в списке автопилота"
    if code == "user_override_off":
        return "автопилот для этого клиента выключен"
    if code == "auto_disabled":
        return "выдача реквизитов без смены выключена"
    if code == "signer_circuit_open":
        return "кошелёк автопилота недоступен или ниже порога"
    if code == "coin_short":
        coin = str(info.get("coin") or "").upper()
        need = info.get("need")
        free = info.get("available")
        if coin and need is not None and free is not None:
            return f"{coin}: нужно {_fmt_coin(need)}, свободно {_fmt_coin(free)}"
        return "на этой валюте меньше, чем сумма заявки"
    if code == "coin_unknown":
        return "баланс этой валюты не удалось проверить"
    if code == "shadow_would_auto":
        return "тестовый режим: реквизиты не выдаются"
    if code == "sell_requires_shift":
        return "продажа без полной смены не выдаётся"
    if code == "gate_error":
        return "проверка автопилота не прошла"
    if code == "no_bill":
        return "Payfast не выдал счёт, без смены заявка оператору не создаётся"
    if code == "autopilot_unavailable":
        return "автопилот не ответил, реквизиты без смены не выдали"
    return ""


async def _send_batch(bot, events: list[dict[str, Any]]) -> None:
    chat_id, topic_id = _notify_target()
    if not chat_id:
        logger.warning("no_shift_block notify skipped: chat not configured")
        return

    now = datetime.now()
    last_hour = await count_no_shift_blocks_since(now - timedelta(hours=1))
    since_empty = await count_no_shift_blocks_since_empty_shift()
    batch_n = len(events)
    last = events[-1]
    user_id = last.get("user_id")
    username = last.get("username")
    direction = _direction_label(str(last.get("direction") or "buy"))
    missing_roles = tuple(last.get("missing_roles") or ())
    why = str(last.get("why") or "").strip()

    uname = f" (@{html.escape(username)})" if username else ""
    batch_line = ""
    if batch_n > 1:
        batch_line = f"📦 За последние {int(_DEBOUNCE_SEC)} с: <b>{batch_n}</b> попыток\n"

    reasons = {(e.get("reason") or "no_shift") for e in events}
    if reasons == {"all_busy"}:
        title = "🚫 <b>Блокировка реквизитов (реки заняты / нет bill)</b>"
        extra = "ℹ️ На смене есть оператор — Payfast не выдал реквизиты (NO_BILL / all_busy).\n"
        counters = f"📊 Попыток за последний час: <b>{last_hour}</b>\n"
    elif "all_busy" in reasons and "no_shift" in reasons:
        title = "🚫 <b>Блокировка реквизитов (смесь: нет смены + реки заняты)</b>"
        extra = ""
        counters = (
            f"📊 Попыток за последний час: <b>{last_hour}</b>\n"
            f"📊 Всего с момента закрытия смены: <b>{since_empty}</b>\n"
        )
    else:
        block_title = _reason_label(str(last.get("reason") or "no_shift"), missing_roles)
        title = f"🚫 <b>Блокировка реквизитов ({html.escape(block_title)})</b>"
        extra = ""
        counters = (
            f"📊 Попыток за последний час: <b>{last_hour}</b>\n"
            f"📊 Всего с момента закрытия смены: <b>{since_empty}</b>\n"
        )

    missing_roles_line = ""
    if missing_roles:
        missing_roles_line = (
            "🧩 Не хватает роли на смене: "
            f"<b>{html.escape(', '.join(ROLE_LABELS.get(str(role), str(role)) for role in missing_roles))}</b>\n"
        )
    why_line = f"Почему: <b>{html.escape(why)}</b>\n" if why else ""
    reki_line = ""
    if "all_busy" in reasons:
        summary = await _reki_summary()
        if summary:
            reki_line = f"{html.escape(summary)}\n"

    text = (
        f"{title}\n\n"
        f"👤 user_id: <code>{user_id}</code>{uname}\n"
        f"💱 Направление: {direction}\n"
        f"{missing_roles_line}"
        f"{why_line}"
        f"{extra}"
        f"{reki_line}"
        f"\n{batch_line}"
        f"{counters}"
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')}"
    )
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if topic_id is not None:
        kwargs["message_thread_id"] = topic_id
    try:
        await bot.send_message(**kwargs)
    except Exception as e:
        logger.warning("no_shift_block notify failed: %s", e)


async def _flush_pending(bot, bot_data: dict) -> None:
    await asyncio.sleep(_DEBOUNCE_SEC)
    state = _state(bot_data)
    events = list(state.get("events") or [])
    state["events"] = []
    state["task"] = None
    if events:
        await _send_batch(bot, events)


async def record_no_shift_block_and_notify(
    bot,
    bot_data: dict,
    *,
    user_id: int,
    direction: str,
    username: str | None = None,
    reason: str = "no_shift",
    fiat_amount: int | None = None,
    missing_roles: tuple[str, ...] = (),
    why: str | None = None,
) -> None:
    inserted = await record_no_shift_requisites_block(user_id, direction, reason, fiat_amount)
    if not inserted:
        return
    state = _state(bot_data)
    state.setdefault("events", []).append(
        {
            "user_id": int(user_id),
            "direction": direction,
            "username": username,
            "reason": reason,
            "missing_roles": tuple(missing_roles),
            "why": (why or "").strip(),
        }
    )
    task = state.get("task")
    if task is None or task.done():
        state["task"] = asyncio.create_task(_flush_pending(bot, bot_data))
