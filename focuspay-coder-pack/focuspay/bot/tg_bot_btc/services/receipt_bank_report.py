"""Разбор команды /checks и выборка апрувнутых чеков по банку отправителя.

`payment_snapshot -> bill -> bank` — банк реквизита, то есть куда клиент
переводил. В PDF это строка «банк получателя». Команде нужен банк, из
которого ушли деньги: подпись внизу чека, почта поддержки или шаблон
приложения. Пишут его как придётся («ВТБ», «Банк ВТБ», «VTB», «Сбер»),
поэтому запрос оператора — набор подстрок, а не одно точное значение.
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.merchant_order_id import resolve_merchant_display_id
from services.payment_snapshot import order_payment_snapshot
from services.receipt_pdf_inspect import read_receipt_markup
from services.text_sanitize import sanitize_telegram_html

_MSK = timezone(timedelta(hours=3))

DEFAULT_COUNT = 10
MAX_COUNT = 20
# Пачка свежих документов за один заход к базе. Отправителя читаем из PDF,
# поэтому запрос шире, чем число чеков в ответе.
SCAN_BATCH = 80
# 500 документов — примерно две-три недели. Редкие банки (ВТБ как отправитель)
# встречаются около 2% чеков; дальше команда уже слишком долгая.
MAX_SCAN = 500

# label -> алиасы запроса + подстроки для поиска в payment_snapshot.
_BANKS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("ВТБ", ("втб", "vtb"), ("втб", "vtb")),
    ("Сбербанк", ("сбер", "сбербанк", "sber", "sberbank"), ("сбер", "sber")),
    # «T-Банк» на проде пишут и латинской T, и кириллической — нужны оба варианта.
    ("Т-Банк", ("тбанк", "т-банк", "тинькофф", "tinkoff", "tbank", "t-bank", "tcs"),
     ("тинь", "tinkoff", "т-банк", "t-банк", "тбанк", "tbank", "t-bank", "tcs")),
    ("Альфа-Банк", ("альфа", "alfa", "alpha"), ("альфа", "alfa", "alpha")),
    ("Райффайзен", ("райф", "райффайзен", "raif", "raiffeisen"), ("райф", "raif")),
    ("Газпромбанк", ("газпром", "газпромбанк", "gazprom", "gpb"), ("газпром", "gazprom", "gpb")),
    ("Промсвязьбанк", ("псб", "промсвязьбанк", "промсвязь", "psb", "psbank"),
     ("промсвязь", "псб", "psb")),
    ("ЮMoney", ("юmoney", "юмани", "yoomoney", "umoney"), ("юmoney", "юмани", "yoomoney")),
    ("Вайлдберриз Банк", ("вб", "вайлдберриз", "wb", "wbbank"), ("вайлдберриз", "wbbank")),
    ("Ренессанс Кредит", ("ренессанс", "renessans", "renaissance"), ("ренессанс", "renessans")),
    ("Озон Банк", ("озон", "ozon"), ("озон", "ozon")),
    ("Яндекс Банк", ("яндекс", "yandex"), ("яндекс", "yandex")),
    ("Совкомбанк", ("совком", "совкомбанк", "sovcom"), ("совком", "sovcom")),
    ("Почта Банк", ("почта", "pochta"), ("почта", "pochta")),
    ("Росбанк", ("росбанк", "rosbank"), ("росбанк", "rosbank")),
    ("МТС Банк", ("мтс", "mts"), ("мтс", "mts")),
    ("Ак Барс", ("акбарс", "ак барс", "akbars"), ("акбарс", "akbars", "ак барс")),
    ("Открытие", ("открытие", "otkritie"), ("открыт", "otkritie")),
    ("ОТП Банк", ("отп", "otp"), ("отп", "otp")),
    ("Уралсиб", ("уралсиб", "uralsib"), ("уралсиб", "uralsib")),
    ("Хоум Банк", ("хоум", "home"), ("хоум", "home")),
    ("Русский Стандарт", ("рс", "русскийстандарт", "rsb"), ("русский стандарт", "rsb")),
)


def bank_help_list() -> str:
    return ", ".join(aliases[0] for _, aliases, _ in _BANKS)


def resolve_bank_query(raw: str) -> tuple[str, list[str]] | None:
    """«vtb» → ('ВТБ', ['%втб%', '%vtb%']). Незнакомое слово ищем как есть."""
    token = (raw or "").strip().lower().replace("ё", "е")
    if len(token) < 2:
        return None
    for label, aliases, needles in _BANKS:
        if token in aliases:
            return label, [f"%{n}%" for n in needles]
    return raw.strip(), [f"%{token}%"]


def parse_checks_request(args: list[str] | None) -> tuple[str, list[str], int] | None:
    """`/checks vtb 10` → (label, patterns, count). Число необязательно."""
    parts = [str(a).strip() for a in (args or []) if str(a).strip()]
    if not parts:
        return None

    count = DEFAULT_COUNT
    if parts[-1].isdigit():
        n = int(parts[-1])
        if n < 1:
            return None
        count = min(n, MAX_COUNT)
        parts = parts[:-1]
    if not parts:
        return None

    resolved = resolve_bank_query(" ".join(parts))
    if resolved is None:
        return None
    label, patterns = resolved
    return label, patterns, count


def _fmt_when(value) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return str(value)[:16]
    if not isinstance(value, datetime):
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_MSK).strftime("%d.%m %H:%M")


def _fmt_rub(amount) -> str:
    try:
        n = float(amount or 0)
    except (TypeError, ValueError):
        n = 0.0
    return f"{n:,.0f} ₽".replace(",", " ")


def order_bank(order: dict) -> str:
    sender = str(order.get("_sender_bank") or "").strip()
    if sender:
        return sender
    bill = order_payment_snapshot(order).get("bill")
    if isinstance(bill, dict):
        return str(bill.get("bank") or "").strip()
    return ""


def order_bank_label(order: dict) -> str:
    """Банк в строке сводки: отправитель, и получатель если он другой."""
    sender = order_bank(order)
    recipient = str(order.get("_recipient_bank") or "").strip()
    if recipient and fold_bank(recipient) != fold_bank(sender):
        return f"{sender} → {recipient}"
    return sender


def format_check_line(order: dict, *, file_missing: bool) -> str:
    disp = html.escape(resolve_merchant_display_id(order))
    bank = html.escape(order_bank_label(order) or "—")
    fiat = html.escape(_fmt_rub(order.get("fiat_amount")))
    status = html.escape(str(order.get("status") or "—"))
    when = html.escape(_fmt_when(order.get("created_at")))
    line = f"🆔 <code>{disp}</code> · {fiat} · {bank} · {status} · {when}"
    if file_missing:
        line += " · файла нет"
    return line


def format_check_caption(order: dict) -> str:
    disp = html.escape(resolve_merchant_display_id(order))
    bank = html.escape(order_bank_label(order) or "—")
    fiat = html.escape(_fmt_rub(order.get("fiat_amount")))
    uid = html.escape(str(order.get("user_id") or "—"))
    when = html.escape(_fmt_when(order.get("created_at")))
    return sanitize_telegram_html(
        f"🆔 <code>{disp}</code> · {fiat} · {bank}\n👤 ID <code>{uid}</code> · {when}"
    )


def format_checks_summary(
    label: str,
    count: int,
    orders: list[dict],
    *,
    scanned: int = 0,
    capped: bool = False,
) -> str:
    lines = [
        "🧾 <b>Апрувнутые чеки</b>",
        f"🏦 Отправки из: <b>{html.escape(label)}</b> · запрошено: {int(count)}",
        "",
    ]
    if not orders:
        lines.append("Чеков не нашлось.")
    else:
        total = 0.0
        for order in orders:
            lines.append(format_check_line(order, file_missing=bool(order.get("_file_missing"))))
            try:
                total += float(order.get("fiat_amount") or 0)
            except (TypeError, ValueError):
                pass
        lines.append("")
        lines.append(f"Σ {html.escape(_fmt_rub(total))} по {len(orders)} чекам")
    if scanned and (not orders or capped):
        lines.append(f"Просмотрено документов: {int(scanned)}.")
    return sanitize_telegram_html("\n".join(lines))


# В чеках Альфа-Банка слова разделены неразрывным пробелом, обычный пробел их не находит.
_ODD_SPACE = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")


def fold_bank(value: str) -> str:
    text = _ODD_SPACE.sub(" ", value or "")
    return (
        text.lower()
        .replace("ё", "е")
        .replace("\u2011", "-")
        .replace("–", "-")
        .replace("—", "-")
    )


_RECIPIENT_LINE = re.compile(r"банк\s+получателя\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_SENDER_LINE = re.compile(r"банк\s+отправителя\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_BIK_RECIPIENT = re.compile(r"бик\s+банка\s+получателя", re.IGNORECASE)


def _text_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _field_value(lines: list[str], index: int, match: re.Match[str]) -> str:
    value = match.group(1).strip(" :.-")
    if not value and index + 1 < len(lines):
        value = lines[index + 1].strip(" :.-")
    return re.sub(r"\s+", " ", value).strip()


def known_bank(fragment: str) -> str | None:
    """Короткая строка (поле чека) → каноническое имя. Не для всего текста PDF."""
    folded = fold_bank(fragment)
    if not folded:
        return None
    hits: list[tuple[int, str]] = []
    for label, _aliases, needles in _BANKS:
        for needle in needles:
            if len(needle) < 3:
                continue
            if needle in folded:
                hits.append((len(needle), label))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def explicit_sender(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = _SENDER_LINE.search(line)
        if not match:
            continue
        value = _field_value(lines, index, match)
        if value:
            return value[:48]
    return None


def explicit_recipient(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = _RECIPIENT_LINE.search(line)
        if not match:
            continue
        value = _field_value(lines, index, match)
        if value:
            return value[:48]
    return None


def without_recipient(lines: list[str]) -> str:
    """Текст без значения «банк получателя»: оно не говорит, кто выпустил чек."""
    kept: list[str] = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            if not _RECIPIENT_LINE.search(line):
                continue
        if _BIK_RECIPIENT.search(line):
            continue
        match = _RECIPIENT_LINE.search(line)
        if match:
            if not match.group(1).strip(" :.-"):
                skip_next = True
            continue
        kept.append(line)
    return "\n".join(kept)


def sender_matches(sender: str, patterns: list[str]) -> bool:
    folded = fold_bank(sender)
    if not folded:
        return False
    for pattern in patterns:
        needle = fold_bank(pattern).strip("%")
        if len(needle) >= 2 and needle in folded:
            return True
    return False


def identify_sender(text: str, producer: str = "", creator: str = "") -> str | None:
    """Банк, из приложения которого клиент отправил перевод. None — не разобрали."""
    lines = _text_lines(text)
    sender_field = explicit_sender(lines)
    if sender_field:
        return known_bank(sender_field) or sender_field

    body = fold_bank(without_recipient(lines))
    prod = fold_bank(producer)
    crea = fold_bank(creator)
    if not body and not prod and not crea:
        return None

    if "озон банк" in body or "ozon банк" in body or "ozon bank" in body:
        return "Озон Банк"
    if "банк втб" in body or "втб (пао)" in body or "втб(пао)" in body:
        return "ВТБ"
    if "отп банк" in body:
        return "ОТП Банк"
    if "gazprombank" in body or "газпромбанк" in body:
        return "Газпромбанк"
    if "akbars.ru" in body or "ак барс" in body or "акбарс" in body:
        return "Ак Барс"
    if "raiffeisen" in body or "райффайзен" in body:
        return "Райффайзен"
    if "tbank.ru" in body or "t-bank.ru" in body:
        return "Т-Банк"
    if "yoomoney" in body or "юmoney" in body or "юмани" in body:
        return "ЮMoney"
    if "номер кошелька" in body and (
        "перевод на карту" in body or "перевод завершен" in body or "перевод завершён" in body
    ):
        return "ЮMoney"
    # Чек Сбера: JasperReports 6.18 (и «Чек по операции»). Т-Банк на этой версии не сидит.
    if "jasperreports library version 6.18" in crea:
        return "Сбербанк"
    if "чек по операции" in body and (
        "код авторизации" in body or "номер документа" in body or "itext 2.1.7" in prod
    ):
        return "Сбербанк"
    if "перевод клиенту сбербанка" in body:
        return "Сбербанк"
    if "перевод в другой банк по номеру карты" in body and "jasperreports" in crea:
        return "Сбербанк"
    # Квитанция Альфа-Банка: логотип картинкой, в тексте слова «Альфа» нет.
    # Поля всегда «Сформирована» + «Квитанция о переводе по СБП»
    # (Oracle BI или та же страница, сохранённая с iPhone).
    if "сформирована" in body and "квитанция о переводе по сбп" in body:
        return "Альфа-Банк"
    for phrase, label in (
        ("сбербанк", "Сбербанк"),
        ("сбербанка", "Сбербанк"),
        ("тинькофф", "Т-Банк"),
        ("альфа-банк", "Альфа-Банк"),
        ("альфа банк", "Альфа-Банк"),
    ):
        if phrase in body:
            return label
    return None


def recipient_label(text: str) -> str:
    value = explicit_recipient(_text_lines(text))
    if not value:
        return ""
    return known_bank(value) or value


def _receipt_path(name: str, root: Path) -> Path | None:
    raw = str(name or "").strip()
    if not raw or raw in {".", ".."} or raw != Path(raw).name:
        return None
    if "/" in raw or "\\" in raw or "\x00" in raw:
        return None
    base = root.resolve()
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def match_sender_orders(
    orders: list[dict], patterns: list[str], root: Path, need: int
) -> list[dict]:
    """Оставляет заявки, чек которых выпущен запрошенным банком."""
    found: list[dict] = []
    limit = max(0, int(need))
    for order in orders:
        if len(found) >= limit:
            break
        path = _receipt_path(str(order.get("receipt_file") or ""), root)
        if path is None or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if not raw.startswith(b"%PDF"):
            continue
        text, producer, creator = read_receipt_markup(raw)
        sender = identify_sender(text, producer, creator)
        if not sender or not sender_matches(sender, patterns):
            continue
        matched = dict(order)
        matched["_sender_bank"] = sender
        matched["_recipient_bank"] = recipient_label(text)
        matched["_path"] = path
        matched["_file_missing"] = False
        found.append(matched)
    return found


async def collect_sender_receipts(
    patterns: list[str], count: int, root: Path
) -> tuple[list[dict], int, bool]:
    """(чеки, сколько документов просмотрено, упёрлись в потолок)."""
    from services.db import get_recent_approved_receipt_documents

    want = max(1, min(int(count or 1), MAX_COUNT))
    found: list[dict] = []
    scanned = 0
    offset = 0
    while len(found) < want and scanned < MAX_SCAN:
        batch_n = min(SCAN_BATCH, MAX_SCAN - scanned)
        rows = await get_recent_approved_receipt_documents(batch_n, offset)
        if not rows:
            break
        orders = [dict(row) for row in rows]
        found.extend(
            await asyncio.to_thread(
                match_sender_orders, orders, patterns, root, want - len(found)
            )
        )
        scanned += len(rows)
        offset += len(rows)
        if len(rows) < batch_n:
            break
    capped = len(found) < want and scanned >= MAX_SCAN
    return found[:want], scanned, capped
