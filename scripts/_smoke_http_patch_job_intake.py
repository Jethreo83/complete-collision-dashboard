"""Real HTTP-level smoke test for the NEW PATCH /jobs/{ro_number} route
(2026-09-06 later cron cycle, closing "Next up" item #1 from the prior
cycle's WORKLOG). Runs a real uvicorn process against real staging and
hits it with real `requests` HTTP calls, not TestClient mocks (those
already exist in test_api.py) -- specifically to catch what mocks can't:
pydantic exclude_unset behavior actually round-tripping through real JSON
serialization, and the real UPDATE actually landing in Postgres.

Same discipline as scripts/_smoke_http_create_estimate.py: test data
created/deleted via explicit, narrowly-targeted SQL matched on a unique
marker RO number and VIN, never a blanket delete; every step verified by
an independent follow-up query.

Usage:
  1. Set COLLISION_DB_ENV_VAR to an env var name holding a STAGING
     connection string (neondb_owner -- collision_app is NOLOGIN, same
     unresolved gap documented in app/db.py's header).
  2. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  3. Run: python scripts/_smoke_http_patch_job_intake.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository as repo
from app.db import cursor as db_cursor
from app.models import JobCategory, JobStatus, RepairOrder

RO_NUMBER = "RO-SMOKE-HTTP-PATCH-001"
VIN = "SMOKEHTTPPATCHVIN01"
PERSON_EMAIL = "smoke.http.patch@example.com"
ACTOR = "_smoke_http_patch_job_intake"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_prereqs(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
            "VALUES ('SmokeHTTPPatch', 'Tester', %s, %s) RETURNING id",
            (PERSON_EMAIL, ACTOR),
        )
        person_id = cur.fetchone()["id"]
        customer = repo.create_customer_for_existing_person(cur, person_id, ACTOR)
        vehicle = repo.get_or_create_vehicle(
            cur, customer.id, ACTOR, vin=VIN, make="Toyota", model="Camry", year=2021,
        )
        site = repo.get_or_create_site(cur, "Smoke HTTP Patch Site", ACTOR)
        ro = repo.create_repair_order(
            cur,
            RepairOrder(
                ro_number=RO_NUMBER, vehicle_id=vehicle.id, customer_id=customer.id,
                site_id=site.id, category=JobCategory.COLLISION, status=JobStatus.ESTIMATE,
                claim_number="CLM-ORIGINAL", insurer="Original Insurer",
                adjuster_name="Original Adjuster", posture="paying",
            ),
            ACTOR,
        )
    return person_id, customer.id, vehicle.id, ro.id


def cleanup(env_var, person_id, customer_id, vehicle_id, job_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("DELETE FROM collision.job_event WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM collision.job WHERE id = %s AND ro_number = %s", (job_id, RO_NUMBER))
        cur.execute("DELETE FROM collision.vehicle WHERE id = %s AND vin = %s", (vehicle_id, VIN))
        cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        cur.execute("DELETE FROM platform.person WHERE id = %s AND email_normalized = %s", (person_id, PERSON_EMAIL))


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM collision.job WHERE ro_number = %s", (RO_NUMBER,))
        n_job = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM collision.vehicle WHERE vin = %s", (VIN,))
        n_veh = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM platform.person WHERE email_normalized = %s", (PERSON_EMAIL,))
        n_person = cur.fetchone()["n"]
    check("cleanup confirmed: 0 job rows", n_job == 0, n_job)
    check("cleanup confirmed: 0 vehicle rows", n_veh == 0, n_veh)
    check("cleanup confirmed: 0 person rows", n_person == 0, n_person)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_id = customer_id = vehicle_id = job_id = None
    try:
        person_id, customer_id, vehicle_id, job_id = setup_prereqs(env_var)

        # 1. Partial PATCH: only insurer supplied -- claim_number/adjuster_name/
        #    posture must survive UNCHANGED (this is the real risk exclude_unset
        #    guards against: a naive implementation would null them out).
        r1 = requests.patch(
            f"{base_url}/jobs/{RO_NUMBER}",
            json={"insurer": "New Insurer Co", "actor": ACTOR},
            timeout=10,
        )
        check("PATCH partial status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("PATCH partial: insurer updated", body1.get("insurer") == "New Insurer Co", body1)
        check("PATCH partial: claim_number unchanged", body1.get("claim_number") == "CLM-ORIGINAL", body1)
        check("PATCH partial: adjuster_name unchanged", body1.get("adjuster_name") == "Original Adjuster", body1)
        check("PATCH partial: posture unchanged", body1.get("posture") == "paying", body1)

        # 2. Explicit null: clear adjuster_name specifically, everything else
        #    (including the insurer just set above) must survive.
        r2 = requests.patch(
            f"{base_url}/jobs/{RO_NUMBER}",
            json={"adjuster_name": None, "actor": ACTOR},
            timeout=10,
        )
        check("PATCH null-clear status 200", r2.status_code == 200, (r2.status_code, r2.text))
        body2 = r2.json() if r2.status_code == 200 else {}
        check("PATCH null-clear: adjuster_name cleared", body2.get("adjuster_name") is None, body2)
        check("PATCH null-clear: insurer still New Insurer Co", body2.get("insurer") == "New Insurer Co", body2)
        check("PATCH null-clear: claim_number still unchanged", body2.get("claim_number") == "CLM-ORIGINAL", body2)

        # 3. Independent re-read via GET, confirming the PATCHes actually
        #    persisted to Postgres, not just reflected in the PATCH response.
        r3 = requests.get(f"{base_url}/jobs/{RO_NUMBER}", timeout=10)
        check("GET after PATCH status 200", r3.status_code == 200, (r3.status_code, r3.text))
        body3 = r3.json() if r3.status_code == 200 else {}
        check("GET after PATCH: insurer persisted", body3.get("insurer") == "New Insurer Co", body3)
        check("GET after PATCH: adjuster_name persisted as null", body3.get("adjuster_name") is None, body3)
        check("GET after PATCH: claim_number persisted unchanged", body3.get("claim_number") == "CLM-ORIGINAL", body3)
        check("GET after PATCH: posture persisted unchanged", body3.get("posture") == "paying", body3)

        # 4. Unknown RO -> 404, not a 500 or silent no-op.
        r4 = requests.patch(
            f"{base_url}/jobs/RO-DOES-NOT-EXIST-ANYWHERE",
            json={"claim_number": "CLM-X", "actor": ACTOR},
            timeout=10,
        )
        check("PATCH unknown RO returns 404", r4.status_code == 404, (r4.status_code, r4.text))
    finally:
        if job_id is not None:
            cleanup(env_var, person_id, customer_id, vehicle_id, job_id)
            verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed (14/14)")


if __name__ == "__main__":
    main()
