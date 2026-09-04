"""Tests for pdr_settlement.py — run with: python -m pytest test_pdr_settlement.py
or plain: python test_pdr_settlement.py

Exercises the actual Operating Agreement formula (Rev 70-30 v4) against
hand-computed expected values, not just "does it run."
"""

from decimal import Decimal

from pdr_settlement import (
    ROCategory,
    RepairOrder,
    compute_monthly_settlement,
    format_statement,
)


def _dec(s):
    return Decimal(s)


def test_collision_split_nets_labor_and_rent():
    # Collision RO: revenue 10000, direct costs 2000, labor 1500, rent 500
    # net profit = 10000 - 2000 - 1500 - 500 = 6000
    # CC 70% = 4200.00 ; PDR 30% = 1800.00
    ro = RepairOrder(
        ro_number="RO-1001",
        category=ROCategory.COLLISION,
        site="South",
        gross_revenue=_dec("10000.00"),
        direct_ro_costs=_dec("2000.00"),
        labor_cost=_dec("1500.00"),
        rent_utility_share=_dec("500.00"),
    )
    settlement = compute_monthly_settlement("2026-08", "South", [ro])
    c = settlement.categories[ROCategory.COLLISION]
    assert c.net_profit == _dec("6000.00")
    assert c.cc_share_amount == _dec("4200.00")
    assert c.pdr_share_amount == _dec("1800.00")
    assert c.cc_share_amount + c.pdr_share_amount == c.net_profit


def test_pdr_split_ignores_labor_and_rent():
    # PDR RO: revenue 3000, direct costs 500, labor/rent supplied but must
    # be IGNORED per the agreement (only Collision nets those).
    # net profit = 3000 - 500 = 2500
    # CC 5% = 125.00 ; PDR 95% = 2375.00
    ro = RepairOrder(
        ro_number="RO-2002",
        category=ROCategory.PDR,
        site="South",
        gross_revenue=_dec("3000.00"),
        direct_ro_costs=_dec("500.00"),
        labor_cost=_dec("9999.00"),       # must be ignored
        rent_utility_share=_dec("9999.00"),  # must be ignored
    )
    settlement = compute_monthly_settlement("2026-08", "South", [ro])
    c = settlement.categories[ROCategory.PDR]
    assert c.net_profit == _dec("2500.00")
    assert c.cc_share_amount == _dec("125.00")
    assert c.pdr_share_amount == _dec("2375.00")


def test_hail_split():
    # Hail RO: revenue 8000, direct costs 1000 -> net profit 7000
    # CC 40% = 2800.00 ; PDR 60% = 4200.00
    ro = RepairOrder(
        ro_number="RO-3003",
        category=ROCategory.HAIL,
        site="South",
        gross_revenue=_dec("8000.00"),
        direct_ro_costs=_dec("1000.00"),
    )
    settlement = compute_monthly_settlement("2026-08", "South", [ro])
    c = settlement.categories[ROCategory.HAIL]
    assert c.net_profit == _dec("7000.00")
    assert c.cc_share_amount == _dec("2800.00")
    assert c.pdr_share_amount == _dec("4200.00")


def test_multiple_ros_same_category_aggregate():
    ros = [
        RepairOrder("RO-A", ROCategory.PDR, "South", _dec("1000.00"), _dec("100.00")),
        RepairOrder("RO-B", ROCategory.PDR, "South", _dec("2000.00"), _dec("200.00")),
    ]
    settlement = compute_monthly_settlement("2026-08", "South", ros)
    c = settlement.categories[ROCategory.PDR]
    assert c.ro_numbers == ["RO-A", "RO-B"]
    assert c.gross_revenue == _dec("3000.00")
    assert c.net_profit == _dec("2700.00")  # (900)+(1800)


def test_rounding_drift_reconciles_to_cc_not_pdr():
    # net profit that doesn't split cleanly at 2 decimal places under 70/30
    # e.g. net profit = 100.01 -> 70% = 70.007 -> rounds to 70.01
    #                             30% = 30.003 -> rounds to 30.00
    # sum = 100.01, matches net profit exactly here, so pick a case that
    # actually drifts: net profit = 0.01 at 70/30
    # 70% of 0.01 = 0.007 -> rounds to 0.01 ; 30% of 0.01 = 0.003 -> rounds to 0.00
    # sum = 0.01 -- still fine. Try 33/... use PDR 5/95 with 0.01:
    # 5% of .01 = .0005 -> rounds to .00 ; 95% of .01 = .0095 -> rounds to .01
    # sum = 0.01, fine again with ROUND_HALF_UP on single cent inputs.
    # Construct a case with real drift: net profit = 0.03 at 70/30
    # 70% = 0.021 -> 0.02 ; 30% = 0.009 -> 0.01 ; sum = 0.03 (fine)
    # Drift arises when both round the same direction and away from the
    # true sum, e.g. net profit = 0.05 at 70/30:
    # 70% = 0.035 -> ROUND_HALF_UP -> 0.04 ; 30% = 0.015 -> 0.02 ; sum=0.06 != 0.05
    ro = RepairOrder(
        ro_number="RO-DRIFT",
        category=ROCategory.COLLISION,
        site="South",
        gross_revenue=_dec("0.05"),
        direct_ro_costs=_dec("0.00"),
    )
    settlement = compute_monthly_settlement("2026-08", "South", [ro])
    c = settlement.categories[ROCategory.COLLISION]
    assert c.net_profit == _dec("0.05")
    # total must exactly equal net profit after drift correction
    assert c.cc_share_amount + c.pdr_share_amount == c.net_profit
    # drift correction goes to CC's side per the module's documented policy
    assert c.pdr_share_amount == _dec("0.02")
    assert c.cc_share_amount == _dec("0.03")


def test_wrong_site_raises():
    ro = RepairOrder("RO-X", ROCategory.HAIL, "North", _dec("100"), _dec("0"))
    try:
        compute_monthly_settlement("2026-08", "South", [ro])
        assert False, "expected ValueError for mismatched site"
    except ValueError:
        pass


def test_format_statement_contains_totals():
    ro = RepairOrder("RO-9", ROCategory.HAIL, "South", _dec("1000"), _dec("0"))
    settlement = compute_monthly_settlement("2026-08", "South", [ro])
    text = format_statement(settlement)
    assert "DRAFT — HELD FOR REVIEW" in text
    assert "RO-9" in text
    assert "TOTAL OWED TO PDR CREW: $600.00" in text  # 60% of 1000


def _run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"PASS: {t.__name__}")
    print(f"\n{passed}/{len(tests)} tests passed")


if __name__ == "__main__":
    _run_all()
