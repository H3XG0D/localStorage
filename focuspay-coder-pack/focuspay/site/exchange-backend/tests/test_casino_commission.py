from decimal import Decimal

import pytest

from casino_finance import (
    CasinoSettings,
    allocate_commission,
    calculate_equal_stake_settlement,
    calculate_house_settlement,
    commission_share_profile,
    commission_shares_for_rate,
    scale_stake_share_percents,
)


def _settings() -> CasinoSettings:
    return CasinoSettings(
        commission_rate=Decimal("15"),
        commission_rate_wagering_active=Decimal("15"),
        commission_rate_wagering_complete=Decimal("5"),
        wagering_percent=Decimal("21"),
        creator_cut_percent=Decimal("5"),
        referral_l1_percent=Decimal("2"),
        referral_l2_percent=Decimal("2"),
        creator_cut_percent_wagering_active=Decimal("3"),
        referral_l1_percent_wagering_active=Decimal("2"),
        referral_l2_percent_wagering_active=Decimal("2"),
        creator_cut_percent_wagering_complete=Decimal("1"),
        referral_l1_percent_wagering_complete=Decimal("0.5"),
        referral_l2_percent_wagering_complete=Decimal("0.5"),
        min_bet_rub=Decimal("10"),
        max_bet_rub=Decimal("100000"),
        min_withdrawal_rub=Decimal("100"),
        enabled_games={},
    )


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("15"), (Decimal("3"), Decimal("2"), Decimal("2"))),
        (Decimal("5"), (Decimal("1"), Decimal("0.5"), Decimal("0.5"))),
    ],
)
def test_wagering_profiles_match_configured_distribution(rate, expected):
    assert commission_share_profile(_settings(), rate) == expected


def test_explicit_profile_name_overrides_rate_ambiguity():
    settings = _settings()
    assert commission_share_profile(
        settings,
        Decimal("15"),
        profile="wagering_complete",
    ) == (
        settings.creator_cut_percent_wagering_complete,
        settings.referral_l1_percent_wagering_complete,
        settings.referral_l2_percent_wagering_complete,
    )


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("15"), (Decimal("3.00"), Decimal("2.00"), Decimal("2.00"), Decimal("8.00"))),
        (Decimal("5"), (Decimal("1.00"), Decimal("0.50"), Decimal("0.50"), Decimal("3.00"))),
    ],
)
def test_wagering_distribution_uses_full_actual_commission(rate, expected):
    creator, referral_l1, referral_l2 = commission_share_profile(_settings(), rate)
    allocations = allocate_commission(
        Decimal("100"),
        commission_rate=rate,
        creator_percent=creator,
        referral_l1_percent=referral_l1,
        referral_l2_percent=referral_l2,
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
    )
    assert (allocations.creator, allocations.referral_l1, allocations.referral_l2, allocations.owner) == expected
    assert allocations.total == rate


@pytest.mark.parametrize(
    ("rate", "payout", "commission"),
    [
        (Decimal("15"), Decimal("185.00"), Decimal("15.00")),
        (Decimal("5"), Decimal("195.00"), Decimal("5.00")),
    ],
)
def test_house_game_withholds_commission_from_winnings_only(rate, payout, commission):
    settlement = calculate_house_settlement(Decimal("100"), Decimal("2"), rate)
    assert settlement.payout == payout
    assert settlement.commission == commission


    result = calculate_equal_stake_settlement(
        stake_each=Decimal("100"),
        commission_rate=Decimal("15"),
    )

    assert result.losing_stake == Decimal("100.00")
    assert result.pot == Decimal("200.00")
    assert result.commission == Decimal("15.00")
    assert result.payout == Decimal("185.00")


def test_commission_allocations_are_absolute_percentages_of_losing_stake():
    allocations = allocate_commission(
        Decimal("100.00"),
        commission_rate=Decimal("15"),
        creator_percent=Decimal("5"),
        referral_l1_percent=Decimal("2"),
        referral_l2_percent=Decimal("2"),
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
    )

    assert allocations.creator == Decimal("5.00")
    assert allocations.referral_l1 == Decimal("2.00")
    assert allocations.referral_l2 == Decimal("2.00")
    assert allocations.owner == Decimal("6.00")
    assert allocations.total == Decimal("15.00")


