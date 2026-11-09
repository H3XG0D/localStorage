"""Читаемая выдача реквизита клиенту: только банк / карта|телефон / ФИО.

Payfast в bill кладёт служебные поля (token, limit_sum, sub_token). Их нельзя
показывать внештатнику и его покупателю — как в webapp реквизитов FocusPay.
"""
from __future__ import annotations

import re
from typing import Any

from external_deal_timing import EXTERNAL_DEAL_CLIENT_PAY_MIN

_PHONE_RE = re.compile(r"^[\d+\s()-]{10,}$")

BANNED_PAY_WARNING = (
    "Не оплачивайте с МТС Банка и Уралсиба — такие переводы не принимаем."
)


def public_payin_bill(bill: Any) -> dict[str, str]:
    """Только поля, которые можно отдать магазину и клиенту."""
    if not isinstance(bill, dict):
        return {}
    bank = str(bill.get("bank") or bill.get("bankName") or "").strip()
    reciver = str(
        bill.get("reciver")
        or bill.get("receiver")
        or bill.get("card")
        or bill.get("phone")
        or ""
    ).strip()
    fio = str(bill.get("fio") or bill.get("holderName") or "").strip()
    out: dict[str, str] = {}
    if bank:
        out["bank"] = bank
    if reciver:
        out["reciver"] = reciver
    if fio:
        out["fio"] = fio
    return out


def _looks_like_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 10 and bool(_PHONE_RE.match(value.strip()))


def _format_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"
    if len(digits) == 10:
        return f"+7 {digits[0:3]} {digits[3:6]} {digits[6:8]} {digits[8:]}"
    return value.strip()


def _format_rub_amount(amount: Any) -> str:
    try:
        n = int(round(float(amount)))
    except (TypeError, ValueError):
        n = 0
    return f"{n:,}".replace(",", " ")


def client_payment_fields(bill: Any, sub_token: str | None) -> list[dict[str, str]]:
    """Подписи как у кабинета: Банк, Номер карты / Телефон СБП, ФИО / Получатель."""
    raw = bill if isinstance(bill, dict) else {}
    pub = public_payin_bill(raw)
    sub = (sub_token or "SBPRUB").upper()
    bank = pub.get("bank") or ""
    fio = pub.get("fio") or ""
    reciver = pub.get("reciver") or ""
    fields: list[dict[str, str]] = []
    if bank:
        fields.append({"label": "Банк", "value": bank})
    if sub == "SBPRUB":
        phone_raw = fio if _looks_like_phone(fio) else reciver if _looks_like_phone(reciver) else ""
        name_raw = reciver if phone_raw == fio else fio if phone_raw == reciver else (fio or reciver)
        if phone_raw:
            fields.append({"label": "Телефон СБП", "value": _format_phone(phone_raw)})
        if name_raw and name_raw != phone_raw:
            fields.append({"label": "Получатель", "value": name_raw})
        elif not phone_raw and reciver:
            fields.append({"label": "Реквизит", "value": reciver})
        elif not phone_raw and fio:
            fields.append({"label": "Реквизит", "value": fio})
    else:
        if reciver:
            fields.append({"label": "Номер карты", "value": reciver})
        if fio:
            fields.append({"label": "ФИО", "value": fio})
    return fields


def format_client_payment_text(
    *,
    amount_rub: Any,
    sub_token: str | None,
    bill: Any = None,
    deal_id: Any = None,
) -> str:
    """Итоговый текст для клиента магазина / «Копировать всё»."""
    sub = (sub_token or "SBPRUB").upper()
    method = "Карта" if sub == "CARDRUB" else "СБП"
    minutes = int(EXTERNAL_DEAL_CLIENT_PAY_MIN)
    labeled = {item["label"]: item["value"] for item in client_payment_fields(bill, sub)}
    requisite = (
        labeled.get("Номер карты")
        or labeled.get("Телефон СБП")
        or labeled.get("Реквизит")
        or ""
    )
    bank = labeled.get("Банк") or ""
    holder = labeled.get("ФИО") or labeled.get("Получатель") or ""

    lines = [
        "⚡ Реквизит выдан",
        "",
        f"⛔ {BANNED_PAY_WARNING}",
        "",
    ]
    if deal_id is not None and str(deal_id).strip() != "":
        lines.append(f"▸ Заявка: #{deal_id}")
    lines.append(f"▸ Сумма: {_format_rub_amount(amount_rub)} ₽")
    if requisite:
        lines.append(f"▸ Реквизит: {requisite}")
    if bank:
        lines.append(f"▸ Банк: {bank}")
    if holder:
        lines.append(f"▸ Получатель: {holder}")
    lines.append(f"▸ Способ: {method}")
    lines.append(f"▸ Срок оплаты: {minutes} минут")
    lines.extend(
        [
            "",
            "📌 Переведите ровно эту сумму, одним платежом.",
        ]
    )
    if method == "СБП":
        lines.append("По СБП — только на указанный банк.")
    lines.extend(
        [
            "",
            "Чек лучше сразу PDF, сразу после перевода.",
            f"Если деньги ушли, а чек пришёл позже {minutes} минут — оплату не подтвердим, средства могут пропасть.",
            "Если по чеку будут вопросы — попросим видео экрана. Без него заявку закроем.",
        ]
    )
    return "\n".join(lines)
