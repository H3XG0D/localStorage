"""
Premium Telegram emoji для FocusPay.

    from services.tg_emoji import e
    e("wallet")  ->  '<tg-emoji emoji-id="...">👛</tg-emoji>'

ВАЖНО:
  - Премиум-эмодзи (<tg-emoji>) работают ТОЛЬКО в тексте сообщений и подписях
    (parse_mode=HTML). На reply/inline-кнопках HTML не парсится —
    там только unicode или icon_custom_emoji_id.
  - Внутри <tg-emoji> фолбэк ОБЯЗАН быть unicode-эмодзи.
  - Чтобы премиум-эмодзи показывались зрителям — у владельца бота
    нужна активная подписка Telegram Premium.
"""

from __future__ import annotations

# Формат: "key": ("emoji_id", "unicode_fallback")

_BASE: dict[str, tuple[str, str]] = {
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
}

_TGMACICONS: dict[str, tuple[str, str]] = {}

_CRYPTO: dict[str, tuple[str, str]] = {
    "btc": ("6032744483102133873", "💵"),
    "usdt": ("6032709766881479783", "💵"),
    "trx": ("6030661990899257068", "💵"),
    "ltc": ("5891232414574841140", "💵"),
}

EMOJI: dict[str, tuple[str, str]] = {**_BASE, **_TGMACICONS, **_CRYPTO}

BTN: dict[str, str] = {
    "btc": "🟠",
    "usdt": "🟢",
    "trx": "🔴",
    "ltc": "⚪",
}


def e(key: str) -> str:
    """Вернуть <tg-emoji> тег или сам ключ, если такого нет."""
    if key not in EMOJI:
        return key
    eid_val, fb = EMOJI[key]
    if not eid_val:
        return fb
    return f'<tg-emoji emoji-id="{eid_val}">{fb}</tg-emoji>'


def eid(key: str) -> str | None:
    """emoji_id для icon_custom_emoji_id на кнопках; None если нет."""
    pair = EMOJI.get(key)
    return pair[0] if pair and pair[0] else None


def has(key: str) -> bool:
    return key in EMOJI


def sym(key: str, default: str = "") -> str:
    """Символ эмодзи для кнопки."""
    return BTN.get(key, default)