def test_missing_referrers_transfer_their_stake_shares_to_owner():
    allocations = allocate_commission(
        Decimal("100.00"),
        commission_rate=Decimal("15"),
        creator_percent=Decimal("5"),
        referral_l1_percent=Decimal("2"),
        referral_l2_percent=Decimal("2"),
        has_creator=True,
        has_referral_l1=False,
        has_referral_l2=False,
    )

    assert allocations.creator == Decimal("5.00")
    assert allocations.referral_l1 == Decimal("0.00")
    assert allocations.referral_l2 == Decimal("0.00")
    assert allocations.owner == Decimal("10.00")
    assert allocations.total == Decimal("15.00")


def test_recipient_shares_cannot_exceed_commission_rate():
    with pytest.raises(ValueError, match="cannot exceed"):
        allocate_commission(
            Decimal("100.00"),
            commission_rate=Decimal("15"),
            creator_percent=Decimal("12"),
            referral_l1_percent=Decimal("2"),
            referral_l2_percent=Decimal("2"),
            has_creator=True,
            has_referral_l1=True,
            has_referral_l2=True,
        )


def test_rounding_never_allocates_more_or_less_than_commission():
    allocations = allocate_commission(
        Decimal("0.02"),
        commission_rate=Decimal("100"),
        creator_percent=Decimal("34"),
        referral_l1_percent=Decimal("33"),
        referral_l2_percent=Decimal("33"),
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
    )

    assert allocations.creator == Decimal("0.01")
    assert allocations.referral_l1 == Decimal("0.01")
    assert allocations.referral_l2 == Decimal("0.00")
    assert allocations.owner == Decimal("0.00")
    assert allocations.total == Decimal("0.02")


@pytest.mark.parametrize("rate", [Decimal("-0.01"), Decimal("100.01")])
def test_whole_percent_must_be_between_zero_and_one_hundred(rate):
    with pytest.raises(ValueError, match="between 0 and 100"):
        calculate_equal_stake_settlement(Decimal("100"), rate)


def test_zero_commission_cap_does_not_change_pvp_or_house_settlement():
    pvp = calculate_equal_stake_settlement(Decimal("100"), Decimal("15"))
    pvp_capped = calculate_equal_stake_settlement(
        Decimal("100"), Decimal("15"), commission_cap_rub=0, commission_min_rub=0
    )
    assert pvp == pvp_capped
    house = calculate_house_settlement(Decimal("100"), Decimal("2"), Decimal("15"))
    house_capped = calculate_house_settlement(
        Decimal("100"), Decimal("2"), Decimal("15"), commission_cap_rub=0, commission_min_rub=0
    )
    assert house == house_capped
    uncapped = allocate_commission(
        Decimal("100.00"),
        commission_rate=Decimal("15"),
        creator_percent=Decimal("5"),
        referral_l1_percent=Decimal("2"),
        referral_l2_percent=Decimal("2"),
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
        commission_cap_rub=0,
        commission_min_rub=0,
    )
    assert uncapped.total == Decimal("15.00")


def test_commission_cap_clamps_pvp_house_and_allocation():
    pvp = calculate_equal_stake_settlement(
        Decimal("100"), Decimal("15"), commission_cap_rub=10, commission_min_rub=0
    )
    assert pvp.commission == Decimal("10.00")
    assert pvp.payout == Decimal("190.00")
    house = calculate_house_settlement(
        Decimal("100"), Decimal("2"), Decimal("15"), commission_cap_rub=10, commission_min_rub=0
    )
    assert house.commission == Decimal("10.00")
    assert house.payout == Decimal("190.00")
    allocations = allocate_commission(
        Decimal("100.00"),
        commission_rate=Decimal("15"),
        creator_percent=Decimal("5"),
        referral_l1_percent=Decimal("2"),
        referral_l2_percent=Decimal("2"),
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
        commission_cap_rub=10,
        commission_min_rub=0,
    )
    assert allocations.total == Decimal("10.00")
    assert allocations.creator == Decimal("5.00")
    assert allocations.referral_l1 == Decimal("2.00")
    assert allocations.referral_l2 == Decimal("2.00")
    assert allocations.owner == Decimal("1.00")


