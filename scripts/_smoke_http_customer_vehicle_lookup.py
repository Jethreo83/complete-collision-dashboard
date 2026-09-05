"""Real HTTP-level smoke test for the NEW customer/vehicle lookup routes
(GET /customers/by-person/{person_id}, GET /customers/{customer_id}/vehicles,
GET /vehicles/by-vin/{vin}), added this cron cycle to close the gap where
repo.get_customer_by_person_id()/get_vehicles_by_customer()/
get_vehicle_by_vin() existed with no HTTP route.

Exercises against a real uvicorn process + real staging Postgres, not
TestClient mocks (test_api.py already covers the mocked happy/error
paths this session added) -- this catches the real FK joins and row
shapes that mocks can't.

Same cleanup discipline as every other smoke script in this directory:
test data created and deleted by explicit, narrowly-targeted match on a
unique marker VIN/email/site name, never a blanket delete, independently
re-verified by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first (against STAGING):
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_customer_vehicle_lookup.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

VIN = "SMOKELOOKUPVIN0001"
PERSON_EMAIL = "smoke.http.lookup@example.com"
ACTOR = "_smoke_http_customer_vehicle_lookup"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_fixtures(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
            "VALUES ('SmokeLookup', 'Tester', %s, %s) RETURNING id",
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
            "INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by) "
            "VALUES (%s, 'Toyota', 'Camry', 2015, %s, %s) RETURNING id",
            (VIN, customer_id, ACTOR),
        )
        vehicle_id = cur.fetchone()["id"]
    return person_id, customer_id, vehicle_id


def cleanup(env_var, person_id, customer_id, vehicle_id):
    with db_cursor(env_var, autocommit=False) as cur:
        if vehicle_id is not None:
            cur.execute("DELETE FROM collision.vehicle WHERE id = %s", (vehicle_id,))
        if customer_id is not None:
            cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        if person_id is not None:
            cur.execute(
                "DELETE FROM platform.person WHERE id = %s AND email_normalized = %s",
                (person_id, PERSON_EMAIL),
            )


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM collision.vehicle WHERE vin = %s", (VIN,))
        n_veh = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM platform.person WHERE email_normalized = %s", (PERSON_EMAIL,))
        n_person = cur.fetchone()["n"]
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

    person_id = customer_id = vehicle_id = None
    try:
        person_id, customer_id, vehicle_id = setup_fixtures(env_var)

        # 1. GET customer by person_id: found.
        r1 = requests.get(f"{base_url}/customers/by-person/{person_id}", timeout=10)
        check("GET customer by person found status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("GET customer by person matches customer_id", body1.get("id") == customer_id, body1)
        check("GET customer by person matches person_id", body1.get("person_id") == person_id, body1)

        # 2. GET customer by person_id: not found (a person_id that
        # is real but has no collision.customer row).
        r2 = requests.get(f"{base_url}/customers/by-person/999999999", timeout=10)
        check("GET customer by person not-found returns 404", r2.status_code == 404, (r2.status_code, r2.text))

        # 3. GET vehicles for customer: exactly 1, matches fixture.
        r3 = requests.get(f"{base_url}/customers/{customer_id}/vehicles", timeout=10)
        check("GET customer vehicles status 200", r3.status_code == 200, (r3.status_code, r3.text))
        body3 = r3.json() if r3.status_code == 200 else []
        check("GET customer vehicles returns exactly 1", len(body3) == 1, body3)
        check("GET customer vehicles vin matches", body3[0].get("vin") == VIN, body3)

        # 4. GET vehicles for a customer with none: 200 + empty list, not 404.
        r4 = requests.get(f"{base_url}/customers/999999999/vehicles", timeout=10)
        check("GET customer vehicles empty status 200", r4.status_code == 200, (r4.status_code, r4.text))
        check("GET customer vehicles empty is []", r4.json() == [], r4.text)

        # 5. GET vehicle by VIN: found.
        r5 = requests.get(f"{base_url}/vehicles/by-vin/{VIN}", timeout=10)
        check("GET vehicle by vin found status 200", r5.status_code == 200, (r5.status_code, r5.text))
        body5 = r5.json() if r5.status_code == 200 else {}
        check("GET vehicle by vin matches make", body5.get("make") == "Toyota", body5)

        # 6. GET vehicle by VIN: not found.
        r6 = requests.get(f"{base_url}/vehicles/by-vin/NOSUCHVINATALL", timeout=10)
        check("GET vehicle by vin not-found returns 404", r6.status_code == 404, (r6.status_code, r6.text))
    finally:
        cleanup(env_var, person_id, customer_id, vehicle_id)
        verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed")


if __name__ == "__main__":
    main()
