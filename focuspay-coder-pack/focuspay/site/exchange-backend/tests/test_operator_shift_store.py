"""Regression: canonical ids, multi-shift set, chat/topic, midnight."""
from datetime import datetime, timedelta, timezone

from operator_availability import evaluate_shift_gate
from operator_shift_store import (
    add_active_shift_user,
    canonical_telegram_user_id,
    list_active_shift_user_ids,
    normalize_topic_id,
    read_operator_shift_state,
    read_operator_shift_target,
    remove_active_shift_user,
    replace_active_shift_user_ids,
    same_shift_chat_context,
    write_operator_shift_target,
)


def _use_tmp_store(tmp_path, monkeypatch):
    path = tmp_path / "operator_shifts_chat.json"
    monkeypatch.setenv("OPERATOR_SHIFT_CONFIG_FILE", str(path))
    return path


def test_canonical_telegram_user_id_rejects_aliases():
    assert canonical_telegram_user_id(1097952683) == 1097952683
    assert canonical_telegram_user_id("1097952683") == 1097952683
    assert canonical_telegram_user_id("Rrrrram") is None
    assert canonical_telegram_user_id("@miltos") is None
    assert canonical_telegram_user_id(-1001234567890) is None
    assert canonical_telegram_user_id(0) is None
    assert canonical_telegram_user_id("web-12") is None
    assert canonical_telegram_user_id(None) is None
    assert canonical_telegram_user_id(True) is None


def test_normalize_topic_id_none_vs_concrete():
    assert normalize_topic_id(None) is None
    assert normalize_topic_id(0) is None
    assert normalize_topic_id(42) == 42
    assert same_shift_chat_context(-1001, None, stored={"chat_id": -1001})
    assert not same_shift_chat_context(-1001, 42, stored={"chat_id": -1001})
    assert same_shift_chat_context(
        -1001, 42, stored={"chat_id": -1001, "topic_id": 42}
    )


def test_two_sequential_opens_keep_both_user_ids(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    add_active_shift_user(111)
    second = add_active_shift_user(222)
    assert set(second) == {111, 222}
    assert set(list_active_shift_user_ids()) == {111, 222}


def test_write_chat_target_does_not_wipe_active_set(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    add_active_shift_user(111)
    add_active_shift_user(222)
    write_operator_shift_target(-10042, 7)
    assert read_operator_shift_target() == {"chat_id": -10042, "topic_id": 7}
    assert set(list_active_shift_user_ids()) == {111, 222}
    write_operator_shift_target(-10042, None)
    assert read_operator_shift_target() == {"chat_id": -10042}
    assert set(list_active_shift_user_ids()) == {111, 222}


def test_replace_from_db_snapshot_keeps_set_not_last_writer(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    add_active_shift_user(111)
    synced = replace_active_shift_user_ids(
        [111, "222", "@miltos", -1001, 0, "Rrrrram"]
    )
    assert synced == [111, 222]


def test_close_one_shift_keeps_the_other(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    add_active_shift_user(111)
    add_active_shift_user(222)
    assert remove_active_shift_user(111) == [222]


def test_active_set_survives_midnight(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    add_active_shift_user(111)
    add_active_shift_user(222)
    yesterday = datetime.now(timezone.utc) - timedelta(hours=14)
    state = read_operator_shift_state()
    assert set(state["active_user_ids"]) == {111, 222}
    assert not any(key.startswith("20") and len(key) == 10 for key in state)
    gate = evaluate_shift_gate(
        [
            {
                "operator_roles": ["client"],
                "telegram_user_id": 111,
                "started_at": yesterday,
            },
            {
                "operator_roles": ["finance"],
                "telegram_user_id": 222,
                "started_at": yesterday,
            },
        ]
    )
    assert gate.allow is True
    assert gate.reason == "ok"
    assert gate.active_count == 2
