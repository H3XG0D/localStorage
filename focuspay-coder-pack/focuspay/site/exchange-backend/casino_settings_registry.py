"""Единственный источник правды по ключам casino_settings."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

GAME_KEYS: tuple[str, ...] = (
    "pvp_dice",
    "baccara",
    "blackjack",
    "raffle",
    "cub",
    "roulette",
    "holdem",
    "jackpot",
    "fixed_room",
    "clan_war",
    "russian_draughts",
)


class UnknownSettingKey(ValueError):
    """Ключ не входит в реестр — писать его в casino_settings нельзя."""


class SettingValueError(ValueError):
    """Значение не проходит проверку реестра."""


@dataclass(frozen=True)
class SettingSpec:
    key: str
    group: str
    kind: str
    default: object
    min_value: Decimal | None
    max_value: Decimal | None
    title_ru: str
    help_ru: str
    requires_finance_owner: bool = False


def _percent(value: str, title: str, help_ru: str, group: str = "commission") -> SettingSpec:
    return SettingSpec(
        key="",
        group=group,
        kind="percent",
        default=Decimal(value),
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        title_ru=title,
        help_ru=help_ru,
    )


def _amount(
    value: str,
    title: str,
    help_ru: str,
    *,
    group: str = "limits",
    min_value: str = "0.01",
) -> SettingSpec:
    return SettingSpec(
        key="",
        group=group,
        kind="amount",
        default=Decimal(value),
        min_value=Decimal(min_value),
        max_value=None,
        title_ru=title,
        help_ru=help_ru,
    )


def _int(
    value: str,
    title: str,
    help_ru: str,
    *,
    group: str,
    min_value: str,
    max_value: str | None = None,
) -> SettingSpec:
    return SettingSpec(
        key="",
        group=group,
        kind="int",
        default=int(value),
        min_value=Decimal(min_value),
        max_value=Decimal(max_value) if max_value is not None else None,
        title_ru=title,
        help_ru=help_ru,
    )


def _bool(value: bool, title: str, help_ru: str, *, group: str) -> SettingSpec:
    return SettingSpec(
        key="",
        group=group,
        kind="bool",
        default=value,
        min_value=None,
        max_value=None,
        title_ru=title,
        help_ru=help_ru,
    )


def _spec(key: str, template: SettingSpec) -> SettingSpec:
    return SettingSpec(
        key=key,
        group=template.group,
        kind=template.kind,
        default=template.default,
        min_value=template.min_value,
        max_value=template.max_value,
        title_ru=template.title_ru,
        help_ru=template.help_ru,
        requires_finance_owner=template.requires_finance_owner,
    )


def _cashback_grid_default() -> list[dict[str, object]]:
    return [
        {"min_wager_rub": 0, "percent": 2},
        {"min_wager_rub": 50000, "percent": 5},
        {"min_wager_rub": 100000, "percent": 7},
        {"min_wager_rub": 200000, "percent": 10},
        {"min_wager_rub": 500000, "percent": 15},
    ]


def _commission_grid_default() -> list[dict[str, object]]:
    return [
        {"min_wager_rub": 0, "active_rate": 15, "complete_rate": 5},
        {"min_wager_rub": 50000, "active_rate": 12, "complete_rate": 4},
        {"min_wager_rub": 100000, "active_rate": 10, "complete_rate": 3},
        {"min_wager_rub": 200000, "active_rate": 8, "complete_rate": 2.5},
    ]


def _level_reach_bonuses_default() -> list[dict[str, object]]:
    return [
        {"min_wager_rub": 50000, "bonus_rub": 500},
        {"min_wager_rub": 100000, "bonus_rub": 1000},
        {"min_wager_rub": 200000, "bonus_rub": 2500},
        {"min_wager_rub": 500000, "bonus_rub": 5000},
    ]


def _build_registry() -> dict[str, SettingSpec]:
    items = (
        _spec(
            "commission_rate",
            _percent("15", "Комиссия", "Доля казино с банка раунда. Базовый профиль совпадает с активным отыгрышем."),
        ),
        _spec(
            "commission_rate_wagering_active",
            _percent("15", "Комиссия при активном отыгрыше", "Ставка комиссии, пока депозит не отыгран."),
        ),
        _spec(
            "commission_rate_wagering_complete",
            _percent("5", "Комиссия после отыгрыша", "Ставка комиссии после выполнения условия отыгрыша."),
        ),
        _spec(
            "wagering_percent",
            _percent(
                "21",
                "Отыгрыш",
                "Какой процент депозита казино должно получить комиссией с игрока, прежде чем вывод откроется. Не оборот ставок: при комиссии 15% и 21% отыгрыша с 1000 ₽ это 210 ₽ плюса ≈ 1400 ₽ ставок.",
                group="wagering",
            ),
        ),
        _spec(
            "creator_cut_percent",
            _percent("5", "Доля создателя", "Доля создателя комнаты из комиссии."),
        ),
        _spec(
            "referral_l1_percent",
            _percent("2", "Реферал L1", "Доля реферала первого уровня из комиссии."),
        ),
        _spec(
            "referral_l2_percent",
            _percent("2", "Реферал L2", "Доля реферала второго уровня из комиссии."),
        ),
        _spec(
            "creator_cut_percent_wagering_active",
            _percent("3", "Доля создателя при отыгрыше", "Доля создателя, пока депозит не отыгран."),
        ),
        _spec(
            "referral_l1_percent_wagering_active",
            _percent("2", "Реферал L1 при отыгрыше", "Доля L1, пока депозит не отыгран."),
        ),
        _spec(
            "referral_l2_percent_wagering_active",
            _percent("2", "Реферал L2 при отыгрыше", "Доля L2, пока депозит не отыгран."),
        ),
        _spec(
            "creator_cut_percent_wagering_complete",
            _percent("1", "Доля создателя после отыгрыша", "Доля создателя после выполнения отыгрыша."),
        ),
        _spec(
            "referral_l1_percent_wagering_complete",
            _percent("0.5", "Реферал L1 после отыгрыша", "Доля L1 после выполнения отыгрыша."),
        ),
        _spec(
            "referral_l2_percent_wagering_complete",
            _percent("0.5", "Реферал L2 после отыгрыша", "Доля L2 после выполнения отыгрыша."),
        ),
        _spec(
            "min_bet_rub",
            _amount("10", "Минимальная ставка", "Нижняя граница ставки в рублях."),
        ),
        _spec(
            "max_bet_rub",
            _amount("100000", "Максимальная ставка", "Верхняя граница ставки в рублях."),
        ),
        _spec(
            "min_withdrawal_rub",
            _amount("100", "Минимальный вывод", "Нижняя граница заявки на вывод в рублях."),
        ),
        SettingSpec(
            key="enabled_games",
            group="games",
            kind="bool_map",
            default={game: True for game in GAME_KEYS},
            min_value=None,
            max_value=None,
            title_ru="Включённые игры",
            help_ru="Булев словарь по известным играм. Неизвестный ключ игры отклоняется.",
        ),
        SettingSpec(
            key="cashback_volume_tiers",
            group="tiers",
            kind="json_grid",
            default=_cashback_grid_default(),
            min_value=None,
            max_value=None,
            title_ru="Сетка кешбека",
            help_ru="Тиры по недельному обороту ставок → процент от eligible-loss.",
        ),
        SettingSpec(
            key="commission_volume_tiers",
            group="tiers",
            kind="json_grid",
            default=_commission_grid_default(),
            min_value=None,
            max_value=None,
            title_ru="Сетка комиссии",
            help_ru="Тиры по недельному обороту → ставки комиссии до и после отыгрыша.",
        ),
        SettingSpec(
            key="level_reach_bonuses",
            group="tiers",
            kind="json_grid",
            default=_level_reach_bonuses_default(),
            min_value=None,
            max_value=None,
            title_ru="Бонус за уровень",
            help_ru="Разовый кредит на баланс, когда недельный оборот впервые пересекает порог уровня.",
        ),
        _spec(
            "max_profit_pct_per_round",
            _percent(
                "1.0",
                "Макс. выигрыш за раунд (% банка)",
                "Какой процент банка может выиграть один игрок за раунд. В расчёт ставки попадает в задаче 5.",
                group="bankroll",
            ),
        ),
        _spec(
            "max_profit_pct_per_round_all",
            _percent(
                "1.5",
                "Макс. выигрыш всех за раунд (% банка)",
                "Суммарный потолок выигрыша всех игроков за раунд, в процентах банка.",
                group="bankroll",
            ),
        ),
        _spec(
            "bankroll_floor_rub",
            _amount(
                "0",
                "Порог банкролла (₽)",
                "Ниже этого порога игры против казино отключаются. 0 = выключено.",
                group="bankroll",
                min_value="0",
            ),
        ),
        _spec(
            "liability_amount_rub",
            _amount(
                "0",
                "Потолок обязательств (₽)",
                "Из него выводится максимальная ставка. 0 = не ограничивает.",
                group="bankroll",
                min_value="0",
            ),
        ),
        SettingSpec(
            key="per_game_limits",
            group="limits",
            kind="json_object",
            default={},
            min_value=None,
            max_value=None,
            title_ru="Лимиты по играм",
            help_ru="Словарь {игра: {min, max}}. Пустое значение игры = глобальный min_bet/max_bet.",
        ),
        _spec(
            "bet_step_rub",
            _amount("10", "Шаг ставки (₽)", "Шаг кнопок ± на ставке.", group="limits", min_value="0.01"),
        ),
        _spec(
            "max_concurrent_games_per_player",
            _int(
                "10",
                "Макс. одновременных игр",
                "Сколько незавершённых игр может держать один игрок.",
                group="limits",
                min_value="1",
            ),
        ),
        SettingSpec(
            key="max_rounds_per_player_per_day",
            group="limits",
            kind="json_object",
            default={},
            min_value=None,
            max_value=None,
            title_ru="Раундов в день по играм",
            help_ru="Словарь {игра: N}. 0 или отсутствие ключа = без ограничения.",
        ),
        _spec(
            "pending_invite_ttl_minutes",
            _int(
                "10",
                "TTL приглашения (мин)",
                "Сколько живёт неподтверждённое приглашение.",
                group="limits",
                min_value="1",
                max_value="60",
            ),
        ),
        _spec(
            "move_timeout_minutes",
            _int(
                "120",
                "Таймаут хода (мин)",
                "Таймаут хода в карточных играх.",
                group="limits",
                min_value="1",
            ),
        ),
        _spec(
            "commission_cap_rub",
            _amount(
                "0",
                "Потолок комиссии (₽)",
                "Абсолютный потолок комиссии с раунда. 0 = без потолка, поведение как сейчас.",
                group="commission",
                min_value="0",
            ),
        ),
        _spec(
            "commission_min_rub",
            _amount(
                "0",
                "Минимальная комиссия (₽)",
                "Нижняя граница комиссии с раунда. 0 = без минимума.",
                group="commission",
                min_value="0",
            ),
        ),
        _spec(
            "deposit_limit_enabled",
            _bool(False, "Лимит депозита", "Игрок может задать лимит пополнений.", group="responsible"),
        ),
        _spec(
            "loss_limit_enabled",
            _bool(False, "Лимит проигрыша", "Игрок может задать лимит проигрыша.", group="responsible"),
        ),
        _spec(
            "wager_limit_enabled",
            _bool(False, "Лимит ставок", "Игрок может задать лимит оборота ставок.", group="responsible"),
        ),
        _spec(
            "session_limit_enabled",
            _bool(False, "Лимит сессии", "Игрок может задать лимит длительности сессии.", group="responsible"),
        ),
        _spec(
            "reality_check_default_minutes",
            _int(
                "60",
                "Напоминание (мин)",
                "Период reality check. 0 = выключено.",
                group="responsible",
                min_value="0",
            ),
        ),
        _spec(
            "self_exclusion_min_hours",
            _int(
                "24",
                "Мин. самоисключение (ч)",
                "Нижняя граница срока самоисключения.",
                group="responsible",
                min_value="1",
            ),
        ),
        _spec(
            "timeout_max_hours",
            _int(
                "72",
                "Макс. тайм-аут (ч)",
                "Верхняя граница короткого перерыва.",
                group="responsible",
                min_value="1",
            ),
        ),
        _spec(
            "limit_loosening_delay_hours",
            _int(
                "24",
                "Задержка ослабления лимита (ч)",
                "Ужесточение действует сразу, ослабление — только после этой паузы.",
                group="responsible",
                min_value="0",
            ),
        ),
        _spec(
            "withdrawal_auto_approve_max_rub",
            _amount(
                "0",
                "Автовывод до (₽)",
                "До этой суммы вывод уходит автоматом. 0 = всё вручную.",
                group="payouts",
                min_value="0",
            ),
        ),
        _spec(
            "withdrawal_manual_review_min_rub",
            _amount(
                "0",
                "Ручная проверка от (₽)",
                "От этой суммы обязательна ручная проверка. 0 = порог выключен.",
                group="payouts",
                min_value="0",
            ),
        ),
        _spec(
            "withdrawal_daily_limit_rub",
            _amount(
                "0",
                "Дневной лимит вывода (₽)",
                "Совокупный лимит вывода за сутки. 0 = без лимита.",
                group="payouts",
                min_value="0",
            ),
        ),
        _spec(
            "withdrawal_hourly_limit_rub",
            _amount(
                "0",
                "Часовой лимит вывода (₽)",
                "Совокупный лимит вывода за час. 0 = без лимита.",
                group="payouts",
                min_value="0",
            ),
        ),
        SettingSpec(
            key="provably_fair_enabled",
            group="fairness",
            kind="bool_map",
            default={game: False for game in GAME_KEYS},
            min_value=None,
            max_value=None,
            title_ru="Provably fair",
            help_ru="Включение provably fair по играм. По умолчанию выключено, поведение не меняется.",
        ),
        _spec(
            "seed_rotation_allowed",
            _bool(True, "Ротация сидов", "Игрок может ротировать пару сидов и раскрыть предыдущий серверный.", group="fairness"),
        ),
        _spec(
            "holdem_small_blind_rub",
            _amount("10", "Покер: малый блайнд (₽)", "Small blind на кэш-столе Hold'em.", group="games"),
        ),
        _spec(
            "holdem_big_blind_rub",
            _amount("20", "Покер: большой блайнд (₽)", "Big blind на кэш-столе Hold'em.", group="games"),
        ),
        _spec(
            "holdem_rake_percent",
            _percent("5", "Покер: рейк (%)", "Доля дома с банка руки Hold'em.", group="games"),
        ),
        _spec(
            "holdem_rake_cap_rub",
            _amount("50", "Покер: потолок рейка (₽)", "Максимальный рейк с одной руки. 0 = без потолка.", group="games", min_value="0"),
        ),
        _spec(
            "holdem_action_timeout_seconds",
            _int(
                "30",
                "Покер: таймаут хода (сек)",
                "Сколько секунд на ход. Просрочка = чек если бесплатно, иначе фолд.",
                group="games",
                min_value="5",
                max_value="300",
            ),
        ),
        _spec(
            "holdem_min_buyin_bb",
            _int("20", "Покер: мин. бай-ин (BB)", "Минимальный бай-ин в больших блайндах.", group="games", min_value="2"),
        ),
        _spec(
            "holdem_max_buyin_bb",
            _int("100", "Покер: макс. бай-ин (BB)", "Максимальный бай-ин в больших блайндах.", group="games", min_value="2"),
        ),
        _spec(
            "draughts_move_timeout_seconds",
            _int(
                "30",
                "Шашки: таймаут хода (сек)",
                "Сколько секунд на ход в русских шашках. Просрочка — сдача ставки. Рейк берётся как у холдема.",
                group="games",
                min_value="5",
                max_value="300",
            ),
        ),
        _spec(
            "jackpot_collect_seconds",
            _int("300", "Джекпот: сбор (сек)", "Окно сбора ставок до спина. Отсчёт с первой ставки.", group="games", min_value="30", max_value="3600"),
        ),
        _spec(
            "jackpot_max_players",
            _int("30", "Джекпот: макс. игроков", "При заполнении раунд крутится сразу.", group="games", min_value="2", max_value="100"),
        ),
        _spec(
            "jackpot_rake_percent",
            _percent("5", "Джекпот: рейк (%)", "Доля дома с банка. Победитель получает остаток.", group="games"),
        ),
        _spec(
            "roulette_table_collect_seconds",
            _int(
                "25",
                "Рулетка стол: сбор (сек)",
                "Окно ставок общего колеса против дома. Отсчёт с первой ставки. Пустой раунд не крутится.",
                group="games",
                min_value="5",
                max_value="120",
            ),
        ),
        _spec(
            "roulette_table_max_players",
            _int(
                "24",
                "Рулетка стол: макс. игроков",
                "При заполнении колесо крутится сразу. Каждый vs дом, не общий банк.",
                group="games",
                min_value="2",
                max_value="48",
            ),
        ),
        _spec(
            "bonus_wallet_enabled",
            _bool(
                True,
                "Бонусные фишки",
                "Отдельный кошелёк бонусных фишек: столы и лобби не смешиваются с реальными ставками.",
                group="games",
            ),
        ),
        _spec(
            "bonus_wallet_grant_chips",
            _amount(
                "1000",
                "Бонусные фишки: номинал",
                "Сколько фишек выдаётся при пополнении пустого бонусного кошелька.",
                group="games",
            ),
        ),
        _spec(
            "bonus_wallet_grant_cooldown_hours",
            _int(
                "24",
                "Бонусные фишки: пауза (ч)",
                "Минимальный интервал между самостоятельными пополнениями бонусного кошелька.",
                group="games",
                min_value="1",
                max_value="720",
            ),
        ),
        _spec(
            "clans_enabled",
            _bool(True, "Кланы", "Создание и вступление в команды игроков.", group="games"),
        ),
        _spec(
            "clan_max_members",
            _int(
                "20",
                "Кланы: макс. состав",
                "Сколько живых участников в одной команде.",
                group="games",
                min_value="2",
                max_value="50",
            ),
        ),
        _spec(
            "fixed_room_rake_percent",
            _percent("5", "Комнаты: рейк (%)", "Доля дома с банка комнаты 2–N. Ставка у всех одинаковая.", group="games"),
        ),
        _spec(
            "fixed_room_max_seats",
            _int("10", "Комнаты: макс. мест", "N мест. Розыгрыш только когда комната заполнена.", group="games", min_value="2", max_value="20"),
        ),
        _spec(
            "fixed_room_collect_seconds",
            _int("600", "Комнаты: набор (сек)", "Если N мест не набралось — возврат ставок.", group="games", min_value="30", max_value="3600"),
        ),
        _spec(
            "clan_war_rake_percent",
            _percent("5", "Война кланов: рейк (%)", "Доля дома с банка. Ставки с кошельков игроков, не с банка клана.", group="games"),
        ),
        _spec(
            "clan_war_max_fighters",
            _int("5", "Война кланов: бойцов со стороны", "Сколько человек с каждого клана. Деньги с личных балансов.", group="games", min_value="1", max_value="20"),
        ),
        _spec(
            "clan_war_collect_seconds",
            _int("1800", "Война кланов: набор (сек)", "Если составы не заполнились — возврат.", group="games", min_value="60", max_value="86400"),
        ),
    )
    return {item.key: item for item in items}


REGISTRY: dict[str, SettingSpec] = _build_registry()
PERCENT_KEYS: frozenset[str] = frozenset(
    spec.key for spec in REGISTRY.values() if spec.kind == "percent"
)
AMOUNT_KEYS: frozenset[str] = frozenset(
    spec.key for spec in REGISTRY.values() if spec.kind == "amount"
)
INT_KEYS: frozenset[str] = frozenset(
    spec.key for spec in REGISTRY.values() if spec.kind == "int"
)
BOOL_KEYS: frozenset[str] = frozenset(
    spec.key for spec in REGISTRY.values() if spec.kind == "bool"
)


def is_known_key(key: str) -> bool:
    return key in REGISTRY


def default_numeric(key: str) -> Decimal:
    spec = REGISTRY[key]
    if spec.kind not in {"percent", "amount"}:
        raise SettingValueError(f"{key} is not a numeric setting")
    return Decimal(spec.default)  # type: ignore[arg-type]


def canonical_defaults() -> dict[str, object]:
    out: dict[str, object] = {}
    for spec in REGISTRY.values():
        out[spec.key] = to_storage(spec.key, spec.default)
    return out


def to_storage(key: str, public_value: object) -> object:
    """Обёртка для JSONB: percent/amount/int/bool как раньше плюс новые виды."""
    spec = REGISTRY[key]
    if spec.kind == "percent":
        return {"percent": _json_number(_unwrap_numeric(spec, public_value))}
    if spec.kind == "amount":
        return {"amount": _json_number(_unwrap_numeric(spec, public_value))}
    if spec.kind == "int":
        return {"value": int(_unwrap_int(spec, public_value))}
    if spec.kind == "bool":
        return {"enabled": _unwrap_bool(spec, public_value)}
    if spec.kind in {"bool_map", "json_grid", "json_object"}:
        return validate_value(key, public_value)
    raise SettingValueError(f"{key} has unsupported kind {spec.kind}")


def _json_number(value: object) -> float:
    number = Decimal(str(value))
    as_float = float(number)
    return as_float


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise SettingValueError("numeric setting must be a number")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SettingValueError("numeric setting must be a number") from exc
    if not number.is_finite():
        raise SettingValueError("numeric setting must be finite")
    return number


def _unwrap_numeric(spec: SettingSpec, value: object) -> Decimal:
    if isinstance(value, Mapping):
        field = "percent" if spec.kind == "percent" else "amount"
        if field not in value:
            raise SettingValueError(f"{spec.key} must contain '{field}'")
        value = value[field]
    return _as_decimal(value)


def _unwrap_int(spec: SettingSpec, value: object) -> int:
    if isinstance(value, Mapping):
        if "value" not in value:
            raise SettingValueError(f"{spec.key} must contain 'value'")
        value = value["value"]
    if isinstance(value, bool) or value is None:
        raise SettingValueError(f"{spec.key} must be an integer")
    number = _as_decimal(value)
    if number != number.to_integral_value():
        raise SettingValueError(f"{spec.key} must be an integer")
    as_int = int(number)
    if spec.min_value is not None and number < spec.min_value:
        raise SettingValueError(f"{spec.key} is below minimum {spec.min_value}")
    if spec.max_value is not None and number > spec.max_value:
        raise SettingValueError(f"{spec.key} is above maximum {spec.max_value}")
    return as_int


def _unwrap_bool(spec: SettingSpec, value: object) -> bool:
    if isinstance(value, Mapping):
        if "enabled" not in value:
            raise SettingValueError(f"{spec.key} must contain 'enabled'")
        value = value["enabled"]
    if not isinstance(value, bool):
        raise SettingValueError(f"{spec.key} must be a boolean")
    return value


def _validate_per_game_limits(value: object) -> dict[str, dict[str, float]]:
    if not isinstance(value, Mapping):
        raise SettingValueError("per_game_limits must be an object")
    parsed: dict[str, dict[str, float]] = {}
    for game, bounds in value.items():
        if game not in GAME_KEYS:
            raise SettingValueError(f"per_game_limits contains unknown game: {game}")
        if not isinstance(bounds, Mapping):
            raise SettingValueError(f"per_game_limits.{game} must be an object")
        extra = [item for item in bounds if item not in {"min", "max"}]
        if extra:
            raise SettingValueError(f"per_game_limits.{game} has unknown field: {extra[0]}")
        row: dict[str, float] = {}
        for field in ("min", "max"):
            if field not in bounds or bounds[field] is None:
                continue
            number = _as_decimal(bounds[field])
            if number < 0:
                raise SettingValueError(f"per_game_limits.{game}.{field} must be >= 0")
            row[field] = _json_number(number)
        if "min" in row and "max" in row and row["min"] > row["max"]:
            raise SettingValueError(f"per_game_limits.{game} min cannot exceed max")
        if row:
            parsed[str(game)] = row
    return parsed


def _validate_max_rounds(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise SettingValueError("max_rounds_per_player_per_day must be an object")
    parsed: dict[str, int] = {}
    for game, raw in value.items():
        if game not in GAME_KEYS:
            raise SettingValueError(f"max_rounds_per_player_per_day contains unknown game: {game}")
        number = _as_decimal(raw)
        if number < 0 or number != number.to_integral_value():
            raise SettingValueError(f"max_rounds_per_player_per_day.{game} must be an integer >= 0")
        parsed[str(game)] = int(number)
    return parsed


def validate_value(key: str, value: object) -> object:
    if key not in REGISTRY:
        raise UnknownSettingKey(f"Unknown casino setting key: {key}")
    spec = REGISTRY[key]
    if spec.kind in {"percent", "amount"}:
        number = _unwrap_numeric(spec, value)
        if spec.min_value is not None and number < spec.min_value:
            raise SettingValueError(f"{key} is below minimum {spec.min_value}")
        if spec.max_value is not None and number > spec.max_value:
            raise SettingValueError(f"{key} is above maximum {spec.max_value}")
        return number
    if spec.kind == "int":
        return _unwrap_int(spec, value)
    if spec.kind == "bool":
        return _unwrap_bool(spec, value)
    if spec.kind == "bool_map":
        if not isinstance(value, Mapping):
            raise SettingValueError(f"{key} must be an object")
        unknown = [item for item in value if item not in GAME_KEYS]
        if unknown:
            raise SettingValueError(f"{key} contains unknown game: {unknown[0]}")
        for item, flag in value.items():
            if not isinstance(flag, bool):
                raise SettingValueError(f"{key}.{item} must be a boolean")
        return dict(value)
    if spec.kind == "json_grid":
        from casino_tier_config import parse_cashback_volume_tiers, parse_commission_volume_tiers

        if key == "cashback_volume_tiers":
            parse_cashback_volume_tiers(value)
            return value
        if key == "commission_volume_tiers":
            parse_commission_volume_tiers(value)
            return value
        if key == "level_reach_bonuses":
            from casino_level_bonus import bonuses_to_public, parse_level_reach_bonuses

            return bonuses_to_public(parse_level_reach_bonuses(value))
        raise SettingValueError(f"{key} has no grid parser")
    if spec.kind == "json_object":
        if key == "per_game_limits":
            return _validate_per_game_limits(value)
        if key == "max_rounds_per_player_per_day":
            return _validate_max_rounds(value)
        raise SettingValueError(f"{key} has no object parser")
    raise SettingValueError(f"{key} has unsupported kind {spec.kind}")


def clamp_commission_rub(
    commission: Decimal | int | float | str,
    *,
    cap_rub: Decimal | int | float | str,
    min_rub: Decimal | int | float | str,
) -> Decimal:
    """Наложить потолок и минимум. cap/min = 0 оставляют сумму как есть."""
    from casino_finance import money

    amount = money(commission)
    cap = money(cap_rub)
    floor = money(min_rub)
    if cap > 0:
        amount = min(amount, cap)
    if floor > 0:
        amount = max(amount, floor)
    return money(amount)


def effective_max_stake(
    *,
    max_bet_rub: Decimal | int | float | str,
    liability_amount_rub: Decimal | int | float | str,
    max_profit_pct_per_round: Decimal | int | float | str,
    bankroll_rub: Decimal | int | float | str,
    payout_multiplier: Decimal | int | float | str,
) -> Decimal:
    """min(глобальный max, обязательства / множитель, % банка / (множитель − 1)).

    Нулевые liability и bankroll не сжимают лимит — текущее поведение сохраняется.
    """
    from casino_finance import money

    candidates = [money(max_bet_rub)]
    liability = money(liability_amount_rub)
    try:
        multiplier = Decimal(str(payout_multiplier))
    except (InvalidOperation, ValueError) as exc:
        raise SettingValueError("payout_multiplier must be a number") from exc
    if not multiplier.is_finite() or multiplier <= 0:
        raise SettingValueError("payout_multiplier must be positive")
    if liability > 0:
        candidates.append(money(liability / multiplier))
    bankroll = money(bankroll_rub)
    profit_pct = _as_decimal(max_profit_pct_per_round)
    if bankroll > 0 and profit_pct > 0 and multiplier > 1:
        candidates.append(money(bankroll * profit_pct / Decimal("100") / (multiplier - 1)))
    return min(candidates)
