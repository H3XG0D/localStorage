"""
games/raffle.py — Розыгрыши с условиями участия.

Адаптировано для FocusPay Casino:
- Использует FocusPayClient для баланса (hold/confirm/release/payout)
- Async/await вместо threading
- Распределение комиссий через referral_integration
- Админ создаёт розыгрыш командой с условиями (оборот, депозиты)
- 6 слотов участников, победитель определяется броском кубика

Публичные функции:
- register_raffle_handlers(bot, client, chat_id) — регистрация handlers
- raffle_cleaner() — фоновая очистка таймаутов

Команды (только в групповом чате):
- /fast [сумма] [today N] [total N] [dep N] — создать розыгрыш (только админ)
- /allfast — список активных розыгрышей
- /delprize [#номер] — удалить розыгрыш (только админ)
"""
import asyncio
import secrets
from datetime import datetime
from typing import Optional, Tuple

from telebot.async_telebot import AsyncTeleBot
from telebot import types

import config
from focuspay_client import FocusPayClient


# ==================== IN-MEMORY STATE ====================

active_raffles = {}
raffle_counter = 0
raffle_counter_lock = asyncio.Lock()
_raffle_locks = {}

def get_raffle_lock(raffle_id: int) -> asyncio.Lock:
    if raffle_id not in _raffle_locks:
        _raffle_locks[raffle_id] = asyncio.Lock()
    return _raffle_locks[raffle_id]

_secure_random = secrets.SystemRandom()

RAFFLE_SLOTS = getattr(config, "RAFFLE_SLOTS", 6)
RAFFLE_TIMEOUT_HOURS = getattr(config, "RAFFLE_TIMEOUT_HOURS", 3)
MAX_ADMIN_RAFFLES = 3


# ==================== ПАРСИНГ АРГУМЕНТОВ ====================

def parse_fast_args(parts: list):
    """Парсит аргументы /fast: сумма + опциональные условия today/total/dep.
    Возвращает (dict_with_settings, None) при успехе или (None, error_msg)."""
    if len(parts) < 2:
        return None, "❌ Использование: <code>/fast сумма [today N] [total N] [dep N]</code>"
    try:
        prize = float(parts[1].replace(",", "."))
    except ValueError:
        return None, "❌ Неверная сумма приза."
    if prize <= 0:
        return None, "❌ Сумма приза должна быть больше 0."
    
    req_today = req_total = req_dep = 0.0
    i = 2
    while i < len(parts):
        key = parts[i].lower()
        if key not in ("today", "total", "dep"):
            return None, f"❌ Неизвестный параметр: <code>{parts[i]}</code>"
        if i + 1 >= len(parts):
            return None, f"❌ После <code>{key}</code> должно быть число."
        try:
            val = float(parts[i + 1].replace(",", "."))
        except ValueError:
            return None, f"❌ Неверное значение для <code>{key}</code>."
        if val < 0:
            return None, f"❌ Значение <code>{key}</code> не может быть отрицательным."
        if key == "today":
            req_today = val
        elif key == "total":
            req_total = val
        elif key == "dep":
            req_dep = val
        i += 2
    
    return {
        "prize": prize,
        "req_today": req_today,
        "req_total": req_total,
        "req_dep": req_dep,
    }, None


# ==================== РЕНДЕР ====================

def build_raffle_text(r: dict, rid: int) -> str:
    """Строит текст сообщения розыгрыша."""
    parts = r.get("participants", [])
    req_lines = []
    if r.get("req_today", 0) > 0:
        req_lines.append(f"  • Требуется оборот за текущие сутки — {r['req_today']:.2f} {config.CURRENCY_SYMBOL}")
    if r.get("req_total", 0) > 0:
        req_lines.append(f"  • Требуется оборот за все время — {r['req_total']:.2f} {config.CURRENCY_SYMBOL}")
    if r.get("req_dep", 0) > 0:
        req_lines.append(f"  • Требуется общий депозит — {r['req_dep']:.2f} {config.CURRENCY_SYMBOL}")
    
    req_block = ("\n<b>Условия участия:</b>\n" + "\n".join(req_lines) + "\n") if req_lines else ""
    
    lines = []
    for i in range(RAFFLE_SLOTS):
        if i < len(parts):
            p = parts[i]
            un = f"<a href='tg://user?id={p['user_id']}'>{p.get('first_name') or p.get('username') or str(p['user_id'])}</a>"
            lines.append(f"  {i + 1}. {un}")
        else:
            lines.append(f"  {i + 1}. —")
    
    return (
        f"🎁 <b>Розыгрыш #{rid}</b>\n\n"
        f"💰 Приз: <b>{r['prize']:.2f} {config.CURRENCY_SYMBOL}</b>\n"
        f"👥 Участников: {len(parts)}/{RAFFLE_SLOTS}\n"
        f"{req_block}\n"
        f"<b>Список игроков:</b>\n" + "\n".join(lines) + "\n\n"
        f"Нажмите кнопку ниже, чтобы участвовать."
    )


