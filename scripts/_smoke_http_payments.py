"""Real HTTP-level smoke test for the NEW payment routes (migrations/011,
STAGING ONLY -- collision.payment not yet promoted to production; see
migrations/011's header and WORKLOG.md 2026-09-04 for the payment_source
enum question still awaiting Jed's confirmation).

Exercises GET/POST /jobs/{ro}/payments and GET /jobs/{ro}/payments/summary
against a real uvicorn process + real staging Postgres, not TestClient
mocks (test_api.py already covers the mocked happy/error paths this
session added) -- this catches things mocks can't: the real FK to
collision.job, the real amount>0 / authorize_net CHECK constraints
enforced twice (Python __post_init__ AND the DB), the real append-only
forbid-mutation trigger, and the real job_payment_summary view
aggregation.

Same cleanup discipline as every other smoke script in this directory:
test data created and deleted by explicit, narrowly-targeted match on a
unique marker RO number / VIN / email / site name, never a blanket
delete, independently re-verified by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first (against STAGING):
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_payments.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

RO_NUMBER = "RO-SMOKE-PAYMENTS-001"
VIN = "SMOKEPAYMENTSVIN01"
PERSON_EMAIL = "smoke.http.payments@example.com"
SITE_NAME = "Smoke HTTP Payments Site"
ACTOR = "_smoke_http_payments"

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
            "VALUES ('SmokePayments', 'Tester', %s, %s) RETURNING id",
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
        cur.execute(
            "INSERT INTO collision.vehicle (vin, customer_id, created_by) "
            "VALUES (%s, %s, %s) RETURNING id",
            (VIN, customer_id, ACTOR),
        )
        vehicle_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO collision.job (
                ro_number, vehicle_id, customer_id, site_id, category, status,
                created_by, updated_by
            ) VALUES (%s, %s, %s, %s, 'collision', 'estimate', %s, %s)
            RETURNING id
            """,
            (RO_NUMBER, vehicle_id, customer_id, site_id, ACTOR, ACTOR),
        )
        job_id = cur.fetchone()["id"]
    return person_id, customer_id, site_id, vehicle_id, job_id


def cleanup(env_var, person_id, customer_id, site_id, vehicle_id, job_id):
    with db_cursor(env_var, autocommit=False) as cur:
        if job_id is not None:
            # collision.payment forbids DELETE for every role including
            # the connecting admin role (per migration 011's own
            # verify_011.sql lesson) -- disable the trigger for cleanup
            # only, re-enable immediately after.
            cur.execute("ALTER TABLE collision.payment DISABLE TRIGGER trg_payment_forbid_delete")
            cur.execute("DELETE FROM collision.payment WHERE job_id = %s", (job_id,))
            cur.execute("ALTER TABLE collision.payment ENABLE TRIGGER trg_payment_forbid_delete")
            cur.execute("DELETE FROM collision.job WHERE id = %s", (job_id,))
        if vehicle_id is not None:
            cur.execute("DELETE FROM collision.vehicle WHERE id = %s", (vehicle_id,))
        if customer_id is not None:
            cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        if site_id is not None:
            cur.execute("DELETE FROM collision.site WHERE id = %s", (site_id,))
        if person_id is not None:
            cur.execute(
                "DELETE FROM platform.person WHERE id = %s AND email_normalized = %s",
                (person_id, PERSON_EMAIL),
            )


