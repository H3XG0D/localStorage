"""Unique generated casino avatar when the player has no photo.

Goofy cartoon portraits. Same seed always draws the same picture;
different seeds get different pictures. No shared default clip-art.
"""
from __future__ import annotations

import hashlib
import re
from typing import Sequence

from fastapi import HTTPException

_SEED_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HASH_NS = "focuspay-casino-ident-v1:"
_IDENT_VERSION = "3"

# bg, skin, hair, shirt, accent
_PALETTES: tuple[tuple[str, str, str, str, str], ...] = (
    ("#173a4a", "#f3c7a4", "#2a1810", "#3ecf8e", "#e8fff4"),
    ("#3b1d4d", "#e8b898", "#1a1024", "#e879f9", "#fce7ff"),
    ("#1f2f1a", "#f0c8a8", "#3a2418", "#86efac", "#f0fdf4"),
    ("#3a1f1a", "#f2c2a0", "#241410", "#fb923c", "#fff7ed"),
    ("#1a2744", "#efc4a6", "#0f172a", "#60a5fa", "#eff6ff"),
    ("#3f2a12", "#f4d0b0", "#1c140c", "#fbbf24", "#fffbeb"),
    ("#2a1030", "#e9b89a", "#140818", "#c084fc", "#faf5ff"),
    ("#102828", "#f0c6a8", "#082020", "#2dd4bf", "#f0fdfa"),
    ("#2c1810", "#f6d3b4", "#120c08", "#f97316", "#fff7ed"),
    ("#12182c", "#e8c0a8", "#080c18", "#818cf8", "#eef2ff"),
    ("#241810", "#f2c8a4", "#181008", "#a3e635", "#f7fee7"),
    ("#301018", "#f0b8a0", "#180810", "#fb7185", "#fff1f2"),
    ("#102030", "#ecc2a6", "#081018", "#38bdf8", "#f0f9ff"),
    ("#203010", "#f4ccaa", "#101808", "#4ade80", "#f0fdf4"),
    ("#301828", "#eab49c", "#180c14", "#f472b6", "#fdf2f8"),
    ("#182838", "#f1c8ac", "#0c141c", "#22d3ee", "#ecfeff"),
    ("#382010", "#f6d0a8", "#1c1008", "#facc15", "#fefce8"),
    ("#201038", "#e8b8a4", "#100820", "#a78bfa", "#f5f3ff"),
    ("#103028", "#f0c4a0", "#081810", "#34d399", "#ecfdf5"),
    ("#381818", "#f2c0a4", "#1c0c0c", "#f87171", "#fef2f2"),
    ("#183040", "#ecc8b0", "#0c181f", "#67e8f9", "#ecfeff"),
    ("#283010", "#f4d4b0", "#141808", "#bef264", "#f7fee7"),
    ("#301030", "#eab0a0", "#180818", "#e879f9", "#faf5ff"),
    ("#102418", "#f0c8a4", "#08140c", "#4ade80", "#f0fdf4"),
)


def user_ident_seed(user_id: int) -> str:
    uid = int(user_id)
    if uid == 0:
        raise ValueError("user_id must be non-zero")
    if uid < 0:
        return f"n{abs(uid)}"
    return f"u{uid}"


def robot_ident_seed(
    *,
    profile_id: object = None,
    profile_key: object = None,
    display_name: object = None,
    seat_no: object = None,
) -> str:
    try:
        pid = int(profile_id) if profile_id not in (None, "") else 0
    except (TypeError, ValueError):
        pid = 0
    if pid:
        return f"r{pid}"
    key = str(profile_key or "").strip()
    if key:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return f"k{digest}"
    label = str(display_name or "bot").strip() or "bot"
    try:
        seat = int(seat_no) if seat_no not in (None, "") else 0
    except (TypeError, ValueError):
        seat = 0
    digest = hashlib.sha256(f"{label}:{seat}".encode("utf-8")).hexdigest()[:16]
    return f"b{digest}"


def parse_ident_seed(raw: object) -> str:
    text = str(raw or "").strip()
    if not _SEED_RE.match(text):
        raise HTTPException(status_code=404, detail="Avatar not found")
    return text


def default_avatar_public_url(seed: str) -> str:
    return f"/api/public/casino-idents/{parse_ident_seed(seed)}?v={_IDENT_VERSION}"


