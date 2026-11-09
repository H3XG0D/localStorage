"""Оценка возраста Telegram-аккаунта по user_id (локально, без сторонних ботов).

Telegram выдаёт user_id почти монотонно во времени. По опорным точкам
(user_id → unix) дата интерполируется. Точность ~недели/месяца — достаточно
чтобы отличить «аккаунт вчера» от «годы».
"""
from __future__ import annotations

from datetime import datetime, timezone

# (user_id, unix_timestamp) — отсортировано по id. Приближённые вехи.
_ANCHORS: list[tuple[int, int]] = [
    (1_000_000, 1_380_000_000),  # ~2013-09
    (100_000_000, 1_452_000_000),  # ~2016-01
    (300_000_000, 1_500_000_000),  # ~2017-07
    (500_000_000, 1_530_000_000),  # ~2018-06
    (800_000_000, 1_560_000_000),  # ~2019-06
    (1_000_000_000, 1_593_000_000),  # ~2020-06
    (1_300_000_000, 1_610_000_000),  # ~2021-01
    (1_700_000_000, 1_640_000_000),  # ~2021-12
    (2_000_000_000, 1_660_000_000),  # ~2022-08
    (5_000_000_000, 1_690_000_000),  # ~2023-07
    (6_500_000_000, 1_710_000_000),  # ~2024-03
    (7_500_000_000, 1_725_000_000),  # ~2024-09
    (8_200_000_000, 1_750_000_000),  # ~2025-06 (экстраполяция)
]


def estimate_creation_date(user_id: int) -> datetime | None:
    if user_id <= 0:
        return None

    anchors = _ANCHORS
    if user_id <= anchors[0][0]:
        (id1, t1), (id2, t2) = anchors[0], anchors[1]
    elif user_id >= anchors[-1][0]:
        (id1, t1), (id2, t2) = anchors[-2], anchors[-1]
    else:
        (id1, t1), (id2, t2) = anchors[0], anchors[1]
        for i in range(len(anchors) - 1):
            if anchors[i][0] <= user_id <= anchors[i + 1][0]:
                (id1, t1), (id2, t2) = anchors[i], anchors[i + 1]
                break

    if id2 == id1:
        return None
    slope = (t2 - t1) / (id2 - id1)
    ts = t1 + slope * (user_id - id1)
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def estimate_age_days(user_id: int, now: datetime | None = None) -> int | None:
    created = estimate_creation_date(user_id)
    if created is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - created).days)
