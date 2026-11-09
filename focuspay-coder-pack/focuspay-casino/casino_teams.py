"""Telegram commands for player clans. Money stays on the backend."""
from __future__ import annotations

import html
from typing import Any, Mapping

import httpx
from telebot.async_telebot import AsyncTeleBot

from casino_menu import MENU_TEAM
from focuspay_client import FocusPayClient


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def api_error_text(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
            detail = payload.get("detail") if isinstance(payload, Mapping) else None
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            if isinstance(detail, list):
                for item in detail:
                    if isinstance(item, Mapping):
                        msg = item.get("msg")
                        if isinstance(msg, str) and msg.strip():
                            return msg.strip()
        except Exception:
            pass
    return "Не удалось выполнить запрос. Попробуйте позже."


def _fmt_rub(value: object) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def format_clan(clan: Mapping[str, Any], *, with_code: bool = False) -> str:
    tag = _esc(clan.get("tag"))
    name = _esc(clan.get("name"))
    wager = _fmt_rub(clan.get("wager_rub"))
    count = clan.get("member_count") or 0
    cap = clan.get("max_members") or 20
    lines = [
        f"<b>[{tag}] {name}</b>",
        f"Оборот недели: {wager} ₽ · {count}/{cap}",
    ]
    members = clan.get("members") if isinstance(clan.get("members"), list) else []
    for member in members:
        if not isinstance(member, Mapping):
            continue
        label = _esc(member.get("display_name") or member.get("user_id"))
        role = " владелец" if member.get("role") == "owner" else ""
        lines.append(f"· {label}{role} — {_fmt_rub(member.get('wager_rub'))} ₽")
    if with_code and clan.get("invite_code"):
        lines.append(f"Код: <code>{_esc(clan.get('invite_code'))}</code>")
    return "\n".join(lines)


def _private(message) -> bool:
    return getattr(getattr(message, "chat", None), "type", "") == "private"


def register_team_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    @bot.message_handler(commands=["team", "teamcreate", "teamjoin", "teamleave", "teamkick", "teaminvite", "teamtop", "teamdisband", "teamtransfer"])
    async def team_commands(message):
        if not _private(message):
            await bot.send_message(message.chat.id, "Команды доступны в личке с ботом.")
            return
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        if not isinstance(user_id, int):
            return
        text = (message.text or "").strip()
        cmd = text.split()[0].lstrip("/").split("@")[0].lower()
        parts = text.split(maxsplit=2)
        try:
            if cmd == "teamcreate":
                if len(parts) < 3:
                    await bot.send_message(message.chat.id, "Формат: /teamcreate TAG Имя")
                    return
                result = await client.create_clan(telegram_id=user_id, tag=parts[1], name=parts[2])
                clan = result.get("clan") if isinstance(result, Mapping) else None
                await bot.send_message(
                    message.chat.id,
                    format_clan(clan or {}, with_code=True) if isinstance(clan, Mapping) else "Команда создана.",
                    parse_mode="HTML",
                )
                return
            if cmd == "teamjoin":
                if len(parts) < 2:
                    await bot.send_message(message.chat.id, "Формат: /teamjoin КОД")
                    return
                result = await client.join_clan(telegram_id=user_id, code=parts[1])
                clan = result.get("clan") if isinstance(result, Mapping) else None
                await bot.send_message(
                    message.chat.id,
                    format_clan(clan or {}) if isinstance(clan, Mapping) else "Вы в команде.",
                    parse_mode="HTML",
                )
                return
            if cmd == "teamleave":
                result = await client.leave_clan(telegram_id=user_id)
                await bot.send_message(message.chat.id, f"Вы вышли из [{_esc(result.get('left_tag'))}].")
                return
            if cmd == "teamkick":
                if len(parts) < 2 or not parts[1].isdigit():
                    await bot.send_message(message.chat.id, "Формат: /teamkick TELEGRAM_ID")
                    return
                result = await client.kick_clan_member(telegram_id=user_id, target_id=int(parts[1]))
                clan = result.get("clan") if isinstance(result, Mapping) else None
                await bot.send_message(
                    message.chat.id,
                    format_clan(clan or {}, with_code=True) if isinstance(clan, Mapping) else "Игрок исключён.",
                    parse_mode="HTML",
                )
                return
            if cmd == "teaminvite":
                result = await client.rotate_clan_invite(telegram_id=user_id)
                clan = result.get("clan") if isinstance(result, Mapping) else None
                await bot.send_message(
                    message.chat.id,
                    format_clan(clan or {}, with_code=True) if isinstance(clan, Mapping) else "Код обновлён.",
                    parse_mode="HTML",
                )
                return
            if cmd == "teamdisband":
                result = await client.disband_clan(telegram_id=user_id)
                await bot.send_message(message.chat.id, f"Команда [{_esc(result.get('disbanded_tag'))}] распущена.")
                return
            if cmd == "teamtransfer":
                if len(parts) < 2 or not parts[1].isdigit():
                    await bot.send_message(message.chat.id, "Формат: /teamtransfer TELEGRAM_ID")
                    return
                result = await client.transfer_clan(telegram_id=user_id, target_id=int(parts[1]))
                clan = result.get("clan") if isinstance(result, Mapping) else None
                await bot.send_message(
                    message.chat.id,
                    format_clan(clan or {}) if isinstance(clan, Mapping) else "Владение передано.",
                    parse_mode="HTML",
                )
                return
            if cmd == "teamtop":
                ranking = await client.get_clan_top()
                clans = ranking.get("clans") if isinstance(ranking, Mapping) else []
                if not clans:
                    await bot.send_message(message.chat.id, "Топ пуст. Создайте команду: /teamcreate TAG Имя")
                    return
                lines = ["<b>Топ команд за неделю</b>"]
                for index, clan in enumerate(clans[:10], start=1):
                    if not isinstance(clan, Mapping):
                        continue
                    lines.append(
                        f"{index}. [{_esc(clan.get('tag'))}] {_esc(clan.get('name'))} — {_fmt_rub(clan.get('wager_rub'))} ₽"
                    )
                await bot.send_message(message.chat.id, "\n".join(lines), parse_mode="HTML")
                return
            mine = await client.get_clan(user_id)
            clan = mine.get("clan") if isinstance(mine, Mapping) else None
            if not clan:
                await bot.send_message(
                    message.chat.id,
                    "Вы не в команде.\n/teamcreate TAG Имя\n/teamjoin КОД\n/teamtop",
                )
                return
            await bot.send_message(
                message.chat.id,
                format_clan(clan, with_code=bool(clan.get("is_owner"))),
                parse_mode="HTML",
            )
        except httpx.HTTPStatusError as exc:
            await bot.send_message(message.chat.id, api_error_text(exc))
        except Exception:
            await bot.send_message(message.chat.id, "Не удалось выполнить запрос. Попробуйте позже.")

    @bot.message_handler(func=lambda m: getattr(m, "text", "") == MENU_TEAM and _private(m))
    async def menu_team(message):
        message.text = "/team"
        await team_commands(message)