def default_avatar_url_for_user(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    if uid == 0:
        return None
    return default_avatar_public_url(user_ident_seed(uid))


def _u16(digest: bytes, offset: int) -> int:
    return int.from_bytes(digest[offset : offset + 2], "big")


def _pick(digest: bytes, offset: int, n: int) -> int:
    return _u16(digest, offset) % int(n)


def _digest(seed: str) -> bytes:
    return hashlib.sha256(f"{_HASH_NS}{seed}".encode("utf-8")).digest()


def _hair(style: int, color: str) -> str:
    if style == 0:
        return f'<ellipse cx="32" cy="22" rx="16" ry="12" fill="{color}"/>'
    if style == 1:
        return (
            f'<path d="M16 28 C16 12 48 12 48 28 L46 22 C40 10 24 10 18 22 Z" fill="{color}"/>'
        )
    if style == 2:
        return f'<rect x="15" y="12" width="34" height="16" rx="8" fill="{color}"/>'
    if style == 3:
        return (
            f'<path d="M18 30 C14 8 50 8 46 30 C40 18 24 18 18 30 Z" fill="{color}"/>'
            f'<circle cx="20" cy="18" r="5" fill="{color}"/>'
            f'<circle cx="44" cy="18" r="5" fill="{color}"/>'
        )
    if style == 4:
        return f'<path d="M14 34 L18 10 H46 L50 34 C42 20 22 20 14 34 Z" fill="{color}"/>'
    if style == 5:
        return (
            f'<ellipse cx="32" cy="20" rx="18" ry="14" fill="{color}"/>'
            f'<rect x="14" y="20" width="36" height="10" fill="{color}"/>'
        )
    if style == 6:
        return f'<path d="M20 14 H44 L50 28 H14 Z" fill="{color}"/>'
    return (
        f'<path d="M16 26 C18 8 46 8 48 26 L44 16 H20 Z" fill="{color}"/>'
        f'<circle cx="32" cy="12" r="4" fill="{color}"/>'
    )


def _eyes(kind: int, accent: str) -> str:
    if kind == 0:
        return (
            f'<circle cx="26" cy="30" r="2.4" fill="#1a1410"/>'
            f'<circle cx="38" cy="30" r="2.4" fill="#1a1410"/>'
        )
    if kind == 1:
        return (
            f'<rect x="23" y="28" width="6" height="3.2" rx="1.4" fill="#1a1410"/>'
            f'<rect x="35" y="28" width="6" height="3.2" rx="1.4" fill="#1a1410"/>'
        )
    if kind == 2:
        return (
            f'<circle cx="26" cy="30" r="3" fill="#fff"/>'
            f'<circle cx="38" cy="30" r="3" fill="#fff"/>'
            f'<circle cx="27" cy="30.4" r="1.5" fill="#1a1410"/>'
            f'<circle cx="39" cy="30.4" r="1.5" fill="#1a1410"/>'
        )
    if kind == 3:
        return (
            f'<path d="M23 31 Q26 27 29 31" fill="none" stroke="#1a1410" stroke-width="1.6" stroke-linecap="round"/>'
            f'<path d="M35 31 Q38 27 41 31" fill="none" stroke="#1a1410" stroke-width="1.6" stroke-linecap="round"/>'
        )
    if kind == 4:
        return (
            f'<circle cx="26" cy="30" r="2.6" fill="#1a1410"/>'
            f'<circle cx="38" cy="30" r="2.6" fill="#1a1410"/>'
            f'<circle cx="26.7" cy="29.2" r="0.8" fill="#fff"/>'
            f'<circle cx="38.7" cy="29.2" r="0.8" fill="#fff"/>'
            f'<circle cx="32" cy="28" r="1.1" fill="{accent}"/>'
        )
    return (
        f'<ellipse cx="26" cy="30" rx="3.2" ry="2.4" fill="#1a1410"/>'
        f'<ellipse cx="38" cy="30" rx="3.2" ry="2.4" fill="#1a1410"/>'
        f'<circle cx="26.6" cy="29.4" r="0.7" fill="#fff"/>'
        f'<circle cx="38.6" cy="29.4" r="0.7" fill="#fff"/>'
    )


def _mouth(kind: int) -> str:
    if kind == 0:
        return '<path d="M27 39 Q32 43 37 39" fill="none" stroke="#7a3d2a" stroke-width="1.7" stroke-linecap="round"/>'
    if kind == 1:
        return '<path d="M28 40 Q32 38 36 40" fill="none" stroke="#7a3d2a" stroke-width="1.7" stroke-linecap="round"/>'
    if kind == 2:
        return '<rect x="29" y="38.5" width="6" height="2.2" rx="1.1" fill="#7a3d2a"/>'
    if kind == 3:
        return '<path d="M28 39 Q32 45 36 39 Z" fill="#c45c4a"/>'
    if kind == 4:
        return '<circle cx="32" cy="40" r="1.5" fill="#7a3d2a"/>'
    return '<path d="M26 39 Q32 42 38 39" fill="none" stroke="#7a3d2a" stroke-width="1.8" stroke-linecap="round"/>'


def _accessory(kind: int, accent: str, hair: str) -> str:
    if kind == 0:
        return ""
    if kind == 1:
        return (
            f'<rect x="20" y="28" width="24" height="2" rx="1" fill="{accent}" opacity="0.9"/>'
            f'<circle cx="26" cy="30" r="4.4" fill="none" stroke="{accent}" stroke-width="1.5"/>'
            f'<circle cx="38" cy="30" r="4.4" fill="none" stroke="{accent}" stroke-width="1.5"/>'
        )
    if kind == 2:
        return f'<circle cx="46" cy="34" r="1.6" fill="{accent}"/>'
    if kind == 3:
        return (
            f'<path d="M24 14 L32 6 L40 14" fill="none" stroke="{hair}" stroke-width="3" stroke-linecap="round"/>'
            f'<circle cx="32" cy="8" r="2.2" fill="{accent}"/>'
        )
    if kind == 4:
        return f'<rect x="18" y="16" width="28" height="6" rx="2" fill="{hair}"/><rect x="16" y="20" width="32" height="3" fill="{hair}"/>'
    return f'<path d="M18 24 Q12 30 18 36" fill="none" stroke="{accent}" stroke-width="2" stroke-linecap="round"/>'


def _marks(digest: bytes, accent: str) -> str:
    bits = digest[16:]
    parts: list[str] = []
    for i in range(6):
        x = 10 + (bits[i] % 45)
        y = 8 + (bits[i + 6] % 20)
        r = 0.8 + (bits[i] % 3) * 0.4
        if bits[i] % 3 == 0:
            continue
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r:.1f}" fill="{accent}" opacity="0.55"/>')
    return "".join(parts)


