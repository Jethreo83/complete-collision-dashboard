"""Real HTTP-level smoke test for the NEW GET /jobs route (2026-09-07
continuous-build cycle: closes the "no way to browse/list jobs" gap --
every prior job route required already knowing a specific ro_number).
Runs a real uvicorn process against real staging and hits it with real
`requests` calls, not TestClient mocks (test_api.py already covers the
mocked happy/error paths) -- this exercises the real SQL filter/limit/
offset logic in app.repository.list_repair_orders() against actual
Postgres rows, which mocks can't catch.

Same cleanup discipline as every other smoke script in this directory:
test data created and deleted by explicit, narrowly-targeted match on a
unique marker RO number / VIN / email / site name, never a blanket
delete, independently re-verified by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_list_jobs.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

RO_PREFIX = "RO-SMOKE-LISTJOBS-"
VIN_PREFIX = "SMOKELISTJOBSVIN"
PERSON_EMAIL = "smoke.http.listjobs@example.com"
SITE_NAME = "Smoke HTTP List Jobs Site"
ACTOR = "_smoke_http_list_jobs"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_fixtures(env_var):
    """Creates one person/customer/site, then 3 jobs with different
    category/status combos so filters have something real to
    distinguish. Returns (person_id, ro_numbers)."""
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
            "VALUES ('SmokeListJobs', 'Tester', %s, %s) RETURNING id",
            (PERSON_EMAIL, ACTOR),
        )
        person_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO collision.customer (person_id, source, created_by) "
            "VALUES (%s, 'walk_in', %s) RETURNING id",
            (person_id, ACTOR),
        )
        customer_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO collision.site (name, created_by) VALUES (%s, %s) RETURNING id",
            (SITE_NAME, ACTOR),
        )
        site_id = cur.fetchone()["id"]

        ro_numbers = []
        specs = [
            ("collision", "estimate"),
            ("pdr", "bodywork"),
            ("collision", "bodywork"),
        ]
        for i, (category, status) in enumerate(specs, start=1):
            ro_number = f"{RO_PREFIX}{i:03d}"
            vin = f"{VIN_PREFIX}{i:02d}"
            cur.execute(
                "INSERT INTO collision.vehicle (vin, customer_id, created_by) "
                "VALUES (%s, %s, %s) RETURNING id",
                (vin, customer_id, ACTOR),
            )
            vehicle_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO collision.job (
                    ro_number, vehicle_id, customer_id, site_id, category, status,
                    created_by, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (ro_number, vehicle_id, customer_id, site_id, category, status, ACTOR, ACTOR),
            )
            ro_numbers.append(ro_number)
    return person_id, customer_id, site_id, ro_numbers


def cleanup(env_var, person_id, customer_id, site_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "DELETE FROM collision.job_event WHERE job_id IN "
            "(SELECT id FROM collision.job WHERE ro_number LIKE %s)",
            (f"{RO_PREFIX}%",),
        )
        cur.execute("DELETE FROM collision.job WHERE ro_number LIKE %s", (f"{RO_PREFIX}%",))
        cur.execute("DELETE FROM collision.vehicle WHERE vin LIKE %s", (f"{VIN_PREFIX}%",))
        if customer_id is not None:
            cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        if site_id is not None:
            cur.execute("DELETE FROM collision.site WHERE id = %s", (site_id,))
        if person_id is not None:
            cur.execute(
                "DELETE FROM platform.person WHERE id = %s AND email_normalized = %s",
                (person_id, PERSON_EMAIL),
            )


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM collision.job WHERE ro_number LIKE %s", (f"{RO_PREFIX}%",))
        n_job = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM collision.vehicle WHERE vin LIKE %s", (f"{VIN_PREFIX}%",))
        n_veh = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM platform.person WHERE email_normalized = %s", (PERSON_EMAIL,))
        n_person = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM collision.site WHERE name = %s", (SITE_NAME,))
        n_site = cur.fetchone()["n"]
    check("cleanup confirmed: 0 job rows", n_job == 0, n_job)
    check("cleanup confirmed: 0 vehicle rows", n_veh == 0, n_veh)
    check("cleanup confirmed: 0 person rows", n_person == 0, n_person)
    check("cleanup confirmed: 0 site rows", n_site == 0, n_site)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_id = customer_id = site_id = None
    try:
        person_id, customer_id, site_id, ro_numbers = setup_fixtures(env_var)

        # Filter by site_id: should return exactly our 3 fixture rows,
        # never more (staging may have other tracks' data concurrently).
        r = requests.get(f"{base_url}/jobs", params={"site_id": site_id}, timeout=10)
        check("GET /jobs?site_id status 200", r.status_code == 200, (r.status_code, r.text))
        body = r.json() if r.status_code == 200 else []
        got_ro_numbers = {j["ro_number"] for j in body}
        check(
            "GET /jobs?site_id returns exactly our 3 fixture jobs",
            got_ro_numbers == set(ro_numbers),
            got_ro_numbers,
        )

        # Combine site_id + category=collision: should be 2 of the 3.
        r2 = requests.get(f"{base_url}/jobs", params={"site_id": site_id, "category": "collision"}, timeout=10)
        check("GET /jobs?site_id&category=collision status 200", r2.status_code == 200, (r2.status_code, r2.text))
        body2 = r2.json() if r2.status_code == 200 else []
        check(
            "GET /jobs?site_id&category=collision returns exactly 2",
            len(body2) == 2 and all(j["category"] == "collision" for j in body2),
            body2,
        )

        # Combine site_id + status=bodywork: should be 2 of the 3
        # (pdr/bodywork and collision/bodywork).
        r3 = requests.get(f"{base_url}/jobs", params={"site_id": site_id, "status": "bodywork"}, timeout=10)
        check("GET /jobs?site_id&status=bodywork status 200", r3.status_code == 200, (r3.status_code, r3.text))
        body3 = r3.json() if r3.status_code == 200 else []
        check(
            "GET /jobs?site_id&status=bodywork returns exactly 2",
            len(body3) == 2 and all(j["status"] == "bodywork" for j in body3),
            body3,
        )

        # limit/offset paging within our fixture set: order is
        # opened_at DESC, id DESC, so limit=1 offset=0 gets the
        # highest-id (most recently created) of the 3.
        r4 = requests.get(f"{base_url}/jobs", params={"site_id": site_id, "limit": 1, "offset": 0}, timeout=10)
        r5 = requests.get(f"{base_url}/jobs", params={"site_id": site_id, "limit": 1, "offset": 1}, timeout=10)
        page1 = r4.json() if r4.status_code == 200 else []
        page2 = r5.json() if r5.status_code == 200 else []
        check("GET /jobs limit=1 returns exactly 1", len(page1) == 1, page1)
        check(
            "GET /jobs limit=1 offset=1 returns a different row than offset=0",
            len(page2) == 1 and page2[0]["ro_number"] != page1[0]["ro_number"],
            (page1, page2),
        )

        # Bad status/category values return real 400s over HTTP.
        r6 = requests.get(f"{base_url}/jobs", params={"status": "not_a_real_status"}, timeout=10)
        check("GET /jobs bad status returns 400", r6.status_code == 400, (r6.status_code, r6.text))
        r7 = requests.get(f"{base_url}/jobs", params={"category": "not_a_real_category"}, timeout=10)
        check("GET /jobs bad category returns 400", r7.status_code == 400, (r7.status_code, r7.text))
    finally:
        cleanup(env_var, person_id, customer_id, site_id)
        verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed (11/11)")


if __name__ == "__main__":
    main()
