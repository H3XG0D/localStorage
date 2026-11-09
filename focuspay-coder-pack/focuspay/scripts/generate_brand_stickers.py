#!/usr/bin/env python3
"""Generate FocusPay brand sticker WEBP assets (512x512) for Telegram."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "focussite" / "frontend" / "public" / "brand-stickers"
LOGO = Path("/tmp/focuspay-f.png")
SIZE = 512


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()


def base_bg(*, planet: bool = True) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (10, 10, 10, 255))
    draw = ImageDraw.Draw(img)
    # soft vignette / beams
    for i in range(80):
        a = int(18 * (1 - i / 80))
        draw.rectangle([i, i, SIZE - 1 - i, SIZE - 1 - i], outline=(255, 255, 255, a))
    # stars
    rnd = [37, 91, 14, 200, 333, 410, 55, 480, 120, 260, 300, 70, 450, 180, 400, 40]
    for i, x in enumerate(rnd):
        y = (x * 7 + i * 41) % SIZE
        r = 1 if i % 3 else 2
        draw.ellipse([x % SIZE - r, y - r, x % SIZE + r, y + r], fill=(255, 255, 255, 160))
    if planet:
        # planet horizon at bottom
        cx, cy, rad = SIZE // 2, SIZE + 40, 220
        planet = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        pd = ImageDraw.Draw(planet)
        pd.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(28, 28, 30, 255))
        # glow ring
        for k in range(12):
            pd.ellipse(
                [cx - rad - k, cy - rad - k, cx + rad + k, cy + rad + k],
                outline=(255, 255, 255, max(0, 40 - k * 3)),
            )
        # orbital arcs
        for rad2, offs in ((260, 0), (300, 8)):
            pd.arc(
                [cx - rad2, cy - rad2 + offs, cx + rad2, cy + rad2 + offs],
                start=200,
                end=340,
                fill=(255, 255, 255, 90),
                width=2,
            )
        planet = planet.filter(ImageFilter.GaussianBlur(0.6))
        img = Image.alpha_composite(img, planet)
    return img


def paste_logo(img: Image.Image, *, y: int = 70, scale: float = 1.0) -> None:
    logo = Image.open(LOGO).convert("RGBA")
    w = int(logo.width * scale)
    h = int(logo.height * scale)
    logo = logo.resize((w, h), Image.Resampling.LANCZOS)
    x = (SIZE - w) // 2
    img.alpha_composite(logo, (x, y))


def label(img: Image.Image, text: str, *, y: int = 390, size: int = 42) -> None:
    draw = ImageDraw.Draw(img)
    font = _font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (SIZE - tw) // 2
    # subtle shadow
    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=(244, 244, 245, 255))


def icon_circle(img: Image.Image, glyph: str, *, y: int = 160, size: int = 120) -> None:
    draw = ImageDraw.Draw(img)
    r = 70
    cx, cy = SIZE // 2, y + r
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 220), width=4)
    font = _font(size)
    bbox = draw.textbbox((0, 0), glyph, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw / 2, cy - th / 2 - 8), glyph, font=font, fill=(255, 255, 255, 255))


def save(img: Image.Image, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.webp"
    # Telegram: static WEBP, keep under 512KB
    rgb_bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    composed = Image.alpha_composite(rgb_bg, img)
    composed.save(path, "WEBP", quality=90, method=6)
    return path


def make_all() -> list[tuple[str, str, Path]]:
    """Return list of (slug, emoji, path)."""
    specs: list[tuple[str, str, callable]] = []

    def logo():
        im = base_bg()
        paste_logo(im, y=90, scale=1.15)
        label(im, "FocusPay", y=400, size=40)
        return im

    def hi():
        im = base_bg()
        paste_logo(im, y=50, scale=0.85)
        label(im, "SUPPORT", y=320, size=36)
        label(im, "Привет!", y=390, size=44)
        return im

    def wait():
        im = base_bg()
        icon_circle(im, "…", y=140, size=100)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Ждите", y=390, size=48)
        return im

    def done():
        im = base_bg()
        icon_circle(im, "✓", y=140, size=110)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Готово", y=390, size=48)
        return im

    def thanks():
        im = base_bg()
        paste_logo(im, y=80, scale=0.95)
        label(im, "Спасибо", y=390, size=46)
        return im

    def pulse():
        im = base_bg(planet=False)
        draw = ImageDraw.Draw(im)
        # upward chart
        pts = [(80, 360), (150, 300), (220, 320), (300, 220), (380, 180), (440, 120)]
        draw.line(pts, fill=(255, 255, 255, 230), width=6)
        for x, y in pts:
            draw.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255, 255))
        paste_logo(im, y=40, scale=0.5)
        label(im, "Курс ↑", y=400, size=46)
        return im

    def promo():
        im = base_bg()
        icon_circle(im, "★", y=140, size=110)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Промо", y=390, size=48)
        return im

    def check():
        im = base_bg()
        icon_circle(im, "🛡", y=140, size=90)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Проверено", y=390, size=40)
        return im

    def news():
        im = base_bg()
        icon_circle(im, "◉", y=140, size=100)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Новости", y=390, size=46)
        return im

    def help_():
        im = base_bg()
        icon_circle(im, "?", y=140, size=120)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Помощь", y=390, size=48)
        return im

    def ok():
        im = base_bg()
        icon_circle(im, "OK", y=150, size=72)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Ок", y=390, size=48)
        return im

    def paid():
        im = base_bg()
        icon_circle(im, "₽", y=140, size=110)
        paste_logo(im, y=40, scale=0.55)
        label(im, "Оплачено", y=390, size=42)
        return im

    items = [
        ("01_logo", "🤍", logo),
        ("02_hi", "👋", hi),
        ("03_wait", "⏳", wait),
        ("04_done", "✅", done),
        ("05_thanks", "🙏", thanks),
        ("06_pulse", "📈", pulse),
        ("07_promo", "🎁", promo),
        ("08_check", "🛡️", check),
        ("09_news", "📣", news),
        ("10_help", "🆘", help_),
        ("11_ok", "👍", ok),
        ("12_paid", "💳", paid),
    ]
    out: list[tuple[str, str, Path]] = []
    for slug, emoji, fn in items:
        path = save(fn(), slug)
        out.append((slug, emoji, path))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return out


if __name__ == "__main__":
    make_all()
