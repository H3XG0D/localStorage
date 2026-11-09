"""Метки доверия внештатника (доверенный / новый клиент)."""
from __future__ import annotations


def client_trust_label(is_trusted: bool) -> str:
    return "доверенный" if is_trusted else "новый"


def deal_client_label(is_new: bool) -> str:
    return "новый" if is_new else "повторный"


def deal_fields_from_row(row: dict | None) -> dict:
    is_new = True if row is None else bool(row.get("client_is_new", True))
    return {
        "client_is_new": is_new,
        "deal_client_label": deal_client_label(is_new),
    }


def effective_auto_credit(is_trusted: bool, auto_credit_on_payfast: bool) -> bool:
    return bool(is_trusted and auto_credit_on_payfast)


def trust_fields_from_row(row: dict | None) -> dict:
    if not row:
        return {
            "is_trusted_client": False,
            "auto_credit_on_payfast": False,
            "client_trust_label": client_trust_label(False),
        }
    trusted = bool(row.get("is_trusted_client"))
    auto = effective_auto_credit(trusted, bool(row.get("auto_credit_on_payfast")))
    return {
        "is_trusted_client": trusted,
        "auto_credit_on_payfast": auto,
        "client_trust_label": client_trust_label(trusted),
    }
