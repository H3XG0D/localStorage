"""FocusPay brand style preset for sticker generation (no third-party brands)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrandPreset:
    name: str = "focuspay_mono_cosmic_v1"
    palette: tuple[str, ...] = ("#0a0a0a", "#141414", "#ffffff", "#e8e8e8")
    typography: str = "bold geometric sans; short labels; no serif display"
    style_prompt: str = (
        "FocusPay branded Telegram sticker, 512x512, monochrome F mark, "
        "near-black cosmic vignette, soft white stars, clean vector-like shapes, "
        "high contrast, transparent-friendly silhouette, no photorealism"
    )
    negative_prompt: str = (
        "photorealistic face, celebrity, NSFW, gore, watermark, logo of other brands, "
        "telegram logo, bitcoin orange logo, binance, bybit, okx, paypal, visa, mastercard, "
        "apple logo, google logo, disney, nike, adidas, text dump, lowres, blurry, collage"
    )
    canvas_px: int = 512
    extra_tags: tuple[str, ...] = field(
        default_factory=lambda: ("sticker", "focuspay", "mono", "cosmic")
    )


DEFAULT_BRAND = BrandPreset()


def build_generation_prompt(idea: str, *, brand: BrandPreset | None = None) -> str:
    b = brand or DEFAULT_BRAND
    idea_clean = " ".join((idea or "").strip().split())
    return f"{b.style_prompt}. Concept: {idea_clean}. Typography: {b.typography}."
