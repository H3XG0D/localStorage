"""Графическая CAPTCHA для Telegram-бота.

Отправляет пользователю PNG-картинку с текстом (буквы+цифры).
Пользователь вводит ответ текстом. Правильный ответ подписан HMAC.

Поддерживаемые типы заданий:
  - Арифметика: 9*7, 13+8, 25-6
  - Короткий буквенно-цифровой код: A3K7, 2MX9
"""
from __future__ import annotations

import hashlib
import hmac
import io
import logging
import os
import secrets
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from services import config_rates

logger = logging.getLogger("bot_captcha")

_SLOT_SEC = 300   # Токен живёт 10 мин (текущий + предыдущий слот)
_IMG_W = 240
_IMG_H = 80
_FONT_SIZE = 38

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            logger.debug("captcha font load failed path=%s", path, exc_info=True)
    return ImageFont.load_default()


def _slot() -> int:
    return int(time.time()) // _SLOT_SEC


def _sign(answer: str, slot: int) -> str:
    secret = (getattr(config_rates, "CALLBACK_SECRET", "") or "").encode()
    if not secret:
        secret = getattr(config_rates, "WEBHOOK_SECRET", "").encode()
    payload = f"botcaptcha:{answer.upper()}:{slot}"
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:32]


def _randint(a: int, b: int) -> int:
    return a + secrets.randbelow(b - a + 1)


def _random_dark() -> tuple[int, int, int]:
    return (_randint(15, 120), _randint(15, 120), _randint(15, 120))


def _generate_text() -> tuple[str, str]:
    """Возвращает (текст_на_картинке, правильный_ответ_upper)."""
    kind = secrets.choice(["math", "math", "alphanum"])
    if kind == "math":
        op = secrets.choice(["+", "-", "*"])
        if op == "+":
            a, b = _randint(3, 20), _randint(3, 20)
            return f"{a}+{b}", str(a + b)
        elif op == "-":
            a, b = _randint(12, 30), _randint(2, 10)
            return f"{a}-{b}", str(a - b)
        else:
            a, b = _randint(2, 9), _randint(2, 9)
            return f"{a}x{b}", str(a * b)
    else:
        chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        code = "".join(secrets.choice(chars) for _ in range(_randint(4, 5)))
        return code, code.upper()


def generate_captcha_image() -> tuple[bytes, str]:
    """Генерирует PNG-картинку и возвращает (png_bytes, hmac_token)."""
    text, answer = _generate_text()

    bg = (_randint(230, 255), _randint(230, 255), _randint(230, 255))
    img = Image.new("RGB", (_IMG_W, _IMG_H), color=bg)
    draw = ImageDraw.Draw(img)

    # Фоновый шум
    for _ in range(500):
        x, y = _randint(0, _IMG_W - 1), _randint(0, _IMG_H - 1)
        draw.point((x, y), fill=_random_dark())

    # Фоновые линии
    for _ in range(5):
        draw.line(
            [(_randint(0, _IMG_W), _randint(0, _IMG_H)),
             (_randint(0, _IMG_W), _randint(0, _IMG_H))],
            fill=_random_dark(), width=1,
        )

    # Каждый символ — отдельно, с поворотом и сдвигом
    font = _load_font(_FONT_SIZE)
    n = len(text)
    char_w = _IMG_W // (n + 1)
    x_start = char_w // 2

    for i, ch in enumerate(text):
        angle = _randint(0, 4000) / 100.0 - 20.0
        color = _random_dark()
        y_off = _randint(-7, 7)

        cw = _FONT_SIZE + 24
        ch_img = Image.new("RGBA", (cw, cw), (0, 0, 0, 0))
        ImageDraw.Draw(ch_img).text((10, 6), ch, font=font, fill=color + (255,))
        ch_img = ch_img.rotate(angle, expand=False, resample=Image.BICUBIC)

        x_pos = x_start + i * char_w - 10
        y_pos = (_IMG_H - _FONT_SIZE) // 2 + y_off - 6
        img.paste(ch_img, (x_pos, y_pos), ch_img)

    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))

    # Линии поверх текста
    draw = ImageDraw.Draw(img)
    for _ in range(3):
        draw.line(
            [(_randint(0, _IMG_W), _randint(8, _IMG_H - 8)),
             (_randint(0, _IMG_W), _randint(8, _IMG_H - 8))],
            fill=_random_dark(), width=2,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    slot = _slot()
    token = _sign(answer, slot)
    return png_bytes, token


def verify_captcha_answer(token: str | None, answer_raw: str | None) -> bool:
    """Проверить текстовый ответ пользователя."""
    if not token or not answer_raw:
        return False
    answer = str(answer_raw).strip().upper()
    if not answer:
        return False
    slot = _slot()
    for s in (slot, slot - 1):
        expected = _sign(answer, s)
        if hmac.compare_digest(expected, token):
            return True
    return False
