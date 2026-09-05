"""Real HTTP-level smoke test for the NEW GET /customers/{customer_id}
route (2026-09 cron cycle: closes the gap where every job route exposes
a bare customer_id int and GET /customers/{customer_id}/vehicles already
takes that same id as a path param, but nothing could look the customer
row itself up by it -- only by person_id via GET /customers/by-person/
{person_id}).

Runs a real uvicorn process against real staging and hits it with real
`requests` calls, not TestClient mocks (test_api.py already covers the
mocked happy/404 paths) -- this exercises the real SQL lookup in
app.repository.get_customer_by_id() against actual Postgres rows.

Same cleanup discipline as every other smoke script in this directory:
test data created and deleted by explicit, narrowly-targeted match on a
unique marker email, never a blanket delete, independently re-verified
by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_get_customer_by_id.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

PERSON_EMAIL = "smoke.http.getcustomerbyid@example.com"
ACTOR = "_smoke_http_get_customer_by_id"

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
            "VALUES ('SmokeGetCustomerById', 'Tester', %s, %s) RETURNING id",
            (PERSON_EMAIL, ACTOR),
        )
        person_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO collision.customer (person_id, source, created_by) "
            "VALUES (%s, 'insurer_referred', %s) RETURNING id",
            (person_id, ACTOR),
        )
        customer_id = cur.fetchone()["id"]
    return person_id, customer_id


def cleanup(env_var, person_id, customer_id):
    with db_cursor(env_var, autocommit=False) as cur:
        if customer_id is not None:
            cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        if person_id is not None:
            cur.execute(
                "DELETE FROM platform.person WHERE id = %s AND email_normalized = %s",
                (person_id, PERSON_EMAIL),
            )


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM platform.person WHERE email_normalized = %s", (PERSON_EMAIL,))
        n_person = cur.fetchone()["n"]
    check("cleanup confirmed: 0 person rows", n_person == 0, n_person)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_id = customer_id = None
    try:
        person_id, customer_id = setup_fixtures(env_var)

        r1 = requests.get(f"{base_url}/customers/{customer_id}", timeout=10)
        check("GET /customers/{id} found status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("GET /customers/{id} matches id", body1.get("id") == customer_id, body1)
        check("GET /customers/{id} matches person_id", body1.get("person_id") == person_id, body1)
        check("GET /customers/{id} matches source", body1.get("source") == "insurer_referred", body1)

        r2 = requests.get(f"{base_url}/customers/999999999", timeout=10)
        check("GET /customers/{id} unknown id returns 404", r2.status_code == 404, (r2.status_code, r2.text))
    finally:
        cleanup(env_var, person_id, customer_id)
        verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed (5/5)")


if __name__ == "__main__":
    main()