def test_scale_same_rate_leaves_shares_unchanged():
    assert scale_stake_share_percents(15, 15, 3, 2, 2) == (
        Decimal("3"),
        Decimal("2"),
        Decimal("2"),
    )


def test_scale_15_to_10_is_two_thirds():
    creator, referral_l1, referral_l2 = scale_stake_share_percents(10, 15, 3, 2, 2)
    assert creator == Decimal("2")
    assert referral_l1 == Decimal("2") * Decimal("10") / Decimal("15")
    assert referral_l2 == Decimal("2") * Decimal("10") / Decimal("15")


def test_scale_above_base_grows_shares():
    creator, referral_l1, referral_l2 = scale_stake_share_percents(18, 15, 3, 2, 2)
    assert creator == Decimal("3.6")
    assert referral_l1 == Decimal("2.4")
    assert referral_l2 == Decimal("2.4")


def test_commission_shares_for_rate_scales_active_volume_tier():
    creator, referral_l1, referral_l2 = commission_shares_for_rate(
        _settings(),
        profile="wagering_active",
        commission_rate=Decimal("10"),
    )
    assert creator == Decimal("2")
    assert referral_l1 == Decimal("2") * Decimal("10") / Decimal("15")
    assert referral_l2 == Decimal("2") * Decimal("10") / Decimal("15")


def test_commission_shares_for_rate_scales_complete_volume_tier():
    creator, referral_l1, referral_l2 = commission_shares_for_rate(
        _settings(),
        profile="wagering_complete",
        commission_rate=Decimal("4"),
    )
    assert creator == Decimal("0.8")
    assert referral_l1 == Decimal("0.4")
    assert referral_l2 == Decimal("0.4")


def test_allocate_commission_uses_scaled_volume_tier_shares():
    creator, referral_l1, referral_l2 = commission_shares_for_rate(
        _settings(),
        profile="wagering_active",
        commission_rate=Decimal("10"),
    )
    allocations = allocate_commission(
        Decimal("100"),
        commission_rate=Decimal("10"),
        creator_percent=creator,
        referral_l1_percent=referral_l1,
        referral_l2_percent=referral_l2,
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
    )
    assert allocations.creator == Decimal("2.00")
    assert allocations.referral_l1 == Decimal("1.33")
    assert allocations.referral_l2 == Decimal("1.33")
    assert allocations.owner == Decimal("5.34")
    assert allocations.total == Decimal("10.00")


def test_allocate_complete_volume_tier_scales_on_100_rub():
    creator, referral_l1, referral_l2 = commission_shares_for_rate(
        _settings(),
        profile="wagering_complete",
        commission_rate=Decimal("4"),
    )
    allocations = allocate_commission(
        Decimal("100"),
        commission_rate=Decimal("4"),
        creator_percent=creator,
        referral_l1_percent=referral_l1,
        referral_l2_percent=referral_l2,
        has_creator=True,
        has_referral_l1=True,
        has_referral_l2=True,
    )
    assert allocations.creator == Decimal("0.80")
    assert allocations.referral_l1 == Decimal("0.40")
    assert allocations.referral_l2 == Decimal("0.40")
    assert allocations.owner == Decimal("2.40")
    assert allocations.total == Decimal("4.00")


def test_commission_min_raises_floor_without_changing_zero_min():
    raised = calculate_equal_stake_settlement(
        Decimal("100"), Decimal("5"), commission_cap_rub=0, commission_min_rub=8
    )
    assert raised.commission == Decimal("8.00")
    assert raised.payout == Decimal("192.00")
    same = calculate_equal_stake_settlement(
        Decimal("100"), Decimal("5"), commission_cap_rub=0, commission_min_rub=0
    )
    assert same.commission == Decimal("5.00")
