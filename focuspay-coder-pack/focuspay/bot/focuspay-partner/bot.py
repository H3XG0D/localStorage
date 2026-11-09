"""
Focus Pay — партнёрский бот + Telegram Mini App (тестовая версия).
aiogram 3.x + aiohttp + SQLite. Запуск: python bot.py
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import re
import secrets
import urllib.parse
from pathlib import Path

import aiohttp

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardButton,
    InlineKeyboardMarkup, KeyboardButton, MenuButtonWebApp, Message,
    ReplyKeyboardMarkup, WebAppInfo,
)
from dotenv import load_dotenv

import animate
import banner_video
import banners
import brand
import exchange_link

# ───────────────────────── Настройки ─────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
EXCHANGE_TG = os.getenv("EXCHANGE_TG", "@focuspay")
SUPPORT_TG = os.getenv("SUPPORT_TG", "@support")
RATE = int(os.getenv("RATE_PER_1K", "18"))
RATE_BROKER = int(os.getenv("RATE_BROKER", "20"))
MIN_VIEWS = int(os.getenv("MIN_VIEWS", "10000"))
MIN_PAYOUT = int(os.getenv("MIN_PAYOUT", "2000"))
REF_PCT = int(os.getenv("REF_PCT", "7"))
REF_DAYS = int(os.getenv("REF_DAYS", "30"))
DB_PATH = os.getenv("DB_PATH", "focuspay.db")
MATERIALS_DIR = Path(os.getenv("MATERIALS_DIR", "materials"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"   # открыть приложение в обычном браузере без Telegram
BASE = Path(__file__).parent
BOT_USERNAME = ""

# Трафик в обменник
EXCHANGE_BOT = os.getenv("EXCHANGE_BOT", EXCHANGE_TG).lstrip("@")
TRACK_SECRET = os.getenv("TRACK_SECRET", "")
CLIENT_REWARD = int(os.getenv("CLIENT_REWARD", "0"))       # ₽ автору за первый обмен клиента (0 — не платим)
# Бонусы удержания (0 — выключено)
FIRST_BONUS = int(os.getenv("FIRST_BONUS", "200"))
MILESTONE_N = int(os.getenv("MILESTONE_N", "100"))          # каждые N принятых роликов…
MILESTONE_BONUS = int(os.getenv("MILESTONE_BONUS", "1000"))  # …бонус, ₽
# Автопроверка
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "0") == "1"
AUTO_MAX = int(os.getenv("AUTO_MAX", "3000"))
# ИИ-поддержка
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
# Фирменный баннер: где плашка для промокода (доли кадра) и когда показывать (сек)
BRAND_X0 = float(os.getenv("BRAND_X0", "0.0526"))
BRAND_Y0 = float(os.getenv("BRAND_Y0", "0.8907"))
BRAND_X1 = float(os.getenv("BRAND_X1", "0.6063"))
BRAND_Y1 = float(os.getenv("BRAND_Y1", "0.9685"))
BRAND_FROM = float(os.getenv("BRAND_FROM", "1.6"))
BRAND_TO = float(os.getenv("BRAND_TO", "0"))
VOICE_AT = float(os.getenv("VOICE_AT", "0.3"))
# Промокоды для клиентов обменника
PROMO_ON = int(os.getenv("PROMO_ON", "1"))                       # 1 — промокоды работают, 0 — выключены у всех
PROMO_DISCOUNT = int(os.getenv("PROMO_DISCOUNT", "200"))         # скидка клиенту на обмен, ₽
PROMO_CASHBACK_DAYS = int(os.getenv("PROMO_CASHBACK_DAYS", "30"))  # сколько дней действует кэшбэк
PROMO_BUDGET = int(os.getenv("PROMO_BUDGET", "20000"))           # бюджет кэшбэка в месяц, ₽ (0 — без лимита)
PROMO_MAX_TG_ID = int(os.getenv("PROMO_MAX_TG_ID", "0"))         # отсекать слишком новые аккаунты (ID больше N), 0 — выкл
PROMO_MIN_AMOUNT = int(os.getenv("PROMO_MIN_AMOUNT", "3000"))    # минимальная сумма обмена, ₽
PROMO_DAILY_LIMIT = int(os.getenv("PROMO_DAILY_LIMIT", "20"))    # применений одного кода в сутки
PROMO_SPIKE = int(os.getenv("PROMO_SPIKE", "8"))                 # применений за час → код на паузу
PROMO_MODE = int(os.getenv("PROMO_MODE", "0"))                   # 0 — скидка сразу, 1 — кэшбэк на второй обмен
PROMO_MAX_USES = int(os.getenv("PROMO_MAX_USES", "100"))         # активаций на один код
PROMO_CODE_DAYS = int(os.getenv("PROMO_CODE_DAYS", "14"))        # код живёт дней
PROMO_NEW_EVERY = int(os.getenv("PROMO_NEW_EVERY", "3"))         # новый код не чаще чем раз в N дней (если старый не кончился)
PROMO_ACTIVE_MAX = int(os.getenv("PROMO_ACTIVE_MAX", "2"))       # одновременно живых кодов у автора
AUTHORS_CHAT = os.getenv("AUTHORS_CHAT", "")
PF_SHORT = {"tiktok": "tt", "reels": "ig", "shorts": "yt", "vk": "vk"}
SHORT_PF = {v: k for k, v in PF_SHORT.items()}

PLATFORMS = {
    "tiktok": ("TikTok", ("tiktok.com",)),
    "reels": ("Instagram Reels", ("instagram.com",)),
    "shorts": ("YouTube Shorts", ("youtube.com", "youtu.be")),
    "vk": ("VK Клипы", ("vk.com", "vkvideo.ru", "vk.ru")),
}
METHODS = {"sbp": "СБП / карта", "usdt": "USDT TRC-20", "ton": "TON"}
REJECT_REASONS = {
    "low": "меньше порога просмотров",
    "noins": "нет баннеров Focus Pay или они обрезаны / без звука / не там, где нужно",
    "fake": "накрутка",
    "dup": "дубль / чужой ролик",
    "other": "не соответствует правилам",
}
# (название, с каких просмотров, ставка, бонус)
LEVELS = [
    ("Новичок", 0, RATE, "Базовая ставка"),
    ("Трейдер", 100_000, RATE, "Проверка заявок за 12 часов"),
    ("Брокер", 1_000_000, RATE_BROKER, "Ставка выше и выплаты вне очереди"),
]


def sp(n) -> str:
    return f"{n:,}".replace(",", " ")


def calc(views: int, rate: int = RATE) -> int:
    return 0 if views < MIN_VIEWS else (views // 1000) * rate


def norm_url(url: str) -> str:
    url = url.strip()
    yt = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if yt and ("youtu" in url.lower()):
        return "https://youtube.com/shorts/" + yt.group(1)
    url = url.split("?")[0].split("#")[0].rstrip("/")
    m = re.match(r"(https?://)([^/]+)(.*)", url)
    if not m:
        return url
    host = m.group(2).lower()
    for pre in ("www.", "m.", "vm."):
        if host.startswith(pre) and pre != "vm.":
            host = host[len(pre):]
    return m.group(1).lower() + host + m.group(3)


def build_rules() -> str:
    return f"""<b>📜 Правила партнёрки Focus Pay</b>

<b>Суть.</b> Вставляешь нашу озвучку и баннер в свой ролик. Ролик набрал от {sp(MIN_VIEWS)} просмотров — платим {RATE} ₽ за каждую полную 1 000 (на уровне «Брокер» — {RATE_BROKER} ₽).

<b>1. Что обязательно в ролике</b>
• <b>Баннер сверху</b> — маленькая плашка Focus Pay вверху кадра на весь ролик (минимум 80% времени), не перекрывает лица и субтитры;
• <b>Баннер в центре</b> — карточка Focus Pay со звуком (25% экрана, 6 сек) в середине ролика: между 30% и 70% длительности, целиком, без обрезки и ускорения, звук не тише основного;
• оба баннера — твои персональные, с твоим промокодом (кнопка «Материалы»);
• ролик цельный, не разбитый на части (1/2, 2/2); один ролик — один рекламодатель.

<b>2. Площадки:</b> TikTok, Instagram Reels, YouTube Shorts, VK Клипы.

<b>3. Как считаем</b>
• порог {sp(MIN_VIEWS)} просмотров;
• считаем полные тысячи: 10 900 = 10 000;
• просмотры фиксируются на момент проверки, доначислений за рост нет;
• один ролик = одна заявка.

<b>4. Запрещено</b>
• накрутка (первый раз — отказ, второй — бан);
• один ролик с разных аккаунтов, чужие ролики;
• другие обменники в кадре;
• обещания дохода зрителям.

<b>5. Вывод</b>
• СБП / карта, USDT TRC-20 или TON;
• минимум {sp(MIN_PAYOUT)} ₽, срок 24–48 часов.

<b>6. Промокод</b>
• у тебя личный промокод на {PROMO_MAX_USES} активаций — он на твоих баннерах; на обменнике включается после первого принятого ролика;
• кончились активации — бери новый код в «Материалах» (новые коды — после первого принятого ролика);
• {"новый клиент меняет по твоему коду (от " + sp(PROMO_MIN_AMOUNT) + " ₽) и получает кэшбэк " + str(PROMO_DISCOUNT) + " ₽ на второй обмен" if PROMO_MODE else "новый клиент получает скидку " + str(PROMO_DISCOUNT) + " ₽ на обмен от " + sp(PROMO_MIN_AMOUNT) + " ₽"} — один раз на человека и на одни реквизиты;
• применять свой код самому, со вторых аккаунтов или через знакомых запрещено — код блокируется, автор получает бан;
• код с подозрительной активностью автоматически ставится на паузу до проверки.

<b>7. Рефералы</b>
• {REF_PCT}% от выплат приглашённого автора в первые {REF_DAYS} дней; у друга ставка не уменьшается.

<b>8. Важно</b>
• ролик — реклама, не скрывай это; ставь пометку, если требует площадка;
• за блокировку аккаунта площадкой не отвечаем.

Обменник: {EXCHANGE_TG}
Поддержка: {SUPPORT_TG}"""


RULES = build_rules()

# ───────────────────────── База ─────────────────────────
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, accepted INTEGER DEFAULT 0,
  balance INTEGER DEFAULT 0, earned INTEGER DEFAULT 0,
  strikes INTEGER DEFAULT 0, banned INTEGER DEFAULT 0, created INTEGER);
CREATE TABLE IF NOT EXISTS videos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, platform TEXT,
  url TEXT UNIQUE, views_claimed INTEGER, views_final INTEGER,
  amount INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', reason TEXT,
  screenshot TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS payouts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, method TEXT,
  details TEXT, amount INTEGER, status TEXT DEFAULT 'pending', created INTEGER);
""")
for sql in ("ALTER TABLE users ADD COLUMN first_name TEXT",
            "ALTER TABLE users ADD COLUMN referrer_id INTEGER",
            "ALTER TABLE users ADD COLUMN ref_earned INTEGER DEFAULT 0",
            "ALTER TABLE videos ADD COLUMN decided INTEGER",
            "ALTER TABLE users ADD COLUMN promo TEXT",
            "ALTER TABLE videos ADD COLUMN api_views INTEGER",
            "ALTER TABLE videos ADD COLUMN likes INTEGER",
            "ALTER TABLE videos ADD COLUMN comments INTEGER",
            "ALTER TABLE videos ADD COLUMN flags TEXT",
            "ALTER TABLE videos ADD COLUMN auto INTEGER DEFAULT 0",
            "ALTER TABLE payouts ADD COLUMN decided INTEGER",
            "ALTER TABLE clients ADD COLUMN profit INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN voice TEXT",
            "ALTER TABLE users ADD COLUMN promo_paused INTEGER DEFAULT 0",
            "ALTER TABLE promo_uses ADD COLUMN kind TEXT DEFAULT 'first'"):
    try:
        db.execute(sql)
    except sqlite3.OperationalError:
        pass
db.executescript("""
CREATE TABLE IF NOT EXISTS clients(
  client_id INTEGER PRIMARY KEY, author_id INTEGER, platform TEXT, source TEXT,
  created INTEGER, exchanges INTEGER DEFAULT 0, volume INTEGER DEFAULT 0, first_exchange INTEGER, profit INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS bonuses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, amount INTEGER, note TEXT, created INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS users_promo ON users(promo);
CREATE TABLE IF NOT EXISTS ideas(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, status TEXT DEFAULT 'new', created INTEGER);
CREATE TABLE IF NOT EXISTS idea_likes(idea_id INTEGER, user_id INTEGER, PRIMARY KEY(idea_id, user_id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, client_id INTEGER, amount INTEGER, created INTEGER);
CREATE TABLE IF NOT EXISTS promo_uses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, author_id INTEGER, client_key TEXT, payer_hash TEXT,
  order_id TEXT UNIQUE, amount INTEGER, discount INTEGER, profit INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
  source TEXT, operator_id INTEGER, created INTEGER, completed INTEGER, kind TEXT DEFAULT 'first');
CREATE INDEX IF NOT EXISTS pu_code ON promo_uses(code, created);
CREATE INDEX IF NOT EXISTS pu_client ON promo_uses(client_key);
CREATE INDEX IF NOT EXISTS pu_payer ON promo_uses(payer_hash);
CREATE TABLE IF NOT EXISTS promo_checks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, client_key TEXT, payer_hash TEXT, amount INTEGER,
  ok INTEGER, reason TEXT, source TEXT, created INTEGER);
CREATE INDEX IF NOT EXISTS pc_created ON promo_checks(created);
CREATE TABLE IF NOT EXISTS operators(id INTEGER PRIMARY KEY, name TEXT, added INTEGER);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY, name TEXT, added INTEGER);
CREATE TABLE IF NOT EXISTS promo_codes(
  code TEXT PRIMARY KEY, author_id INTEGER, max_uses INTEGER, created INTEGER, expires INTEGER,
  paused INTEGER DEFAULT 0, closed INTEGER DEFAULT 0, notified INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS pcd_author ON promo_codes(author_id, created);
""")
for _sql in (
    "ALTER TABLE videos ADD COLUMN promo TEXT",
    "ALTER TABLE promo_codes ADD COLUMN exchange_synced INTEGER DEFAULT 0",
):
    try:
        db.execute(_sql)
    except sqlite3.OperationalError:
        pass
try:
    db.execute("ALTER TABLE promo_uses ADD COLUMN kind TEXT DEFAULT 'first'")
except sqlite3.OperationalError:
    pass
db.commit()


def q(sql, *args, one=False):
    cur = db.execute(sql, args)
    db.commit()
    return cur.fetchone() if one else cur.fetchall()


# Настройки, которые можно менять из админки без перезапуска (перекрывают .env)
EDITABLE = {
    "RATE": ("Ставка за 1 000 просмотров, ₽", int), "RATE_BROKER": ("Ставка уровня «Брокер», ₽", int),
    "MIN_VIEWS": ("Порог просмотров для заявки", int), "MIN_PAYOUT": ("Минимум вывода, ₽", int),
    "REF_PCT": ("Рефералка, % от выплат друга", int), "CLIENT_REWARD": ("Автору за нового клиента, ₽", int),
    "FIRST_BONUS": ("Бонус за первый ролик, ₽", int), "MILESTONE_N": ("Бонус каждые N роликов: N", int),
    "MILESTONE_BONUS": ("Бонус каждые N роликов: сумма, ₽", int), "AUTO_APPROVE": ("Автоприём YouTube (1/0)", int),
    "AUTO_MAX": ("Автоприём: максимум, ₽", int),
    "PROMO_ON": ("Промокоды включены (1/0)", int),
    "PROMO_MODE": ("Режим: 0 — скидка сразу, 1 — кэшбэк на второй обмен", int),
    "PROMO_MAX_USES": ("Активаций на один код", int),
    "PROMO_CODE_DAYS": ("Код живёт, дней", int),
    "PROMO_NEW_EVERY": ("Новый код не чаще, чем раз в N дней", int),
    "PROMO_ACTIVE_MAX": ("Живых кодов у автора одновременно", int),
    "PROMO_DISCOUNT": ("Скидка / кэшбэк клиенту, ₽", int),
    "PROMO_CASHBACK_DAYS": ("Кэшбэк действует, дней", int),
    "PROMO_BUDGET": ("Бюджет кэшбэка в месяц, ₽ (0 — без лимита)", int),
    "PROMO_MAX_TG_ID": ("Отсекать новые аккаунты: Telegram ID больше (0 — выкл)", int),
    "PROMO_MIN_AMOUNT": ("Промокод: минимальная сумма обмена, ₽", int),
    "PROMO_DAILY_LIMIT": ("Промокод: применений в сутки на один код", int),
    "PROMO_SPIKE": ("Промокод: применений за час → автопауза", int),
    "BRAND_FROM": ("Фирм. баннер: промокод появляется на секунде", float),
    "BRAND_TO": ("Фирм. баннер: промокод исчезает на секунде (0 — до конца)", float),
    "VOICE_AT": ("Озвучка начинается на секунде", float),
    "BRAND_X0": ("Плашка промокода: левый край (0–1)", float),
    "BRAND_Y0": ("Плашка промокода: верх (0–1)", float),
    "BRAND_X1": ("Плашка промокода: правый край (0–1)", float),
    "BRAND_Y1": ("Плашка промокода: низ (0–1)", float),
}


def apply_settings():
    global LEVELS, RULES
    for r in q("SELECT key, value FROM settings"):
        if r["key"] in EDITABLE:
            v = EDITABLE[r["key"]][1](r["value"])
            globals()[r["key"]] = bool(v) if r["key"] == "AUTO_APPROVE" else v
    LEVELS = [("Новичок", 0, RATE, "Базовая ставка"), ("Трейдер", 100_000, RATE, "Проверка заявок за 12 часов"),
              ("Брокер", 1_000_000, RATE_BROKER, "Ставка выше и выплаты вне очереди")]
    RULES = build_rules()


def get_user(uid: int, username: str | None = None, first_name: str | None = None):
    u = q("SELECT * FROM users WHERE id=?", uid, one=True)
    if not u:
        q("INSERT INTO users(id, username, first_name, created) VALUES(?,?,?,?)",
          uid, username, first_name, int(time.time()))
        u = q("SELECT * FROM users WHERE id=?", uid, one=True)
    elif (username and u["username"] != username) or (first_name and u["first_name"] != first_name):
        q("UPDATE users SET username=COALESCE(?, username), first_name=COALESCE(?, first_name) WHERE id=?",
          username, first_name, uid)
        u = q("SELECT * FROM users WHERE id=?", uid, one=True)
    return u


def user_views(uid: int) -> int:
    return q("SELECT COALESCE(SUM(views_final),0) v FROM videos WHERE user_id=? AND status='approved'",
             uid, one=True)["v"]


def level_of(views: int) -> int:
    idx = 0
    for i, lv in enumerate(LEVELS):
        if views >= lv[1]:
            idx = i
    return idx


def level_info(uid: int) -> dict:
    views = user_views(uid)
    i = level_of(views)
    cur = LEVELS[i]
    nxt = LEVELS[i + 1] if i + 1 < len(LEVELS) else None
    pct = 100 if not nxt else round((views - cur[1]) / (nxt[1] - cur[1]) * 100)
    return {
        "idx": i, "name": cur[0], "rate": cur[2], "views": views, "pct": pct,
        "to_next": (f"до «{nxt[0]}» ещё {sp(nxt[1] - views)}" if nxt else "Максимальный уровень"),
        "hint": (f"На уровне «{nxt[0]}»: {nxt[3].lower()}, {nxt[2]} ₽ за 1 000" if nxt else "Ты на вершине"),
    }


TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["A","B","V","G","D","E","E","ZH","Z","I","Y","K","L","M","N","O","P","R","S","T","U","F","H","C","CH","SH","SCH","","Y","","E","YU","YA"]))


PROMO_STOP = ("FOCUSPAY", "FOCUS", "ADMIN", "SUPPORT", "PROMO", "BONUS", "FREE", "TEST", "OPERATOR")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"        # без похожих 0/O, 1/I/L


def _gen_code(u) -> str:
    raw = (u["username"] or u["first_name"] or "").lower()
    base = "".join(TRANSLIT.get(ch, ch.upper()) for ch in raw)
    base = re.sub(r"[^A-Z0-9]", "", base)[:8]
    if len(base) < 3 or any(w in base for w in PROMO_STOP):
        base = "FP"
    base = base[:6]
    while True:            # 3 случайных символа: код не угадать по нику
        code = base + "".join(secrets.choice(CODE_ALPHABET) for _ in range(3 if len(base) >= 4 else 4))
        if not q("SELECT 1 FROM users WHERE promo=?", code, one=True) and not q("SELECT 1 FROM promo_codes WHERE code=?", code, one=True):
            return code


def _register_code(code: str, uid: int, created: int | None = None):
    now = created or int(time.time())
    q("INSERT OR IGNORE INTO promo_codes(code, author_id, max_uses, created, expires) VALUES(?,?,?,?,?)",
      code, uid, PROMO_MAX_USES, now, now + PROMO_CODE_DAYS * 86400)


def code_uses(code: str) -> int:
    return q("SELECT COUNT(*) c FROM promo_uses WHERE code=? AND kind='first' AND status IN ('pending','done')", code, one=True)["c"]


def code_state(c) -> str:
    """active / exhausted / expired / paused / closed"""
    if c["closed"]:
        return "closed"
    if c["paused"]:
        return "paused"
    if code_uses(c["code"]) >= (c["max_uses"] or 0):
        return "exhausted"
    if c["expires"] and time.time() > c["expires"]:
        return "expired"
    return "active"


