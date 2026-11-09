"""Shim: каноническая реализация в services.operator_shift_store."""
from services.operator_shift_store import (  # noqa: F401
    add_active_shift_user,
    canonical_telegram_user_id,
    list_active_shift_user_ids,
    normalize_topic_id,
    operator_shift_file,
    read_operator_shift_state,
    read_operator_shift_target,
    remove_active_shift_user,
    replace_active_shift_user_ids,
    same_shift_chat_context,
    write_operator_shift_target,
)
