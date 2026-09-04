"""Ad-hoc example run of the settlement calculator against realistic
numbers, for eyeballing statement formatting. Not a test file (no
assertions) — see test_pdr_settlement.py for the actual test suite."""

from decimal import Decimal

from pdr_settlement import (
    ROCategory,
    RepairOrder,
    compute_monthly_settlement,
    format_statement,
)

ros = [
    RepairOrder("RO-1201", ROCategory.COLLISION, "South", Decimal("12500.00"), Decimal("3200.00"), Decimal("1800.00"), Decimal("400.00")),
    RepairOrder("RO-1202", ROCategory.COLLISION, "South", Decimal("8000.00"), Decimal("2100.00"), Decimal("1200.00"), Decimal("400.00")),
    RepairOrder("RO-1210", ROCategory.PDR, "South", Decimal("2200.00"), Decimal("350.00")),
    RepairOrder("RO-1215", ROCategory.HAIL, "South", Decimal("15000.00"), Decimal("4000.00")),
]

settlement = compute_monthly_settlement("2026-08", "South", ros)
print(format_statement(settlement))
