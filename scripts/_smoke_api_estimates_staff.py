"""Real end-to-end smoke test for the NEW app/api.py routes added this
cron cycle (estimates + staff), run against real staging -- not mocks.
Exercises app.repository functions directly (same functions app/api.py's
new routes call) under SET ROLE collision_app, matching the real access
pattern (collision_app is NOLOGIN by design, per migrations/001).

Whole script runs in one transaction, explicitly rolled back at the end,
then independently re-queries staging afterward to confirm 0 rows
persisted -- same discipline as scripts/_smoke_staff_provisioning.py and
scripts/_smoke_010_app_layer.py.

Usage: python scripts/_smoke_api_estimates_staff.py <ENV_VAR_NAME>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository as repo
from app.db import cursor
from app.models import JobCategory, JobStatus, StaffRole

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def main():
    env_var = sys.argv[1]
    with cursor(env_var, autocommit=False) as cur:
        cur.execute("SET ROLE collision_app")

        # --- seed a person to provision as staff (find-or-create) ---
        cur.execute(
            "SELECT id FROM platform.person WHERE email_normalized = %s",
            ("smoke.staff.person@example.com",),
        )
        row = cur.fetchone()
        if row:
            person_id = row["id"]
        else:
            cur.execute("RESET ROLE")
            cur.execute(
                """
                INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
                VALUES ('Smoke', 'Tester', 'smoke.staff.person@example.com', '_smoke_api_estimates_staff')
                RETURNING id
                """
            )
            person_id = cur.fetchone()["id"]
            cur.execute("SET ROLE collision_app")

        # --- staff provisioning (same function app.api's POST /staff calls) ---
        staff = repo.provision_staff_user_for_existing_person(
            cur, person_id, StaffRole.RECEPTIONIST,
            "smoke.staff.route@completecollisions.com", "_smoke_api_estimates_staff",
        )
        check("provision_staff_user_for_existing_person", staff.id is not None and staff.active)

        fetched = repo.get_staff_user_by_google_email(cur, "smoke.staff.route@completecollisions.com")
        check("get_staff_user_by_google_email (GET /staff/{email})", fetched is not None and fetched.id == staff.id)

        cap = repo.get_staff_capability(cur, "smoke.staff.route@completecollisions.com")
        check("get_staff_capability active (GET /staff/{email}/capability)", cap == "full", cap)

        deactivated = repo.set_staff_user_active(cur, "smoke.staff.route@completecollisions.com", False, "_smoke_api_estimates_staff")
        check("set_staff_user_active(False) (POST /staff/{email}/active)", deactivated.active is False)

        cap_after = repo.get_staff_capability(cur, "smoke.staff.route@completecollisions.com")
        check("capability NULL after deactivate", cap_after is None, cap_after)

        # --- estimates (real job + real estimate versions), built via the
        # SAME repository functions app/api.py's existing routes already
        # use (create_customer_for_existing_person / create_vehicle /
        # get_or_create_site / create_repair_order) rather than hand-rolled
        # SQL, so this exercises the real, already-reviewed insert shape.
        customer = repo.create_customer_for_existing_person(cur, person_id, "_smoke_api_estimates_staff")
        vehicle = repo.get_or_create_vehicle(cur, customer.id, "_smoke_api_estimates_staff", vin="SMOKEVIN0000000001", make="Toyota", model="Camry", year=2020)
        site = repo.get_or_create_site(cur, "Smoke Site", "_smoke_api_estimates_staff")
        from app.models import RepairOrder
        ro = repo.create_repair_order(
            cur,
            RepairOrder(
                ro_number="RO-SMOKE-001", vehicle_id=vehicle.id, customer_id=customer.id,
                site_id=site.id, category=JobCategory.COLLISION, status=JobStatus.ESTIMATE,
            ),
            "_smoke_api_estimates_staff",
        )
        job_id = ro.id

        est1 = repo.create_manual_estimate(cur, job_id, {"total": "1000.00"}, "_smoke_api_estimates_staff")
        est2 = repo.create_manual_estimate(cur, job_id, {"total": "1200.00"}, "_smoke_api_estimates_staff")
        check("create_manual_estimate versions increment", est1.version == 1 and est2.version == 2)

        all_estimates = repo.get_estimates_for_job(cur, "RO-SMOKE-001")
        check("get_estimates_for_job (GET /jobs/{ro}/estimates)", len(all_estimates) == 2, len(all_estimates))
        check("get_estimates_for_job order", [e.version for e in all_estimates] == [1, 2])

        latest = repo.get_latest_estimate_for_job(cur, "RO-SMOKE-001")
        check("get_latest_estimate_for_job (GET /jobs/{ro}/estimates/latest)", latest.version == 2, latest.version)

        none_yet = repo.get_estimates_for_job(cur, "RO-DOES-NOT-EXIST-ANYWHERE")
        check("get_estimates_for_job unknown RO returns []", none_yet == [])

        cur.execute("RESET ROLE")
        cur.connection.rollback()

    # Independently re-verify: nothing persisted.
    with cursor(env_var, autocommit=False) as cur2:
        cur2.execute("SELECT count(*) AS n FROM collision.staff_user WHERE google_email = 'smoke.staff.route@completecollisions.com'")
        n_staff = cur2.fetchone()["n"]
        cur2.execute("SELECT count(*) AS n FROM collision.job WHERE ro_number = 'RO-SMOKE-001'")
        n_job = cur2.fetchone()["n"]
        check("rollback confirmed: 0 staff_user rows persisted", n_staff == 0, n_staff)
        check("rollback confirmed: 0 job rows persisted", n_job == 0, n_job)
        cur2.connection.rollback()

    total = 10
    passed = total - len(FAILED)
    print(f"\n{passed}/{total} checks passed" if not FAILED else f"\n{passed}/{len(FAILED)+passed} checks passed, FAILURES: {FAILED}")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
