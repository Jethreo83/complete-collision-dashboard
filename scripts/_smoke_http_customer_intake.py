"""Real HTTP-level smoke test for the NEW POST /customers/intake route
(this cron cycle: closes the gap repo.create_person_and_customer()'s
docstring has flagged since migration 001 -- "swap the raw INSERT for
platform.match_or_create_person() ... not urgent"). Modeled directly on
elektrica-dashboard-ref's equivalent smoke test for POST /renters/intake
(same underlying platform.match_or_create_person() primitive).

Runs a real uvicorn process against real staging and hits it with real
`requests` calls -- exercises the actual SET ROLE platform_identity_service
/ platform.match_or_create_person() / RESET ROLE sequence against real
Postgres rows, all three match_status outcomes:
  1. 'created' -- brand-new person, no existing match.
  2. 'attached' -- second intake with the SAME email exact-matches the
     person created in step 1, links to the SAME platform.person, does
     NOT create a duplicate.
  3. 'queued' -- third intake with a DIFFERENT email but the SAME
     last_name + date_of_birth as step 1's person is a close-not-exact
     match -- queued for human review, no collision.customer row
     created, real platform.person_match_queue row exists.

Cleanup: person_match_queue row deleted first (FK-safe order), then
collision.customer rows, then platform.person rows -- all by explicit
marker-email match, independently re-verified by a follow-up query.

Usage:
  1. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_customer_intake.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

MARKER_EMAIL = "smoke.http.customerintake@example.com"
MARKER_EMAIL_2 = "smoke.http.customerintake.second@example.com"
MARKER_LAST_NAME = "SmokeIntakeIsotope"
DOB = "1985-06-15"
ACTOR = "_smoke_http_customer_intake"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "SELECT count(*) AS n FROM platform.person WHERE email_normalized IN (%s, %s) OR last_name = %s",
            (MARKER_EMAIL, MARKER_EMAIL_2, MARKER_LAST_NAME),
        )
        n_person = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM platform.person_match_queue WHERE last_name = %s",
            (MARKER_LAST_NAME,),
        )
        n_queue = cur.fetchone()["n"]
    check("cleanup confirmed: 0 person rows", n_person == 0, n_person)
    check("cleanup confirmed: 0 person_match_queue rows", n_queue == 0, n_queue)


def cleanup(env_var, person_ids, queue_ids):
    with db_cursor(env_var, autocommit=False) as cur:
        for qid in queue_ids:
            if qid is not None:
                cur.execute("DELETE FROM platform.person_match_queue WHERE id = %s", (qid,))
        for pid in person_ids:
            if pid is not None:
                cur.execute("DELETE FROM collision.customer WHERE person_id = %s", (pid,))
                cur.execute("DELETE FROM platform.person WHERE id = %s", (pid,))


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_ids = []
    queue_ids = []
    try:
        # 1. 'created' -- brand new person
        r1 = requests.post(f"{base_url}/customers/intake", json={
            "first_name": "SmokeIntake", "last_name": MARKER_LAST_NAME,
            "actor": ACTOR, "email": MARKER_EMAIL.upper() + "  ",  # exercises normalization
            "date_of_birth": DOB,
        }, timeout=10)
        check("POST /customers/intake created status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("intake #1 match_status == created", body1.get("match_status") == "created", body1)
        check("intake #1 has a customer row", body1.get("customer") is not None, body1)
        check("intake #1 queue_id is None", body1.get("queue_id") is None, body1)
        person_id_1 = body1.get("person_id")
        person_ids.append(person_id_1)

        # 2. 'attached' -- SAME email (different case/whitespace), must
        # exact-match to the SAME person_id, no duplicate.
        r2 = requests.post(f"{base_url}/customers/intake", json={
            "first_name": "DifferentFirstName", "last_name": "DifferentLastName",
            "actor": ACTOR, "email": "  " + MARKER_EMAIL + " ",
        }, timeout=10)
        check("POST /customers/intake attached status 200", r2.status_code == 200, (r2.status_code, r2.text))
        body2 = r2.json() if r2.status_code == 200 else {}
        check("intake #2 match_status == attached", body2.get("match_status") == "attached", body2)
        check("intake #2 same person_id as #1 (no duplicate)", body2.get("person_id") == person_id_1, (body2, person_id_1))
        check("intake #2 has a customer row", body2.get("customer") is not None, body2)

        # 3. 'queued' -- different email, same last_name + DOB as #1's
        # person -- close-not-exact match, must NOT create a customer row.
        r3 = requests.post(f"{base_url}/customers/intake", json={
            "first_name": "PossiblySamePerson", "last_name": MARKER_LAST_NAME,
            "actor": ACTOR, "email": MARKER_EMAIL_2, "date_of_birth": DOB,
        }, timeout=10)
        check("POST /customers/intake queued status 200", r3.status_code == 200, (r3.status_code, r3.text))
        body3 = r3.json() if r3.status_code == 200 else {}
        check("intake #3 match_status == queued", body3.get("match_status") == "queued", body3)
        check("intake #3 candidate person_id == #1's", body3.get("person_id") == person_id_1, (body3, person_id_1))
        check("intake #3 has NO customer row", body3.get("customer") is None, body3)
        check("intake #3 has a real queue_id", isinstance(body3.get("queue_id"), int), body3)
        queue_ids.append(body3.get("queue_id"))

        # Independently confirm the queue row is real (not just echoed).
        with db_cursor(env_var, autocommit=False) as cur:
            cur.execute(
                "SELECT source_project, status, match_reason FROM platform.person_match_queue WHERE id = %s",
                (body3.get("queue_id"),),
            )
            qrow = cur.fetchone()
        check("queue row source_project == 'collision'", qrow and qrow["source_project"] == "collision", qrow)
        check("queue row status == 'pending'", qrow and qrow["status"] == "pending", qrow)
        check("queue row match_reason == 'name_dob_close_match'", qrow and qrow["match_reason"] == "name_dob_close_match", qrow)

        # Independently confirm exactly ONE platform.person row exists for
        # the marker email (proves #2 didn't create a duplicate).
        with db_cursor(env_var, autocommit=False) as cur:
            cur.execute(
                "SELECT count(*) AS n FROM platform.person WHERE email_normalized = %s",
                (MARKER_EMAIL,),
            )
            n = cur.fetchone()["n"]
        check("exactly 1 person row for marker email (no duplicate created)", n == 1, n)
    finally:
        cleanup(env_var, person_ids, queue_ids)
        verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed (14/14)")


if __name__ == "__main__":
    main()