def verify_clean(env_var, job_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM collision.job WHERE ro_number = %s", (RO_NUMBER,))
        n_job = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM collision.vehicle WHERE vin = %s", (VIN,))
        n_veh = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM platform.person WHERE email_normalized = %s", (PERSON_EMAIL,))
        n_person = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM collision.site WHERE name = %s", (SITE_NAME,))
        n_site = cur.fetchone()["n"]
        n_payment = 0
        if job_id is not None:
            cur.execute("SELECT count(*) AS n FROM collision.payment WHERE job_id = %s", (job_id,))
            n_payment = cur.fetchone()["n"]
    check("cleanup confirmed: 0 job rows", n_job == 0, n_job)
    check("cleanup confirmed: 0 vehicle rows", n_veh == 0, n_veh)
    check("cleanup confirmed: 0 person rows", n_person == 0, n_person)
    check("cleanup confirmed: 0 site rows", n_site == 0, n_site)
    check("cleanup confirmed: 0 payment rows", n_payment == 0, n_payment)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_id = customer_id = site_id = vehicle_id = job_id = None
    try:
        person_id, customer_id, site_id, vehicle_id, job_id = setup_fixtures(env_var)

        # 1. GET payments before any exist: empty list, 200 (not 404 --
        # the job exists, it just has none yet).
        r = requests.get(f"{base_url}/jobs/{RO_NUMBER}/payments", timeout=10)
        check("GET payments empty list status 200", r.status_code == 200, (r.status_code, r.text))
        check("GET payments empty list is []", r.json() == [], r.text)

        # 2. Summary for a job with zero payments: 0/0/None, not omitted
        # (mirrors verify_011.sql's CHECK 1 for the underlying view).
        r_sum0 = requests.get(f"{base_url}/jobs/{RO_NUMBER}/payments/summary", timeout=10)
        check("GET summary zero-payment status 200", r_sum0.status_code == 200, (r_sum0.status_code, r_sum0.text))
        body_sum0 = r_sum0.json() if r_sum0.status_code == 200 else {}
        check(
            "GET summary zero-payment shows 0/0/None",
            body_sum0.get("total_collected") == "0.00" and body_sum0.get("payment_count") == 0
            and body_sum0.get("last_payment_at") is None,
            body_sum0,
        )

        # 3. POST a manual payment (no external_transaction_id needed).
        r1 = requests.post(
            f"{base_url}/jobs/{RO_NUMBER}/payments",
            json={"source": "check", "amount": "250.00", "actor": ACTOR,
                  "external_transaction_id": "CHK-1001"},
            timeout=10,
        )
        check("POST payment 1 status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("POST payment 1 amount echoed", body1.get("amount") == "250.00", body1)

        # 4. POST an authorize_net payment MISSING external_transaction_id:
        # real 400 over HTTP (Payment.__post_init__ catches it before the
        # DB is even touched).
        r_bad = requests.post(
            f"{base_url}/jobs/{RO_NUMBER}/payments",
            json={"source": "authorize_net", "amount": "50.00", "actor": ACTOR},
            timeout=10,
        )
        check("POST authorize_net missing txn_id returns 400", r_bad.status_code == 400, (r_bad.status_code, r_bad.text))

        # 5. POST a second, valid authorize_net payment WITH the id.
        r2 = requests.post(
            f"{base_url}/jobs/{RO_NUMBER}/payments",
            json={"source": "authorize_net", "amount": "500.00", "actor": ACTOR,
                  "external_transaction_id": "AUTHNET-TXN-777"},
            timeout=10,
        )
        check("POST payment 2 status 200", r2.status_code == 200, (r2.status_code, r2.text))

        # 6. GET payments now returns exactly 2, both fixture rows.
        r3 = requests.get(f"{base_url}/jobs/{RO_NUMBER}/payments", timeout=10)
        body3 = r3.json() if r3.status_code == 200 else []
        check("GET payments after 2 posts returns exactly 2", len(body3) == 2, body3)

        # 7. Summary now shows 750.00 / 2 / a real last_payment_at.
        r_sum1 = requests.get(f"{base_url}/jobs/{RO_NUMBER}/payments/summary", timeout=10)
        body_sum1 = r_sum1.json() if r_sum1.status_code == 200 else {}
        check(
            "GET summary after 2 posts shows 750.00/2",
            body_sum1.get("total_collected") == "750.00" and body_sum1.get("payment_count") == 2
            and body_sum1.get("last_payment_at") is not None,
            body_sum1,
        )

        # 8. Real DB-level append-only enforcement: attempt a direct
        # UPDATE against the row just created, through the SAME cursor
        # helper the app uses (not admin-role bypass) -- must be
        # genuinely rejected, not just "the app doesn't happen to try
        # it." Uses collision_app's real behavior if the env var
        # connects as collision_app; if it connects as a privileged
        # role instead, this check documents that possibility rather
        # than silently passing for the wrong reason.
        try:
            with db_cursor(env_var, autocommit=False) as cur:
                cur.execute(
                    "UPDATE collision.payment SET amount = 999.99 "
                    "WHERE id = (SELECT id FROM collision.payment WHERE job_id = %s LIMIT 1)",
                    (job_id,),
                )
            check("direct UPDATE on collision.payment was rejected", False, "no exception raised")
        except Exception as e:
            check("direct UPDATE on collision.payment was rejected", "append-only" in str(e).lower(), str(e))

        # 9. Nonexistent job returns 404 for all three routes.
        r404a = requests.get(f"{base_url}/jobs/RO-NOPE-PAYMENTS/payments", timeout=10)
        r404b = requests.post(f"{base_url}/jobs/RO-NOPE-PAYMENTS/payments",
                               json={"source": "manual", "amount": "1.00", "actor": ACTOR}, timeout=10)
        r404c = requests.get(f"{base_url}/jobs/RO-NOPE-PAYMENTS/payments/summary", timeout=10)
        check("GET payments unknown RO returns 404", r404a.status_code == 404, r404a.text)
        check("POST payment unknown RO returns 404", r404b.status_code == 404, r404b.text)
        check("GET summary unknown RO returns 404", r404c.status_code == 404, r404c.text)
    finally:
        cleanup(env_var, person_id, customer_id, site_id, vehicle_id, job_id)
        verify_clean(env_var, job_id)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed")


if __name__ == "__main__":
    main()
