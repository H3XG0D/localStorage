"""Premium Telegram emoji for broadcasts.

Ids match bot/tg_bot_btc/services/tg_emoji.py. A keyboard emoji is not a premium
emoji: Telegram only renders the pack when the text contains <tg-emoji>.
"""
from __future__ import annotations

import re

# key -> (emoji_id, unicode fallback). Empty id means "no premium glyph".
EMOJI: dict[str, tuple[str, str]] = {
    "obmen": ("5874986954180791957", "🔄"),
    "wallet": ("5769403330761593044", "👛"),
    "ruble": ("5231449120635370684", "💰"),
    "dollar": ("5409048419211682843", "💵"),
    "percent": ("5229064374403998351", "➗"),
    "card": ("5927169041595634481", "💳"),
    "sbp": ("5206636501860893075", "💳"),
    "qr": ("5987917196469213507", "📱"),
    "stats": ("5231200819986047254", "📊"),
    "chart_up": ("5449683594425410231", "📈"),
    "chart_down": ("5447183459602669338", "📉"),
    "fire": ("5424972470023104089", "🔥"),
    "gift": ("5406756500108501710", "🆓"),
    "promo": ("", "🎟"),
    "discount": ("5406683434124859552", "🏷"),
    "star": ("5438496463044752972", "⭐"),
    "sport": ("5935847413859225147", "🏆"),
    "check": ("5206607081334906820", "✅"),
    "bell": ("5458603043203327669", "🔔"),
    "link": ("5271604874419647061", "🔗"),
    "info": ("5323442290708985472", "ℹ️"),
    "profile": ("5879770735999717115", "👤"),
    "people": ("5942877472163892475", "👥"),
    "internet": ("5447410659077661506", "🌐"),
    "chat": ("5443038326535759644", "💬"),
    "support": ("5884510167986343350", "💬"),
    "announce": ("5424818078833715060", "📢"),
    "wave": ("5870734657384877785", "👋"),
    "down": ("5875008416132370818", "🔽"),
    "idea": ("5422439311196834318", "💡"),
    "calendar": ("5413879192267805083", "📅"),
    "history": ("5877597667231534929", "📋"),
    "btc": ("6032744483102133873", "💵"),
    "usdt": ("6032709766881479783", "💵"),
    "trx": ("6030661990899257068", "💵"),
    "ltc": ("5891232414574841140", "💵"),
}

_STRICT_RE = re.compile(r'<tg-emoji emoji-id="(\d{5,32})">([^<]{1,8})</tg-emoji>')
_UNKNOWN_RE = re.compile(r"<tg-emoji\b[^>]*>.*?</tg-emoji>", re.I | re.S)
_DANGLING_RE = re.compile(r"</?tg-emoji\b[^>]*>", re.I)


def _fallback_by_id() -> dict[str, str]:
    out: dict[str, str] = {}
    for eid, fb in EMOJI.values():
        if eid and fb and eid not in out:
            out[eid] = fb
    return out


BY_ID = _fallback_by_id()


def _unique_forms() -> dict[str, tuple[str, str]]:
    """Glyphs that map to exactly one premium id. Shared fallbacks (💵 💳 💬) stay plain."""
    owners: dict[str, set[str]] = {}
    canonical: dict[str, str] = {}
    for eid, fb in EMOJI.values():
        if not eid or not fb:
            continue
        for form in {fb, fb.replace("\ufe0f", "")}:
            if not form:
                continue
            owners.setdefault(form, set()).add(eid)
            canonical.setdefault(form, fb)
    out: dict[str, tuple[str, str]] = {}
    for form, ids in owners.items():
        if len(ids) == 1:
            out[form] = (next(iter(ids)), canonical[form])
    return out


# Клавиатурные смайлы вне пака → ближайший премиум-стикер. Иначе рассылка оставляет их плоскими.
_KEYBOARD_ALIASES = {
    "🚀": ("5424818078833715060", "📢"),
    "⚡": ("5424972470023104089", "🔥"),
    "⚡️": ("5424972470023104089", "🔥"),
    "🎨": ("5422439311196834318", "💡"),
    "🔒": ("5206607081334906820", "✅"),
    "🤝": ("5942877472163892475", "👥"),
}

UNIQUE = {**_unique_forms(), **_KEYBOARD_ALIASES}
_UNIQUE_RE = re.compile("|".join(re.escape(k) for k in sorted(UNIQUE, key=len, reverse=True)))


def premium_chars() -> str:
    seen: list[str] = []
    for fb in (canonical for _eid, canonical in UNIQUE.values()):
        if fb not in seen:
            seen.append(fb)
    return " ".join(seen)


def _tag(eid: str, fb: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


def _upgrade_chunk(chunk: str) -> str:
    if not chunk:
        return ""

    def _unwrap(match: re.Match[str]) -> str:
        inner = re.sub(r"<[^>]+>", "", match.group(0))
        return inner

    chunk = _UNKNOWN_RE.sub(_unwrap, chunk)
    chunk = _DANGLING_RE.sub("", chunk)

    def _sub(match: re.Match[str]) -> str:
        eid, fb = UNIQUE[match.group(0)]
        return _tag(eid, fb)

    return _UNIQUE_RE.sub(_sub, chunk)


def apply_premium_emoji(text: str) -> str:
    """Turn pack unicode into <tg-emoji>.

    A well-formed tag keeps its emoji-id, including ids outside the FocusPay pack
    (a post pasted in Telegram). Dirty tags are unwrapped so HTML parse cannot fail.
    """
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    for match in _STRICT_RE.finditer(text):
        out.append(_upgrade_chunk(text[pos : match.start()]))
        eid = match.group(1)
        fb = BY_ID.get(eid)
        if fb:
            out.append(_tag(eid, fb))
        else:
            out.append(match.group(0))
        pos = match.end()
    out.append(_upgrade_chunk(text[pos:]))
    return "".join(out)


def fit_premium_text(text: str, max_len: int = 4096) -> str:
    """Shrink by unwrapping premium tags from the end. Never cut a tag in half."""
    if max_len < 1:
        return ""
    value = text or ""
    while len(value) > max_len:
        last = None
        for last in _STRICT_RE.finditer(value):
            pass
        if last is None:
            return value[:max_len].rstrip()
        value = value[: last.start()] + last.group(2) + value[last.end() :]
    return value
