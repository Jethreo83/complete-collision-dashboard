"""Real HTTP-level smoke test for the NEW POST /import/{kind} route
(2026-09-06 cron cycle, closing the "No CSV-upload HTTP route yet" gap
flagged in every prior WORKLOG's NOT DONE section). Runs a real uvicorn
process against real staging and hits it with real `requests` multipart
uploads -- specifically to catch what TestClient-with-mocked-IMPORTERS
tests in test_api.py structurally cannot: the actual tempfile spool path,
real UploadFile bytes round-tripping, and the real importer functions
actually writing (or dry-running) against real Postgres.

Same discipline as scripts/_smoke_http_patch_job_intake.py: test data
created/deleted via explicit, narrowly-targeted SQL matched on a unique
marker RO number/VIN/email, never a blanket delete; every step verified
by an independent follow-up query.

Usage:
  1. Set COLLISION_DB_ENV_VAR to an env var name holding a STAGING
     connection string (neondb_owner -- collision_app is NOLOGIN).
  2. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  3. Run: python scripts/_smoke_http_import_csv.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

PERSON_EMAIL = "smoke.http.import@example.com"
RO_NUMBER = "RO-SMOKE-HTTP-IMPORT-001"
VIN = "SMOKEHTTPIMPORTVIN01"
ACTOR = "_smoke_http_import_csv"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_person(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
            "VALUES ('SmokeHTTPImport', 'Tester', %s, %s) RETURNING id",
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
        cur.execute("DELETE FROM collision.cost_entry WHERE job_id IN "
                     "(SELECT id FROM collision.job WHERE ro_number = %s)", (RO_NUMBER,))
        cur.execute("DELETE FROM collision.job WHERE ro_number = %s", (RO_NUMBER,))
        cur.execute("DELETE FROM collision.vehicle WHERE vin = %s", (VIN,))
        cur.execute(
            "DELETE FROM collision.customer WHERE person_id = %s", (person_id,),
        )
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

    person_id = None
    try:
        person_id = setup_person(env_var)

        # 1. customers.csv dry-run: existing person (already have one from
        #    setup_person, no collision.customer row yet) -- should report
        #    created=1, dry_run=True, nothing actually written.
        customers_csv = f"first_name,last_name,email,phone,source\nSmoke,HTTPImport,{PERSON_EMAIL},555-0100,walk_in\n"
        r1 = requests.post(
            f"{base_url}/import/customers",
            files={"file": ("customers.csv", customers_csv.encode("utf-8"), "text/csv")},
            data={"actor": ACTOR},
            timeout=10,
        )
        check("POST /import/customers dry-run status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("dry-run reports dry_run=True", body1.get("dry_run") is True, body1)
        check("dry-run reports created=1", body1.get("created") == 1, body1)
        check("dry-run reports ok=True", body1.get("ok") is True, body1)

        with db_cursor(env_var, autocommit=False) as cur:
            cur.execute("SELECT * FROM collision.customer WHERE person_id = %s", (person_id,))
            check("dry-run actually wrote NOTHING (0 customer rows)", cur.fetchone() is None)

        # 2. Same file, commit=true -- should actually create the customer row.
        r2 = requests.post(
            f"{base_url}/import/customers",
            files={"file": ("customers.csv", customers_csv.encode("utf-8"), "text/csv")},
            data={"actor": ACTOR, "commit": "true"},
            timeout=10,
        )
        check("POST /import/customers commit status 200", r2.status_code == 200, (r2.status_code, r2.text))
        body2 = r2.json() if r2.status_code == 200 else {}
        check("commit reports dry_run=False", body2.get("dry_run") is False, body2)
        check("commit reports created=1", body2.get("created") == 1, body2)

        with db_cursor(env_var, autocommit=False) as cur:
            cur.execute("SELECT id FROM collision.customer WHERE person_id = %s", (person_id,))
            customer_row = cur.fetchone()
        check("commit actually created 1 customer row", customer_row is not None, customer_row)

        # 3. Re-running the SAME commit=true import must be idempotent
        #    (skip, not duplicate) -- this is the whole point of the
        #    natural-key idempotency the module docstring promises.
        r3 = requests.post(
            f"{base_url}/import/customers",
            files={"file": ("customers.csv", customers_csv.encode("utf-8"), "text/csv")},
            data={"actor": ACTOR, "commit": "true"},
            timeout=10,
        )
        body3 = r3.json() if r3.status_code == 200 else {}
        check("re-import is idempotent: skipped=1, created=0", body3.get("skipped") == 1 and body3.get("created") == 0, body3)

        # 4. vehicles.csv commit -- links a vehicle to the now-existing customer.
        vehicles_csv = f"customer_email,vin,make,model,year\n{PERSON_EMAIL},{VIN},Honda,Civic,2020\n"
        r4 = requests.post(
            f"{base_url}/import/vehicles",
            files={"file": ("vehicles.csv", vehicles_csv.encode("utf-8"), "text/csv")},
            data={"actor": ACTOR, "commit": "true"},
            timeout=10,
        )
        body4 = r4.json() if r4.status_code == 200 else {}
        check("POST /import/vehicles commit status 200", r4.status_code == 200, (r4.status_code, r4.text))
        check("vehicles commit created=1", body4.get("created") == 1, body4)

        # 5. jobs.csv commit -- creates the RO, exercising the full
        #    email->customer->vehicle->site chain through the real route.
        jobs_csv = (
            f"ro_number,customer_email,vin,site,category,status\n"
            f"{RO_NUMBER},{PERSON_EMAIL},{VIN},Smoke HTTP Import Site,collision,undecided\n"
        )
        r5 = requests.post(
            f"{base_url}/import/jobs",
            files={"file": ("jobs.csv", jobs_csv.encode("utf-8"), "text/csv")},
            data={"actor": ACTOR, "commit": "true"},
            timeout=10,
        )
        body5 = r5.json() if r5.status_code == 200 else {}
        check("POST /import/jobs commit status 200", r5.status_code == 200, (r5.status_code, r5.text))
        check("jobs commit created=1, ok=True", body5.get("created") == 1 and body5.get("ok") is True, body5)

        r5b = requests.get(f"{base_url}/jobs/{RO_NUMBER}", timeout=10)
        check("GET job created via CSV import found, status 200", r5b.status_code == 200, (r5b.status_code, r5b.text))

        # 6. Unknown kind -> 400, real HTTP round trip (not just TestClient).
        r6 = requests.post(
            f"{base_url}/import/not_a_real_kind",
            files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
            data={"actor": ACTOR},
            timeout=10,
        )
        check("POST /import/<bad kind> returns 400", r6.status_code == 400, (r6.status_code, r6.text))

    finally:
        if person_id is not None:
            cleanup(env_var, person_id)
            verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed")


if __name__ == "__main__":
    main()
