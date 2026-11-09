"""Графическая CAPTCHA: изображение с текстом (буквы + цифры).

Схема:
  GET /api/public/captcha | /api/public/human-check
    →  {image: "<base64 PNG>", challenge_id: "<id>"}
  POST /api/auth/register   body: {captcha_token: "<challenge_id>", captcha_answer}
  Бэк: verify_captcha(challenge_id, answer) → True/False (single-use)

Текст на картинке: простое выражение (9*9) или короткая строка.
Challenge хранится в БД с TTL 10 минут, каждый используется только один раз.
Бот не может прочитать текст из HTML — только с картинки.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import secrets
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("math_captcha")

import os

# Путь к шрифту (DejaVu есть на Ubuntu/Debian по умолчанию)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

_IMG_W = 240
_IMG_H = 84
_FONT_SIZE = 44


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            logger.debug("captcha font load failed path=%s", path, exc_info=True)
    return ImageFont.load_default()


# Старые stateless функции удалены — captcha теперь stateful (database-backed)


def _randint(a: int, b: int) -> int:
    return a + secrets.randbelow(b - a + 1)


def _random_color(light: bool = False) -> tuple[int, int, int]:
    if light:
        return (_randint(220, 255), _randint(220, 255), _randint(220, 255))
    return (_randint(20, 140), _randint(20, 140), _randint(20, 140))


def _hash_answer(answer: str) -> str:
    """SHA256 хэш ответа для хранения в БД."""
    return hashlib.sha256(answer.lower().encode()).hexdigest()


def _generate_text() -> tuple[str, str]:
    """Возвращает (text_to_show, answer).

    Виды заданий:
    - Простое арифметическое: 9*9, 7+8, 15-6
    - Короткая буквенно-цифровая строка: A3K7
    """
    kind = secrets.choice(["math", "math", "alphanum"])  # чаще math

    if kind == "math":
        op = secrets.choice(["+", "-", "*"])
        if op == "+":
            a, b = _randint(2, 20), _randint(2, 20)
            text = f"{a}+{b}"
            answer = str(a + b)
        elif op == "-":
            a, b = _randint(10, 30), _randint(2, 10)
            text = f"{a}-{b}"
            answer = str(a - b)
        else:
            a, b = _randint(2, 9), _randint(2, 9)
            text = f"{a}*{b}"
            answer = str(a * b)
        return text, answer
    else:
        # 4–5 символов: цифры и заглавные буквы (без похожих: 0/O, 1/I/l)
        chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        length = _randint(4, 5)
        text = "".join(secrets.choice(chars) for _ in range(length))
        return text, text.upper()


def _render_captcha_image(text: str) -> bytes:
    """Рендерит читаемый текст на картинке с умеренным фоновым шумом."""
    bg_color = (248, 250, 252)
    img = Image.new("RGB", (_IMG_W, _IMG_H), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Шум остаётся только на фоне и не конкурирует с символами по контрасту.
    for _ in range(140):
        x = _randint(0, _IMG_W - 1)
        y = _randint(0, _IMG_H - 1)
        draw.point((x, y), fill=_random_color(light=True))

    # Лёгкие фоновые линии не проходят поверх текста.
    for _ in range(2):
        x1, y1 = _randint(0, _IMG_W), _randint(0, _IMG_H)
        x2, y2 = _randint(0, _IMG_W), _randint(0, _IMG_H)
        draw.line([(x1, y1), (x2, y2)], fill=(218, 224, 230), width=1)

    # Рисуем каждый символ отдельно с небольшим сдвигом и поворотом
    font = _load_font(_FONT_SIZE)
    n = len(text)
    char_w = _IMG_W // (n + 1)
    x_start = char_w // 2

    for i, ch in enumerate(text):
        angle = _randint(0, 1600) / 100.0 - 8.0
        y_offset = _randint(-3, 3)

        # Рисуем символ на мини-изображении, поворачиваем, вставляем
        char_img = Image.new("RGBA", (_FONT_SIZE + 14, _FONT_SIZE + 22), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text(
            (7, 5),
            ch,
            font=font,
            fill=(24, 31, 42, 255),
            stroke_width=1,
            stroke_fill=(10, 14, 20, 255),
        )
        char_img = char_img.rotate(angle, expand=False, resample=Image.Resampling.BICUBIC)

        inner_margin = 10
        usable_width = _IMG_W - inner_margin * 2
        x_center = inner_margin + (i + 0.5) * usable_width / n
        y_pos = (_IMG_H - char_img.height) // 2 + y_offset
        img.paste(char_img, (round(x_center - char_img.width / 2), y_pos), char_img)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def generate_captcha(
    guest_session: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """Возвращает {image: base64_png, challenge_id} для отдачи клиенту.

    Challenge сохраняется в БД с TTL 10 минут.
    """
    from db import get_pool

    text, answer = _generate_text()
    img_bytes = _render_captcha_image(text)
    img_b64 = base64.b64encode(img_bytes).decode()

    answer_hash = _hash_answer(answer)

    # Сохранить challenge в БД
    pool = await get_pool()
    async with pool.acquire() as conn:
        challenge_id = await conn.fetchval(
            """
            INSERT INTO captcha_challenges
                (challenge_text, answer_hash, guest_session, ip_address, user_agent)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            text,
            answer_hash,
            guest_session,
            ip_address,
            user_agent[:500] if user_agent else None,
        )

    return {"image": img_b64, "challenge_id": str(challenge_id)}