def ensure_promo(uid: int) -> str:
    """Текущий промокод автора (для баннеров). Первый выдаётся при регистрации."""
    u = q("SELECT * FROM users WHERE id=?", uid, one=True)
    if u["promo"]:
        if not q("SELECT 1 FROM promo_codes WHERE code=?", u["promo"], one=True):
            _register_code(u["promo"], uid, u["created"] or None)      # коды, выданные до лимитов
        return u["promo"]
    code = _gen_code(u)
    _register_code(code, uid)
    q("UPDATE users SET promo=? WHERE id=?", code, uid)
    return code


def can_new_code(uid: int) -> tuple[bool, str]:
    u = get_user(uid)
    if u["banned"] or u["promo_paused"]:
        return False, "Выдача кодов приостановлена — напиши в поддержку"
    if not q("SELECT 1 FROM videos WHERE user_id=? AND status='approved'", uid, one=True):
        return False, "Новые коды — после первого принятого ролика"
    codes = q("SELECT * FROM promo_codes WHERE author_id=? ORDER BY created DESC", uid)
    active = [c for c in codes if code_state(c) == "active"]
    cur = codes[0] if codes else None
    if cur and code_state(cur) == "active" and time.time() - cur["created"] < PROMO_NEW_EVERY * 86400:
        left = int((cur["created"] + PROMO_NEW_EVERY * 86400 - time.time()) // 3600) + 1
        return False, f"Новый код — через {left} ч или когда закончатся активации текущего"
    if len(active) >= PROMO_ACTIVE_MAX:
        return False, f"У тебя уже {PROMO_ACTIVE_MAX} живых кода — дождись, пока один закончится"
    return True, ""


def new_promo(uid: int) -> tuple[str | None, str]:
    ok, why = can_new_code(uid)
    if not ok:
        return None, why
    u = get_user(uid)
    code = _gen_code(u)
    _register_code(code, uid)
    q("UPDATE users SET promo=? WHERE id=?", code, uid)
    return code, ""


def promo_links(code: str) -> dict:
    return {pf: f"https://t.me/{EXCHANGE_BOT}?start=p_{code}_{short}" for pf, short in PF_SHORT.items()}


# ───────────────────────── Промокоды клиентов: правила и антиабуз ─────────────────────────
PROMO_REASONS = {
    "off": "Промокоды сейчас не действуют",
    "not_found": "Такого промокода нет",
    "paused": "Промокод приостановлен",
    "no_client": "Не указан клиент",
    "no_payer": "Укажите реквизиты клиента",
    "own": "Нельзя использовать свой промокод",
    "min_amount": "Скидка по промокоду — при обмене от {min} ₽",
    "not_new": "Промокод только для первого обмена",
    "client_used": "Этот клиент уже использовал промокод",
    "payer_used": "С этими реквизитами промокод уже использовали",
    "limit": "Лимит промокода на сегодня исчерпан",
    "new_account": "Аккаунт клиента слишком новый для промокода",
    "no_cashback": "У клиента нет кэшбэка",
    "cashback_expired": "Кэшбэк клиента истёк",
    "cashback_used": "Кэшбэк уже использован",
    "budget": "Бюджет промокодов на этот месяц исчерпан — напишите оператору",
    "exhausted": "Активации этого промокода закончились — напишите оператору, что-нибудь придумаем",
    "expired": "Срок действия промокода истёк — напишите оператору",
}
PENDING_TTL = 24 * 3600           # незавершённое применение «сгорает» через сутки


def promo_reason_text(code: str | None) -> str:
    return PROMO_REASONS.get(code or "", code or "").format(min=sp(PROMO_MIN_AMOUNT))


def client_key(v) -> str:
    """Клиент обменника: числовой Telegram ID или @username → единый ключ."""
    s_ = str(v or "").strip()
    if s_.lstrip("-").isdigit():
        return str(int(s_))
    s_ = s_.rstrip("/").split("/")[-1].lstrip("@").lower()
    return s_ if re.fullmatch(r"[a-z0-9_]{3,32}", s_) else ""


def payer_salt() -> str:
    r = q("SELECT value FROM settings WHERE key='PAYER_SALT'", one=True)
    if r:
        return r["value"]
    q("INSERT OR IGNORE INTO settings(key, value) VALUES('PAYER_SALT', ?)", secrets.token_hex(16))
    return q("SELECT value FROM settings WHERE key='PAYER_SALT'", one=True)["value"]


def payer_hash(raw) -> str | None:
    """Отпечаток реквизитов (карта, телефон, кошелёк). Сами реквизиты не храним."""
    s_ = str(raw or "").strip()
    if not s_:
        return None
    m = re.search(r"\+?\d[\d\s\-()]{8,}\d", s_)
    norm = None
    if m:
        d = re.sub(r"\D", "", m.group(0))
        if len(d) >= 10:
            norm = "7" + d[1:] if len(d) == 11 and d[0] == "8" else d
    if not norm:
        norm = re.sub(r"\s+", "", s_).lower()
    return hmac.new(payer_salt().encode(), norm.encode(), hashlib.sha256).hexdigest()[:32]


def author_payer_hashes(uid: int) -> set:
    return {payer_hash(r["details"]) for r in q("SELECT DISTINCT details FROM payouts WHERE user_id=?", uid)} - {None}


def _expire_pending():
    q("UPDATE promo_uses SET status='expired' WHERE status='pending' AND created<?", int(time.time()) - PENDING_TTL)


def _to_int(v) -> int:
    try:
        return int(float(str(v or 0).replace(" ", "").replace("\u00a0", "").replace(",", ".")))
    except ValueError:
        return 0


def promo_validate(code_raw, client_raw, amount, payer_raw=None, is_new=None, source="api", log=True) -> dict:
    """Проверка промокода по всем правилам. Ничего не резервирует."""
    _expire_pending()
    code = re.sub(r"[^A-Za-z0-9]", "", str(code_raw or "")).upper()
    ck, ph, amount = client_key(client_raw), payer_hash(payer_raw), _to_int(amount)
    pc = q("SELECT * FROM promo_codes WHERE code=?", code, one=True) if code else None
    if not pc and code:                                   # старый код без записи
        a0 = q("SELECT * FROM users WHERE promo=?", code, one=True)
        if a0:
            ensure_promo(a0["id"])
            pc = q("SELECT * FROM promo_codes WHERE code=?", code, one=True)
    author = q("SELECT * FROM users WHERE id=?", pc["author_id"], one=True) if pc else None
    now = int(time.time())
    reason, spiked = None, False
    st_ = code_state(pc) if pc else None
    if not PROMO_ON:
        reason = "off"
    elif not author or author["banned"] or not author["accepted"] or st_ == "closed":
        reason = "not_found"
    elif author["promo_paused"] or st_ == "paused":
        reason = "paused"
    elif st_ == "exhausted":
        reason = "exhausted"
    elif st_ == "expired":
        reason = "expired"
    elif not ck:
        reason = "no_client"
    elif not ph:
        reason = "no_payer"
    elif ck in (str(author["id"]), (author["username"] or "").lower()) or ph in author_payer_hashes(author["id"]):
        reason = "own"
    elif amount < PROMO_MIN_AMOUNT:
        reason = "min_amount"
    elif PROMO_MAX_TG_ID and ck.isdigit() and int(ck) > PROMO_MAX_TG_ID:
        reason = "new_account"
    elif is_new is False or (ck.isdigit() and q("SELECT 1 FROM clients WHERE client_id=? AND exchanges>0", int(ck), one=True)):
        reason = "not_new"
    elif q("SELECT 1 FROM promo_uses WHERE client_key=? AND status IN ('pending','done')", ck, one=True):
        reason = "client_used"
    elif q("SELECT 1 FROM promo_uses WHERE payer_hash=? AND client_key!=? AND status IN ('pending','done')", ph, ck, one=True):
        reason = "payer_used"
    else:
        hour = q("SELECT COUNT(*) c FROM promo_uses WHERE code=? AND kind='first' AND status IN ('pending','done') AND created>=?",
                 code, now - 3600, one=True)["c"]
        day = q("SELECT COUNT(*) c FROM promo_uses WHERE code=? AND kind='first' AND status IN ('pending','done') AND created>=?",
                code, now - 86400, one=True)["c"]
        if PROMO_SPIKE and hour >= PROMO_SPIKE:
            q("UPDATE promo_codes SET paused=1 WHERE code=?", code)
            reason, spiked = "paused", True
        elif PROMO_DAILY_LIMIT and day >= PROMO_DAILY_LIMIT:
            reason = "limit"
        elif not PROMO_MODE and PROMO_BUDGET and (q("SELECT COALESCE(SUM(discount),0) s FROM promo_uses WHERE status IN ('pending','done') "
                                                    "AND created>=?", month_start(), one=True)["s"] + PROMO_DISCOUNT > PROMO_BUDGET):
            reason = "budget"
    if log:
        q("INSERT INTO promo_checks(code, client_key, payer_hash, amount, ok, reason, source, created) VALUES(?,?,?,?,?,?,?,?)",
          code, ck, ph, amount, 0 if reason else 1, reason, source, now)
    return {"valid": reason is None, "reason": reason, "reason_text": promo_reason_text(reason) if reason else "",
            "discount": PROMO_DISCOUNT if reason is None and not PROMO_MODE else 0,
            "cashback": PROMO_DISCOUNT if reason is None and PROMO_MODE else 0, "cashback_days": PROMO_CASHBACK_DAYS,
            "mode": "cashback" if PROMO_MODE else "instant",
            "uses_left": max(0, (pc["max_uses"] or 0) - code_uses(code) - (1 if reason is None else 0)) if pc else 0,
            "min_amount": PROMO_MIN_AMOUNT, "code": code,
            "author_id": author["id"] if author else None, "author": user_label(author) if author else None,
            "client_key": ck, "payer_hash": ph, "amount": amount, "spiked": spiked}


def promo_apply(code_raw, client_raw, amount, payer_raw, order_id=None, is_new=None, source="api", operator_id=None) -> dict:
    """Проверка + закрепление скидки за заявкой (статус «ожидает обмена»). Повтор с тем же order_id безопасен."""
    oid = str(order_id or "").strip()[:64]
    if oid:
        ex = q("SELECT * FROM promo_uses WHERE order_id=?", oid, one=True)
        if ex:
            ok = ex["status"] in ("pending", "done")
            return {"valid": ok, "applied": ok, "use_id": ex["id"], "order_id": oid, "status": ex["status"],
                    "discount": ex["discount"] if ok else 0, "code": ex["code"],
                    "reason": None if ok else ex["status"], "reason_text": "" if ok else "Заявка уже закрыта"}
    r = promo_validate(code_raw, client_raw, amount, payer_raw, is_new, source)
    if not r["valid"]:
        return r
    now = int(time.time())
    cur = db.execute("INSERT INTO promo_uses(code, author_id, client_key, payer_hash, order_id, amount, discount, status, "
                     "source, operator_id, created, kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["code"], r["author_id"], r["client_key"], r["payer_hash"], oid or None, r["amount"], r.get("discount", 0),
                      "pending", source, operator_id, now, r.get("kind", "first")))
    db.commit()
    use_id = cur.lastrowid
    if not oid:
        oid = f"op{use_id}"
        q("UPDATE promo_uses SET order_id=? WHERE id=?", oid, use_id)
    if r["client_key"].isdigit() and not q("SELECT 1 FROM clients WHERE client_id=?", int(r["client_key"]), one=True):
        q("INSERT INTO clients(client_id, author_id, platform, source, created) VALUES(?,?,?,?,?)",
          int(r["client_key"]), r["author_id"], "promo", r["code"], now)
    r.update(applied=True, use_id=use_id, order_id=oid, status="pending")
    pc = q("SELECT * FROM promo_codes WHERE code=?", r["code"], one=True)
    if pc and code_state(pc) == "exhausted" and not pc["notified"]:
        q("UPDATE promo_codes SET notified=1 WHERE code=?", r["code"])
        r["exhausted_now"] = True
    return r


def month_start() -> int:
    t = time.localtime()
    return int(time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1)))


def cashback_validate(client_raw, amount, payer_raw=None, source="api", log=True) -> dict:
    """Второй обмен: есть ли у клиента кэшбэк и можно ли его применить."""
    _expire_pending()
    ck, ph, amount = client_key(client_raw), payer_hash(payer_raw), _to_int(amount)
    now = int(time.time())
    first = q("SELECT * FROM promo_uses WHERE client_key=? AND kind='first' AND status='done' ORDER BY id DESC LIMIT 1",
              ck, one=True) if ck else None
    author = q("SELECT * FROM users WHERE id=?", first["author_id"], one=True) if first else None
    reason = None
    if not PROMO_ON:
        reason = "off"
    elif not PROMO_MODE:
        reason = "no_cashback"
    elif not ck:
        reason = "no_client"
    elif not ph:
        reason = "no_payer"
    elif not first:
        reason = "no_cashback"
    elif q("SELECT 1 FROM promo_uses WHERE client_key=? AND kind='cashback' AND status IN ('pending','done')", ck, one=True):
        reason = "cashback_used"
    elif now - (first["completed"] or first["created"]) > PROMO_CASHBACK_DAYS * 86400:
        reason = "cashback_expired"
    elif not author or author["banned"] or author["promo_paused"]:
        reason = "paused"
    elif amount < PROMO_MIN_AMOUNT:
        reason = "min_amount"
    elif q("SELECT 1 FROM promo_uses WHERE payer_hash=? AND client_key!=? AND status IN ('pending','done')", ph, ck, one=True) \
            or ph in author_payer_hashes(author["id"]):
        reason = "payer_used"
    elif PROMO_BUDGET and (q("SELECT COALESCE(SUM(discount),0) s FROM promo_uses WHERE kind='cashback' AND status IN ('pending','done') "
                             "AND created>=?", month_start(), one=True)["s"] + PROMO_DISCOUNT > PROMO_BUDGET):
        reason = "budget"
    if log:
        q("INSERT INTO promo_checks(code, client_key, payer_hash, amount, ok, reason, source, created) VALUES(?,?,?,?,?,?,?,?)",
          first["code"] if first else "", ck, ph, amount, 0 if reason else 1, reason, source + ":cashback", now)
    return {"valid": reason is None, "reason": reason, "reason_text": promo_reason_text(reason) if reason else "",
            "discount": PROMO_DISCOUNT if reason is None else 0, "kind": "cashback", "code": first["code"] if first else "",
            "author_id": first["author_id"] if first else None, "author": user_label(author) if author else None,
            "client_key": ck, "payer_hash": ph, "amount": amount, "min_amount": PROMO_MIN_AMOUNT,
            "expires": (first["completed"] or first["created"]) + PROMO_CASHBACK_DAYS * 86400 if first else None}


def cashback_apply(client_raw, amount, payer_raw, order_id=None, source="api", operator_id=None) -> dict:
    oid = str(order_id or "").strip()[:64]
    if oid:
        ex = q("SELECT * FROM promo_uses WHERE order_id=?", oid, one=True)
        if ex:
            ok = ex["status"] in ("pending", "done")
            return {"valid": ok, "applied": ok, "use_id": ex["id"], "order_id": oid, "status": ex["status"], "kind": ex["kind"],
                    "discount": ex["discount"] if ok else 0, "reason": None if ok else ex["status"], "reason_text": ""}
    r = cashback_validate(client_raw, amount, payer_raw, source)
    if not r["valid"]:
        return r
    cur = db.execute("INSERT INTO promo_uses(code, author_id, client_key, payer_hash, order_id, amount, discount, status, "
                     "source, operator_id, created, kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["code"], r["author_id"], r["client_key"], r["payer_hash"], oid or None, r["amount"], r["discount"],
                      "pending", source, operator_id, int(time.time()), "cashback"))
    db.commit()
    use_id = cur.lastrowid
    if not oid:
        oid = f"cb{use_id}"
        q("UPDATE promo_uses SET order_id=? WHERE id=?", oid, use_id)
    r.update(applied=True, use_id=use_id, order_id=oid, status="pending")
    return r


def promo_finish(order_id: str, act: str, amount=None, profit=None, touch_clients=False) -> tuple[dict | None, str]:
    """act: complete — обмен прошёл; cancel — не состоялся (клиент и реквизиты снова свободны)."""
    u = q("SELECT * FROM promo_uses WHERE order_id=?", str(order_id or ""), one=True)
    if not u:
        return None, "not_found"
    now = int(time.time())
    if act == "complete":
        if u["status"] == "done":
            return dict(u), "already"
        if u["status"] == "cancelled":
            return dict(u), "cancelled"
        amt = _to_int(amount) or u["amount"]
        q("UPDATE promo_uses SET status='done', amount=?, profit=?, completed=? WHERE id=?", amt, _to_int(profit), now, u["id"])
        if touch_clients and (u["client_key"] or "").isdigit():
            cid = int(u["client_key"])
            q("UPDATE clients SET exchanges=exchanges+1, volume=volume+?, profit=profit+?, "
              "first_exchange=COALESCE(first_exchange, ?) WHERE client_id=?", amt, _to_int(profit), now, cid)
    elif act == "cancel":
        if u["status"] == "cancelled":
            return dict(u), "already"
        q("UPDATE promo_uses SET status='cancelled', completed=? WHERE id=?", now, u["id"])
    else:
        return dict(u), "bad_act"
    return dict(q("SELECT * FROM promo_uses WHERE id=?", u["id"], one=True)), "ok"


OWN_ALERTED: dict = {}


async def promo_after_check(bot: Bot, r: dict):
    """Уведомления по итогам проверки: всплеск → пауза, попытка применить свой код, код закончился."""
    if r.pop("exhausted_now", False):
        await safe_send(bot, r["author_id"], f"🎟 Все активации кода <b>{r['code']}</b> разобрали! "
                                             "Новый код — в «🎬 Материалы» (баннер обновится сам).")
    if r.pop("spiked", False):
        await promo_spike_alert(bot, r["author_id"])
    if r.get("reason") == "own" and r.get("author_id") and time.time() - OWN_ALERTED.get(r["author_id"], 0) > 86400:
        OWN_ALERTED[r["author_id"]] = time.time()
        a = get_user(r["author_id"])
        for aid in all_admins():
            await safe_send(bot, aid, f"🚩 <b>Попытка применить свой промокод</b>\nКод {a['promo']}, автор {user_label(a)} "
                                      f"<code>{a['id']}</code>. Скидка не дана. Решай: пауза кода или бан.",
                            ikb([[("⏸ Пауза кода", f"prpause:{a['id']}"), ("⛔ Бан автора", f"ban:{a['id']}")]]))
    r.pop("payer_hash", None)
    return r


async def promo_spike_alert(bot: Bot, author_id: int):
    a = get_user(author_id)
    a = dict(a)
    for aid in all_admins():
        await safe_send(bot, aid, f"⏸ <b>Промокод {a['promo']} на паузе</b> — больше {PROMO_SPIKE} применений за час.\n"
                                  f"Автор: {user_label(a)} <code>{a['id']}</code>. Проверь в админке → Промокоды.",
                        ikb([[("▶️ Снять паузу", f"prres:{a['id']}"), ("⛔ Бан автора", f"ban:{a['id']}")]]))
    await safe_send(bot, author_id, "⏸ Твой промокод временно приостановлен из-за необычной активности. "
                                    f"Мы проверим и включим его. Вопросы — {SUPPORT_TG}")


def add_bonus(uid: int, kind: str, amount: int, note: str):
    if amount <= 0:
        return
    q("INSERT INTO bonuses(user_id, kind, amount, note, created) VALUES(?,?,?,?,?)", uid, kind, amount, note, int(time.time()))
    q("UPDATE users SET balance=balance+?, earned=earned+? WHERE id=?", amount, amount, uid)


def milestone_info(uid: int) -> dict:
    total = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='approved'", uid, one=True)["c"]
    n = max(MILESTONE_N, 1)
    return {"total": total, "count": total % n, "need": n, "bonus": MILESTONE_BONUS, "on": MILESTONE_BONUS > 0}


def author_stats(uid: int) -> dict:
    v = q("SELECT COUNT(*) sub, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) ok, "
          "COALESCE(SUM(CASE WHEN status='approved' THEN views_final END),0) views FROM videos WHERE user_id=?", uid, one=True)
    paid = q("SELECT COALESCE(SUM(amount),0) s FROM payouts WHERE user_id=? AND status='paid'", uid, one=True)["s"]
    clients = q("SELECT COUNT(*) c FROM clients WHERE author_id=?", uid, one=True)["c"]
    u = get_user(uid)
    return {"submitted": v["sub"], "approved": v["ok"] or 0, "views": v["views"], "earned": u["earned"],
            "paid_out": paid, "clients": clients}


async def youtube_stats(url: str) -> dict | None:
    if not YOUTUBE_API_KEY:
        return None
    m = re.search(r"shorts/([A-Za-z0-9_-]{11})", url)
    if not m:
        return None
    api = ("https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet"
           f"&id={m.group(1)}&key={YOUTUBE_API_KEY}")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(api, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
        item = (data.get("items") or [None])[0]
        if not item:
            return {"missing": True}
        st = item.get("statistics", {})
        return {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0), "channel": item["snippet"].get("channelTitle", ""),
                "published": item["snippet"].get("publishedAt", "")}
    except Exception as e:
        logging.warning("YouTube API: %s", e)
        return None


def fraud_flags(claimed: int, st: dict | None) -> list[str]:
    flags = []
    if not st:
        return flags
    if st.get("missing"):
        return ["ролик не найден или скрыт"]
    v = st["views"]
    if v and claimed > v * 1.2:
        flags.append(f"заявлено больше, чем есть ({claimed} > {v})")
    if v >= 20000 and st["likes"] < v * 0.005:
        flags.append("очень мало лайков для таких просмотров")
    if v >= 50000 and st["comments"] == 0:
        flags.append("ноль комментариев")
    return flags