def render_ident_svg(seed: str) -> str:
    key = parse_ident_seed(seed)
    digest = _digest(key)
    bg, skin, hair, shirt, accent = _PALETTES[_pick(digest, 0, len(_PALETTES))]
    hair_style = _pick(digest, 2, 8)
    eye_style = _pick(digest, 4, 6)
    mouth_style = _pick(digest, 6, 6)
    acc_style = _pick(digest, 8, 6)
    face_rx = 13 + _pick(digest, 10, 4)
    face_ry = 14 + _pick(digest, 12, 3)
    shirt_w = 28 + _pick(digest, 14, 8)
    uid = int.from_bytes(digest[20:24], "big")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<defs><clipPath id="c{uid}"><circle cx="32" cy="32" r="32"/></clipPath>'
        f'<radialGradient id="g{uid}" cx="35%" cy="30%"><stop offset="0%" stop-color="{accent}"/>'
        f'<stop offset="100%" stop-color="{bg}"/></radialGradient></defs>'
        f'<g clip-path="url(#c{uid})">'
        f'<rect width="64" height="64" fill="url(#g{uid})"/>'
        f"{_marks(digest, accent)}"
        f'<ellipse cx="32" cy="58" rx="{shirt_w}" ry="16" fill="{shirt}"/>'
        f'<ellipse cx="32" cy="34" rx="{face_rx}" ry="{face_ry}" fill="{skin}"/>'
        f"{_hair(hair_style, hair)}"
        f"{_eyes(eye_style, accent)}"
        f"{_mouth(mouth_style)}"
        f"{_accessory(acc_style, accent, hair)}"
        "</g></svg>"
    )


def all_unique(seeds: Sequence[str]) -> bool:
    pictures = [render_ident_svg(seed) for seed in seeds]
    return len(set(pictures)) == len(pictures)