async def verify_captcha(
    challenge_id: str | None,
    answer_raw: str | None,
    *,
    guest_session: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """Атомарно проверить и погасить challenge, привязанный к клиенту."""
    from db import get_pool

    if not challenge_id or answer_raw is None:
        return False

    answer = str(answer_raw).strip().upper()
    if not answer:
        return False

    try:
        cid = int(challenge_id)
    except (ValueError, TypeError):
        logger.warning("Invalid challenge_id format: %s", challenge_id)
        return False

    answer_hash = _hash_answer(answer)
    normalized_ua = user_agent[:500] if user_agent else None

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Одна SQL-операция не оставляет окно для параллельного replay. Привязки
        # сравниваются только когда они были записаны при выдаче challenge.
        # inet::text в Postgres даёт «172.20.0.4/32», а клиентский IP — без маски;
        # сравниваем как inet, иначе проверка всегда отклоняется.
        consumed_id = await conn.fetchval(
            """
            UPDATE captcha_challenges
            SET consumed_at = now()
            WHERE id = $1
              AND consumed_at IS NULL
              AND created_at > now() - interval '10 minutes'
              AND answer_hash = $2
              AND (guest_session IS NULL OR guest_session::text = $3)
              AND (ip_address IS NULL OR ip_address = $4::inet)
              AND (user_agent IS NULL OR user_agent = $5)
            RETURNING id
            """,
            cid,
            answer_hash,
            guest_session,
            ip_address,
            normalized_ua,
        )

        if consumed_id is None:
            row = await conn.fetchrow(
                """
                SELECT ip_address::text AS ip, guest_session::text AS gs,
                       user_agent AS ua, answer_hash
                FROM captcha_challenges WHERE id = $1
                """,
                cid,
            )
            logger.warning(
                "Captcha rejected id=%s hash_ok=%s stored_ip=%s got_ip=%s gs_ok=%s ua_ok=%s",
                cid,
                bool(row and row["answer_hash"] == answer_hash),
                None if row is None else row["ip"],
                ip_address,
                bool(row and (row["gs"] is None or row["gs"] == guest_session)),
                bool(row and (row["ua"] is None or row["ua"] == normalized_ua)),
            )
            return False

    logger.debug("Captcha verified successfully: id=%s", cid)
    return True
