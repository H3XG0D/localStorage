"""Генерация баннеров Focus Pay (общих и персональных с промокодом автора)."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE = Path(__file__).parent
FONT_B = str(BASE / "webapp" / "static" / "fonts" / "DejaVuSans-Bold.ttf")
FONT_R = str(BASE / "webapp" / "static" / "fonts" / "DejaVuSans.ttf")
HERO = BASE / "webapp" / "static" / "hero.jpg"
LIME = (198, 255, 61)
WHITE = (255, 255, 255)
GREY = (190, 196, 193)


def _font(size, bold=True):
    return ImageFont.truetype(FONT_B if bold else FONT_R, size)


def _mark(draw: ImageDraw.ImageDraw, x, y, h, color=WHITE):
    """Знак F Focus Pay (вектор, 4 скруглённых блока). h — высота знака."""
    k = h / 238
    for rx, ry, rw, rh in ((62, 0, 122, 64), (0, 54, 76, 72), (30, 124, 82, 64), (0, 176, 62, 62)):
        draw.rounded_rectangle([x + rx * k, y + ry * k, x + (rx + rw) * k, y + (ry + rh) * k], radius=12 * k, fill=color)


def _center(draw, text, y, font, fill, width):
    w = draw.textlength(text, font=font)
    draw.text(((width - w) / 2, y), text, font=font, fill=fill)


def vertical(promo: str | None, exchange: str) -> bytes:
    """Полноэкранный баннер 1080×1920 для концовки ролика."""
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (0, 0, 0))
    if HERO.exists():
        hero = Image.open(HERO).convert("RGB").resize((W, W))
        img.paste(hero, (0, 120))
        fade = Image.new("L", (W, 700), 0)
        fd = ImageDraw.Draw(fade)
        for i in range(700):
            fd.line([(0, i), (W, i)], fill=int(255 * min(1, i / 520)))
        img.paste(Image.new("RGB", (W, 700), (0, 0, 0)), (0, 120 + W - 700), fade)
    d = ImageDraw.Draw(img)
    _center(d, "FOCUS PAY", 1150, _font(120), WHITE, W)
    _center(d, "Обмен без цирка", 1300, _font(58, False), GREY, W)
    if promo:
        f = _font(70)
        txt = f"ПРОМОКОД: {promo}"
        tw = d.textlength(txt, font=f)
        bx0, by0 = (W - tw) / 2 - 50, 1440
        d.rounded_rectangle([bx0, by0, bx0 + tw + 100, by0 + 130], radius=65, fill=LIME)
        d.text((bx0 + 50, by0 + 26), txt, font=f, fill=(10, 11, 13))
        _center(d, "введи при обмене", 1600, _font(44, False), GREY, W)
    else:
        f = _font(64)
        txt = "ССЫЛКА В ПРОФИЛЕ"
        tw = d.textlength(txt, font=f)
        bx0, by0 = (W - tw) / 2 - 50, 1450
        d.rounded_rectangle([bx0, by0, bx0 + tw + 100, by0 + 124], radius=62, fill=LIME)
        d.text((bx0 + 50, by0 + 26), txt, font=f, fill=(10, 11, 13))
    _center(d, f"Telegram: {exchange}", 1720, _font(50), WHITE, W)
    out = BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def plaque(promo: str | None, exchange: str) -> bytes:
    """Плашка 1080×240 на прозрачном фоне — вниз кадра."""
    W, H = 1080, 240
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([40, 40, W - 40, H - 30], radius=48, fill=(0, 0, 0, 140))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 30, W - 40, H - 40], radius=44, fill=(8, 8, 10, 245), outline=(61, 77, 23, 255), width=3)
    d.rounded_rectangle([72, 62, 72 + 106, 62 + 106], radius=26, fill=(0, 0, 0, 255), outline=(46, 50, 56, 255), width=2)
    _mark(d, 100, 77, 76)
    d.text((206, 66), "Focus Pay", font=_font(54), fill=WHITE)
    sub = f"промокод {promo} · {exchange}" if promo else f"обмен в Telegram · {exchange}"
    fs = 38
    while d.textlength(sub, font=_font(fs)) > W - 270 and fs > 24:
        fs -= 2
    d.text((208, 136), sub, font=_font(fs), fill=LIME)
    out = BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


if __name__ == "__main__":
    import sys
    ex = sys.argv[1] if len(sys.argv) > 1 else "@focuspay1_bot"
    mat = BASE / "materials"
    mat.mkdir(exist_ok=True)
    (mat / "Баннер вертикальный.png").write_bytes(vertical(None, ex))
    (mat / "Плашка вниз кадра.png").write_bytes(plaque(None, ex))
    print("Готово: баннеры в папке materials")