def user_label(u) -> str:
    return ("@" + u["username"]) if u["username"] else (u["first_name"] or "автор")


# ───────────────────────── Общая логика (бот + приложение) ─────────────────────────
def video_admin_kb(vid: int, uid: int):
    return ikb([
        [("✅ Принять", f"va:{vid}")],
        [("❌ <порога", f"vr:{vid}:low"), ("❌ Нет вставки", f"vr:{vid}:noins")],
        [("❌ Накрутка", f"vr:{vid}:fake"), ("❌ Дубль/чужой", f"vr:{vid}:dup")],
        [("❌ Другое", f"vr:{vid}:other"), ("⛔ Бан автора", f"ban:{uid}")],
    ])


def payout_admin_kb(pid: int):
    return ikb([[("💸 Выплачено", f"pp:{pid}"), ("↩ Отклонить", f"px:{pid}")]])


def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


async def create_video(bot: Bot, uid: int, platform: str, url: str, views: int,
                       shot_file_id: str | None = None, shot_bytes: bytes | None = None) -> tuple[bool, str, int | None]:
    if platform not in PLATFORMS:
        return False, "Неизвестная площадка", None
    if not url.startswith("http") or not any(d in url.lower() for d in PLATFORMS[platform][1]):
        return False, "Ссылка не с выбранной площадки", None
    nurl = norm_url(url)
    if q("SELECT id FROM videos WHERE url=?", nurl, one=True):
        return False, "Этот ролик уже сдавали", None
    if views < MIN_VIEWS:
        return False, f"Нужно от {sp(MIN_VIEWS)} просмотров", None
    st = await youtube_stats(nurl) if platform == "shorts" else None
    flags = fraud_flags(views, st)
    cur_code = q("SELECT promo FROM users WHERE id=?", uid, one=True)["promo"]
    q("INSERT INTO videos(user_id, platform, url, views_claimed, screenshot, created, api_views, likes, comments, flags)"
      " VALUES(?,?,?,?,?,?,?,?,?,?)", uid, platform, nurl, views, shot_file_id, int(time.time()),
      (st or {}).get("views"), (st or {}).get("likes"), (st or {}).get("comments"), "; ".join(flags) or None)
    vid = q("SELECT id FROM videos WHERE url=?", nurl, one=True)["id"]
    q("UPDATE videos SET promo=? WHERE id=?", cur_code, vid)
    u = get_user(uid)
    lv = level_info(uid)
    caption = (f"🎬 <b>Заявка #{vid}</b>\n"
               f"Автор: {user_label(u)} <code>{uid}</code> · {lv['name']}\n"
               f"Нарушений: {u['strikes']}\n"
               f"Площадка: {PLATFORMS[platform][0]}\n"
               f"Ссылка: {nurl}\n"
               f"Заявлено: {sp(views)} → {sp(calc(views, lv['rate']))} ₽")
    if st and not st.get("missing"):
        caption += (f"\n\n🤖 <b>YouTube API:</b> {sp(st['views'])} просм., {sp(st['likes'])} лайков, "
                    f"{sp(st['comments'])} комм.\nКанал: {st['channel']}")
    if flags:
        caption += "\n⚠️ <b>Подозрительно:</b> " + "; ".join(flags)
    # Автоприём: только YouTube с данными API, без флагов, небольшая сумма
    if AUTO_APPROVE and st and not st.get("missing") and not flags and u["strikes"] == 0:
        amount = calc(st["views"], lv["rate"])
        if 0 < amount <= AUTO_MAX:
            q("UPDATE videos SET auto=1 WHERE id=?", vid)
            res = await approve_video(bot, vid, st["views"])
            for aid in all_admins():
                await safe_send(bot, aid, caption + f"\n\n✅ <b>Принято автоматически.</b> {res}\n"
                                "Вставку (озвучка/баннер) автоматика пока не проверяет — загляни выборочно.",
                                ikb([[("⛔ Бан автора", f"ban:{uid}")]]))
            return True, "ok", vid
    for aid in all_admins():
        try:
            if shot_bytes:
                m = await bot.send_photo(aid, BufferedInputFile(shot_bytes, "shot.jpg"),
                                         caption=caption, reply_markup=video_admin_kb(vid, uid))
                if not shot_file_id:
                    shot_file_id = m.photo[-1].file_id
                    q("UPDATE videos SET screenshot=? WHERE id=?", shot_file_id, vid)
            elif shot_file_id:
                await bot.send_photo(aid, shot_file_id, caption=caption, reply_markup=video_admin_kb(vid, uid))
            else:
                await bot.send_message(aid, caption, reply_markup=video_admin_kb(vid, uid))
        except Exception as e:
            logging.warning("Не смог написать админу %s: %s", aid, e)
    return True, "ok", vid


async def approve_video(bot: Bot, vid: int, views: int) -> str:
    v = q("SELECT * FROM videos WHERE id=?", vid, one=True)
    if not v or v["status"] != "pending":
        return "Заявка уже обработана."
    rate = level_info(v["user_id"])["rate"]
    amount = calc(views, rate)
    now = int(time.time())
    if amount == 0:
        q("UPDATE videos SET status='rejected', views_final=?, reason=?, decided=? WHERE id=?",
          views, REJECT_REASONS["low"], now, vid)
        await safe_send(bot, v["user_id"], f"❌ Заявка #{vid} отклонена: по факту {sp(views)} просмотров, "
                                            f"это ниже порога {sp(MIN_VIEWS)}.")
        return f"#{vid}: {sp(views)} < порога — отклонено."
    q("UPDATE videos SET status='approved', views_final=?, amount=?, decided=? WHERE id=?", views, amount, now, vid)
    q("UPDATE users SET balance=balance+?, earned=earned+? WHERE id=?", amount, amount, v["user_id"])
    await safe_send(bot, v["user_id"], f"✅ Заявка #{vid} принята: {sp(views)} просмотров → <b>+{sp(amount)} ₽</b>.")
    uid = v["user_id"]
    approved = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='approved'", uid, one=True)["c"]
    if approved == 1 and FIRST_BONUS > 0:
        add_bonus(uid, "first", FIRST_BONUS, "первый принятый ролик")
        await safe_send(bot, uid, f"🎁 Бонус за первый ролик: +{sp(FIRST_BONUS)} ₽. Добро пожаловать!")
    if approved == 1:
        ensure_promo(uid)
        code = exchange_link.lock_first_video_coupon(db, uid, max_uses=PROMO_MAX_USES)
        if code:
            q("UPDATE videos SET promo=? WHERE id=?", code, vid)
            await sync_author_coupon(bot, uid, code, vid, "first_video")
    if MILESTONE_BONUS > 0 and MILESTONE_N > 0 and approved % MILESTONE_N == 0:
        add_bonus(uid, "milestone", MILESTONE_BONUS, f"{approved} принятых роликов")
        await safe_send(bot, uid, f"🏆 {approved} принятых роликов! Бонус +{sp(MILESTONE_BONUS)} ₽.")
    # реферальное начисление
    u = get_user(v["user_id"])
    if u["referrer_id"] and now - (u["created"] or now) <= REF_DAYS * 86400:
        bonus = amount * REF_PCT // 100
        if bonus > 0:
            q("UPDATE users SET balance=balance+?, earned=earned+?, ref_earned=ref_earned+? WHERE id=?",
              bonus, bonus, bonus, u["referrer_id"])
            await safe_send(bot, u["referrer_id"], f"🤝 Реферальный бонус: +{sp(bonus)} ₽ за ролик приглашённого автора.")
    return f"✅ #{vid} принята: {sp(views)} просмотров → {sp(amount)} ₽ (ставка {rate} ₽)"


async def create_payout(bot: Bot, uid: int, method: str, details: str, amount: int) -> tuple[bool, str, int | None]:
    u = get_user(uid)
    details = (details or "").strip()
    if method not in METHODS:
        return False, "Выбери способ вывода", None
    if len(details) < 6:
        return False, "Реквизиты неполные", None
    if method == "usdt" and not (details.startswith("T") and len(details) == 34):
        return False, "Адрес TRC-20 должен начинаться с T и быть 34 символа", None
    if amount < MIN_PAYOUT or amount > u["balance"]:
        return False, f"Сумма от {sp(MIN_PAYOUT)} до {sp(u['balance'])} ₽", None
    q("UPDATE users SET balance=balance-? WHERE id=?", amount, uid)
    q("INSERT INTO payouts(user_id, method, details, amount, created) VALUES(?,?,?,?,?)",
      uid, method, details, amount, int(time.time()))
    pid = q("SELECT MAX(id) m FROM payouts WHERE user_id=?", uid, one=True)["m"]
    lv = level_info(uid)
    vip = " ⭐ ВНЕ ОЧЕРЕДИ (Брокер)" if lv["idx"] == len(LEVELS) - 1 else ""
    for aid in all_admins():
        await safe_send(bot, aid,
                        f"💸 <b>Вывод #{pid}</b>{vip}\nАвтор: {user_label(u)} <code>{uid}</code>\n"
                        f"Сумма: <b>{sp(amount)} ₽</b>\nСпособ: {METHODS[method]}\nРеквизиты: <code>{details}</code>",
                        payout_admin_kb(pid))
    return True, "ok", pid


async def safe_send(bot: Bot, chat_id: int, text: str, kb=None):
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception as e:
        logging.warning("Не отправилось %s: %s", chat_id, e)


CACHE_DIR = BASE / "cache"
VIDEO_EXT = (".mp4", ".mov", ".webm")


def insert_voice() -> Path | None:
    return next(iter(sorted(MATERIALS_DIR.glob("Озвучка вставка*.mp3"))), None) if MATERIALS_DIR.exists() else None


RENDER_LOCK = asyncio.Lock()


def user_voice(uid: int | None) -> Path | None:
    """Озвучка, которую выбрал автор; если не выбирал или файл удалён — основная."""
    if uid:
        u = q("SELECT voice FROM users WHERE id=?", uid, one=True)
        if u and u["voice"]:
            f = MATERIALS_DIR / "voices" / Path(u["voice"]).name
            if f.exists():
                return f
    return insert_voice()


async def personal_videos(code: str, uid: int | None = None, preview: bool = False) -> list[tuple[Path, str]]:
    """Персональные баннеры с промокодом: в центре (со звуком) и сверху (цикл 60 сек). Кэш."""
    if not animate.ffmpeg_exe():
        return []
    voice = user_voice(uid)
    bf = brand.brand_file(MATERIALS_DIR)
    bcfg = {"x0": BRAND_X0, "y0": BRAND_Y0, "x1": BRAND_X1, "y1": BRAND_Y1, "t_from": BRAND_FROM, "t_to": BRAND_TO,
            "voice_at": VOICE_AT}
    vtag = f"{voice.stem[-12:]}{int(voice.stat().st_mtime)}" if voice else "0"
    if bf:
        h = hashlib.md5(json.dumps(bcfg, sort_keys=True).encode()).hexdigest()[:8]
        mid = CACHE_DIR / f"brand_{code}_{int(bf.stat().st_mtime)}_{vtag}_{h}{'_pv' if preview else ''}.mp4"
    else:
        mid = CACHE_DIR / f"mid_{code}_{vtag}.mp4"
    top = CACHE_DIR / f"top_{code}{'_pv' if preview else ''}.mp4"
    async with RENDER_LOCK:            # не рендерим несколько роликов одновременно — бережём процессор
        if not mid.exists():
            if bf:
                await asyncio.to_thread(brand.render, bf, mid, code, bcfg, voice, "veryfast", 10.0 if preview else None)
            else:
                await asyncio.to_thread(animate.render, "mid", mid, code, EXCHANGE_TG, voice, "key")
        if not top.exists():
            await asyncio.to_thread(animate.render, "top", top, code, EXCHANGE_TG, None, "key", 8 if preview else 60)
    return [(mid, f"Баннер_в_центре_{code}.mp4"), (top, f"Баннер_сверху_{code}.mp4")]


def material_files():
    if not MATERIALS_DIR.exists():
        return []
    skip = {"Баннер бренда.mp4", "Баннер бренда.mov", "brand.mp4", banner_video.BANNER_NAME}
    if brand.brand_file(MATERIALS_DIR):          # есть фирменный — наш общий центральный не нужен
        skip |= {"Баннер в центре (синий фон).mp4", "Баннер в центре (прозрачный).mov"}
    return sorted(p for p in MATERIALS_DIR.glob("*") if p.is_file() and not p.name.startswith(".") and p.name not in skip
                  and not p.name.startswith("Озвучка вставка"))


async def sync_author_coupon(
    bot: Bot, uid: int, code: str, video_id: int | None, issued_for: str, *, notify_failure: bool = True,
) -> None:
    """Кладёт код в promo_campaigns обменника. Без EXCHANGE_API_URL/TRACK_SECRET — только лог."""
    u = get_user(uid)
    name = ("@" + u["username"]) if u["username"] else (u["first_name"] or "")
    try:
        saved = await exchange_link.push_author_coupon(exchange_link.coupon_payload(
            code=code,
            author_telegram_id=uid,
            video_id=video_id,
            issued_for=issued_for,
            author_name=name or None,
        ))
    except Exception as e:
        logging.warning("Связка промокода %s с обменником: %s", code, e)
        if notify_failure and exchange_link.exchange_sync_configured():
            await safe_send(bot, uid, "Промокод на баннере есть, но обменник его пока не принял. Напиши в поддержку.")
        return
    if not saved:
        logging.info("Связка промокода %s пропущена: нет EXCHANGE_API_URL или TRACK_SECRET", code)
        return
    live = str(saved.get("code") or code).upper()
    if live != code:
        q("UPDATE users SET promo=? WHERE id=?", live, uid)
        _register_code(live, uid)
    q(
        "UPDATE promo_codes SET exchange_synced=1, max_uses=?, expires=0 WHERE code=?",
        int(saved.get("max_activations") or PROMO_MAX_USES),
        live,
    )
    if issued_for == "first_video":
        discount = int(saved.get("discount_rub") or PROMO_DISCOUNT)
        minimum = int(saved.get("min_order_rub") or PROMO_MIN_AMOUNT)
        uses = int(saved.get("max_activations") or PROMO_MAX_USES)
        await safe_send(
            bot,
            uid,
            f"Промокод <code>{live}</code> включён на обмен: скидка <b>{sp(discount)} ₽</b> "
            f"при сумме от <b>{sp(minimum)} ₽</b>. Активаций: {uses}.",
        )


async def maybe_sync_current_coupon(bot: Bot, uid: int) -> None:
    approved = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='approved'", uid, one=True)["c"]
    if not approved or not exchange_link.exchange_sync_configured():
        return
    code = ensure_promo(uid)
    row = q("SELECT exchange_synced FROM promo_codes WHERE code=?", code, one=True)
    if row and row["exchange_synced"]:
        return
    any_synced = q("SELECT 1 FROM promo_codes WHERE author_id=? AND exchange_synced=1", uid, one=True)
    await sync_author_coupon(bot, uid, code, None, "extra" if any_synced else "first_video", notify_failure=False)


async def send_materials(bot: Bot, chat_id: int) -> int:
    files = material_files()
    u = q("SELECT * FROM users WHERE id=?", chat_id, one=True)
    code = None
    if u and u["accepted"]:
        code = ensure_promo(chat_id)
        await maybe_sync_current_coupon(bot, chat_id)
        code = ensure_promo(chat_id)
    banner = banner_video.banner_video_path(MATERIALS_DIR)
    if banner:
        caption = "🎬 <b>Баннер Focus Pay</b>"
        if code:
            caption += (
                f"\nПромокод: <code>{code}</code>\n"
                f"Скидка {sp(PROMO_DISCOUNT)} ₽ на обмен от {sp(PROMO_MIN_AMOUNT)} ₽ · {PROMO_MAX_USES} активаций"
            )
        try:
            await banner_video.send_banner_video(bot, chat_id, banner, caption)
        except Exception as e:
            logging.warning("Баннер-видео не отправилось: %s", e)
    if u and u["accepted"]:
        try:
            await bot.send_message(chat_id, "⏳ Готовлю твои персональные баннеры с промокодом — до пары минут…")
            vids = await personal_videos(code, chat_id)
            is_brand = bool(brand.brand_file(MATERIALS_DIR))
            caps = ["🎬 <b>Баннер в центре</b> (со звуком и твоим промокодом) — ставь в середину ролика целиком. "
                    + ("Фон <b>зелёный</b>." if is_brand else "Фон <b>синий</b>."),
                    "📌 <b>Баннер сверху</b> — на весь ролик, обрежь по длине своего видео. Фон <b>синий</b>."]
            for (path, name), cap in zip(vids, caps):
                await bot.send_document(chat_id, FSInputFile(path, filename=name), caption=cap)
            await bot.send_message(chat_id, "Как вставить в CapCut: <b>Наложение</b> → добавь файл → уменьши/растяни по месту → "
                                            "<b>Удалить фон → Хромакей</b> → пипеткой выбери цвет фона. Готово ✅")
        except Exception as e:
            logging.warning("Персональные баннеры: %s", e)
    for p in files:
        try:
            if p.suffix.lower() in (".mp3", ".m4a", ".ogg", ".wav"):
                await bot.send_audio(chat_id, FSInputFile(p), caption=p.stem)
            else:
                await bot.send_document(chat_id, FSInputFile(p), caption=p.stem)
        except Exception as e:
            logging.warning("Файл %s не отправился: %s", p, e)
    return len(files)


# ───────────────────────── Клавиатуры бота ─────────────────────────
BTN_APP = "📱 Открыть приложение"
BTN_RULES, BTN_CALC, BTN_MAT = "📜 Правила", "🧮 Калькулятор", "🎬 Материалы"
BTN_SUBMIT, BTN_CAB, BTN_PAY, BTN_HELP = "📤 Сдать ролик", "👤 Кабинет", "💸 Вывод", "🆘 Поддержка"
MENU_BUTTONS = {BTN_RULES, BTN_CALC, BTN_MAT, BTN_SUBMIT, BTN_CAB, BTN_PAY, BTN_HELP}


def main_kb():
    rows = []
    if WEBAPP_URL:
        rows.append([KeyboardButton(text=BTN_APP, web_app=WebAppInfo(url=WEBAPP_URL))])
    rows += [
        [KeyboardButton(text=BTN_SUBMIT), KeyboardButton(text=BTN_CAB)],
        [KeyboardButton(text=BTN_MAT), KeyboardButton(text=BTN_CALC)],
        [KeyboardButton(text=BTN_PAY), KeyboardButton(text=BTN_RULES)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=rows)


accept_kb = ikb([[("✅ Принимаю правила", "accept")]])
platform_kb = ikb([[(name, f"pf:{key}")] for key, (name, _) in PLATFORMS.items()] + [[("✖ Отмена", "cancel")]])
method_kb = ikb([[(name, f"pm:{key}")] for key, name in METHODS.items()] + [[("✖ Отмена", "cancel")]])


class Submit(StatesGroup):
    platform = State()
    url = State()
    views = State()
    screenshot = State()


class Withdraw(StatesGroup):
    method = State()
    details = State()
    amount = State()


class Calc(StatesGroup):
    views = State()


class AdminApprove(StatesGroup):
    views = State()


router = Router()
NOT_MENU = ~F.text.in_(MENU_BUTTONS)


def is_owner(uid: int) -> bool:
    """Главные админы — из ADMIN_IDS в .env. Только они добавляют и убирают других админов."""
    return uid in ADMIN_IDS


def all_admins() -> list[int]:
    return sorted(ADMIN_IDS | {r["id"] for r in q("SELECT id FROM admins")})


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS or bool(q("SELECT 1 FROM admins WHERE id=?", uid, one=True))


OPERATOR_IDS = {int(x) for x in os.getenv("OPERATOR_IDS", "").replace(" ", "").split(",") if x.isdigit()}


def is_operator(uid: int) -> bool:
    return is_admin(uid) or uid in OPERATOR_IDS or bool(q("SELECT 1 FROM operators WHERE id=?", uid, one=True))


def operator_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎟 Проверка промокодов", web_app=WebAppInfo(url=WEBAPP_URL + "/operator"))]])


async def gate(message: Message) -> bool:
    u = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if u["banned"]:
        await message.answer("⛔ Доступ к партнёрке закрыт. Вопросы — " + SUPPORT_TG)
        return False
    if not u["accepted"]:
        await message.answer(RULES, reply_markup=accept_kb)
        return False
    return True


async def mark_done(cb: CallbackQuery, suffix: str):
    try:
        if cb.message.photo:
            await cb.message.edit_caption(caption=(cb.message.caption or "") + "\n\n" + suffix)
        else:
            await cb.message.edit_text((cb.message.text or "") + "\n\n" + suffix)
    except Exception:
        await cb.message.edit_reply_markup(reply_markup=None)


# ───────────────────────── Старт и меню ─────────────────────────
@router.message(CommandStart())
async def start(message: Message, state: FSMContext, command: CommandObject):
    await state.clear()
    uid = message.from_user.id
    is_new = not q("SELECT id FROM users WHERE id=?", uid, one=True)
    u = get_user(uid, message.from_user.username, message.from_user.first_name)
    arg = (command.args or "").strip()
    if is_new and arg.startswith("r_") and arg[2:].isdigit():
        ref = int(arg[2:])
        if ref != uid and q("SELECT id FROM users WHERE id=?", ref, one=True):
            q("UPDATE users SET referrer_id=? WHERE id=?", ref, uid)
            await safe_send(message.bot, ref, "🤝 По твоей ссылке пришёл новый автор!")
    if u["banned"]:
        return await message.answer("⛔ Доступ к партнёрке закрыт.")
    if is_operator(uid) and not is_admin(uid) and WEBAPP_URL:
        await message.answer("Ты оператор обменника — здесь проверяются промокоды клиентов 👇", reply_markup=operator_kb())
        if not u["accepted"]:
            return
    if not u["accepted"]:
        await message.answer(
            f"👋 Это партнёрка обменника <b>Focus Pay</b>.\n\n"
            f"Вставляешь нашу озвучку и баннер в свои ролики — получаешь "
            f"<b>{RATE} ₽ за 1 000 просмотров</b> (от {sp(MIN_VIEWS)}).\n\nСначала прочитай правила 👇")
        return await message.answer(RULES, reply_markup=accept_kb)
    await message.answer("Главное меню 👇", reply_markup=main_kb())
    if is_admin(uid) and WEBAPP_URL:
        await message.answer("Ты админ — вот панель управления 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть админку", web_app=WebAppInfo(url=WEBAPP_URL + "/admin"))],
            [InlineKeyboardButton(text="🎟 Проверка промокодов", web_app=WebAppInfo(url=WEBAPP_URL + "/operator"))]]))


