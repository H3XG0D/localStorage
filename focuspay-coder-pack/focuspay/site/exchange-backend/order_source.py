"""Canonical order source values shared by API serializers."""

ORDER_SOURCE_LEGACY = "manual"
ORDER_SOURCE_BOT = "bot"
ORDER_SOURCE_SITE = "site"
ORDER_SOURCE_OPERATOR = "manual_operator"
ORDER_SOURCE_MINIAPP = "tg_miniapp"
ORDER_VIA_TG_MINIAPP = ORDER_SOURCE_MINIAPP

ORDER_SOURCE_LABELS = {
    ORDER_SOURCE_BOT: "Telegram-бот",
    ORDER_SOURCE_MINIAPP: "Миниаппка",
    ORDER_SOURCE_SITE: "Сайт",
    ORDER_SOURCE_OPERATOR: "Оператор",
    ORDER_SOURCE_LEGACY: "Старые заявки",
    "telegram_auto": "Telegram",
}


def normalize_order_source(value: object) -> str:
    source = str(value or "").strip().lower()
    return source or ORDER_SOURCE_LEGACY


def order_source_label(value: object) -> str:
    source = normalize_order_source(value)
    return ORDER_SOURCE_LABELS.get(source, source)


def order_source_for_via(via: object) -> str:
    """Exchange miniapp JWT claim is its own source. Anything else is the site."""
    if str(via or "").strip() == ORDER_VIA_TG_MINIAPP:
        return ORDER_SOURCE_MINIAPP
    return ORDER_SOURCE_SITE


def uses_bot_receipt_route(value: object) -> bool:
    """Miniapp receipts follow the same file tree as a receipt sent in the bot."""
    return normalize_order_source(value) in {ORDER_SOURCE_BOT, ORDER_SOURCE_MINIAPP}


def coerce_public_order_source(value: object) -> str:
    """Public create accepts only bot (miniapp) or site. Other values stay site."""
    if str(value or "").strip().lower() == ORDER_SOURCE_BOT:
        return ORDER_SOURCE_BOT
    return ORDER_SOURCE_SITE


def channel_note(order_source: object, detail: str = "") -> str:
    """Ops card prefix. Miniapp, bot, and site stay distinct."""
    source = normalize_order_source(order_source)
    if source == ORDER_SOURCE_MINIAPP:
        prefix = "Миниаппка"
    elif source == ORDER_SOURCE_BOT:
        prefix = "Telegram"
    else:
        prefix = "Сайт"
    extra = str(detail or "").strip()
    return f"{prefix} · {extra}" if extra else prefix
