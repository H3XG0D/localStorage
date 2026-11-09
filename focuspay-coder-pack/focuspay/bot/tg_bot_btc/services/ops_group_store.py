"""Runtime chat_id группы операторов (регистрация текстом «123» в группе)."""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def ops_group_file() -> Path:
    explicit = (os.getenv("OPS_GROUP_ID_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    prod = Path("/opt/tg_bot_btc/data/ops_group_id")
    if prod.parent.is_dir() or prod.is_file():
        return prod
    return _ROOT / "data" / "ops_group_id"


def read_ops_group_id() -> int:
    path = ops_group_file()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def write_ops_group_id(chat_id: int) -> Path:
    path = ops_group_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(chat_id)), encoding="utf-8")
    return path
