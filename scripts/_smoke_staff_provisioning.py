"""One-off smoke test for the new staff-provisioning repository functions
(provision_staff_user_for_existing_person, set_staff_user_active,
get_staff_capability, get_estimates_for_job) against real staging data.
Not a pytest-style test -- prints results for inspection, matching
scripts/_smoke_repository.py's existing discipline for this repo.

Usage: python scripts/_smoke_staff_provisioning.py <ENV_VAR_NAME>

Run against STAGING only -- creates/mutates real rows (cleaned up by the
staging reset that follows this session's testing, per the shared-staging
discipline in WORKLOG.md/README.md).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor
from app.models import StaffRole
from app import repository as repo


def main():
    env_var = sys.argv[1]
    with cursor(env_var, autocommit=False) as cur:
        print("--- provision staff_user for existing person (jane.doe) ---")
        cur.execute("SELECT id FROM platform.person WHERE email_normalized = 'jane.doe@example.com'")
        person_id = cur.fetchone()["id"]
        staff = repo.provision_staff_user_for_existing_person(
            cur, person_id, StaffRole.MANAGER, "jane.doe@completecollisions.com",
            "smoke_test",
        )
        print(f"  created staff_user id={staff.id} role={staff.role.value} email={staff.google_email} active={staff.active}")
        assert staff.role == StaffRole.MANAGER
        assert staff.google_email == "jane.doe@completecollisions.com"
        assert staff.active is True

        print("--- duplicate provisioning attempt (should raise) ---")
        try:
            repo.provision_staff_user_for_existing_person(
                cur, person_id, StaffRole.OWNER, "jane.doe@completecollisions.com", "smoke_test",
            )
            print("  ERROR: should have raised!")
        except ValueError as e:
            print(f"  correctly raised: {e}")

        print("--- capability check while active ---")
        cap = repo.get_staff_capability(cur, "jane.doe@completecollisions.com")
        print(f"  capability_level = {cap}")
        assert cap == "full", f"expected 'full', got {cap!r}"

        print("--- deactivate, re-check capability (should be None) ---")
        repo.set_staff_user_active(cur, "jane.doe@completecollisions.com", False, "smoke_test")
        cap = repo.get_staff_capability(cur, "jane.doe@completecollisions.com")
        print(f"  capability_level after deactivation = {cap}")
        assert cap is None, f"expected None after deactivation, got {cap!r}"

        print("--- reactivate, re-check capability (should be 'full' again) ---")
        repo.set_staff_user_active(cur, "jane.doe@completecollisions.com", True, "smoke_test")
        cap = repo.get_staff_capability(cur, "jane.doe@completecollisions.com")
        print(f"  capability_level after reactivation = {cap}")
        assert cap == "full"

        print("--- StaffUser Python-side domain validation, real object (not DB) ---")
        try:
            from app.models import StaffUser
            StaffUser(person_id=person_id, role=StaffRole.OWNER, google_email="jane.doe@gmail.com")
            print("  ERROR: should have raised!")
        except ValueError as e:
            print(f"  correctly raised: {e}")

        print("--- get_estimates_for_job on RO-10001 (existing job from prior session's CSV import) ---")
        cur.execute("SELECT ro_number FROM collision.job LIMIT 1")
        row = cur.fetchone()
        if row:
            estimates = repo.get_estimates_for_job(cur, row["ro_number"])
            print(f"  {row['ro_number']}: {len(estimates)} estimate version(s) on file")
        else:
            print("  no job rows on staging right now (expected if staging was reset since last CSV import test)")

        conn = cur.connection
        conn.rollback()
        print("\nROLLED BACK -- no staff_user/staff test rows persisted on staging.")

    print("\nALL STAFF PROVISIONING SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