async def check_raffle_requirements(client: FocusPayClient, user_id: int, r: dict) -> Tuple[bool, str]:
    """Возвращает (True, '') если участник подходит под условия, иначе (False, err_msg)."""
    # В реальной версии здесь нужно запросить статистику пользователя из FocusPay API
    # Пока упрощённо — разрешаем всем (TODO: добавить эндпоинт для получения turnover/deposits)
    # Для прототипа считаем что все условия выполнены
    return True, ""


# ==================== HANDLERS ====================

def register_raffle_handlers(bot: AsyncTeleBot, client: FocusPayClient, chat_id: Optional[int]):
    """Регистрирует raffle только при наличии безопасного расчётного контура."""
    if not config.RAFFLE_ENABLED:
        return

    """Регистрирует все обработчики Raffle."""

    @bot.message_handler(commands=["fast"])
    async def cmd_fast(message):
        """Создать розыгрыш (только админ в групповом чате)."""
        if message.from_user.id not in config.ADMIN_IDS:
            await bot.reply_to(message, "❌ Нет доступа.")
            return
        
        if message.chat.type == "private":
            await bot.reply_to(message, "❌ Команда работает только в групповом чате.")
            return
        
        if chat_id and message.chat.id != chat_id:
            await bot.reply_to(message, "❌ Только в официальном чате.")
            return
        
        parts = message.text.split()
        parsed, err = parse_fast_args(parts)
        if err:
            await bot.reply_to(message, err, parse_mode="HTML")
            return
        
        admin_id = message.from_user.id
        active_count = sum(
            1 for r in active_raffles.values()
            if r["admin_id"] == admin_id and r["status"] == "waiting"
        )
        if active_count >= MAX_ADMIN_RAFFLES:
            await bot.reply_to(message, f"❌ Достигнут лимит активных розыгрышей ({MAX_ADMIN_RAFFLES}).")
            return
        
        prize = parsed["prize"]
        
        # Hold баланса админа
        try:
            hold_result = await client.hold_balance(admin_id, prize, "raffle_create")
        except Exception as e:
            await bot.reply_to(message, "❌ Действие временно недоступно. Попробуйте ещё раз позже.")
            return
        
        global raffle_counter
        async with raffle_counter_lock:
            raffle_counter += 1
            rid = raffle_counter
        
        rd = {
            "raffle_id": rid,
            "admin_id": admin_id,
            "prize": prize,
            "hold_id": hold_result.get("hold_id"),
            "chat_id": message.chat.id,
            "message_id": 0,
            "participants": [],
            "req_today": parsed["req_today"],
            "req_total": parsed["req_total"],
            "req_dep": parsed["req_dep"],
            "status": "waiting",
            "created_at": datetime.utcnow(),
        }
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🎫 Участвовать", callback_data=f"raffle_{rid}"))
        
        try:
            sent = await bot.send_message(
                message.chat.id,
                build_raffle_text(rd, rid),
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception as e:
            # Вернуть баланс админу
            try:
                await client.release_bet(admin_id, hold_result.get("hold_id"))
            except Exception:
                pass
            await bot.reply_to(message, "❌ Действие временно недоступно. Попробуйте ещё раз позже.")
            return
        
        rd["message_id"] = sent.message_id
        active_raffles[rid] = rd

    @bot.callback_query_handler(func=lambda c: c.data.startswith("raffle_"))
    async def cb_raffle_join(call):
        """Присоединиться к розыгрышу."""
        try:
            rid = int(call.data.split("_")[1])
        except (ValueError, IndexError):
            return
        
        if rid not in active_raffles:
            await bot.answer_callback_query(call.id, "❌ Розыгрыш не найден.", show_alert=True)
            return
        
        full = False
        async with get_raffle_lock(rid):
            r = active_raffles.get(rid)
            if not r or r["status"] != "waiting":
                await bot.answer_callback_query(call.id, "❌ Розыгрыш уже завершён.", show_alert=True)
                return
            
            uid = call.from_user.id
            if uid in config.ADMIN_IDS:
                await bot.answer_callback_query(call.id, "❌ Администратор не может участвовать в розыгрышах.", show_alert=True)
                return
            
            for p in r["participants"]:
                if p["user_id"] == uid:
                    await bot.answer_callback_query(call.id, "❌ Вы уже участвуете.", show_alert=True)
                    return
            
            ok, err_msg = await check_raffle_requirements(client, uid, r)
            if not ok:
                await bot.answer_callback_query(call.id, err_msg, show_alert=True)
                return
            
            r["participants"].append({
                "user_id": uid,
                "username": call.from_user.username,
                "first_name": call.from_user.first_name or "",
            })
            
            kb = call.message.reply_markup if len(r["participants"]) < RAFFLE_SLOTS else None
            try:
                await bot.edit_message_text(
                    build_raffle_text(r, rid),
                    chat_id=r["chat_id"],
                    message_id=r["message_id"],
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            except Exception:
                pass
            
            full = len(r["participants"]) >= RAFFLE_SLOTS
            if full:
                r["status"] = "rolling"
        
        await bot.answer_callback_query(call.id, "✅ Вы в розыгрыше!")
        if full:
            asyncio.create_task(resolve_raffle(bot, client, rid))

    @bot.message_handler(commands=["allfast"])
    async def cmd_allfast(message):
        """Список активных розыгрышей."""
        active = [(rid, r) for rid, r in active_raffles.items() if r["status"] == "waiting"]
        if not active:
            await bot.reply_to(message, "📭 Активных розыгрышей сейчас нет.")
            return
        
        text = "🎁 <b>Активные розыгрыши</b>\n\n"
        for rid, r in active:
            parts_count = len(r.get("participants", []))
            req_parts = []
            if r.get("req_today", 0) > 0:
                req_parts.append(f"суточ. {r['req_today']:.0f}")
            if r.get("req_total", 0) > 0:
                req_parts.append(f"общ. {r['req_total']:.0f}")
            if r.get("req_dep", 0) > 0:
                req_parts.append(f"деп. {r['req_dep']:.0f}")
            req_line = f"\n  • Условия: {', '.join(req_parts)}" if req_parts else ""
            text += (
                f"🎁 <b>Розыгрыш #{rid}</b>\n"
                f"  • Приз: {r['prize']:.2f} {config.CURRENCY_SYMBOL}\n"
                f"  • Участников: {parts_count}/{RAFFLE_SLOTS}"
                f"{req_line}\n\n"
            )
        await bot.reply_to(message, text, parse_mode="HTML")

    @bot.message_handler(commands=["delprize"])
    async def cmd_delprize(message):
        """Удалить розыгрыш (только админ)."""
        if message.from_user.id not in config.ADMIN_IDS:
            await bot.reply_to(message, "❌ Нет доступа.")
            return
        
        if message.chat.type == "private":
            await bot.reply_to(message, "❌ Работает только в групповом чате.")
            return
        
        target_rid, target_r = None, None
        args = message.text.split()
        
        if len(args) >= 2:
            arg = args[1].lstrip("#").replace(".", "")
            try:
                rid_arg = int(arg)
                if rid_arg in active_raffles and active_raffles[rid_arg]["status"] == "waiting":
                    target_rid, target_r = rid_arg, active_raffles[rid_arg]
            except ValueError:
                pass
            if not target_r:
                await bot.reply_to(message, f"❌ Активный розыгрыш #{args[1]} не найден.")
                return
        elif message.reply_to_message:
            reply_id = message.reply_to_message.message_id
            for rid, r in active_raffles.items():
                if r["message_id"] == reply_id and r["status"] == "waiting":
                    target_rid, target_r = rid, r
                    break
            if not target_r:
                await bot.reply_to(message, "❌ Активный розыгрыш не найден.")
                return
        else:
            await bot.reply_to(
                message,
                "❌ Использование:\n"
                "• <code>/delprize #номер</code>\n"
                "• <code>/delprize</code> в ответ на сообщение с розыгрышем",
                parse_mode="HTML",
            )
            return
        
        admin_id = target_r["admin_id"]
        prize = target_r["prize"]
        
        async with get_raffle_lock(target_rid):
            if target_rid not in active_raffles or active_raffles[target_rid]["status"] != "waiting":
                await bot.reply_to(message, "❌ Розыгрыш уже неактивен.")
                return
            
            # Release hold
            try:
                await client.release_bet(admin_id, target_r["hold_id"])
            except Exception as e:
                print(f"[raffle] Release error on delprize #{target_rid}: {e}")
            
            try:
                await bot.delete_message(target_r["chat_id"], target_r["message_id"])
            except Exception:
                pass
            
            active_raffles.pop(target_rid, None)
        
        await bot.reply_to(
            message,
            f"✅ Розыгрыш #{target_rid} удалён. Приз {prize:.2f} {config.CURRENCY_SYMBOL} возвращён админу",
            parse_mode="HTML",
        )


async def resolve_raffle(bot: AsyncTeleBot, client: FocusPayClient, rid: int):
    """Разрешить розыгрыш — бросить кубик и выплатить победителю."""
    async with get_raffle_lock(rid):
        r = active_raffles.get(rid)
        if not r:
            return
        
        # Убрать кнопку
        try:
            await bot.edit_message_reply_markup(chat_id=r["chat_id"], message_id=r["message_id"], reply_markup=None)
        except Exception:
            pass
        
        # Бросить кубик
        dice_value = _secure_random.randint(1, 6)
        dice_msg = None
        for attempt in range(3):
            try:
                dice_msg = await bot.send_dice(chat_id=r["chat_id"], emoji="🎲", reply_to_message_id=r["message_id"])
                dice_value = dice_msg.dice.value
                break
            except Exception as e:
                print(f"[raffle] Попытка {attempt + 1}/3 бросить кубик #{rid} не удалась: {e}")
                await asyncio.sleep(3)
        
        if dice_msg is None:
            print(f"[raffle] Кубик #{rid} не отправлен, используется локальный random ({dice_value}).")
    
    if dice_msg is not None:
        await asyncio.sleep(4)
    
    async with get_raffle_lock(rid):
        r = active_raffles.get(rid)
        if not r:
            return
        
        parts = r["participants"]
        winner = parts[dice_value - 1]
        winner_id = winner["user_id"]
        winner_name = winner.get("first_name") or winner.get("username") or str(winner_id)
        winner_link = f"<a href='tg://user?id={winner_id}'>{winner_name}</a>"
        
        # Confirm hold админа и выплата победителю
        try:
            await client.confirm_bet(r["admin_id"], r["hold_id"], f"raffle_{rid}")
        except Exception as e:
            print(f"[raffle] Confirm error #{rid}: {e}")
        
        try:
            await client.payout(winner_id, r["prize"], f"raffle_win_{rid}")
        except Exception as e:
            print(f"[raffle] Payout error #{rid}: {e}")
        
        # Отправить результат
        reply_to_id = dice_msg.message_id if dice_msg else r["message_id"]
        for attempt in range(10):
            try:
                await bot.send_message(
                    r["chat_id"],
                    f"🏆 Победитель {winner_link}, приз {r['prize']:.2f} {config.CURRENCY_SYMBOL}",
                    reply_to_message_id=reply_to_id,
                    parse_mode="HTML",
                )
                break
            except Exception as e:
                print(f"[raffle] Попытка {attempt + 1}/10 отправить результат #{rid} не удалась: {e}")
                await asyncio.sleep(5)
        
        active_raffles.pop(rid, None)


# ==================== ФОНОВЫЙ ОЧИСТИТЕЛЬ ====================

async def raffle_cleaner(bot: AsyncTeleBot, client: FocusPayClient):
    """Очищать legacy-розыгрыши только при включённом безопасном контуре."""
    if not config.RAFFLE_ENABLED:
        return

    """Фоновый очиститель: отменяет розыгрыши, которые не собрали участников за N часов."""
    while True:
        try:
            await asyncio.sleep(300)
            now = datetime.utcnow()
            for rid, r in list(active_raffles.items()):
                if r["status"] != "waiting":
                    continue
                if (now - r["created_at"]).total_seconds() < RAFFLE_TIMEOUT_HOURS * 3600:
                    continue
                
                async with get_raffle_lock(rid):
                    if rid not in active_raffles or active_raffles[rid]["status"] != "waiting":
                        continue
                    r = active_raffles[rid]
                    
                    # Release hold админа
                    try:
                        await client.release_bet(r["admin_id"], r["hold_id"])
                    except Exception as e:
                        print(f"[raffle] Release error timeout #{rid}: {e}")
                    
                    try:
                        await bot.send_message(
                            r["chat_id"],
                            "❌ Розыгрыш отменен по причине: нехватка участников в течение 3-х часов",
                            reply_to_message_id=r["message_id"],
                        )
                    except Exception:
                        pass
                    
                    try:
                        await bot.delete_message(r["chat_id"], r["message_id"])
                    except Exception:
                        pass
                    
                    active_raffles.pop(rid, None)
                    print(f"[raffle_cleaner] Розыгрыш #{rid} отменён.")
        except Exception as e:
            print(f"[raffle_cleaner] Ошибка: {e}")
