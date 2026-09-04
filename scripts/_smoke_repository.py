"""One-off script exercising app.repository's status-transition and
cost-reconciliation functions against real staging data created by the
CSV import pipeline test. Prints results for inspection — not a
pytest-style test, just a real-execution smoke check.

Usage: python scripts/_smoke_repository.py <ENV_VAR_NAME>
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor
from app.models import JobStatus
from app import repository as repo


def main():
    env_var = sys.argv[1]
    with cursor(env_var, autocommit=False) as cur:
        print("--- before transition ---")
        ro = repo.get_repair_order_by_ro_number(cur, "RO-10001")
        print(f"RO-10001 status={ro.status.value}")

        print("--- transition estimate -> teardown ---")
        ro = repo.transition_job_status(cur, "RO-10001", JobStatus.TEARDOWN, "smoke_test", note="teardown started")
        print(f"RO-10001 status={ro.status.value}")

        print("--- job_event log ---")
        for ev in repo.list_job_events(cur, "RO-10001"):
            print(f"  {ev.from_status} -> {ev.to_status.value} by {ev.created_by} ({ev.note})")

        print("--- illegal backward transition (should raise) ---")
        try:
            repo.transition_job_status(cur, "RO-10001", JobStatus.ESTIMATE, "smoke_test")
            print("  ERROR: should have raised!")
        except ValueError as e:
            print(f"  correctly raised: {e}")

        print("--- recalculate costs from cost_entry rows ---")
        ro = repo.recalculate_costs_from_entries(cur, "RO-10001", "smoke_test")
        print(f"  labor_cost={ro.labor_cost} direct_ro_costs={ro.direct_ro_costs}")
        expected_labor = Decimal("455.00")
        expected_direct = Decimal("410.50") + Decimal("175.00")
        assert ro.labor_cost == expected_labor, f"expected labor {expected_labor}, got {ro.labor_cost}"
        assert ro.direct_ro_costs == expected_direct, f"expected direct {expected_direct}, got {ro.direct_ro_costs}"
        print("  MATCHES expected values from cost_entries.csv")

        print("--- net_profit after recalculation ---")
        print(f"  net_profit = {ro.net_profit()}")
        expected_net = ro.gross_revenue - (ro.direct_ro_costs + ro.labor_cost + ro.rent_utility_share)
        assert ro.net_profit() == expected_net
        print(f"  MATCHES manual calc: {expected_net}")

    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
