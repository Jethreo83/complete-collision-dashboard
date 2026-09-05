"""Real HTTP-level smoke test for the NEW GET /staff route (2026-09
cron cycle: closes the gap where POST /staff and GET /staff/{email}
existed since 2026-09-06 but nothing could list the whole roster --
same class of gap list_sites()/GET /sites closed for collision.site
the prior cycle).

Runs a real uvicorn process against real staging and hits it with real
`requests` calls (not TestClient mocks) -- exercises the real SQL
filter logic in app.repository.list_staff_users() against actual
Postgres rows.

Same cleanup discipline as every other smoke script in this directory:
test data created and deleted by explicit, narrowly-targeted match on a
unique marker email, never a blanket delete, independently re-verified
by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8011
  2. Run: python scripts/_smoke_http_list_staff.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8011]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

EMAIL_PREFIX_MANAGER = "smoke.liststaff.manager@completecollisions.com"
EMAIL_PREFIX_RECEPTIONIST = "smoke.liststaff.reception@completecollisions.com"
PERSON_EMAILS = [
    "smoke.liststaff.person1@example.com",
    "smoke.liststaff.person2@example.com",
]
ACTOR = "_smoke_http_list_staff"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_fixtures(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        person_ids = []
        for email in PERSON_EMAILS:
            cur.execute(
                "INSERT INTO platform.person (first_name, last_name, email_normalized, created_by) "
                "VALUES ('SmokeListStaff', 'Tester', %s, %s) RETURNING id",
                (email, ACTOR),
            )
            person_ids.append(cur.fetchone()["id"])

        staff_ids = []
        cur.execute(
            "INSERT INTO collision.staff_user (person_id, role, google_email, active, created_by, updated_by) "
            "VALUES (%s, 'manager', %s, true, %s, %s) RETURNING id",
            (person_ids[0], EMAIL_PREFIX_MANAGER, ACTOR, ACTOR),
        )
        staff_ids.append(cur.fetchone()["id"])
        cur.execute(
            "INSERT INTO collision.staff_user (person_id, role, google_email, active, created_by, updated_by) "
            "VALUES (%s, 'receptionist', %s, false, %s, %s) RETURNING id",
            (person_ids[1], EMAIL_PREFIX_RECEPTIONIST, ACTOR, ACTOR),
        )
        staff_ids.append(cur.fetchone()["id"])
    return person_ids, staff_ids


def cleanup(env_var, person_ids, staff_ids):
    with db_cursor(env_var, autocommit=False) as cur:
        for sid in staff_ids or []:
            cur.execute("DELETE FROM collision.staff_user WHERE id = %s", (sid,))
        for pid, email in zip(person_ids or [], PERSON_EMAILS):
            cur.execute(
                "DELETE FROM platform.person WHERE id = %s AND email_normalized = %s",
                (pid, email),
            )


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "SELECT count(*) AS n FROM collision.staff_user WHERE google_email IN (%s, %s)",
            (EMAIL_PREFIX_MANAGER, EMAIL_PREFIX_RECEPTIONIST),
        )
        n_staff = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM platform.person WHERE email_normalized = ANY(%s)",
            (PERSON_EMAILS,),
        )
        n_person = cur.fetchone()["n"]
    check("cleanup confirmed: 0 staff_user rows", n_staff == 0, n_staff)
    check("cleanup confirmed: 0 person rows", n_person == 0, n_person)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8011"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_ids = staff_ids = None
    try:
        person_ids, staff_ids = setup_fixtures(env_var)

        # No filter: should include both fixtures (staging may have
        # other tracks' staff rows too -- check by set membership, not
        # exact total count).
        r1 = requests.get(f"{base_url}/staff", timeout=10)
        check("GET /staff status 200", r1.status_code == 200, (r1.status_code, r1.text))
        emails1 = {s["google_email"] for s in r1.json()} if r1.status_code == 200 else set()
        check(
            "GET /staff includes both fixtures",
            {EMAIL_PREFIX_MANAGER, EMAIL_PREFIX_RECEPTIONIST} <= emails1,
            emails1,
        )

        # active_only=true: should include the active manager, exclude
        # the deactivated receptionist.
        r2 = requests.get(f"{base_url}/staff", params={"active_only": "true"}, timeout=10)
        check("GET /staff?active_only=true status 200", r2.status_code == 200, (r2.status_code, r2.text))
        emails2 = {s["google_email"] for s in r2.json()} if r2.status_code == 200 else set()
        check(
            "GET /staff?active_only=true includes active manager fixture",
            EMAIL_PREFIX_MANAGER in emails2,
            emails2,
        )
        check(
            "GET /staff?active_only=true excludes deactivated receptionist fixture",
            EMAIL_PREFIX_RECEPTIONIST not in emails2,
            emails2,
        )

        # role=receptionist: should include the receptionist fixture,
        # exclude the manager fixture.
        r3 = requests.get(f"{base_url}/staff", params={"role": "receptionist"}, timeout=10)
        check("GET /staff?role=receptionist status 200", r3.status_code == 200, (r3.status_code, r3.text))
        emails3 = {s["google_email"] for s in r3.json()} if r3.status_code == 200 else set()
        check(
            "GET /staff?role=receptionist includes receptionist fixture",
            EMAIL_PREFIX_RECEPTIONIST in emails3,
            emails3,
        )
        check(
            "GET /staff?role=receptionist excludes manager fixture",
            EMAIL_PREFIX_MANAGER not in emails3,
            emails3,
        )

        # Bad role value returns a real 400 over HTTP.
        r4 = requests.get(f"{base_url}/staff", params={"role": "not_a_real_role"}, timeout=10)
        check("GET /staff bad role returns 400", r4.status_code == 400, (r4.status_code, r4.text))
    finally:
        cleanup(env_var, person_ids, staff_ids)
        verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed (10/10)")


if __name__ == "__main__":
    main()
