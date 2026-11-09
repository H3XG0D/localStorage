# Адаптивный антиспам: мягко для обычных юзеров, жёстко при явном флуде.
# In-memory, без БД. Заблокированные запросы отсекаются до хендлеров (экономия CPU).
import time
from typing import TypedDict

WINDOW_SEC = 10
SOFT_LIMIT = 8   # до этого — без задержки
HARD_LIMIT = 14  # явный спам за окно

BASE_DELAY = 1.0
MIN_SPAM_DELAY = 60.0   # минимум 1 минута при жёстком спаме
MAX_DELAY = 180.0         # до 3 минут для повторных нарушений
HARD_PENALTY_FROM = 2     # с этого уровня — не меньше MIN_SPAM_DELAY
MAX_PENALTY_LEVEL = 6

DECAY_AFTER_SEC = 60
RESET_AFTER_SEC = 300
WARN_COOLDOWN_SEC = 10
PRUNE_IDLE_AFTER = 3600
PRUNE_EVERY_N = 500

_prune_counter = 0


class _UserState(TypedDict):
    events: list[float]
    penalty_level: int
    blocked_until: float
    last_violation: float
    last_warn: float


_STATES: dict[int, _UserState] = {}


def _get_admin_ids() -> list[int]:
    try:
        from services.config_rates import TELEGRAM_ADMIN_IDS

        return list(TELEGRAM_ADMIN_IDS) if TELEGRAM_ADMIN_IDS else []
    except Exception:
        return []


def _default_state() -> _UserState:
    return {
        "events": [],
        "penalty_level": 0,
        "blocked_until": 0.0,
        "last_violation": 0.0,
        "last_warn": 0.0,
    }


def _calc_block_delay(state: _UserState, event_count: int) -> float:
    """Экспоненциальная пауза; при явном спаме — минимум MIN_SPAM_DELAY."""
    level = state["penalty_level"]
    delay = BASE_DELAY * (2 ** level)

    if event_count >= HARD_LIMIT or level >= HARD_PENALTY_FROM:
        delay = max(MIN_SPAM_DELAY, delay)

    return min(MAX_DELAY, delay)


def _prune_states(now: float) -> None:
    global _prune_counter
    _prune_counter = 0
    to_del = []
    for uid, state in _STATES.items():
        last_activity = max(
            state["last_violation"],
            state["events"][-1] if state["events"] else 0.0,
        )
        if now - last_activity > PRUNE_IDLE_AFTER and state["blocked_until"] <= now:
            to_del.append(uid)
    for uid in to_del:
        del _STATES[uid]


def _apply_decay(state: _UserState, now: float) -> None:
    if state["penalty_level"] <= 0:
        return
    idle = now - state["last_violation"]
    if idle >= RESET_AFTER_SEC:
        state["penalty_level"] = 0
        state["blocked_until"] = 0.0
        return
    if idle >= DECAY_AFTER_SEC:
        steps = int(idle // DECAY_AFTER_SEC)
        state["penalty_level"] = max(0, state["penalty_level"] - steps)
        if state["penalty_level"] == 0:
            state["blocked_until"] = 0.0


def check_rate_limit(user_id: int) -> tuple[bool, float | None]:
    """
    True — обрабатывать запрос.
    False — игнорировать (хендлеры не вызываются); wait — секунд до разблокировки.
    """
    global _prune_counter

    admin_ids = _get_admin_ids()
    if admin_ids and user_id in admin_ids:
        return True, None

    now = time.time()
    state = _STATES.get(user_id)
    if state is None:
        state = _default_state()
        _STATES[user_id] = state

    _apply_decay(state, now)

    # Уже заблокирован — мгновенный отказ без тяжёлой логики
    if now < state["blocked_until"]:
        return False, state["blocked_until"] - now

    events = [t for t in state["events"] if now - t <= WINDOW_SEC]
    state["events"] = events
    count = len(events)

    if count >= SOFT_LIMIT:
        delay = _calc_block_delay(state, count)
        state["blocked_until"] = now + delay
        state["last_violation"] = now
        state["penalty_level"] = min(MAX_PENALTY_LEVEL, state["penalty_level"] + 1)
        return False, delay

    events.append(now)
    state["events"] = events

    _prune_counter += 1
    if _prune_counter >= PRUNE_EVERY_N:
        _prune_states(now)

    return True, None


def _format_wait(seconds: float) -> str:
    sec = max(1, int(seconds + 0.5))
    if sec >= 60:
        mins = max(1, sec // 60)
        return f"~{mins} мин"
    return f"~{sec} сек"


async def _maybe_warn_user(update, wait_sec: float | None, user_id: int) -> bool:
    """True — callback уже закрыт (alert). False — спиннер ещё крутится."""
    if wait_sec is None:
        return False
    state = _STATES.get(user_id)
    if not state or state["penalty_level"] < 1:
        return False

    now = time.time()
    if now - state["last_warn"] < WARN_COOLDOWN_SEC:
        return False
    state["last_warn"] = now

    text = f"⏳ Слишком много запросов. Подождите {_format_wait(wait_sec)}."

    try:
        if update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
            return True
        elif update.message:
            await update.message.reply_text(text)
    except Exception as e:
        print(f"[antispam] warn user {user_id}: {e}")
    return False


async def rate_limit_ok(update) -> bool:
    """True — продолжать обработку, False — выйти (с редким предупреждением)."""
    if not update or not getattr(update, "effective_user", None):
        return True

    user_id = update.effective_user.id
    ok, wait = check_rate_limit(user_id)
    if ok:
        return True

    answered = await _maybe_warn_user(update, wait, user_id)
    query = getattr(update, "callback_query", None)
    if query is not None and not answered:
        try:
            await query.answer()
        except Exception:
            pass
    return False
