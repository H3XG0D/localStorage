"""Unit tests for payin_resolver.build_payin_plan."""
from __future__ import annotations

import pytest

from services.payin_resolver import build_payin_plan


def _bill_response() -> dict:
    return {"bill": {"bank": "Test", "reciver": "123"}}


def test_full_bill_always_single():
    plan = build_payin_plan(
        10198,
        "SBPRUB",
        api_response=_bill_response(),
    )
    assert plan.mode == "single"
    assert plan.parts == [10198]
    assert plan.has_bill is True


def test_no_bill_amount_above_operator_min_is_operator():
    plan = build_payin_plan(10198, "SBPRUB", api_response=None)
    assert plan.mode == "operator"
    assert plan.has_bill is False


def test_no_bill_with_partial_probe_ok_still_operator():
    plan = build_payin_plan(
        10198,
        "SBPRUB",
        api_response=None,
        partial_probe_ok=True,
    )
    assert plan.mode == "operator"
    assert plan.has_bill is False


def test_no_bill_below_operator_min_is_reject():
    plan = build_payin_plan(500, "SBPRUB", api_response=None)
    assert plan.mode == "reject"


def test_error_response_treated_as_no_bill():
    plan = build_payin_plan(
        8000,
        "SBPRUB",
        api_response={"status_pending": "error", "error": "fail"},
    )
    assert plan.mode == "operator"
    assert plan.has_bill is False


def test_empty_bill_without_reciver_is_not_single():
    plan = build_payin_plan(
        8000,
        "SBPRUB",
        api_response={"status_pending": "ok", "bill": None, "uuid_system": "u1"},
    )
    assert plan.mode == "operator"
    assert plan.has_bill is False


def test_bill_without_reciver_is_not_single():
    plan = build_payin_plan(
        8000,
        "CARDRUB",
        api_response={"status_pending": "ok", "bill": {"bank": "CARD"}},
    )
    assert plan.mode == "operator"
    assert plan.has_bill is False


def test_resolved_sub_token_preserved_on_single():
    plan = build_payin_plan(
        8000,
        "SBPRUB",
        api_response=_bill_response(),
        resolved_sub_token="SBPRUB",
    )
    assert plan.mode == "single"
    assert plan.resolved_sub_token == "SBPRUB"
