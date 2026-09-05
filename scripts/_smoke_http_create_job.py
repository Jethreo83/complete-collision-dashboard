"""Real HTTP-level smoke test for the NEW POST /jobs route (2026-09-06/07
continuous-build cycle: closes the "no HTTP-reachable RO intake path"
gap -- every prior route in app/api.py only operated on a job that
already existed). Runs a real uvicorn process against real staging and
hits it with real `requests` calls, not TestClient mocks (test_api.py
already covers those) -- this catches wiring bugs mocks can't: pydantic
request/response serialization, the actual customer/vehicle/site
find-or-create chain running against real Postgres, and the real HTTP
status codes a caller gets.

Same cleanup discipline as every other smoke script in this directory
(see scripts/_smoke_http_create_estimate.py): test data created and
deleted by explicit, narrowly-targeted match on a unique marker RO
number / VIN / email, never a blanket delete, independently re-verified
by a follow-up query after cleanup.

Usage:
  1. Set an env var to a STAGING connection string (neondb_owner --
     collision_app is NOLOGIN, POST /jobs itself needs no privileged
     grant since create_customer_for_existing_person/get_or_create_vehicle/
     get_or_create_site/create_repair_order are all collision_app-safe;
     only the ONE-TIME platform.person row this script creates as its
     own test fixture needs a privileged connection, matching
     create_person_and_customer()'s documented gap).
  2. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  3. Run: python scripts/_smoke_http_create_job.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

RO_NUMBER = "RO-SMOKE-HTTP-CREATE-001"
VIN = "SMOKEHTTPCREATEVIN01"
PERSON_EMAIL = "smoke.http.createjob@example.com"
SITE_NAME = "Smoke HTTP Create Site"
ACTOR = "_smoke_http_create_job"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def create_fixture_person(env_var):
    """Only the platform.person row is a privileged-connection fixture
    here -- POST /jobs itself deliberately requires an already-existing
    person_id (see JobIntakeCreateRequest's docstring), so this mirrors
    what a real caller would already have (e.g. from an identity-service
    lookup) rather than testing something the route doesn't actually do."""
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
            "VALUES ('SmokeHTTPCreate', 'Tester', %s, %s) RETURNING id",
            (PERSON_EMAIL, ACTOR),
        )
        return cur.fetchone()["id"]


def cleanup(env_var, person_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "DELETE FROM collision.job_event WHERE job_id IN "
            "(SELECT id FROM collision.job WHERE ro_number = %s)",
            (RO_NUMBER,),
        )
        cur.execute("DELETE FROM collision.job WHERE ro_number = %s", (RO_NUMBER,))
        cur.execute("DELETE FROM collision.vehicle WHERE vin = %s", (VIN,))
        cur.execute(
            "DELETE FROM collision.customer WHERE person_id = %s",
            (person_id,),
        )
        cur.execute("DELETE FROM collision.site WHERE name = %s", (SITE_NAME,))
        if person_id is not None:
            cur.execute("DELETE FROM platform.person WHERE id = %s AND email_normalized = %s", (person_id, PERSON_EMAIL))


def verify_clean(env_var, person_id):
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

    person_id = None
    try:
        person_id = create_fixture_person(env_var)

        body = {
            "person_id": person_id, "site_name": SITE_NAME, "ro_number": RO_NUMBER,
            "category": "collision", "vin": VIN, "make": "Toyota", "model": "Camry",
            "year": 2021, "claim_number": "CLM-SMOKE-1", "insurer": "Smoke Insurance Co",
            "actor": ACTOR,
        }
        r = requests.post(f"{base_url}/jobs", json=body, timeout=10)
        check("POST /jobs status 200", r.status_code == 200, (r.status_code, r.text))
        created = r.json() if r.status_code == 200 else {}
        check("POST /jobs ro_number round-tripped", created.get("ro_number") == RO_NUMBER, created)
        check("POST /jobs status defaults to undecided", created.get("status") == "undecided", created)
        check("POST /jobs claim_number round-tripped", created.get("claim_number") == "CLM-SMOKE-1", created)

        # Independent follow-up GET confirms it's actually persisted, not
        # just echoed back in the POST response.
        r2 = requests.get(f"{base_url}/jobs/{RO_NUMBER}", timeout=10)
        check("GET /jobs after create returns 200", r2.status_code == 200, (r2.status_code, r2.text))
        check("GET /jobs after create matches", r2.json().get("ro_number") == RO_NUMBER, r2.json())

        # Idempotency guard: re-POSTing the same ro_number is a 400, not a
        # silent duplicate/overwrite.
        r3 = requests.post(f"{base_url}/jobs", json=body, timeout=10)
        check("POST /jobs duplicate ro_number returns 400", r3.status_code == 400, (r3.status_code, r3.text))

        # Bad category value.
        r4 = requests.post(
            f"{base_url}/jobs",
            json={**body, "ro_number": "RO-SMOKE-HTTP-CREATE-002", "category": "not_a_category"},
            timeout=10,
        )
        check("POST /jobs bad category returns 400", r4.status_code == 400, (r4.status_code, r4.text))

        # person_id that doesn't reference a real platform.person row.
        r5 = requests.post(
            f"{base_url}/jobs",
            json={**body, "ro_number": "RO-SMOKE-HTTP-CREATE-003", "person_id": 999999999},
            timeout=10,
        )
        check("POST /jobs nonexistent person_id returns 400", r5.status_code == 400, (r5.status_code, r5.text))
    finally:
        cleanup(env_var, person_id)
        verify_clean(env_var, person_id)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed (9/9)")


if __name__ == "__main__":
    main()
