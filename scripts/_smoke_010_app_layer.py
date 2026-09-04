"""Real end-to-end smoke test for migration 010's application-layer fix:
exercises app.repository.create_repair_order() and the jobs.csv
cost-conversion logic in app.csv_import.py, running with SET ROLE
collision_app active (not a privileged role's default), the same way
scripts/verify_*.sql test the real grant boundary -- collision_app is
NOLOGIN by design (migrations/001), so it can never be connected to
directly; app.db.get_connection() always authenticates as whatever role
owns the connection string, and the real app is expected to SET ROLE
collision_app after connecting (or connect through a pooler/proxy that
does so) -- not modeled by this smoke script's env vars alone, so this
version issues `SET ROLE collision_app` explicitly on the cursor before
calling repository functions, then RESET ROLE before the connection
closes.

Usage: python scripts/_smoke_010_app_layer.py <PRIVILEGED_ENV_VAR>
"""
import csv
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor
from app.models import JobCategory, JobStatus, RepairOrder
from app import repository as repo
from app import csv_import


def main():
    privileged_env = sys.argv[1]

    # Prerequisites (person/customer/vehicle) need real platform.person
    # INSERT privilege -- collision_app never has that (migrations/001,
    # by design), so this part stays on the privileged role, same as
    # create_person_and_customer()'s own docstring says it must.
    with cursor(privileged_env, autocommit=False) as cur:
        customer = repo.create_person_and_customer(
            cur, "Smoke", "Test010", "smoke_test_010",
            email="smoke.test010@example.com",
        )
        vehicle = repo.get_or_create_vehicle(
            cur, customer.id, "smoke_test_010", vin="SMOKE010VIN0000001", make="Test", model="Ten", year=2021,
        )
        print(f"Prerequisites: customer.id={customer.id} vehicle.id={vehicle.id}")
        cur.connection.commit()

    # Now the real test: create_repair_order() called with SET ROLE
    # collision_app active -- proves the actual REVOKE/GRANT boundary
    # from migration 010, not just that raw SQL against staging works.
    with cursor(privileged_env, autocommit=False) as cur:
        cur.execute("SET ROLE collision_app")
        try:
            ro = RepairOrder(
                ro_number="RO-SMOKE-010", vehicle_id=vehicle.id, customer_id=customer.id,
                site_id=None, category=JobCategory.COLLISION, status=JobStatus.UNDECIDED,
                gross_revenue=Decimal("4000.00"), rent_utility_share=Decimal("100.00"),
            )
            site = repo.get_or_create_site(cur, "Smoke Test Site 010", "smoke_test_010")
            ro.site_id = site.id
            created = repo.create_repair_order(cur, ro, "smoke_test_010")
            print(f"create_repair_order() succeeded as collision_app: id={created.id}, "
                  f"labor_cost={created.labor_cost}, direct_ro_costs={created.direct_ro_costs}")
            assert created.labor_cost == Decimal("0.00"), f"expected 0.00, got {created.labor_cost}"
            assert created.direct_ro_costs == Decimal("0.00"), f"expected 0.00, got {created.direct_ro_costs}"
            print("  MATCHES expected: new job starts at 0/0 (DEFAULT, not app-supplied)")

            from app.models import CostEntry, CostCategory
            repo.add_cost_entry(
                cur,
                CostEntry(job_id=created.id, category=CostCategory.LABOR, amount=Decimal("250.00"),
                          description="smoke test labor"),
                "smoke_test_010",
            )
            refreshed = repo.get_repair_order_by_ro_number(cur, "RO-SMOKE-010")
            print(f"After cost_entry insert: labor_cost={refreshed.labor_cost}")
            assert refreshed.labor_cost == Decimal("250.00"), f"expected 250.00, got {refreshed.labor_cost}"
            print("  MATCHES expected: trigger derived labor_cost from the real cost_entry insert")

            # Confirm the guarantee itself: even WITH SET ROLE collision_app
            # active, a direct UPDATE of labor_cost must still fail.
            try:
                cur.execute("UPDATE collision.job SET labor_cost = 999999.99 WHERE id = %s", (created.id,))
                raise AssertionError("collision_app was able to directly UPDATE labor_cost -- REVOKE not enforced")
            except Exception as e:
                if "insufficient_privilege" not in str(type(e).__name__).lower() and "permission denied" not in str(e).lower():
                    raise
                print("  CONFIRMED: direct UPDATE of labor_cost as collision_app still rejected (permission denied)")
                cur.connection.rollback()
                cur.execute("SET ROLE collision_app")  # rollback reset the role too; re-set for cleanliness
        finally:
            cur.execute("RESET ROLE")
        cur.connection.rollback()
        print("Rolled back -- no test data persisted.")

    # CSV cost-conversion path: write a temp jobs.csv with a non-zero
    # labor_cost/direct_ro_costs and confirm import_jobs_csv() converts
    # them into cost_entry rows instead of silently dropping them.
    # This runs the same way the real CSV CLI does (privileged
    # connection, per csv_import.py's own module docstring), with
    # SET ROLE collision_app active for the actual job/cost_entry writes.
    with cursor(privileged_env, autocommit=False) as cur:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ro_number", "customer_email", "vin", "site", "category", "status",
                "gross_revenue", "direct_ro_costs", "labor_cost", "rent_utility_share",
            ])
            writer.writerow([
                "RO-SMOKE-010-CSV", "smoke.test010@example.com", "SMOKE010VIN0000001",
                "Smoke Test Site 010 CSV", "collision", "undecided",
                "3000.00", "175.00", "425.00", "50.00",
            ])
            csv_path = f.name

        cur.execute("SET ROLE collision_app")
        report = csv_import.import_jobs_csv(cur, csv_path, "smoke_test_010", dry_run=False)
        cur.execute("RESET ROLE")
        print(report.summary())
        assert report.ok(), f"import had errors: {report.errors}"

        ro = repo.get_repair_order_by_ro_number(cur, "RO-SMOKE-010-CSV")
        print(f"CSV-imported job: labor_cost={ro.labor_cost}, direct_ro_costs={ro.direct_ro_costs}")
        assert ro.labor_cost == Decimal("425.00"), f"expected 425.00 (converted from CSV), got {ro.labor_cost}"
        assert ro.direct_ro_costs == Decimal("175.00"), f"expected 175.00 (converted from CSV), got {ro.direct_ro_costs}"
        print("  MATCHES expected: jobs.csv flat totals were converted into cost_entry rows, "
              "trigger derived the job's totals from them -- NOT silently dropped")

        entries = repo.list_cost_entries(cur, "RO-SMOKE-010-CSV")
        print(f"cost_entry rows created: {len(entries)}")
        for e in entries:
            print(f"  {e.category.value}: {e.amount} ({e.description})")
        assert len(entries) == 2, f"expected 2 cost_entry rows (labor + other), got {len(entries)}"

        Path(csv_path).unlink()
        cur.connection.rollback()
        print("Rolled back -- no test data persisted.")

    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