@router.message(Command("myid"))
async def my_id(message: Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("operator"))
async def operator_open(message: Message):
    if not is_operator(message.from_user.id):
        return await message.answer("Эта команда только для операторов обменника.")
    if not WEBAPP_URL:
        return await message.answer("Панель открывается через WEBAPP_URL — бот должен работать на сервере.")
    await message.answer("🎟 Проверка промокодов клиентов", reply_markup=operator_kb())


@router.callback_query(F.data.startswith("prpause:"))
async def promo_pause_cb(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    uid = int(cb.data.split(":")[1])
    q("UPDATE users SET promo_paused=1 WHERE id=?", uid)
    await mark_done(cb, "⏸ Код на паузе")
    await cb.answer("Код на паузе")


@router.callback_query(F.data.startswith("prres:"))
async def promo_resume_cb(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    uid = int(cb.data.split(":")[1])
    q("UPDATE users SET promo_paused=0 WHERE id=?", uid)
    await mark_done(cb, "▶️ Пауза снята")
    await safe_send(bot, uid, "▶️ Твой промокод снова работает.")
    await cb.answer("Пауза снята")


@router.callback_query(F.data == "accept")
async def accept_rules(cb: CallbackQuery):
    get_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    q("UPDATE users SET accepted=1 WHERE id=?", cb.from_user.id)
    ensure_promo(cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "✅ Готово!\n1. Забери озвучку и баннер в «🎬 Материалы».\n2. Вставь их в свои ролики.\n"
        f"3. Ролик набрал {sp(MIN_VIEWS)}+ — сдавай его в приложении или кнопкой «📤 Сдать ролик».",
        reply_markup=main_kb())
    await cb.answer()


@router.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Отменено.", reply_markup=main_kb())
    await cb.answer()


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


@router.message(F.text == BTN_RULES)
async def rules(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(RULES)


@router.message(F.text == BTN_HELP)
async def help_(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(f"Поддержка партнёров: {SUPPORT_TG}\nОбменник: {EXCHANGE_TG}")


@router.message(F.text == BTN_CALC)
async def calc_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Calc.views)
    await message.answer("Сколько просмотров у ролика? Напиши число:")


@router.message(Calc.views, NOT_MENU)
async def calc_do(message: Message):
    digits = "".join(ch for ch in (message.text or "") if ch.isdigit())
    if not digits:
        return await message.answer("Нужно число, например 25000")
    v = int(digits)
    rate = level_info(message.from_user.id)["rate"]
    pay = calc(v, rate)
    txt = (f"{sp(v)} просмотров — ниже порога {sp(MIN_VIEWS)}, выплаты нет." if pay == 0
           else f"{sp(v)} просмотров → <b>{sp(pay)} ₽</b> ({v // 1000} × {rate} ₽)")
    await message.answer(txt + "\n\nМожешь ввести ещё число или выбрать пункт меню.")


@router.message(F.text == BTN_MAT)
async def materials(message: Message, state: FSMContext):
    await state.clear()
    if not await gate(message):
        return
    if not material_files():
        return await message.answer("Материалы скоро появятся. Напиши в поддержку: " + SUPPORT_TG)
    await message.answer("🎬 Материалы. Обязательно: озвучка + баннер в кадре ≥ 5 сек.")
    await send_materials(message.bot, message.chat.id)


@router.message(F.text == BTN_CAB)
async def cabinet(message: Message, state: FSMContext):
    await state.clear()
    if not await gate(message):
        return
    uid = message.from_user.id
    u = get_user(uid)
    lv = level_info(uid)
    pend = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='pending'", uid, one=True)["c"]
    ok = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='approved'", uid, one=True)["c"]
    await message.answer(
        f"<b>👤 Кабинет</b>\n\nБаланс: <b>{sp(u['balance'])} ₽</b>\nВсего заработано: {sp(u['earned'])} ₽\n"
        f"Уровень: {lv['name']} ({lv['rate']} ₽ / 1 000), {lv['to_next']}\n\n"
        f"Принято роликов: {ok} ({sp(lv['views'])} просмотров)\nНа проверке: {pend}\n\n"
        f"Подробнее — в приложении.")


# ───────────────────────── Сдача ролика в чате ─────────────────────────
@router.message(F.text == BTN_SUBMIT)
async def submit_start(message: Message, state: FSMContext):
    await state.clear()
    if not await gate(message):
        return
    await state.set_state(Submit.platform)
    await message.answer(f"Где опубликован ролик? (от {sp(MIN_VIEWS)} просмотров)", reply_markup=platform_kb)


@router.callback_query(Submit.platform, F.data.startswith("pf:"))
async def submit_platform(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    await state.update_data(platform=key)
    await state.set_state(Submit.url)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"{PLATFORMS[key][0]} — пришли ссылку на ролик:")
    await cb.answer()


@router.message(Submit.url, NOT_MENU)
async def submit_url(message: Message, state: FSMContext):
    data = await state.get_data()
    url = (message.text or "").strip()
    if not url.startswith("http") or not any(d in url.lower() for d in PLATFORMS[data["platform"]][1]):
        return await message.answer("Это не ссылка с выбранной площадки. Пришли целиком или /cancel.")
    if q("SELECT id FROM videos WHERE url=?", norm_url(url), one=True):
        return await message.answer("Этот ролик уже сдавали.")
    await state.update_data(url=url)
    await state.set_state(Submit.views)
    await message.answer("Сколько сейчас просмотров? Напиши число:")


@router.message(Submit.views, NOT_MENU)
async def submit_views(message: Message, state: FSMContext):
    digits = "".join(ch for ch in (message.text or "") if ch.isdigit())
    if not digits:
        return await message.answer("Нужно число, например 15400")
    v = int(digits)
    if v < MIN_VIEWS:
        await state.clear()
        return await message.answer(f"Пока {sp(v)} — ниже порога {sp(MIN_VIEWS)}.", reply_markup=main_kb())
    await state.update_data(views=v)
    await state.set_state(Submit.screenshot)
    await message.answer("Пришли <b>скриншот статистики</b> ролика (фото), где видно просмотры.")


@router.message(Submit.screenshot, F.photo)
async def submit_screenshot(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    ok, err, vid = await create_video(bot, message.from_user.id, data["platform"], data["url"],
                                      data["views"], shot_file_id=message.photo[-1].file_id)
    if not ok:
        return await message.answer("❌ " + err, reply_markup=main_kb())
    await message.answer(f"✅ Заявка #{vid} на проверке. Статус — в приложении.", reply_markup=main_kb())


@router.message(Submit.screenshot, NOT_MENU)
async def submit_screenshot_wrong(message: Message):
    await message.answer("Нужен скриншот (фото). Или /cancel.")


# ───────────────────────── Вывод в чате ─────────────────────────
@router.message(F.text == BTN_PAY)
async def pay_start(message: Message, state: FSMContext):
    await state.clear()
    if not await gate(message):
        return
    u = get_user(message.from_user.id)
    if u["balance"] < MIN_PAYOUT:
        return await message.answer(f"Баланс {sp(u['balance'])} ₽. Минимум для вывода — {sp(MIN_PAYOUT)} ₽.")
    await state.set_state(Withdraw.method)
    await message.answer(f"Баланс: {sp(u['balance'])} ₽. Куда выводим?", reply_markup=method_kb)


@router.callback_query(Withdraw.method, F.data.startswith("pm:"))
async def pay_method(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    await state.update_data(method=key)
    await state.set_state(Withdraw.details)
    hint = {"sbp": "номер телефона и банк", "usdt": "адрес USDT TRC-20 (начинается с T)",
            "ton": "адрес TON-кошелька (и memo, если нужен)"}[key]
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"{METHODS[key]}. Пришли {hint}:")
    await cb.answer()


@router.message(Withdraw.details, NOT_MENU)
async def pay_details(message: Message, state: FSMContext):
    await state.update_data(details=(message.text or "").strip())
    await state.set_state(Withdraw.amount)
    u = get_user(message.from_user.id)
    await message.answer(f"Сумма вывода? (от {sp(MIN_PAYOUT)} до {sp(u['balance'])} ₽, или «всё»)")


@router.message(Withdraw.amount, NOT_MENU)
async def pay_amount(message: Message, state: FSMContext, bot: Bot):
    u = get_user(message.from_user.id)
    text = (message.text or "").lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    amount = u["balance"] if "вс" in text else int(digits or 0)
    data = await state.get_data()
    ok, err, pid = await create_payout(bot, u["id"], data["method"], data["details"], amount)
    if not ok:
        return await message.answer("❌ " + err)
    await state.clear()
    await message.answer(f"💸 Заявка на вывод #{pid}: {sp(amount)} ₽. Срок 24–48 часов.", reply_markup=main_kb())


# ───────────────────────── Админка ─────────────────────────
@router.callback_query(F.data.startswith("va:"))
async def adm_approve_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    vid = int(cb.data.split(":")[1])
    v = q("SELECT * FROM videos WHERE id=?", vid, one=True)
    if not v or v["status"] != "pending":
        return await cb.answer("Заявка уже обработана", show_alert=True)
    await state.set_state(AdminApprove.views)
    await state.update_data(vid=vid, msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.message.answer(f"Заявка #{vid}: пришли <b>фактическое</b> число просмотров "
                            f"или «ок» — принять заявленные {sp(v['views_claimed'])}.")
    await cb.answer()


@router.message(AdminApprove.views)
async def adm_approve_finish(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    v = q("SELECT * FROM videos WHERE id=?", data["vid"], one=True)
    text = (message.text or "").lower().strip()
    if text in ("ок", "ok", "да"):
        views = v["views_claimed"]
    else:
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return await message.answer("Пришли число или «ок».")
        views = int(digits)
    await state.clear()
    await message.answer(await approve_video(bot, data["vid"], views))
    try:
        await bot.edit_message_reply_markup(chat_id=data["chat_id"], message_id=data["msg_id"], reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("vr:"))
async def adm_reject(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    _, vid, code = cb.data.split(":")
    v = q("SELECT * FROM videos WHERE id=?", int(vid), one=True)
    if not v or v["status"] != "pending":
        return await cb.answer("Заявка уже обработана", show_alert=True)
    reason = REJECT_REASONS[code]
    q("UPDATE videos SET status='rejected', reason=?, decided=? WHERE id=?", reason, int(time.time()), v["id"])
    extra = ""
    if code == "fake":
        q("UPDATE users SET strikes=strikes+1 WHERE id=?", v["user_id"])
        if get_user(v["user_id"])["strikes"] >= 2:
            q("UPDATE users SET banned=1 WHERE id=?", v["user_id"])
            extra = "\n⛔ Повторное нарушение — доступ закрыт."
        else:
            extra = "\n⚠️ Предупреждение. Повторная накрутка — бан."
    await mark_done(cb, f"❌ Отклонено: {reason}")
    await safe_send(bot, v["user_id"], f"❌ Заявка #{v['id']} отклонена: {reason}.{extra}")
    await cb.answer("Отклонено")


@router.callback_query(F.data.startswith("ban:"))
async def adm_ban(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    uid = int(cb.data.split(":")[1])
    q("UPDATE users SET banned=1 WHERE id=?", uid)
    q("UPDATE videos SET status='rejected', reason='бан автора' WHERE user_id=? AND status='pending'", uid)
    await mark_done(cb, f"⛔ Автор {uid} забанен")
    await safe_send(bot, uid, "⛔ Доступ к партнёрке закрыт за нарушение правил.")
    await cb.answer("Забанен")


@router.callback_query(F.data.startswith("pp:"))
async def adm_paid(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[1])
    p = q("SELECT * FROM payouts WHERE id=?", pid, one=True)
    if not p or p["status"] != "pending":
        return await cb.answer("Уже обработано", show_alert=True)
    q("UPDATE payouts SET status='paid', decided=? WHERE id=?", int(time.time()), pid)
    await mark_done(cb, "💸 Выплачено")
    await safe_send(bot, p["user_id"], f"💸 Вывод #{pid} на {sp(p['amount'])} ₽ отправлен. Спасибо за работу!")
    await cb.answer("Отмечено")


@router.callback_query(F.data.startswith("px:"))
async def adm_payout_reject(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[1])
    p = q("SELECT * FROM payouts WHERE id=?", pid, one=True)
    if not p or p["status"] != "pending":
        return await cb.answer("Уже обработано", show_alert=True)
    q("UPDATE payouts SET status='rejected', decided=? WHERE id=?", int(time.time()), pid)
    q("UPDATE users SET balance=balance+? WHERE id=?", p["amount"], p["user_id"])
    await mark_done(cb, "↩ Отклонено, сумма возвращена")
    await safe_send(bot, p["user_id"], f"↩ Вывод #{pid} отклонён, {sp(p['amount'])} ₽ вернулись на баланс. "
                                       f"Проверь реквизиты или напиши {SUPPORT_TG}.")
    await cb.answer("Отклонено")


@router.message(Command("stats"))
async def adm_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    users = q("SELECT COUNT(*) c FROM users WHERE accepted=1", one=True)["c"]
    vids = q("SELECT status, COUNT(*) c, COALESCE(SUM(views_final),0) v, COALESCE(SUM(amount),0) a "
             "FROM videos GROUP BY status")
    paid = q("SELECT COALESCE(SUM(amount),0) s FROM payouts WHERE status='paid'", one=True)["s"]
    waiting = q("SELECT COALESCE(SUM(amount),0) s FROM payouts WHERE status='pending'", one=True)["s"]
    owed = q("SELECT COALESCE(SUM(balance),0) s FROM users", one=True)["s"]
    refs = q("SELECT COALESCE(SUM(ref_earned),0) s FROM users", one=True)["s"]
    lines = [f"{r['status']}: {r['c']} шт., {sp(r['v'])} просм., {sp(r['a'])} ₽" for r in vids]
    await message.answer("<b>📊 Статистика</b>\n"
                         f"Авторов: {users}\n\n" + "\n".join(lines or ["роликов нет"]) +
                         f"\n\nВыплачено: {sp(paid)} ₽\nЖдут выплаты: {sp(waiting)} ₽\n"
                         f"На балансах: {sp(owed)} ₽\nРеферальных начислено: {sp(refs)} ₽")


@router.message(Command("ban", "unban"))
async def adm_ban_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("Формат: /ban 123456 или /unban 123456")
    flag = 1 if parts[0].startswith("/ban") else 0
    q("UPDATE users SET banned=?, strikes=CASE WHEN ?=0 THEN 0 ELSE strikes END WHERE id=?", flag, flag, int(parts[1]))
    await message.answer(("⛔ Забанен " if flag else "✅ Разбанен ") + parts[1])


@router.message(Command("pending"))
async def adm_pending(message: Message):
    if not is_admin(message.from_user.id):
        return
    v = q("SELECT COUNT(*) c FROM videos WHERE status='pending'", one=True)["c"]
    p = q("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM payouts WHERE status='pending'", one=True)
    await message.answer(f"⏳ Роликов на проверке: {v}\n💸 Выводов в очереди: {p['c']} на {sp(p['s'])} ₽")


# ───────────────────────── ИИ-поддержка ─────────────────────────
AI_HISTORY: dict[int, list] = {}
human_kb = ikb([[("🙋 Позвать человека", "human")]])


def ai_context(uid: int) -> str:
    u = get_user(uid)
    lv = level_info(uid)
    vids = q("SELECT id, platform, views_claimed, views_final, amount, status, reason, created FROM videos "
             "WHERE user_id=? ORDER BY id DESC LIMIT 8", uid)
    pays = q("SELECT id, amount, method, status, created FROM payouts WHERE user_id=? ORDER BY id DESC LIMIT 5", uid)
    lines = [f"Баланс: {u['balance']} ₽, заработано всего: {u['earned']} ₽, уровень: {lv['name']} ({lv['rate']} ₽/1000), "
             f"нарушений: {u['strikes']}, промокод: {ensure_promo(uid)}"]
    for v in vids:
        lines.append(f"Заявка #{v['id']} {PLATFORMS[v['platform']][0]}: статус {v['status']}, заявлено {v['views_claimed']}, "
                     f"засчитано {v['views_final']}, сумма {v['amount']} ₽, причина отказа: {v['reason'] or '—'}, "
                     f"создана {time.strftime('%d.%m %H:%M', time.localtime(v['created']))}")
    for p_ in pays:
        lines.append(f"Вывод #{p_['id']}: {p_['amount']} ₽ на {METHODS.get(p_['method'], p_['method'])}, статус {p_['status']}, "
                     f"создан {time.strftime('%d.%m %H:%M', time.localtime(p_['created']))}")
    return "\n".join(lines)


AI_LAST_ALERT = {"t": 0}
HUMAN_TAG = "[ЧЕЛОВЕК]"


def ai_system(uid: int) -> str:
    clean_rules = re.sub(r"<[^>]+>", "", RULES)
    return f"""Ты — живой и толковый саппорт партнёрки обменника Focus Pay в Telegram. Авторы коротких роликов (TikTok, Reels, Shorts, VK Клипы) вставляют баннеры Focus Pay в свои видео и получают деньги за просмотры и за клиентов.

КАК ОТВЕЧАТЬ
- По-русски, на «ты», дружелюбно и по делу, как опытный менеджер, а не робот. 1–6 коротких предложений; если нужна инструкция — нумерованные шаги.
- Сначала сам ответь на вопрос, используя правила, справку и данные автора ниже. Подставляй его реальные цифры: баланс, статусы заявок, причины отказа, промокод.
- Если вопрос общий (как снимать, какие ролики заходят, как монтировать) — помоги советом.
- Не выдумывай: если в данных нет ответа — так и скажи.
- Ты не можешь менять статусы, начислять деньги или ускорять выплаты — это делает команда.
- Позови человека ТОЛЬКО если: спор о деньгах или ошибка в балансе/выплате; выплата висит дольше 48 часов; жалоба на модерацию после твоего объяснения; бан; автор прямо просит человека. Тогда кратко скажи, что передаёшь команде, и последней строкой напиши ровно {HUMAN_TAG}
- Никаких инвестиционных советов и обещаний дохода.

СПРАВКА
- Материалы: кнопка «🎬 Материалы» в боте или вкладка «Материалы» в приложении. Бот присылает персональные баннеры с промокодом автора: «Баннер в центре» (со звуком, ставится в середину ролика) и «Баннер сверху» (на весь ролик).
- Как вставить в CapCut: открыть ролик → «Наложение» → «Добавить наложение» → выбрать файл баннера → растянуть/уменьшить по месту → «Удалить фон» → «Хромакей» → пипеткой ткнуть в цвет фона (у баннера в центре — зелёный, если это фирменный, иначе синий) → ползунок «Интенсивность» чуть вверх, пока фон не исчезнет.
- Где промокод и ссылки: приложение → Профиль → «Мои клиенты в обменнике». Для каждой площадки своя ссылка — так видно, откуда пришёл клиент.
- Сдать ролик: «📤 Сдать ролик» или вкладка «Сдать» в приложении: площадка → ссылка → просмотры → скрин статистики. Сдавать, когда ролик уже набрал основные просмотры — доплат за рост нет.
- Статус заявки: в приложении на главной, нажать на заявку. Обычно проверка до 24 часов.
- Вывод: от {MIN_PAYOUT} ₽, СБП/карта, USDT TRC-20 или TON, 24–48 часов.
- Уровни: Новичок, Трейдер (от 100K принятых просмотров — проверка за 12 ч), Брокер (от 1M — {RATE_BROKER} ₽ за 1000 и выплаты вне очереди).
- Бонусы: +{FIRST_BONUS} ₽ за первый принятый ролик; +{MILESTONE_BONUS} ₽ за каждые {MILESTONE_N} принятых роликов; {REF_PCT}% от выплат приглашённого автора первые {REF_DAYS} дней.{(" Ещё +" + str(CLIENT_REWARD) + " ₽ за первый обмен каждого нового клиента по промокоду автора.") if CLIENT_REWARD > 0 else " За клиентов, пришедших по промокоду, отдельный бонус не начисляется — промокод нужен для статистики."}
- Промокод автора: стоит на баннерах, а скидкой на обмен становится после первого принятого ролика. У кода {PROMO_MAX_USES} активаций. Кончились — новый код в «Материалах» (после первого принятого ролика, не чаще раза в {PROMO_NEW_EVERY} дн., не больше {PROMO_ACTIVE_MAX} живых кодов). {"Клиент получает кэшбэк " + str(PROMO_DISCOUNT) + " ₽ на второй обмен" if PROMO_MODE else "Клиент получает скидку " + str(PROMO_DISCOUNT) + " ₽"} при обмене от {PROMO_MIN_AMOUNT} ₽; один раз на человека и на одни реквизиты. Если активации кончились — клиент пишет оператору. Свой код применять нельзя (блокировка и бан). Код с подозрительной активностью автоматически ставится на паузу до проверки командой. Сменить код может только команда — через поддержку.
- Идеи для бота: приложение → Профиль → «Идеи для бота».
- Приложение открывается кнопкой «📱 Открыть приложение».

ПРАВИЛА
{clean_rules}

ДАННЫЕ ЭТОГО АВТОРА
{ai_context(uid)}"""


async def _ai_alert(bot: Bot | None, msg: str):
    if bot and time.time() - AI_LAST_ALERT["t"] > 1800:
        AI_LAST_ALERT["t"] = time.time()
        for aid in all_admins():
            await safe_send(bot, aid, f"⚠️ ИИ-поддержка не отвечает: <code>{msg[:300]}</code>")


async def ask_ai(uid: int, text: str, bot: Bot | None = None) -> tuple[str, bool] | None:
    """Возвращает (ответ, нужен_человек) или None, если ИИ недоступен."""
    if not ANTHROPIC_API_KEY and not OPENAI_API_KEY:
        return None
    system = ai_system(uid)
    hist = AI_HISTORY.setdefault(uid, [])
    hist.append({"role": "user", "content": text[:2000]})
    del hist[:-10]
    try:
        async with aiohttp.ClientSession() as s:
            if ANTHROPIC_API_KEY:
                async with s.post("https://api.anthropic.com/v1/messages",
                                  headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                                           "content-type": "application/json"},
                                  json={"model": AI_MODEL, "max_tokens": 700, "system": system, "messages": hist},
                                  timeout=aiohttp.ClientTimeout(total=45)) as r:
                    data = await r.json()
                answer = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
            else:
                body = {"model": OPENAI_MODEL, "max_completion_tokens": 900, "temperature": 0.5,
                        "messages": [{"role": "system", "content": system}] + hist}
                hdr = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
                async with s.post("https://api.openai.com/v1/chat/completions", headers=hdr, json=body,
                                  timeout=aiohttp.ClientTimeout(total=60)) as r:
                    data = await r.json()
                if "error" in data and "temperature" in json.dumps(data["error"]):   # модели без temperature
                    body.pop("temperature")
                    async with s.post("https://api.openai.com/v1/chat/completions", headers=hdr, json=body,
                                      timeout=aiohttp.ClientTimeout(total=60)) as r:
                        data = await r.json()
                answer = ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if not answer:
            err_msg = json.dumps(data.get("error", data), ensure_ascii=False)
            logging.warning("AI ошибка ответа: %s", err_msg)
            hist.pop()
            await _ai_alert(bot, err_msg)
            return None
        need_human = HUMAN_TAG in answer
        answer = answer.replace(HUMAN_TAG, "").strip()
        hist.append({"role": "assistant", "content": answer})
        return answer, need_human
    except Exception as e:
        logging.warning("AI ошибка: %s", e)
        hist.pop()
        await _ai_alert(bot, str(e))
        return None


@router.callback_query(F.data == "human")
async def call_human(cb: CallbackQuery, bot: Bot):
    u = get_user(cb.from_user.id)
    hist = AI_HISTORY.get(u["id"], [])
    last = next((h["content"] for h in reversed(hist) if h["role"] == "user"), "—")
    for aid in all_admins():
        await safe_send(bot, aid, f"🙋 <b>Автор просит человека</b>\n{user_label(u)} <code>{u['id']}</code>\n\n"
                                  f"Вопрос: {last[:1500]}\n\nОтветить: <code>/reply {u['id']} текст</code>")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"Передал команде, ответим здесь же. Если срочно — {SUPPORT_TG}")
    await cb.answer()


@router.message(Command("reset"))
async def ai_reset(message: Message):
    AI_HISTORY.pop(message.from_user.id, None)
    await message.answer("Начнём заново 🙂 Задай вопрос.")


@router.message(Command("reply"))
async def adm_reply(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return await message.answer("Формат: /reply ID текст ответа")
    await safe_send(bot, int(parts[1]), "💬 <b>Ответ поддержки:</b>\n" + parts[2])
    await message.answer("Отправлено ✅")


@router.message(Command("broadcast"))
async def adm_broadcast(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2:
        return await message.answer("Формат: /broadcast текст — разошлю всем авторам")
    users = q("SELECT id FROM users WHERE accepted=1 AND banned=0")
    ok = 0
    for u in users:
        try:
            await bot.send_message(u["id"], text[1])
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await message.answer(f"Разослано: {ok} из {len(users)}")


@router.message(Command("traffic"))
async def adm_traffic(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = q("SELECT platform, COUNT(*) c, SUM(CASE WHEN exchanges>0 THEN 1 ELSE 0 END) ex, COALESCE(SUM(volume),0) vol "
             "FROM clients GROUP BY platform")
    top = q("SELECT c.author_id, us.username, us.promo, COUNT(*) n, SUM(CASE WHEN c.exchanges>0 THEN 1 ELSE 0 END) ex "
            "FROM clients c JOIN users us ON us.id=c.author_id GROUP BY c.author_id ORDER BY ex DESC, n DESC LIMIT 10")
    names = {"tt": "TikTok", "ig": "Reels", "yt": "Shorts", "vk": "VK", "promo": "Промокод"}
    txt = "<b>🚦 Трафик в обменник</b>\n" + ("\n".join(
        f"{names.get(r['platform'], r['platform'] or '—')}: {r['c']} пришло, {r['ex']} обменяли, оборот {sp(r['vol'])} ₽"
        for r in rows) or "пока пусто")
    if top:
        txt += "\n\n<b>Лучшие авторы:</b>\n" + "\n".join(
            f"{i + 1}. {('@' + t['username']) if t['username'] else t['author_id']} ({t['promo']}): {t['n']} пришло, {t['ex']} обменяли"
            for i, t in enumerate(top))
    await message.answer(txt)


@router.message(Command("admin"))
async def adm_open(message: Message):
    if not is_admin(message.from_user.id):
        return
    if not WEBAPP_URL:
        return await message.answer("Админка открывается через WEBAPP_URL — запусти бота через start.sh или на сервере.")
    await message.answer("📊 Админ-панель Focus Pay", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть админку", web_app=WebAppInfo(url=WEBAPP_URL + "/admin"))]]))


@router.message(Command("ideas"))
async def adm_ideas(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = q("SELECT i.id, i.text, i.status, (SELECT COUNT(*) FROM idea_likes l WHERE l.idea_id=i.id) likes "
             "FROM ideas i WHERE i.status IN ('new','progress') ORDER BY likes DESC LIMIT 15")
    if not rows:
        return await message.answer("Идей пока нет.")
    await message.answer("<b>💡 Топ идей</b>\n\n" + "\n\n".join(
        f"#{r['id']} · ❤️ {r['likes']} · {IDEA_STATUS[r['status']]}\n{r['text']}" for r in rows) +
        "\n\nСменить статус: /idea ID progress | done | reject")


@router.message(Command("idea"))
async def adm_idea_status(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    st = {"progress": "progress", "done": "done", "reject": "rejected"}.get(parts[2] if len(parts) > 2 else "")
    if len(parts) < 3 or not parts[1].isdigit() or not st:
        return await message.answer("Формат: /idea ID progress | done | reject")
    idea = q("SELECT * FROM ideas WHERE id=?", int(parts[1]), one=True)
    if not idea:
        return await message.answer("Нет такой идеи.")
    q("UPDATE ideas SET status=? WHERE id=?", st, idea["id"])
    note = {"progress": "взяли в работу 🛠", "done": "добавили в бота 🎉 Спасибо!", "rejected": "пока отложили"}[st]
    await safe_send(bot, idea["user_id"], f"💡 Твою идею #{idea['id']} {note}\n«{idea['text'][:200]}»")
    await message.answer(f"Идея #{idea['id']}: {IDEA_STATUS[st]} ✅")


@router.message(F.text)
async def fallback(message: Message):
    if not await gate(message):
        return
    if (message.text or "").startswith("/"):
        return await message.answer("Не знаю такой команды. Выбери пункт меню 👇", reply_markup=main_kb())
    await message.bot.send_chat_action(message.chat.id, "typing")
    res = await ask_ai(message.from_user.id, message.text, message.bot)
    if res:
        answer, need_human = res
        return await message.answer(answer, reply_markup=human_kb if need_human else None, parse_mode=None)
    await message.answer("Сейчас не могу ответить сам. Нажми кнопку — вопрос уйдёт команде, ответим здесь.", reply_markup=human_kb)


@router.message()
async def fallback_other(message: Message):
    if not await gate(message):
        return
    await message.answer("Выбери пункт меню 👇", reply_markup=main_kb())


# ───────────────────────── API для Mini App ─────────────────────────
def check_init_data(init_data: str):
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        h = parsed.pop("hash", None)
        if not h:
            return None
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), h):
            return None
        if time.time() - int(parsed.get("auth_date", 0)) > 86400:
            return None
        return json.loads(parsed["user"])
    except Exception:
        return None


def auth(request: web.Request, need_accepted=True):
    tg_user = check_init_data(request.headers.get("X-Init-Data", ""))
    if not tg_user and DEV_MODE and ADMIN_IDS:
        tg_user = {"id": sorted(ADMIN_IDS)[0], "first_name": "Dev"}
    if not tg_user:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "Открой приложение из Telegram"}),
                                   content_type="application/json")
    u = get_user(tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
    if u["banned"]:
        raise web.HTTPForbidden(text=json.dumps({"error": "Доступ закрыт"}), content_type="application/json")
    if need_accepted and not u["accepted"]:
        raise web.HTTPForbidden(text=json.dumps({"error": "Сначала прими правила"}), content_type="application/json")
    return u


def err(msg: str, status=400):
    return web.json_response({"error": msg}, status=status)


async def api_me(request: web.Request):
    u = auth(request, need_accepted=False)
    uid = u["id"]
    lv = level_info(uid)
    pend = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='pending'", uid, one=True)["c"]
    ok = q("SELECT COUNT(*) c FROM videos WHERE user_id=? AND status='approved'", uid, one=True)["c"]
    in_payout = q("SELECT COALESCE(SUM(amount),0) s FROM payouts WHERE user_id=? AND status='pending'", uid, one=True)["s"]
    recent = [dict(id=v["id"], platform=v["platform"], views=v["views_final"] or v["views_claimed"],
                   amount=v["amount"], status=v["status"], reason=v["reason"], created=v["created"])
              for v in q("SELECT * FROM videos WHERE user_id=? ORDER BY id DESC LIMIT 6", uid)]
    # заработок по дням за последние 7 дней
    days, now = [], time.time()
    names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i in range(6, -1, -1):
        t0 = time.mktime(time.localtime(now - i * 86400)[:3] + (0, 0, 0, 0, 0, -1))
        s = q("SELECT COALESCE(SUM(amount),0) s FROM videos WHERE user_id=? AND status='approved' AND decided>=? AND decided<?",
              uid, int(t0), int(t0 + 86400), one=True)["s"]
        days.append({"d": names[time.localtime(t0).tm_wday], "sum": s})
    invited = q("SELECT COUNT(*) c FROM users WHERE referrer_id=?", uid, one=True)["c"]
    active = q("SELECT COUNT(DISTINCT v.user_id) c FROM videos v JOIN users u ON u.id=v.user_id "
               "WHERE u.referrer_id=? AND v.status='approved'", uid, one=True)["c"]
    return web.json_response({
        "user": {"id": uid, "username": u["username"], "first_name": u["first_name"],
                 "accepted": bool(u["accepted"]), "created": u["created"]},
        "balance": u["balance"], "earned": u["earned"], "in_payout": in_payout,
        "stats": {"views": lv["views"], "approved": ok, "pending": pend},
        "level": lv,
        "levels": [{"name": l[0], "from": l[1], "rate": l[2], "perk": l[3]} for l in LEVELS],
        "recent": recent, "chart": days,
        "ref": {"link": f"https://t.me/{BOT_USERNAME}?start=r_{uid}", "invited": invited,
                "active": active, "earned": u["ref_earned"] or 0},
        "config": {"rate": RATE, "min_views": MIN_VIEWS, "min_payout": MIN_PAYOUT, "ref_pct": REF_PCT,
                   "ref_days": REF_DAYS, "exchange": EXCHANGE_TG, "support": SUPPORT_TG, "bot": BOT_USERNAME,
                   "client_reward": CLIENT_REWARD, "first_bonus": FIRST_BONUS, "milestone_n": MILESTONE_N,
                   "milestone_bonus": MILESTONE_BONUS, "authors_chat": AUTHORS_CHAT},
        "milestone": milestone_info(uid),
        "totals": author_stats(uid),
        "traffic": traffic_info(uid) if u["accepted"] else None,
    })


def traffic_info(uid: int) -> dict:
    code = ensure_promo(uid)
    by = {r["platform"]: {"came": r["c"], "exchanged": r["ex"]} for r in q(
        "SELECT platform, COUNT(*) c, SUM(CASE WHEN exchanges>0 THEN 1 ELSE 0 END) ex FROM clients "
        "WHERE author_id=? GROUP BY platform", uid)}
    pu = q("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status='done' THEN 1 ELSE 0 END),0) d FROM promo_uses "
           "WHERE author_id=? AND kind='first' AND status IN ('pending','done')", uid, one=True)
    by["promo"] = {"came": pu["n"], "exchanged": pu["d"]}
    came = sum(x["came"] for x in by.values())
    ex = sum(x["exchanged"] or 0 for x in by.values())
    earned = q("SELECT COALESCE(SUM(amount),0) s FROM bonuses WHERE user_id=? AND kind='client'", uid, one=True)["s"]
    u = get_user(uid)
    codes = []
    for c in q("SELECT * FROM promo_codes WHERE author_id=? ORDER BY created DESC LIMIT 8", uid):
        codes.append({"code": c["code"], "used": code_uses(c["code"]), "max": c["max_uses"], "expires": c["expires"],
                      "state": code_state(c), "current": c["code"] == code})
    can, why = can_new_code(uid)
    return {"codes": codes, "can_new": can, "why_not": why, "mode": "cashback" if PROMO_MODE else "instant",
            "promo": code, "links": promo_links(code), "came": came, "exchanged": ex, "earned": earned, "by": by,
            "promo_uses": pu["d"], "promo_paused": bool(u["promo_paused"]), "promo_on": bool(PROMO_ON),
            "promo_discount": PROMO_DISCOUNT, "promo_min": PROMO_MIN_AMOUNT, "promo_days": PROMO_CASHBACK_DAYS}


async def api_promo_new(request: web.Request):
    u = auth(request)
    code, why = new_promo(u["id"])
    if not code:
        return err(why)
    q("UPDATE promo_codes SET max_uses=?, expires=0 WHERE code=?", PROMO_MAX_USES, code)
    await sync_author_coupon(request.app["bot"], u["id"], code, None, "extra")
    return web.json_response({"ok": True, "code": ensure_promo(u["id"])})


async def api_accept(request: web.Request):
    u = auth(request, need_accepted=False)
    q("UPDATE users SET accepted=1 WHERE id=?", u["id"])
    ensure_promo(u["id"])
    return web.json_response({"ok": True})


async def api_video(request: web.Request):
    u = auth(request)
    v = q("SELECT * FROM videos WHERE id=? AND user_id=?", int(request.match_info["vid"]), u["id"], one=True)
    if not v:
        return err("Заявка не найдена", 404)
    return web.json_response(dict(id=v["id"], platform=v["platform"], url=v["url"],
                                  views_claimed=v["views_claimed"], views_final=v["views_final"],
                                  amount=v["amount"], status=v["status"], reason=v["reason"],
                                  created=v["created"], decided=v["decided"]))


async def api_submit(request: web.Request):
    u = auth(request)
    form = await request.post()
    shot = form.get("screenshot")
    if not shot or not hasattr(shot, "file"):
        return err("Прикрепи скриншот статистики")
    data = shot.file.read()
    if len(data) > 8 * 1024 * 1024:
        return err("Скрин слишком большой (до 8 МБ)")
    try:
        views = int("".join(ch for ch in str(form.get("views", "")) if ch.isdigit()) or 0)
    except ValueError:
        views = 0
    ok, msg, vid = await create_video(request.app["bot"], u["id"], str(form.get("platform", "")),
                                      str(form.get("url", "")).strip(), views, shot_bytes=data)
    return web.json_response({"ok": True, "id": vid}) if ok else err(msg)


async def api_payout(request: web.Request):
    u = auth(request)
    body = await request.json()
    try:
        amount = int(body.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    ok, msg, pid = await create_payout(request.app["bot"], u["id"], body.get("method", ""),
                                       body.get("details", ""), amount)
    return web.json_response({"ok": True, "id": pid}) if ok else err(msg)


async def api_top(request: web.Request):
    u = auth(request)
    since = int(time.time()) - 7 * 86400
    if request.query.get("by") == "clients":
        rows = q("SELECT c.author_id uid, COUNT(*) came, SUM(CASE WHEN c.exchanges>0 THEN 1 ELSE 0 END) ex, "
                 "us.username, us.first_name FROM clients c JOIN users us ON us.id=c.author_id "
                 "WHERE c.created>=? GROUP BY c.author_id ORDER BY ex DESC, came DESC LIMIT 20", since)
        return web.json_response({"top": [
            {"rank": i + 1, "name": ("@" + r["username"]) if r["username"] else (r["first_name"] or "Автор"),
             "came": r["came"], "exchanged": r["ex"] or 0, "me": r["uid"] == u["id"]} for i, r in enumerate(rows)]})
    rows = q("SELECT v.user_id, SUM(v.views_final) views, SUM(v.amount) amount, us.username, us.first_name "
             "FROM videos v JOIN users us ON us.id=v.user_id WHERE v.status='approved' AND v.decided>=? "
             "GROUP BY v.user_id ORDER BY views DESC LIMIT 20", since)
    top = [{"rank": i + 1, "name": ("@" + r["username"]) if r["username"] else (r["first_name"] or "Автор"),
            "views": r["views"], "amount": r["amount"], "me": r["user_id"] == u["id"]} for i, r in enumerate(rows)]
    return web.json_response({"top": top})


async def api_materials(request: web.Request):
    auth(request)
    items = []
    for p in material_files():
        ext = p.suffix.lower()
        kind = ("audio" if ext in (".mp3", ".m4a", ".ogg", ".wav") else "image" if ext in (".png", ".jpg", ".jpeg", ".webp")
                else "video" if ext in VIDEO_EXT else "file")
        items.append({"name": p.stem, "file": p.name, "kind": kind, "url": f"/files/{urllib.parse.quote(p.name)}"})
    return web.json_response({"items": items})


async def api_materials_send(request: web.Request):
    u = auth(request)
    n = await send_materials(request.app["bot"], u["id"])
    return web.json_response({"ok": True, "count": n})


async def api_insert(request: web.Request):
    """Персональная анимированная вставка для превью в приложении."""
    u = auth(request)
    vids = await personal_videos(ensure_promo(u["id"]), u["id"], preview=True)
    if not vids:
        return err("ffmpeg не установлен", 503)
    return web.FileResponse(vids[1 if request.query.get("kind") == "top" else 0][0], headers={"Content-Type": "video/mp4"})


async def api_banner(request: web.Request):
    u = auth(request)
    code = ensure_promo(u["id"])
    kind = request.query.get("kind", "vertical")
    png = banners.plaque(code, EXCHANGE_TG) if kind == "plaque" else banners.vertical(code, EXCHANGE_TG)
    return web.Response(body=png, content_type="image/png")


def _check_secret(request: web.Request):
    if not TRACK_SECRET or not hmac.compare_digest(request.headers.get("X-Track-Secret", ""), TRACK_SECRET):
        raise web.HTTPForbidden(text=json.dumps({"error": "bad secret"}), content_type="application/json")


def _author_by_promo(code: str):
    return q("SELECT * FROM users WHERE promo=? AND banned=0", (code or "").strip().upper(), one=True)


async def api_promo_check(request: web.Request):
    """Для бота обменника: GET /api/promo/VOVA → существует ли промокод."""
    _check_secret(request)
    a = _author_by_promo(request.match_info["code"])
    return web.json_response({"valid": bool(a), "author_id": a["id"] if a else None})


async def _promo_body(request: web.Request) -> dict:
    _check_secret(request)
    try:
        return await request.json()
    except Exception:
        raise web.HTTPBadRequest(text=json.dumps({"error": "нужен JSON"}), content_type="application/json")


def _is_new(v):
    return None if v is None else bool(v)


async def api_promo_validate(request: web.Request):
    """Бот обменника: проверить промокод (ничего не резервирует)."""
    b = await _promo_body(request)
    r = promo_validate(b.get("code"), b.get("client_id"), b.get("amount_rub"), b.get("payer"), _is_new(b.get("is_new")), "api")
    return web.json_response(await promo_after_check(request.app["bot"], r))


async def api_promo_apply(request: web.Request):
    """Бот обменника: применить промокод к заявке order_id (скидка закрепляется до завершения/отмены)."""
    b = await _promo_body(request)
    if not str(b.get("order_id") or "").strip():
        return err("order_id обязателен")
    r = promo_apply(b.get("code"), b.get("client_id"), b.get("amount_rub"), b.get("payer"), b.get("order_id"),
                    _is_new(b.get("is_new")), "api")
    return web.json_response(await promo_after_check(request.app["bot"], r))


async def api_cashback_validate(request: web.Request):
    """Бот обменника: есть ли у клиента кэшбэк на этот обмен."""
    b = await _promo_body(request)
    r = cashback_validate(b.get("client_id"), b.get("amount_rub"), b.get("payer"), "api")
    r.pop("payer_hash", None)
    return web.json_response(r)


async def api_cashback_apply(request: web.Request):
    b = await _promo_body(request)
    if not str(b.get("order_id") or "").strip():
        return err("order_id обязателен")
    r = cashback_apply(b.get("client_id"), b.get("amount_rub"), b.get("payer"), b.get("order_id"), "api")
    r.pop("payer_hash", None)
    return web.json_response(r)


async def api_promo_finish(request: web.Request):
    """Бот обменника: заявка с промокодом завершена (complete) или отменена (cancel)."""
    b = await _promo_body(request)
    act = request.match_info["act"]
    u, st = promo_finish(b.get("order_id"), act, b.get("amount_rub"), b.get("profit_rub"), touch_clients=False)
    if st in ("not_found", "bad_act"):
        return err("Заявка не найдена" if st == "not_found" else "неизвестное действие", 404 if st == "not_found" else 400)
    return web.json_response({"ok": True, "status": u["status"], "result": st})


def record_exchange_activation(code: str, author_id: int, client_id: int, discount: int) -> None:
    """Активация купона, которую подтвердил обменник. Один раз на клиента."""
    ck = str(int(client_id))
    if q("SELECT 1 FROM promo_uses WHERE client_key=? AND status IN ('pending','done')", ck, one=True):
        return
    q(
        "INSERT INTO promo_uses(code, author_id, client_key, payer_hash, order_id, amount, discount, status, source, created, kind) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        code, author_id, ck, None, None, 0, int(discount or 0), "pending", "exchange", int(time.time()), "first",
    )


def mark_exchange_activation_done(client_id: int, order_id: str, amount: int) -> None:
    ck = str(int(client_id))
    use = q(
        "SELECT * FROM promo_uses WHERE client_key=? AND kind='first' AND status IN ('pending','done') ORDER BY id DESC LIMIT 1",
        ck,
        one=True,
    )
    if not use or (use["status"] == "done" and use["order_id"]):
        return
    now = int(time.time())
    oid = (order_id or "").strip()[:64]
    can_attach = bool(oid) and not use["order_id"] and not q("SELECT 1 FROM promo_uses WHERE order_id=?", oid, one=True)
    if can_attach:
        q(
            "UPDATE promo_uses SET status='done', completed=?, amount=CASE WHEN COALESCE(amount,0)=0 THEN ? ELSE amount END, order_id=? WHERE id=?",
            now, int(amount or 0), oid, use["id"],
        )
        return
    q(
        "UPDATE promo_uses SET status='done', completed=?, amount=CASE WHEN COALESCE(amount,0)=0 THEN ? ELSE amount END WHERE id=?",
        now, int(amount or 0), use["id"],
    )


async def api_track(request: web.Request):
    """Для бота обменника. События:
    {"event":"start","client_id":123,"start_param":"p_VOVA_tt"}  — клиент пришёл по ссылке автора
    {"event":"promo","client_id":123,"promo":"VOVA"}              — клиент ввёл промокод
    {"event":"exchange","client_id":123,"amount_rub":15000}       — клиент совершил обмен
    """
    _check_secret(request)
    b = await request.json()
    cid = int(b.get("client_id", 0))
    if not cid:
        return err("client_id обязателен")
    ev = b.get("event")
    now = int(time.time())
    bot = request.app["bot"]
    if ev in ("start", "promo"):
        if ev == "start":
            m = re.match(r"p_([A-Za-z0-9]+)(?:_(tt|ig|yt|vk))?$", str(b.get("start_param", "")), re.I)
            if not m:
                return web.json_response({"ok": False, "reason": "не наш start_param"})
            code, pf = m.group(1).upper(), (m.group(2) or "link").lower()
        else:
            code, pf = str(b.get("promo", "")).upper(), "promo"
        a = _author_by_promo(code)
        if not a:
            return web.json_response({"ok": False, "reason": "промокод не найден"})
        if a["id"] == cid:
            return web.json_response({"ok": False, "reason": "свой промокод"})
        if ev == "promo":
            record_exchange_activation(code, a["id"], cid, _to_int(b.get("discount") or PROMO_DISCOUNT))
        exists = q("SELECT * FROM clients WHERE client_id=?", cid, one=True)
        if exists:   # клиента закрепляем за первым автором
            return web.json_response({"ok": True, "author_id": exists["author_id"], "new": False})
        q("INSERT INTO clients(client_id, author_id, platform, source, created) VALUES(?,?,?,?,?)",
          cid, a["id"], pf, code, now)
        return web.json_response({"ok": True, "author_id": a["id"], "new": True})
    if ev == "exchange":
        oid = str(b.get("order_id") or "").strip()[:64]
        amount_early = int(b.get("amount_rub", 0) or 0)
        if oid:
            if q("SELECT 1 FROM orders WHERE order_id=?", oid, one=True):
                mark_exchange_activation_done(cid, oid, amount_early)
                return web.json_response({"ok": True, "duplicate": True})
            q("INSERT INTO orders(order_id, client_id, amount, created) VALUES(?,?,?,?)", oid, cid, amount_early, now)
        c = q("SELECT * FROM clients WHERE client_id=?", cid, one=True)
        if not c:
            mark_exchange_activation_done(cid, oid, amount_early)
            return web.json_response({"ok": True, "attributed": False})
        amount = int(b.get("amount_rub", 0) or 0)
        profit = int(b.get("profit_rub", 0) or 0)
        first = c["exchanges"] == 0
        q("UPDATE clients SET exchanges=exchanges+1, volume=volume+?, profit=profit+?, first_exchange=COALESCE(first_exchange, ?) "
          "WHERE client_id=?", amount, profit, now, cid)
        mark_exchange_activation_done(cid, oid, amount)
        if first and CLIENT_REWARD > 0:
            add_bonus(c["author_id"], "client", CLIENT_REWARD, f"клиент {cid}")
            await safe_send(bot, c["author_id"], f"💎 Новый клиент по твоему промокоду сделал первый обмен! "
                                                 f"+{sp(CLIENT_REWARD)} ₽ на баланс.")
        return web.json_response({"ok": True, "attributed": True, "first": first})
    return err("неизвестное событие")


# ───────────────────────── Панель оператора обменника ─────────────────────────
def operator_auth(request: web.Request):
    u = auth(request, need_accepted=False)
    if not is_operator(u["id"]):
        raise web.HTTPForbidden(text=json.dumps({"error": "Только для операторов обменника"}), content_type="application/json")
    return u


def _use_row(r) -> dict:
    a = q("SELECT * FROM users WHERE id=?", r["author_id"], one=True)
    return {"id": r["id"], "code": r["code"], "author": user_label(a) if a else "—", "author_id": r["author_id"],
            "client": r["client_key"], "order_id": r["order_id"], "amount": r["amount"], "discount": r["discount"],
            "profit": r["profit"], "status": r["status"], "source": r["source"], "created": r["created"], "completed": r["completed"],
            "kind": r["kind"] or "first"}


async def op_me(request: web.Request):
    u = operator_auth(request)
    return web.json_response({"name": user_label(u), "admin": is_admin(u["id"]), "cashback": PROMO_DISCOUNT,
                              "mode": "cashback" if PROMO_MODE else "instant",
                              "days": PROMO_CASHBACK_DAYS, "min_amount": PROMO_MIN_AMOUNT, "on": bool(PROMO_ON)})


async def op_check(request: web.Request):
    u = operator_auth(request)
    b = await request.json()
    is_new = False if b.get("was_client") else None
    r = promo_validate(b.get("code"), b.get("client"), b.get("amount"), b.get("payer"), is_new, "operator")
    return web.json_response(await promo_after_check(request.app["bot"], r))


async def op_apply(request: web.Request):
    u = operator_auth(request)
    b = await request.json()
    is_new = False if b.get("was_client") else None
    r = promo_apply(b.get("code"), b.get("client"), b.get("amount"), b.get("payer"), b.get("order_id"), is_new,
                    "operator", u["id"])
    return web.json_response(await promo_after_check(request.app["bot"], r))


async def op_cashback(request: web.Request):
    u = operator_auth(request)
    b = await request.json()
    if b.get("apply"):
        r = cashback_apply(b.get("client"), b.get("amount"), b.get("payer"), b.get("order_id"), "operator", u["id"])
    else:
        r = cashback_validate(b.get("client"), b.get("amount"), b.get("payer"), "operator")
    r.pop("payer_hash", None)
    return web.json_response(r)


async def op_uses(request: web.Request):
    u = operator_auth(request)
    _expire_pending()
    since = int(time.time()) - 3 * 86400
    if is_admin(u["id"]) and request.query.get("all") == "1":
        rows = q("SELECT * FROM promo_uses WHERE created>=? ORDER BY id DESC LIMIT 100", since)
    else:
        rows = q("SELECT * FROM promo_uses WHERE operator_id=? AND created>=? ORDER BY id DESC LIMIT 100", u["id"], since)
    return web.json_response({"items": [_use_row(r) for r in rows]})


async def op_use_action(request: web.Request):
    u = operator_auth(request)
    r = q("SELECT * FROM promo_uses WHERE id=?", int(request.match_info["uid"]), one=True)
    if not r or (r["operator_id"] != u["id"] and not is_admin(u["id"])):
        return err("Применение не найдено", 404)
    b = await request.json() if request.can_read_body else {}
    row, st = promo_finish(r["order_id"], request.match_info["act"], b.get("amount"), b.get("profit"), touch_clients=True)
    if st in ("not_found", "bad_act"):
        return err("Не получилось")
    return web.json_response({"ok": True, "status": row["status"], "result": st})


async def operator_page(request: web.Request):
    return web.FileResponse(BASE / "webapp" / "operator.html")


IDEA_STATUS = {"new": "Новая", "progress": "В работе", "done": "Добавлено", "rejected": "Отклонено"}


async def api_ideas(request: web.Request):
    u = auth(request)
    order = "created DESC" if request.query.get("sort") == "new" else "likes DESC, created DESC"
    rows = q("SELECT i.*, us.username, us.first_name, (SELECT COUNT(*) FROM idea_likes l WHERE l.idea_id=i.id) likes, "
             "EXISTS(SELECT 1 FROM idea_likes l WHERE l.idea_id=i.id AND l.user_id=?) mine "
             f"FROM ideas i JOIN users us ON us.id=i.user_id WHERE i.status!='rejected' ORDER BY {order} LIMIT 50", u["id"])
    return web.json_response({"ideas": [
        {"id": r["id"], "text": r["text"], "status": r["status"], "status_name": IDEA_STATUS[r["status"]],
         "likes": r["likes"], "liked": bool(r["mine"]), "own": r["user_id"] == u["id"], "created": r["created"],
         "author": ("@" + r["username"]) if r["username"] else (r["first_name"] or "Автор")} for r in rows]})


async def api_idea_add(request: web.Request):
    u = auth(request)
    text = re.sub(r"\s+", " ", str((await request.json()).get("text", ""))).strip()
    if len(text) < 10:
        return err("Опиши идею подробнее (от 10 символов)")
    if len(text) > 300:
        return err("Слишком длинно — до 300 символов")
    today = q("SELECT COUNT(*) c FROM ideas WHERE user_id=? AND created>=?", u["id"], int(time.time()) - 86400, one=True)["c"]
    if today >= 3:
        return err("Не больше 3 идей в сутки")
    q("INSERT INTO ideas(user_id, text, created) VALUES(?,?,?)", u["id"], text, int(time.time()))
    iid = q("SELECT MAX(id) m FROM ideas WHERE user_id=?", u["id"], one=True)["m"]
    q("INSERT OR IGNORE INTO idea_likes(idea_id, user_id) VALUES(?,?)", iid, u["id"])
    for aid in all_admins():
        await safe_send(request.app["bot"], aid, f"💡 <b>Новая идея #{iid}</b> от {user_label(u)}:\n{text}\n\n"
                                                 f"Статус: <code>/idea {iid} progress</code> · <code>done</code> · <code>reject</code>")
    return web.json_response({"ok": True, "id": iid})


async def api_idea_like(request: web.Request):
    u = auth(request)
    iid = int(request.match_info["iid"])
    if not q("SELECT id FROM ideas WHERE id=? AND status!='rejected'", iid, one=True):
        return err("Идея не найдена", 404)
    if q("SELECT 1 FROM idea_likes WHERE idea_id=? AND user_id=?", iid, u["id"], one=True):
        q("DELETE FROM idea_likes WHERE idea_id=? AND user_id=?", iid, u["id"])
        liked = False
    else:
        q("INSERT INTO idea_likes(idea_id, user_id) VALUES(?,?)", iid, u["id"])
        liked = True
    likes = q("SELECT COUNT(*) c FROM idea_likes WHERE idea_id=?", iid, one=True)["c"]
    return web.json_response({"ok": True, "liked": liked, "likes": likes})



# ───────────────────────── АДМИНКА: API ─────────────────────────
def admin_auth(request: web.Request):
    u = auth(request, need_accepted=False)
    if not is_admin(u["id"]):
        raise web.HTTPForbidden(text=json.dumps({"error": "Только для админов"}), content_type="application/json")
    return u


def _day_series(sql: str, days: int, *args) -> list[dict]:
    """sql должен вернуть строки (ts) — суммируем по дням."""
    now = time.time()
    t0 = time.mktime(time.localtime(now - (days - 1) * 86400)[:3] + (0, 0, 0, 0, 0, -1))
    buckets = [0] * days
    for r in q(sql, int(t0), *args):
        i = int((r[0] - t0) // 86400)
        if 0 <= i < days:
            buckets[i] += r[1] or 0
    return [{"d": time.strftime("%d.%m", time.localtime(t0 + i * 86400)), "v": v} for i, v in enumerate(buckets)]


async def adm_overview(request: web.Request):
    admin_auth(request)
    days = max(1, min(365, int(request.query.get("days", 30))))
    since = int(time.time()) - days * 86400
    one = lambda sql, *a: q(sql, *a, one=True)[0] or 0
    views = one("SELECT SUM(views_final) FROM videos WHERE status='approved' AND decided>=?", since)
    v_sub = one("SELECT COUNT(*) FROM videos WHERE created>=?", since)
    v_ok = one("SELECT COUNT(*) FROM videos WHERE status='approved' AND decided>=?", since)
    v_bad = one("SELECT COUNT(*) FROM videos WHERE status='rejected' AND decided>=?", since)
    v_auto = one("SELECT COUNT(*) FROM videos WHERE auto=1 AND decided>=?", since)
    paid = one("SELECT SUM(amount) FROM payouts WHERE status='paid' AND decided>=?", since)
    accrued_views = one("SELECT SUM(amount) FROM videos WHERE status='approved' AND decided>=?", since)
    bonuses = {r["kind"]: r["s"] for r in q("SELECT kind, SUM(amount) s FROM bonuses WHERE created>=? GROUP BY kind", since)}
    ref_paid = 0  # реферальные начисления учитываются в earned пригласившего; отдельно — из ref_earned (за всё время)
    accrued = accrued_views + sum(bonuses.values())
    clients = one("SELECT COUNT(*) FROM clients WHERE created>=?", since)
    exch = one("SELECT COUNT(*) FROM clients WHERE first_exchange>=?", since)
    volume = one("SELECT SUM(volume) FROM clients WHERE created>=?", since)
    profit = one("SELECT SUM(profit) FROM clients WHERE created>=?", since)
    new_authors = one("SELECT COUNT(*) FROM users WHERE created>=? AND accepted=1", since)
    active = one("SELECT COUNT(DISTINCT user_id) FROM videos WHERE created>=?", since)
    names = {"tt": "TikTok", "ig": "Reels", "yt": "Shorts", "vk": "VK", "promo": "Промокод"}
    by_pf = [{"name": names.get(r["platform"], r["platform"]), "came": r["c"], "exchanged": r["ex"] or 0, "volume": r["vol"] or 0}
             for r in q("SELECT platform, COUNT(*) c, SUM(CASE WHEN exchanges>0 THEN 1 ELSE 0 END) ex, SUM(volume) vol "
                        "FROM clients WHERE created>=? GROUP BY platform ORDER BY c DESC", since)]
    views_by_pf = [{"name": PLATFORMS[r["platform"]][0], "views": r["v"] or 0, "videos": r["n"]}
                   for r in q("SELECT platform, SUM(views_final) v, COUNT(*) n FROM videos WHERE status='approved' AND decided>=? "
                              "GROUP BY platform ORDER BY v DESC", since)]
    top_views = [dict(r) for r in q("SELECT v.user_id id, us.username, us.promo, SUM(v.views_final) views, SUM(v.amount) amount, COUNT(*) n "
                                    "FROM videos v JOIN users us ON us.id=v.user_id WHERE v.status='approved' AND v.decided>=? "
                                    "GROUP BY v.user_id ORDER BY views DESC LIMIT 7", since)]
    top_clients = [dict(r) for r in q("SELECT c.author_id id, us.username, us.promo, COUNT(*) came, "
                                      "SUM(CASE WHEN c.exchanges>0 THEN 1 ELSE 0 END) ex, SUM(c.volume) volume "
                                      "FROM clients c JOIN users us ON us.id=c.author_id WHERE c.created>=? "
                                      "GROUP BY c.author_id ORDER BY ex DESC, came DESC LIMIT 7", since)]
    funnel = [
        ["Зашли в бота", one("SELECT COUNT(*) FROM users WHERE created>=?", since)],
        ["Приняли правила", one("SELECT COUNT(*) FROM users WHERE created>=? AND accepted=1", since)],
        ["Сдали ролик", one("SELECT COUNT(*) FROM users u WHERE created>=? AND EXISTS(SELECT 1 FROM videos v WHERE v.user_id=u.id)", since)],
        ["Ролик принят", one("SELECT COUNT(*) FROM users u WHERE created>=? AND EXISTS(SELECT 1 FROM videos v WHERE v.user_id=u.id AND v.status='approved')", since)],
        ["Получили выплату", one("SELECT COUNT(*) FROM users u WHERE created>=? AND EXISTS(SELECT 1 FROM payouts p WHERE p.user_id=u.id AND p.status='paid')", since)],
    ]
    pend_v = q("SELECT COUNT(*) c, MIN(created) m FROM videos WHERE status='pending'", one=True)
    pend_p = q("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s, MIN(created) m FROM payouts WHERE status='pending'", one=True)
    flagged = one("SELECT COUNT(*) FROM videos WHERE status='pending' AND flags IS NOT NULL")
    now = time.time()
    alerts = []
    if pend_v["c"] and now - pend_v["m"] > 86400:
        alerts.append(f"Есть заявки на ролики старше 24 часов ({pend_v['c']} в очереди)")
    if pend_p["c"] and now - pend_p["m"] > 36 * 3600:
        alerts.append(f"Выводы ждут дольше 36 часов — авторы начнут нервничать ({pend_p['c']} на {sp(pend_p['s'])} ₽)")
    if flagged:
        alerts.append(f"Подозрительных заявок в очереди: {flagged}")
    paused_n = one("SELECT COUNT(*) FROM users WHERE promo_paused=1")
    if paused_n:
        alerts.append(f"Промокодов на паузе: {paused_n} — проверь в «Ещё → Промокоды»")
    if clients == 0 and views > 50000:
        alerts.append("Просмотры есть, а клиентов 0 — проверь связку с ботом обменника (INTEGRATION.md)")
    owed = one("SELECT SUM(balance) FROM users")
    promo_done = one("SELECT COUNT(*) FROM promo_uses WHERE status='done' AND created>=?", since)
    promo_disc = one("SELECT SUM(discount) FROM promo_uses WHERE status='done' AND created>=?", since)
    cost = accrued + promo_disc
    return web.json_response({
        "days": days,
        "kpi": {"views": views, "videos_submitted": v_sub, "videos_approved": v_ok, "videos_rejected": v_bad,
                "videos_auto": v_auto, "paid": paid, "accrued": accrued, "accrued_views": accrued_views, "bonuses": bonuses,
                "clients": clients, "exchanged": exch, "volume": volume, "profit": profit, "new_authors": new_authors,
                "active_authors": active, "owed": owed,
                "cpm": round(accrued_views / views * 1000, 1) if views else 0,
                "cpa": round(cost / exch) if exch else None,
                "conv": round(exch / clients * 100, 1) if clients else None,
                "roi": round((profit - cost) / cost * 100) if cost and profit else None,
                "promo_done": promo_done, "promo_disc": promo_disc},
        "series": {
            "views": _day_series("SELECT decided, views_final FROM videos WHERE status='approved' AND decided>=?", min(days, 31)),
            "clients": _day_series("SELECT created, 1 FROM clients WHERE created>=?", min(days, 31)),
            "paid": _day_series("SELECT decided, amount FROM payouts WHERE status='paid' AND decided>=?", min(days, 31)),
        },
        "by_platform": by_pf, "views_by_platform": views_by_pf, "top_views": top_views, "top_clients": top_clients,
        "funnel": funnel, "alerts": alerts,
        "queue": {"videos": pend_v["c"], "payouts": pend_p["c"], "payouts_sum": pend_p["s"], "flagged": flagged,
                  "ideas": one("SELECT COUNT(*) FROM ideas WHERE status='new'"),
                  "promo_paused": one("SELECT COUNT(*) FROM users WHERE promo_paused=1")},
    })


def _video_row(v) -> dict:
    u = get_user(v["user_id"])
    lv = level_info(v["user_id"])
    return {"id": v["id"], "platform": v["platform"], "platform_name": PLATFORMS[v["platform"]][0], "url": v["url"],
            "views_claimed": v["views_claimed"], "views_final": v["views_final"], "api_views": v["api_views"],
            "likes": v["likes"], "comments": v["comments"], "flags": v["flags"], "status": v["status"], "reason": v["reason"],
            "amount": v["amount"], "auto": bool(v["auto"]), "created": v["created"], "decided": v["decided"],
            "has_shot": bool(v["screenshot"]), "estimate": calc(v["api_views"] or v["views_claimed"], lv["rate"]),
            "author": {"id": u["id"], "name": user_label(u), "strikes": u["strikes"], "level": lv["name"], "promo": u["promo"]}}


async def adm_videos(request: web.Request):
    admin_auth(request)
    st = request.query.get("status", "pending")
    order = "id ASC" if st == "pending" else "id DESC"
    rows = q(f"SELECT * FROM videos WHERE status=? ORDER BY {order} LIMIT 100", st)
    return web.json_response({"items": [_video_row(v) for v in rows]})


async def adm_shot(request: web.Request):
    admin_auth(request)
    v = q("SELECT screenshot FROM videos WHERE id=?", int(request.match_info["vid"]), one=True)
    if not v or not v["screenshot"]:
        return err("Нет скрина", 404)
    bot = request.app["bot"]
    f = await bot.get_file(v["screenshot"])
    data = await bot.download_file(f.file_path)
    return web.Response(body=data.read(), content_type="image/jpeg")


async def reject_video_fn(bot: Bot, vid: int, code: str) -> str:
    v = q("SELECT * FROM videos WHERE id=?", vid, one=True)
    if not v or v["status"] != "pending":
        return "Заявка уже обработана"
    reason = REJECT_REASONS.get(code, REJECT_REASONS["other"])
    q("UPDATE videos SET status='rejected', reason=?, decided=? WHERE id=?", reason, int(time.time()), vid)
    extra = ""
    if code == "fake":
        q("UPDATE users SET strikes=strikes+1 WHERE id=?", v["user_id"])
        if get_user(v["user_id"])["strikes"] >= 2:
            q("UPDATE users SET banned=1 WHERE id=?", v["user_id"])
            extra = "\n⛔ Повторное нарушение — доступ закрыт."
        else:
            extra = "\n⚠️ Предупреждение. Повторная накрутка — бан."
    await safe_send(bot, v["user_id"], f"❌ Заявка #{vid} отклонена: {reason}.{extra}")
    return f"#{vid} отклонена: {reason}"


async def adm_video_action(request: web.Request):
    admin_auth(request)
    vid, act = int(request.match_info["vid"]), request.match_info["act"]
    b = await request.json() if request.can_read_body else {}
    bot = request.app["bot"]
    if act == "approve":
        v = q("SELECT * FROM videos WHERE id=?", vid, one=True)
        views = int(b.get("views") or (v["api_views"] or v["views_claimed"]))
        return web.json_response({"ok": True, "msg": await approve_video(bot, vid, views)})
    if act == "reject":
        return web.json_response({"ok": True, "msg": await reject_video_fn(bot, vid, b.get("code", "other"))})
    return err("неизвестное действие")


async def adm_payouts(request: web.Request):
    admin_auth(request)
    st = request.query.get("status", "pending")
    rows = q("SELECT p.*, us.username, us.first_name FROM payouts p JOIN users us ON us.id=p.user_id WHERE p.status=? "
             f"ORDER BY {'p.id ASC' if st == 'pending' else 'p.id DESC'} LIMIT 100", st)
    vip_from = LEVELS[-1][1]
    return web.json_response({"items": [{
        "id": r["id"], "user_id": r["user_id"], "name": ("@" + r["username"]) if r["username"] else (r["first_name"] or str(r["user_id"])),
        "method": METHODS.get(r["method"], r["method"]), "details": r["details"], "amount": r["amount"], "status": r["status"],
        "created": r["created"], "decided": r["decided"], "vip": user_views(r["user_id"]) >= vip_from} for r in rows]})


async def adm_payout_action(request: web.Request):
    admin_auth(request)
    pid, act = int(request.match_info["pid"]), request.match_info["act"]
    p_ = q("SELECT * FROM payouts WHERE id=?", pid, one=True)
    if not p_ or p_["status"] != "pending":
        return err("Уже обработано")
    bot = request.app["bot"]
    now = int(time.time())
    if act == "paid":
        q("UPDATE payouts SET status='paid', decided=? WHERE id=?", now, pid)
        await safe_send(bot, p_["user_id"], f"💸 Вывод #{pid} на {sp(p_['amount'])} ₽ отправлен. Спасибо за работу!")
    elif act == "reject":
        q("UPDATE payouts SET status='rejected', decided=? WHERE id=?", now, pid)
        q("UPDATE users SET balance=balance+? WHERE id=?", p_["amount"], p_["user_id"])
        await safe_send(bot, p_["user_id"], f"↩ Вывод #{pid} отклонён, {sp(p_['amount'])} ₽ вернулись на баланс. "
                                            f"Проверь реквизиты или напиши {SUPPORT_TG}.")
    else:
        return err("неизвестное действие")
    return web.json_response({"ok": True})


async def adm_authors(request: web.Request):
    admin_auth(request)
    sq = (request.query.get("q") or "").strip().lstrip("@").lower()
    sort = {"views": "views DESC", "earned": "u.earned DESC", "clients": "clients DESC", "new": "u.created DESC"}.get(
        request.query.get("sort", "views"), "views DESC")
    rows = q("SELECT u.*, (SELECT COALESCE(SUM(views_final),0) FROM videos v WHERE v.user_id=u.id AND v.status='approved') views, "
             "(SELECT COUNT(*) FROM videos v WHERE v.user_id=u.id AND v.status='approved') vids, "
             "(SELECT COUNT(*) FROM clients c WHERE c.author_id=u.id) clients, "
             "(SELECT COALESCE(SUM(amount),0) FROM payouts p WHERE p.user_id=u.id AND p.status='paid') paid, "
             "(SELECT COUNT(*) FROM promo_uses pu WHERE pu.author_id=u.id AND pu.status='done') promo_n "
             "FROM users u WHERE u.accepted=1 AND (?='' OR LOWER(COALESCE(u.username,'')) LIKE ? OR LOWER(COALESCE(u.promo,'')) LIKE ? "
             f"OR CAST(u.id AS TEXT)=?) ORDER BY {sort} LIMIT 100", sq, f"%{sq}%", f"%{sq}%", sq)
    return web.json_response({"items": [{
        "id": r["id"], "name": user_label(r), "promo": r["promo"], "views": r["views"], "videos": r["vids"],
        "clients": r["clients"], "earned": r["earned"], "paid": r["paid"], "balance": r["balance"], "strikes": r["strikes"],
        "banned": bool(r["banned"]), "level": LEVELS[level_of(r["views"])][0], "created": r["created"],
        "promo_n": r["promo_n"], "promo_paused": bool(r["promo_paused"])} for r in rows]})


async def adm_author_action(request: web.Request):
    admin_auth(request)
    uid, act = int(request.match_info["uid"]), request.match_info["act"]
    b = await request.json() if request.can_read_body else {}
    bot = request.app["bot"]
    if not q("SELECT id FROM users WHERE id=?", uid, one=True):
        return err("Нет такого автора", 404)
    if act in ("ban", "unban"):
        flag = 1 if act == "ban" else 0
        q("UPDATE users SET banned=?, strikes=CASE WHEN ?=0 THEN 0 ELSE strikes END WHERE id=?", flag, flag, uid)
        if flag:
            q("UPDATE videos SET status='rejected', reason='бан автора', decided=? WHERE user_id=? AND status='pending'", int(time.time()), uid)
        await safe_send(bot, uid, "⛔ Доступ к партнёрке закрыт за нарушение правил." if flag else "✅ Доступ к партнёрке восстановлен.")
        return web.json_response({"ok": True})
    if act == "bonus":
        amount = int(b.get("amount", 0))
        note = str(b.get("note", "")).strip()[:200] or "от команды"
        if not amount:
            return err("Сумма не может быть 0")
        if amount < 0:
            bal = get_user(uid)["balance"]
            if bal <= 0:
                return err("У автора нулевой баланс — списывать нечего")
            amount = max(amount, -bal)
        q("INSERT INTO bonuses(user_id, kind, amount, note, created) VALUES(?,?,?,?,?)", uid, "manual", amount, note, int(time.time()))
        q("UPDATE users SET balance=balance+?, earned=earned+? WHERE id=?", amount, max(amount, 0), uid)
        await safe_send(bot, uid, (f"🎁 Бонус +{sp(amount)} ₽: {note}" if amount > 0 else f"➖ Списание {sp(-amount)} ₽: {note}"))
        return web.json_response({"ok": True})
    if act == "message":
        text = str(b.get("text", "")).strip()
        if not text:
            return err("Пустое сообщение")
        await safe_send(bot, uid, "💬 <b>Сообщение от команды:</b>\n" + text)
        return web.json_response({"ok": True})
    return err("неизвестное действие")


async def adm_ideas(request: web.Request):
    admin_auth(request)
    rows = q("SELECT i.*, us.username, us.first_name, (SELECT COUNT(*) FROM idea_likes l WHERE l.idea_id=i.id) likes "
             "FROM ideas i JOIN users us ON us.id=i.user_id ORDER BY CASE i.status WHEN 'new' THEN 0 WHEN 'progress' THEN 1 "
             "WHEN 'done' THEN 2 ELSE 3 END, likes DESC LIMIT 100")
    return web.json_response({"items": [{"id": r["id"], "text": r["text"], "status": r["status"], "status_name": IDEA_STATUS[r["status"]],
                                         "likes": r["likes"], "author": ("@" + r["username"]) if r["username"] else (r["first_name"] or "Автор"),
                                         "created": r["created"]} for r in rows]})


async def adm_idea_action(request: web.Request):
    admin_auth(request)
    iid = int(request.match_info["iid"])
    st = (await request.json()).get("status")
    if st not in IDEA_STATUS:
        return err("неверный статус")
    idea = q("SELECT * FROM ideas WHERE id=?", iid, one=True)
    if not idea:
        return err("Нет идеи", 404)
    q("UPDATE ideas SET status=? WHERE id=?", st, iid)
    note = {"progress": "взяли в работу 🛠", "done": "добавили в бота 🎉 Спасибо!", "rejected": "пока отложили", "new": None}[st]
    if note:
        await safe_send(request.app["bot"], idea["user_id"], f"💡 Твою идею #{iid} {note}\n«{idea['text'][:200]}»")
    return web.json_response({"ok": True})


async def adm_broadcast(request: web.Request):
    admin_auth(request)
    text = str((await request.json()).get("text", "")).strip()
    if len(text) < 3:
        return err("Слишком короткий текст")
    bot = request.app["bot"]

    async def run():
        ok = 0
        users = q("SELECT id FROM users WHERE accepted=1 AND banned=0")
        for u in users:
            try:
                await bot.send_message(u["id"], text)
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        for aid in all_admins():
            await safe_send(bot, aid, f"📣 Рассылка завершена: {ok} из {len(users)}")
    asyncio.create_task(run())
    return web.json_response({"ok": True, "total": q("SELECT COUNT(*) c FROM users WHERE accepted=1 AND banned=0", one=True)["c"]})


async def adm_settings(request: web.Request):
    admin_auth(request)
    if request.method == "POST":
        b = await request.json()
        for k, v in b.items():
            if k in EDITABLE:
                try:
                    val = EDITABLE[k][1](v)
                except (TypeError, ValueError):
                    return err(f"Неверное значение: {EDITABLE[k][0]}")
                if val < 0:
                    return err(f"Не может быть меньше 0: {EDITABLE[k][0]}")
                q("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", k, str(val))
        apply_settings()
    return web.json_response({"items": [{"key": k, "label": lbl, "value": (float(globals()[k]) if tp is float else int(globals()[k])),
                                         "float": tp is float} for k, (lbl, tp) in EDITABLE.items()]})


async def adm_export(request: web.Request):
    u = admin_auth(request)
    kind = (await request.json()).get("type", "videos")
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if kind == "payouts":
        w.writerow(["id", "автор_id", "сумма", "способ", "реквизиты", "статус", "создан", "решение"])
        for r in q("SELECT * FROM payouts ORDER BY id"):
            w.writerow([r["id"], r["user_id"], r["amount"], r["method"], r["details"], r["status"],
                        time.strftime("%d.%m.%Y %H:%M", time.localtime(r["created"])),
                        time.strftime("%d.%m.%Y %H:%M", time.localtime(r["decided"])) if r["decided"] else ""])
    elif kind == "clients":
        w.writerow(["клиент_id", "автор_id", "площадка", "промокод", "пришёл", "обменов", "оборот", "прибыль"])
        for r in q("SELECT * FROM clients ORDER BY created"):
            w.writerow([r["client_id"], r["author_id"], r["platform"], r["source"],
                        time.strftime("%d.%m.%Y", time.localtime(r["created"])), r["exchanges"], r["volume"], r["profit"]])
    elif kind == "promo":
        w.writerow(["id", "код", "автор_id", "клиент", "заявка", "сумма", "скидка", "прибыль", "статус", "источник", "создано"])
        for r in q("SELECT * FROM promo_uses ORDER BY id"):
            w.writerow([r["id"], r["code"], r["author_id"], r["client_key"], r["order_id"], r["amount"], r["discount"], r["profit"],
                        r["status"], r["source"], time.strftime("%d.%m.%Y %H:%M", time.localtime(r["created"]))])
    elif kind == "authors":
        w.writerow(["id", "ник", "промокод", "баланс", "заработано", "нарушений", "бан", "с"])
        for r in q("SELECT * FROM users WHERE accepted=1 ORDER BY created"):
            w.writerow([r["id"], r["username"], r["promo"], r["balance"], r["earned"], r["strikes"], r["banned"],
                        time.strftime("%d.%m.%Y", time.localtime(r["created"] or 0))])
    else:
        kind = "videos"
        w.writerow(["id", "автор_id", "площадка", "ссылка", "заявлено", "засчитано", "сумма", "статус", "причина", "создана"])
        for r in q("SELECT * FROM videos ORDER BY id"):
            w.writerow([r["id"], r["user_id"], r["platform"], r["url"], r["views_claimed"], r["views_final"], r["amount"],
                        r["status"], r["reason"], time.strftime("%d.%m.%Y %H:%M", time.localtime(r["created"]))])
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    await request.app["bot"].send_document(u["id"], BufferedInputFile(data, f"focuspay_{kind}_{time.strftime('%Y%m%d')}.csv"),
                                           caption=f"📄 Выгрузка: {kind}. Открывается в Excel / Google Таблицах.")
    return web.json_response({"ok": True})



# ───────────────────────── АДМИНКА: озвучки (OpenAI TTS) и тест баннера ─────────────────────────
VOICE_DIR = MATERIALS_DIR / "voices"
TTS_VOICES = [("onyx", "Мужской, низкий"), ("ash", "Мужской, бодрый"), ("echo", "Мужской, спокойный"),
              ("verse", "Мужской, выразительный"), ("nova", "Женский, бодрый"), ("coral", "Женский, тёплый"),
              ("sage", "Нейтральный"), ("shimmer", "Женский, мягкий")]
TTS_STYLES = {
    "energy": "Говори по-русски как ведущий рекламы: энергично, уверенно, с улыбкой в голосе, чётко, без пауз между словами.",
    "deep": "Говори по-русски низким уверенным голосом, спокойно и весомо, как дорогая реклама банка.",
    "bold": "Говори по-русски дерзко и напористо, как брокер, который знает, что делает. Быстрый темп.",
    "friendly": "Говори по-русски дружелюбно и легко, как друг советует проверенный сервис.",
}
VOICE_PRESETS = [
    "Меняй выгодно и быстро с Focus Pay.",
    "Focus Pay — обмен, который не отвлекает. Промокод на экране.",
    "Пока другие ждут, ты уже поменял. Focus Pay.",
    "Focus Pay. Быстро. Понятно. Без лишних движений.",
    "Нужно поменять? Focus Pay — ссылка в шапке профиля.",
    "Вводи промокод автора и меняй с Focus Pay.",
    "Рубли, USDT, крипта — меняй спокойно с Focus Pay.",
    "Не ищи обменник в чатах. Есть Focus Pay.",
]


def _voice_meta() -> dict:
    f = VOICE_DIR / "voices.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _voice_meta_save(meta: dict):
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    (VOICE_DIR / "voices.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


async def adm_voices(request: web.Request):
    admin_auth(request)
    meta = _voice_meta()
    active = (meta.get("_active") or {}).get("file")
    items = []
    for f in sorted(VOICE_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True) if VOICE_DIR.exists() else []:
        m = meta.get(f.name, {})
        items.append({"file": f.name, "text": m.get("text", f.stem), "voice": m.get("voice", ""), "style": m.get("style", ""),
                      "active": f.name == active, "created": int(f.stat().st_mtime)})
    return web.json_response({"items": items, "presets": VOICE_PRESETS,
                              "voices": [{"id": v, "label": l} for v, l in TTS_VOICES],
                              "styles": [{"id": k, "label": {"energy": "Энергично", "deep": "Низко и весомо", "bold": "Дерзко",
                                                             "friendly": "Дружелюбно"}[k]} for k in TTS_STYLES],
                              "tts": bool(OPENAI_API_KEY), "has_brand": bool(brand.brand_file(MATERIALS_DIR))})


async def adm_voice_create(request: web.Request):
    admin_auth(request)
    if not OPENAI_API_KEY:
        return err("Для озвучки нужен OPENAI_API_KEY в настройках")
    b = await request.json()
    text = str(b.get("text", "")).strip()
    if text not in VOICE_PRESETS:
        return err("Выбери одну из готовых фраз")
    voice = b.get("voice") if b.get("voice") in dict(TTS_VOICES) else "onyx"
    style = b.get("style") if b.get("style") in TTS_STYLES else "energy"
    if len(text) < 3:
        return err("Введи текст озвучки")
    body = {"model": OPENAI_TTS_MODEL, "voice": voice, "input": text, "response_format": "mp3", "instructions": TTS_STYLES[style]}
    async with aiohttp.ClientSession() as s:
        async with s.post("https://api.openai.com/v1/audio/speech", json=body, timeout=aiohttp.ClientTimeout(total=90),
                          headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}) as r:
            if r.status != 200:                                   # старая модель без стиля — запасной вариант
                first_err = await r.text()
                body = {"model": "tts-1-hd", "voice": voice if voice in ("onyx", "echo", "nova", "shimmer", "alloy", "fable") else "onyx",
                        "input": text, "response_format": "mp3"}
                async with s.post("https://api.openai.com/v1/audio/speech", json=body, timeout=aiohttp.ClientTimeout(total=90),
                                  headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}) as r2:
                    if r2.status != 200:
                        logging.warning("TTS: %s | %s", first_err[:300], (await r2.text())[:300])
                        return err("OpenAI не сделал озвучку: " + first_err[:200])
                    audio = await r2.read()
            else:
                audio = await r.read()
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    name = f"voice_{time.strftime('%m%d_%H%M%S')}_{voice}.mp3"
    (VOICE_DIR / name).write_bytes(audio)
    meta = _voice_meta()
    meta[name] = {"text": text, "voice": voice, "style": style}
    _voice_meta_save(meta)
    return web.json_response({"ok": True, "file": name})


async def adm_voice_file(request: web.Request):
    admin_auth(request)
    f = VOICE_DIR / Path(request.match_info["name"]).name
    if not f.exists():
        return err("Нет файла", 404)
    return web.FileResponse(f, headers={"Content-Type": "audio/mpeg"})


async def adm_voice_action(request: web.Request):
    admin_auth(request)
    name, act = Path(request.match_info["name"]).name, request.match_info["act"]
    f = VOICE_DIR / name
    if not f.exists():
        return err("Нет файла", 404)
    meta = _voice_meta()
    if act == "active":
        import shutil as _sh
        _sh.copy(f, MATERIALS_DIR / "Озвучка вставка.mp3")
        meta["_active"] = {"file": name}
        _voice_meta_save(meta)
        return web.json_response({"ok": True, "msg": "Озвучка стала основной — баннеры авторов пересоберутся с ней"})
    if act == "delete":
        f.unlink()
        meta.pop(name, None)
        if (meta.get("_active") or {}).get("file") == name:
            meta.pop("_active", None)
        _voice_meta_save(meta)
        return web.json_response({"ok": True})
    return err("неизвестное действие")


async def api_voices(request: web.Request):
    u = auth(request)
    meta = _voice_meta()
    active = (meta.get("_active") or {}).get("file")
    chosen = u["voice"] if u["voice"] and (VOICE_DIR / u["voice"]).exists() else None
    labels = dict(TTS_VOICES)
    items = [{"file": f.name, "text": meta.get(f.name, {}).get("text", ""), "voice": labels.get(meta.get(f.name, {}).get("voice", ""), ""),
              "main": f.name == active, "chosen": f.name == chosen or (not chosen and f.name == active)}
             for f in sorted(VOICE_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime)] if VOICE_DIR.exists() else []
    return web.json_response({"items": items})


async def api_voice_file(request: web.Request):
    auth(request)
    f = VOICE_DIR / Path(request.match_info["name"]).name
    if not f.exists() or f.suffix != ".mp3":
        return err("Нет файла", 404)
    return web.FileResponse(f, headers={"Content-Type": "audio/mpeg"})


async def api_voice_select(request: web.Request):
    u = auth(request)
    name = Path(str((await request.json()).get("file", ""))).name
    if not (VOICE_DIR / name).exists():
        return err("Такой озвучки нет")
    q("UPDATE users SET voice=? WHERE id=?", name, u["id"])
    return web.json_response({"ok": True})


async def adm_brand_test(request: web.Request):
    u = admin_auth(request)
    bot = request.app["bot"]
    code = ensure_promo(u["id"])

    async def run():
        try:
            await safe_send(bot, u["id"], "⏳ Собираю тестовые баннеры с твоим промокодом…")
            for path, name in await personal_videos(code, u["id"]):
                await bot.send_document(u["id"], FSInputFile(path, filename=name), caption=f"Тест: {name}")
        except Exception as e:
            await safe_send(bot, u["id"], f"❌ Не получилось собрать: {e}")
    asyncio.create_task(run())
    return web.json_response({"ok": True})


REASON_SHORT = {"exhausted": "Активации кончились", "expired": "Код истёк", "new_account": "Новый аккаунт", "no_cashback": "Нет кэшбэка", "cashback_expired": "Кэшбэк истёк",
                "cashback_used": "Кэшбэк уже был", "budget": "Бюджет месяца", "off": "Промокоды выключены", "not_found": "Нет такого кода", "paused": "Код на паузе",
                "no_client": "Без клиента", "no_payer": "Без реквизитов", "own": "Свой код", "min_amount": "Сумма меньше минимума",
                "not_new": "Не первый обмен", "client_used": "Клиент уже применял", "payer_used": "Реквизиты уже были",
                "limit": "Дневной лимит"}


async def adm_promo(request: web.Request):
    admin_auth(request)
    _expire_pending()
    days = max(1, min(365, int(request.query.get("days", 30))))
    now = int(time.time())
    since = now - days * 86400
    one = lambda sql, *a: q(sql, *a, one=True)[0] or 0
    done_n = one("SELECT COUNT(*) FROM promo_uses WHERE kind='first' AND status='done' AND created>=?", since)
    cb_n = one("SELECT COUNT(*) FROM promo_uses WHERE kind='cashback' AND status='done' AND created>=?", since)
    volume = one("SELECT SUM(amount) FROM promo_uses WHERE status='done' AND created>=?", since)
    month_used = one("SELECT SUM(discount) FROM promo_uses WHERE kind='cashback' AND status IN ('pending','done') AND created>=?", month_start())
    kpi = {"checks": one("SELECT COUNT(*) FROM promo_checks WHERE created>=?", since),
           "fails": one("SELECT COUNT(*) FROM promo_checks WHERE ok=0 AND created>=?", since),
           "done": done_n, "cashback_n": cb_n, "returned_pct": round(cb_n / done_n * 100) if done_n else None,
           "budget": PROMO_BUDGET, "budget_used": month_used,
           "pending": one("SELECT COUNT(*) FROM promo_uses WHERE status='pending'"),
           "cancelled": one("SELECT COUNT(*) FROM promo_uses WHERE status IN ('cancelled','expired') AND created>=?", since),
           "discounts": one("SELECT SUM(discount) FROM promo_uses WHERE status='done' AND created>=?", since),
           "volume": volume, "avg": round(volume / done_n) if done_n else 0,
           "profit": one("SELECT SUM(profit) FROM promo_uses WHERE status='done' AND created>=?", since),
           "codes_used": one("SELECT COUNT(DISTINCT code) FROM promo_uses WHERE status='done' AND created>=?", since),
           "paused": one("SELECT COUNT(*) FROM users WHERE promo_paused=1")}
    reasons = [{"name": REASON_SHORT.get(r["reason"], r["reason"]), "n": r["n"]} for r in q(
        "SELECT reason, COUNT(*) n FROM promo_checks WHERE ok=0 AND created>=? GROUP BY reason ORDER BY n DESC", since)]
    codes = []
    for r in q("SELECT pc.*, u.username, u.first_name, u.id uid, u.banned, u.promo_paused upaused, "
               "(SELECT COUNT(*) FROM promo_uses p WHERE p.code=pc.code AND p.status='done') done, "
               "(SELECT COALESCE(SUM(discount),0) FROM promo_uses p WHERE p.code=pc.code AND p.status='done') disc, "
               "(SELECT COALESCE(SUM(amount),0) FROM promo_uses p WHERE p.code=pc.code AND p.status='done') vol, "
               "(SELECT COUNT(*) FROM promo_checks c WHERE c.code=pc.code AND c.ok=0) fails, "
               "(SELECT COUNT(*) FROM promo_checks c WHERE c.code=pc.code AND c.reason='own') own, "
               "(SELECT COUNT(*) FROM videos v WHERE v.promo=pc.code) vids "
               "FROM promo_codes pc JOIN users u ON u.id=pc.author_id ORDER BY pc.created DESC LIMIT 150"):
        codes.append({"id": r["uid"], "code": r["code"], "name": user_label(r), "state": code_state(r),
                      "paused": bool(r["paused"] or r["upaused"]), "banned": bool(r["banned"]), "used": code_uses(r["code"]),
                      "max": r["max_uses"], "expires": r["expires"], "done": r["done"], "discounts": r["disc"],
                      "volume": r["vol"], "fails": r["fails"], "own": r["own"], "videos": r["vids"]})
    sus = []
    for r in q("SELECT code, author_id FROM promo_codes WHERE paused=1 AND closed=0"):
        sus.append({"kind": "paused", "text": f"Код {r['code']} на паузе (всплеск применений или вручную)", "code": r["code"]})
    for r in q("SELECT promo, id FROM users WHERE promo_paused=1"):
        sus.append({"kind": "paused_author", "text": f"Все коды автора на паузе (код {r['promo']})", "uid": r["id"]})
    for r in q("SELECT c.code, COUNT(*) n, u.id uid FROM promo_checks c JOIN users u ON u.promo=c.code "
               "WHERE c.reason='own' AND c.created>=? GROUP BY c.code", since):
        sus.append({"kind": "own", "text": f"Код {r['code']}: автор пытался применить свой код ({r['n']} раз)", "uid": r["uid"]})
    for r in q("SELECT payer_hash, COUNT(DISTINCT code) codes, GROUP_CONCAT(DISTINCT code) list FROM promo_checks "
               "WHERE payer_hash IS NOT NULL AND code!='' AND created>=? GROUP BY payer_hash HAVING codes>=2", since):
        sus.append({"kind": "payer", "text": f"Одни и те же реквизиты пробовали {r['codes']} разных кода: {r['list']}"})
    for r in q("SELECT client_key, COUNT(*) n, GROUP_CONCAT(DISTINCT code) list FROM promo_checks "
               "WHERE ok=0 AND client_key!='' AND created>=? GROUP BY client_key HAVING n>=3", now - 86400):
        sus.append({"kind": "client", "text": f"Клиент {r['client_key']}: {r['n']} неудачных попыток за сутки ({r['list']})"})
    recent = [_use_row(r) for r in q("SELECT * FROM promo_uses ORDER BY id DESC LIMIT 40")]
    ops = [{"id": r["id"], "name": r["name"] or "", "env": False} for r in q("SELECT * FROM operators ORDER BY added")]
    ops += [{"id": i, "name": "из настроек сервера", "env": True} for i in sorted(OPERATOR_IDS)]
    return web.json_response({"days": days, "kpi": kpi, "reasons": reasons, "codes": codes, "suspicious": sus,
                              "recent": recent, "operators": ops,
                              "rules": {"on": bool(PROMO_ON), "discount": PROMO_DISCOUNT, "min": PROMO_MIN_AMOUNT,
                                        "daily": PROMO_DAILY_LIMIT, "spike": PROMO_SPIKE, "days": PROMO_CASHBACK_DAYS,
                                        "mode": PROMO_MODE, "max_uses": PROMO_MAX_USES, "code_days": PROMO_CODE_DAYS,
                                        "budget": PROMO_BUDGET}})


async def adm_promo_code(request: web.Request):
    admin_auth(request)
    uid, act = int(request.match_info["uid"]), request.match_info["act"]
    a = q("SELECT * FROM users WHERE id=?", uid, one=True)
    if not a:
        return err("Нет автора", 404)
    bot = request.app["bot"]
    if act in ("pause", "resume"):
        q("UPDATE users SET promo_paused=? WHERE id=?", 1 if act == "pause" else 0, uid)
        await safe_send(bot, uid, "⏸ Твой промокод приостановлен. Вопросы — " + SUPPORT_TG if act == "pause"
                        else "▶️ Твой промокод снова работает.")
        return web.json_response({"ok": True})
    if act == "rename":
        code = re.sub(r"[^A-Za-z0-9]", "", str((await request.json()).get("code", ""))).upper()
        if not 4 <= len(code) <= 12:
            return err("Код: 4–12 символов, латиница и цифры")
        if any(w in code for w in PROMO_STOP):
            return err("Такие слова в коде нельзя")
        if q("SELECT 1 FROM users WHERE promo=? AND id!=?", code, uid, one=True):
            return err("Такой код уже занят")
        if q("SELECT 1 FROM promo_codes WHERE code=?", code, one=True):
            return err("Такой код уже был")
        q("UPDATE users SET promo=? WHERE id=?", code, uid)
        _register_code(code, uid)
        await safe_send(bot, uid, f"🎟 Твой промокод изменён: <b>{code}</b>. Возьми новые баннеры в «🎬 Материалы».")
        return web.json_response({"ok": True, "code": code})
    return err("неизвестное действие")


async def adm_promo_one(request: web.Request):
    """Действия с конкретным кодом: pause / resume / close / limit (+max) / extend (+days)."""
    admin_auth(request)
    code, act = request.match_info["code"].upper(), request.match_info["act"]
    pc = q("SELECT * FROM promo_codes WHERE code=?", code, one=True)
    if not pc:
        return err("Нет такого кода", 404)
    b = await request.json() if request.can_read_body else {}
    if act in ("pause", "resume"):
        q("UPDATE promo_codes SET paused=? WHERE code=?", 1 if act == "pause" else 0, code)
    elif act == "close":
        q("UPDATE promo_codes SET closed=1 WHERE code=?", code)
    elif act == "limit":
        m = _to_int(b.get("max"))
        if m < 0:
            return err("Неверное число")
        q("UPDATE promo_codes SET max_uses=?, notified=0 WHERE code=?", m, code)
    elif act == "extend":
        q("UPDATE promo_codes SET expires=? WHERE code=?", int(time.time()) + max(1, _to_int(b.get("days")) or 7) * 86400, code)
    else:
        return err("неизвестное действие")
    return web.json_response({"ok": True, "state": code_state(q("SELECT * FROM promo_codes WHERE code=?", code, one=True))})


async def adm_promo_use(request: web.Request):
    admin_auth(request)
    r = q("SELECT * FROM promo_uses WHERE id=?", int(request.match_info["id"]), one=True)
    if not r:
        return err("Нет применения", 404)
    row, st = promo_finish(r["order_id"], request.match_info["act"], touch_clients=r["source"] == "operator")
    if st in ("not_found", "bad_act"):
        return err("Не получилось")
    return web.json_response({"ok": True, "status": row["status"]})


async def adm_team(request: web.Request):
    u = admin_auth(request)
    admins = [{"id": i, "name": "главный (из настроек сервера)", "owner": True} for i in sorted(ADMIN_IDS)]
    admins += [{"id": r["id"], "name": r["name"] or "", "owner": False} for r in q("SELECT * FROM admins ORDER BY added")]
    ops = [{"id": r["id"], "name": r["name"] or "", "env": False} for r in q("SELECT * FROM operators ORDER BY added")]
    ops += [{"id": i, "name": "из настроек сервера", "env": True} for i in sorted(OPERATOR_IDS)]
    return web.json_response({"admins": admins, "operators": ops, "can_admins": is_owner(u["id"]), "me": u["id"]})


async def adm_admins(request: web.Request):
    u = admin_auth(request)
    if not is_owner(u["id"]):
        return err("Добавлять и убирать админов может только главный админ", 403)
    b = await request.json()
    aid = _to_int(b.get("id"))
    if b.get("remove"):
        q("DELETE FROM admins WHERE id=?", aid)
        return web.json_response({"ok": True})
    if aid <= 0:
        return err("Нужен числовой Telegram ID (человек узнает его командой /myid в боте)")
    q("INSERT OR REPLACE INTO admins(id, name, added) VALUES(?,?,?)", aid, str(b.get("name", "")).strip()[:60], int(time.time()))
    if WEBAPP_URL:
        await safe_send(request.app["bot"], aid, "Тебе дали доступ к админке Focus Pay 👇", InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📊 Открыть админку", web_app=WebAppInfo(url=WEBAPP_URL + "/admin"))]]))
    return web.json_response({"ok": True})


async def adm_operators(request: web.Request):
    admin_auth(request)
    b = await request.json()
    oid = _to_int(b.get("id"))
    if oid <= 0:
        return err("Нужен числовой Telegram ID (оператор узнает его командой /myid в боте)")
    q("INSERT OR REPLACE INTO operators(id, name, added) VALUES(?,?,?)", oid, str(b.get("name", "")).strip()[:60], int(time.time()))
    if WEBAPP_URL:
        await safe_send(request.app["bot"], oid, "Тебе дали доступ к проверке промокодов Focus Pay 👇", operator_kb())
    return web.json_response({"ok": True})


async def adm_operator_del(request: web.Request):
    admin_auth(request)
    q("DELETE FROM operators WHERE id=?", int(request.match_info["oid"]))
    return web.json_response({"ok": True})


async def admin_page(request: web.Request):
    return web.FileResponse(BASE / "webapp" / "admin.html")


async def daily_digest(bot: Bot):
    """Каждый день в DIGEST_HOUR — короткая сводка админам."""
    hour = int(os.getenv("DIGEST_HOUR", "10"))
    while True:
        now = time.localtime()
        target = time.mktime(now[:3] + (hour, 0, 0, 0, 0, -1))
        if target <= time.time():
            target += 86400
        await asyncio.sleep(target - time.time())
        try:
            since = int(time.time()) - 86400
            one = lambda sql, *a: q(sql, *a, one=True)[0] or 0
            txt = ("☀️ <b>Сводка за сутки</b>\n"
                   f"Роликов сдано: {one('SELECT COUNT(*) FROM videos WHERE created>=?', since)}, "
                   f"принято: {one('SELECT COUNT(*) FROM videos WHERE status=? AND decided>=?', 'approved', since)}\n"
                   f"Просмотров: {sp(one('SELECT SUM(views_final) FROM videos WHERE status=? AND decided>=?', 'approved', since))}\n"
                   f"Клиентов пришло: {one('SELECT COUNT(*) FROM clients WHERE created>=?', since)}, "
                   f"обменяли: {one('SELECT COUNT(*) FROM clients WHERE first_exchange>=?', since)}\n"
                   f"Выплачено: {sp(one('SELECT SUM(amount) FROM payouts WHERE status=? AND decided>=?', 'paid', since))} ₽\n"
                   f"Новых клиентов по промокодам: {one('SELECT COUNT(*) FROM promo_uses WHERE kind=? AND status=? AND created>=?', 'first', 'done', since)}, "
                   f"кэшбэков выдано: {sp(one('SELECT SUM(discount) FROM promo_uses WHERE kind=? AND status=? AND created>=?', 'cashback', 'done', since))} ₽\n"
                   f"Новых авторов: {one('SELECT COUNT(*) FROM users WHERE created>=? AND accepted=1', since)}\n\n"
                   f"⏳ В очереди: роликов {one('SELECT COUNT(*) FROM videos WHERE status=?', 'pending')}, "
                   f"выводов {one('SELECT COUNT(*) FROM payouts WHERE status=?', 'pending')}")
            for aid in all_admins():
                await safe_send(bot, aid, txt, ikb([[("📊 Открыть админку", "noop")]]) if not WEBAPP_URL else
                                InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                                    text="📊 Открыть админку", web_app=WebAppInfo(url=WEBAPP_URL + "/admin"))]]))
        except Exception as e:
            logging.warning("Сводка: %s", e)


async def files_handler(request: web.Request):
    """Только файлы из списка материалов: исходник бренда, озвучки и служебные файлы наружу не отдаются."""
    name = request.match_info["name"]
    for p_ in material_files():
        if p_.name == name:
            return web.FileResponse(p_)
    raise web.HTTPNotFound()


async def index(request: web.Request):
    return web.FileResponse(BASE / "webapp" / "index.html")


def build_web(bot: Bot) -> web.Application:
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app["bot"] = bot
    app.router.add_get("/", index)
    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/accept", api_accept)
    app.router.add_get("/api/video/{vid:\\d+}", api_video)
    app.router.add_post("/api/submit", api_submit)
    app.router.add_post("/api/payout", api_payout)
    app.router.add_get("/api/top", api_top)
    app.router.add_get("/api/materials", api_materials)
    app.router.add_post("/api/materials/send", api_materials_send)
    app.router.add_get("/api/banner", api_banner)
    app.router.add_get("/api/promo/{code}", api_promo_check)
    app.router.add_post("/api/track", api_track)
    app.router.add_post("/api/promo/validate", api_promo_validate)
    app.router.add_post("/api/me/promo/new", api_promo_new)
    app.router.add_post("/api/promo/apply", api_promo_apply)
    app.router.add_post("/api/promo/{act:complete|cancel}", api_promo_finish)
    app.router.add_post("/api/promo/cashback/validate", api_cashback_validate)
    app.router.add_post("/api/promo/cashback/apply", api_cashback_apply)
    app.router.add_post("/api/op/cashback", op_cashback)
    app.router.add_get("/operator", operator_page)
    app.router.add_get("/api/op/me", op_me)
    app.router.add_post("/api/op/check", op_check)
    app.router.add_post("/api/op/apply", op_apply)
    app.router.add_get("/api/op/uses", op_uses)
    app.router.add_post("/api/op/uses/{uid:\\d+}/{act:complete|cancel}", op_use_action)
    app.router.add_get("/api/admin/promo", adm_promo)
    app.router.add_post("/api/admin/promo/code/{uid:\\d+}/{act}", adm_promo_code)
    app.router.add_post("/api/admin/promo/use/{id:\\d+}/{act:complete|cancel}", adm_promo_use)
    app.router.add_post("/api/admin/promo/one/{code}/{act}", adm_promo_one)
    app.router.add_post("/api/admin/operators", adm_operators)
    app.router.add_get("/api/admin/team", adm_team)
    app.router.add_post("/api/admin/admins", adm_admins)
    app.router.add_post("/api/admin/operators/{oid:\\d+}/delete", adm_operator_del)
    app.router.add_get("/api/ideas", api_ideas)
    app.router.add_post("/api/ideas", api_idea_add)
    app.router.add_post("/api/ideas/{iid:\\d+}/like", api_idea_like)
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/api/admin/overview", adm_overview)
    app.router.add_get("/api/admin/videos", adm_videos)
    app.router.add_get("/api/admin/shot/{vid:\\d+}", adm_shot)
    app.router.add_post("/api/admin/videos/{vid:\\d+}/{act}", adm_video_action)
    app.router.add_get("/api/admin/payouts", adm_payouts)
    app.router.add_post("/api/admin/payouts/{pid:\\d+}/{act}", adm_payout_action)
    app.router.add_get("/api/admin/authors", adm_authors)
    app.router.add_post("/api/admin/authors/{uid:\\d+}/{act}", adm_author_action)
    app.router.add_get("/api/admin/ideas", adm_ideas)
    app.router.add_post("/api/admin/ideas/{iid:\\d+}", adm_idea_action)
    app.router.add_post("/api/admin/broadcast", adm_broadcast)
    app.router.add_get("/api/admin/settings", adm_settings)
    app.router.add_post("/api/admin/settings", adm_settings)
    app.router.add_post("/api/admin/export", adm_export)
    app.router.add_get("/api/admin/voices", adm_voices)
    app.router.add_post("/api/admin/voices", adm_voice_create)
    app.router.add_get("/api/admin/voice/{name}", adm_voice_file)
    app.router.add_post("/api/admin/voice/{name}/{act}", adm_voice_action)
    app.router.add_post("/api/admin/brandtest", adm_brand_test)
    app.router.add_get("/api/voices", api_voices)
    app.router.add_get("/api/voice/{name}", api_voice_file)
    app.router.add_post("/api/voice/select", api_voice_select)
    app.router.add_static("/static", BASE / "webapp" / "static")
    MATERIALS_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    app.router.add_get("/files/{name}", files_handler)
    app.router.add_get("/api/insert", api_insert)
    return app


async def main():
    global BOT_USERNAME
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("Заполни BOT_TOKEN в файле .env")
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS пуст — заявки никому не будут приходить!")
    # бонус за клиентов выключен по умолчанию (один раз; потом меняется в админке)
    if not q("SELECT 1 FROM settings WHERE key='CLIENT_REWARD'", one=True):
        q("INSERT INTO settings(key, value) VALUES('CLIENT_REWARD', '0')")
    apply_settings()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    BOT_USERNAME = (await bot.get_me()).username
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    runner = web.AppRunner(build_web(bot))
    await runner.setup()
    await web.TCPSite(runner, WEB_HOST, WEB_PORT).start()
    logging.info("Mini App: http://localhost:%s  (в Telegram — через WEBAPP_URL=%s)", WEB_PORT, WEBAPP_URL or "не задан")
    logging.info("ИИ-поддержка: %s | YouTube-проверка: %s | автоприём: %s | трекинг обменника: %s",
                 ("вкл (Claude)" if ANTHROPIC_API_KEY else "вкл (OpenAI)" if OPENAI_API_KEY else "выкл"), "вкл" if YOUTUBE_API_KEY else "выкл",
                 f"вкл (до {AUTO_MAX} ₽)" if AUTO_APPROVE else "выкл", "вкл" if TRACK_SECRET else "выкл")
    if WEBAPP_URL:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Приложение", web_app=WebAppInfo(url=WEBAPP_URL)))
    asyncio.create_task(daily_digest(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
