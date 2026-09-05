"""Real HTTP-level smoke test for the NEW POST /jobs/{ro_number}/estimates
route (2026-09-06 cron cycle) -- runs a real uvicorn process against real
staging and hits it with real curl requests, not TestClient mocks (those
already exist in test_api.py). This is specifically to catch wiring bugs
mocks can't: pydantic request/response serialization, dict jsonb
round-tripping through psycopg2.extras.Json, and the actual HTTP status
codes a caller gets.

Lesson from the migration-010 incident (see WORKLOG.md 2026-09-06): a
script that only ever runs against disposable staging can hide an unsafe
assumption. This script has NO db.cursor()-style implicit commit reliance
for its OWN bookkeeping -- test data is created and deleted by explicit,
narrowly-targeted SQL matched on a unique marker RO number
('RO-SMOKE-HTTP-EST-001') and a unique VIN, never a blanket delete, and
every step is verified by an independent follow-up query, not just a
"no exception raised" assumption.

Usage:
  1. Set COLLISION_DB_ENV_VAR to an env var name holding a STAGING
     connection string (neondb_owner -- collision_app is NOLOGIN, same
     gap documented in app/db.py's header, unchanged this cycle).
  2. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  3. Run: python scripts/_smoke_http_create_estimate.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository as repo
from app.db import cursor as db_cursor
from app.models import JobCategory, JobStatus, RepairOrder

RO_NUMBER = "RO-SMOKE-HTTP-EST-001"
VIN = "SMOKEHTTPVIN000001"
PERSON_EMAIL = "smoke.http.estimate@example.com"
ACTOR = "_smoke_http_create_estimate"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_prereqs(env_var):
    """Create person/customer/vehicle/site/job via the SAME repository
    functions the rest of this app uses (create_customer_for_existing_person /
    get_or_create_vehicle / get_or_create_site / create_repair_order) rather
    than hand-rolled SQL -- avoids re-deriving every NOT NULL/default column
    (e.g. job.updated_by) a raw INSERT would need to match exactly.
    Committed (autocommit default off but exits the `with` cleanly) because
    the separate uvicorn worker process needs its own connection to see this
    data; cleaned up explicitly at the end by matching these exact
    identifiers, never a blanket delete."""
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
            "VALUES ('SmokeHTTP', 'Tester', %s, %s) RETURNING id",
            (PERSON_EMAIL, ACTOR),
        )
        person_id = cur.fetchone()["id"]
        customer = repo.create_customer_for_existing_person(cur, person_id, ACTOR)
        vehicle = repo.get_or_create_vehicle(
            cur, customer.id, ACTOR, vin=VIN, make="Honda", model="Civic", year=2019,
        )
        site = repo.get_or_create_site(cur, "Smoke HTTP Site", ACTOR)
        ro = repo.create_repair_order(
            cur,
            RepairOrder(
                ro_number=RO_NUMBER, vehicle_id=vehicle.id, customer_id=customer.id,
                site_id=site.id, category=JobCategory.COLLISION, status=JobStatus.ESTIMATE,
            ),
            ACTOR,
        )
    return person_id, customer.id, vehicle.id, ro.id


def cleanup(env_var, person_id, customer_id, vehicle_id, job_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("DELETE FROM collision.estimate WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM collision.job_event WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM collision.job WHERE id = %s AND ro_number = %s", (job_id, RO_NUMBER))
        cur.execute("DELETE FROM collision.vehicle WHERE id = %s AND vin = %s", (vehicle_id, VIN))
        cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        cur.execute("DELETE FROM platform.person WHERE id = %s AND email_normalized = %s", (person_id, PERSON_EMAIL))
        # Bug found + fixed 2026-09-08 cron cycle: this cleanup never deleted
        # the "Smoke HTTP Site" row setup_prereqs() creates via
        # get_or_create_site() -- left a permanent orphan row on shared
        # staging every time this script ran. Delete by exact name match,
        # only if nothing else references it (this script is the only
        # writer of this specific site name).
        cur.execute(
            "DELETE FROM collision.site WHERE name = 'Smoke HTTP Site' "
            "AND NOT EXISTS (SELECT 1 FROM collision.job WHERE site_id = collision.site.id)"
        )


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

        r = requests.post(
            f"{base_url}/jobs/{RO_NUMBER}/estimates",
            json={"content": {"total": "4500.00", "lines": ["bumper", "paint"]}, "actor": ACTOR},
            timeout=10,
        )
        check("POST estimate v1 status 200", r.status_code == 200, (r.status_code, r.text))
        check("POST estimate v1 version==1", r.status_code == 200 and r.json().get("version") == 1, r.text)

        r2 = requests.post(
            f"{base_url}/jobs/{RO_NUMBER}/estimates",
            json={"content": {"total": "4700.00", "lines": ["bumper", "paint", "sensor recalibration"]}, "actor": ACTOR},
            timeout=10,
        )
        check("POST estimate v2 status 200", r2.status_code == 200, (r2.status_code, r2.text))
        check("POST estimate v2 version==2", r2.status_code == 200 and r2.json().get("version") == 2, r2.text)

        r3 = requests.get(f"{base_url}/jobs/{RO_NUMBER}/estimates", timeout=10)
        check("GET estimates returns 2, ordered", r3.status_code == 200 and [e["version"] for e in r3.json()] == [1, 2], r3.text)

        r4 = requests.get(f"{base_url}/jobs/{RO_NUMBER}/estimates/latest", timeout=10)
        check("GET latest returns version 2", r4.status_code == 200 and r4.json().get("version") == 2, r4.text)
        check("GET latest content round-tripped correctly", r4.json().get("confirmed_content", {}).get("total") == "4700.00", r4.text)

        r5 = requests.post(
            f"{base_url}/jobs/RO-DOES-NOT-EXIST-ANYWHERE/estimates",
            json={"content": {"total": "1.00"}, "actor": ACTOR},
            timeout=10,
        )
        check("POST estimate unknown RO returns 404", r5.status_code == 404, (r5.status_code, r5.text))
    finally:
        if job_id is not None:
            cleanup(env_var, person_id, customer_id, vehicle_id, job_id)
            verify_clean(env_var)

    total_checks = len(FAILED) if FAILED else None
    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed (11/11)")


if __name__ == "__main__":
    main()
