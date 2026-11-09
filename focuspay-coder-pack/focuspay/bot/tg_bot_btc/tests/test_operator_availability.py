"""Unit tests for operator_availability."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from services import config_rates
from services.operator_availability import (
    bypasses_operator_shift_check,
    evaluate_shift_gate,
    has_operator_on_shift,
    missing_operator_roles,
    should_block_requisites_no_shift,
)


def test_has_operator_on_shift_true():
    with patch(
        "services.operator_availability.get_active_operator_shifts",
        new=AsyncMock(return_value=[{"operator_roles": ["client", "finance"]}]),
    ):
        assert asyncio.run(has_operator_on_shift()) is True


def test_has_operator_on_shift_false():
    with patch(
        "services.operator_availability.get_active_operator_shifts",
        new=AsyncMock(return_value=[]),
    ):
        assert asyncio.run(has_operator_on_shift()) is False


def test_missing_operator_roles_requires_both_roles():
    assert missing_operator_roles([{"operator_roles": ["client"]}]) == ("finance",)
    assert missing_operator_roles([{"operator_roles": ["finance"]}]) == ("client",)
    assert missing_operator_roles([
        {"operator_roles": ["client", "finance"]},
    ]) == ()
    assert missing_operator_roles([
        {"operator_role": "finance", "operator_roles": []},
    ]) == ("client",)


def test_bypasses_operator_shift_check_admin(monkeypatch):
    monkeypatch.setattr(config_rates, "TELEGRAM_ADMIN_IDS", [42])
    assert bypasses_operator_shift_check(42) is True
    assert bypasses_operator_shift_check(99) is False


def test_should_block_when_no_shift_and_not_admin(monkeypatch):
    monkeypatch.setattr(config_rates, "TELEGRAM_ADMIN_IDS", [])
    with patch(
        "services.operator_availability.get_active_operator_shifts",
        new=AsyncMock(return_value=[]),
    ):
        assert asyncio.run(should_block_requisites_no_shift(100)) is True


def test_should_not_block_admin_without_shift(monkeypatch):
    monkeypatch.setattr(config_rates, "TELEGRAM_ADMIN_IDS", [100])
    with patch(
        "services.operator_availability.get_active_operator_shifts",
        new=AsyncMock(return_value=[]),
    ):
        assert asyncio.run(should_block_requisites_no_shift(100)) is False


def test_active_covering_shift_allows_buy():
    gate = evaluate_shift_gate(
        [{"operator_roles": ["client", "finance"], "telegram_user_id": 111}]
    )
    assert gate.allow is True
    assert gate.reason == "ok"
    assert gate.telegram_user_ids == (111,)


def test_no_shift_blocks_buy():
    gate = evaluate_shift_gate([])
    assert gate.allow is False
    assert gate.reason == "no_shift"
    assert gate.missing_roles == ("client", "finance")


def test_two_open_shifts_are_recognized_for_buy():
    gate = evaluate_shift_gate(
        [
            {"operator_roles": ["client"], "telegram_user_id": 111},
            {"operator_roles": ["finance"], "telegram_user_id": 222},
        ]
    )
    assert gate.allow is True
    assert gate.active_count == 2
    assert set(gate.telegram_user_ids) == {111, 222}


def test_username_is_not_treated_as_canonical_shift_id():
    gate = evaluate_shift_gate(
        [
            {"operator_roles": ["client", "finance"], "telegram_user_id": "Rrrrram"},
        ]
    )
    assert gate.allow is True
    assert gate.telegram_user_ids == ()
    assert gate.unbound_count == 1


def test_shift_rows_without_role_fields_default_to_client_only():
    gate = evaluate_shift_gate(
        [
            {"operator_name": "Rrrrram"},
            {"operator_name": "miltos"},
        ]
    )
    assert gate.allow is False
    assert gate.reason == "incomplete_shift"
    assert gate.missing_roles == ("finance",)


def test_finance_and_client_roles_on_one_shift_allow():
    gate = evaluate_shift_gate(
        [
            {"operator_roles": ["client"], "telegram_user_id": 111},
            {"operator_roles": ["finance", "client"], "telegram_user_id": 222},
        ]
    )
    assert gate.allow is True
    assert gate.reason == "ok"


def test_two_client_shifts_still_incomplete():
    gate = evaluate_shift_gate(
        [
            {"operator_roles": ["client"], "telegram_user_id": 111},
            {"operator_roles": ["client"], "telegram_user_id": 222},
        ]
    )
    assert gate.allow is False
    assert gate.reason == "incomplete_shift"
    assert gate.missing_roles == ("finance",)
    assert set(gate.telegram_user_ids) == {111, 222}
