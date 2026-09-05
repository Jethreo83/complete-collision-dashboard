"""Real HTTP-level smoke test for the NEW GET /settlements/pdr-crew route
(continuous-build cycle -- app/settlement.py wiring pdr_settlement.py's
tested-since-2026-09-04 calculator to real collision.job data).

Same discipline as every other smoke script here: real uvicorn process
against real staging Postgres, real requests HTTP calls, test data
created/deleted via explicit narrowly-targeted SQL, independently
re-verified by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first (against STAGING):
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_settlement.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from decimal import Decimal
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository as repo
from app.db import cursor as db_cursor
from app.models import JobCategory

SITE_NAME = "Smoke HTTP Settlement Site"
PERSON_EMAIL = "smoke.http.settlement@example.com"
VIN_COLLISION = "SMOKESETTLEVIN0001"
VIN_PDR = "SMOKESETTLEVIN0002"
RO_COLLISION = "RO-SMOKE-SETTLE-COL-001"
RO_PDR = "RO-SMOKE-SETTLE-PDR-001"
RO_OTHER_MONTH = "RO-SMOKE-SETTLE-COL-002"  # closed a different month, must be excluded
ACTOR = "_smoke_http_settlement"
MONTH = "2026-06"  # fixed test month, unlikely to collide with real data
OTHER_MONTH = "2026-05"

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
            "VALUES ('SmokeSettlement', 'Tester', %s, %s) RETURNING id",
            (PERSON_EMAIL, ACTOR),
        )
        person_id = cur.fetchone()["id"]
        customer = repo.create_customer_for_existing_person(cur, person_id, ACTOR, source="walk_in")
        site = repo.get_or_create_site(cur, SITE_NAME, ACTOR)
        vehicle_col = repo.get_or_create_vehicle(cur, customer.id, ACTOR, vin=VIN_COLLISION, make="Honda", model="Civic", year=2020)
        vehicle_pdr = repo.get_or_create_vehicle(cur, customer.id, ACTOR, vin=VIN_PDR, make="Toyota", model="Camry", year=2021)

        from app.models import RepairOrder as RO

        ro_col = repo.create_repair_order(
            cur,
            RO(
                ro_number=RO_COLLISION, vehicle_id=vehicle_col.id, customer_id=customer.id,
                site_id=site.id, category=JobCategory.COLLISION,
                gross_revenue=Decimal("1000.00"),
            ),
            ACTOR,
        )
        # direct_ro_costs/labor_cost are trigger-derived from cost_entry
        # (migration 010) -- add via add_cost_entry, not a direct column write.
        from app.models import CostCategory, CostEntry
        repo.add_cost_entry(cur, CostEntry(job_id=ro_col.id, category=CostCategory.LABOR, amount=Decimal("200.00"), source="manual"), ACTOR)
        repo.add_cost_entry(cur, CostEntry(job_id=ro_col.id, category=CostCategory.PARTS, amount=Decimal("100.00"), source="manual"), ACTOR)
        # rent_utility_share is still a direct column per migration 006 (not trigger-derived).
        cur.execute("UPDATE collision.job SET rent_utility_share = %s WHERE id = %s", (Decimal("100.00"), ro_col.id))
        cur.execute("UPDATE collision.job SET closed_at = %s WHERE id = %s", (f"{MONTH}-15T12:00:00Z", ro_col.id))

        ro_pdr = repo.create_repair_order(
            cur,
            RO(
                ro_number=RO_PDR, vehicle_id=vehicle_pdr.id, customer_id=customer.id,
                site_id=site.id, category=JobCategory.PDR,
                gross_revenue=Decimal("500.00"),
            ),
            ACTOR,
        )
        repo.add_cost_entry(cur, CostEntry(job_id=ro_pdr.id, category=CostCategory.PARTS, amount=Decimal("50.00"), source="manual"), ACTOR)
        cur.execute("UPDATE collision.job SET closed_at = %s WHERE id = %s", (f"{MONTH}-20T12:00:00Z", ro_pdr.id))

        # A third job closed in a DIFFERENT month at the same site -- must
        # be excluded from the MONTH settlement, proving the month filter
        # actually filters rather than returning everything for the site.
        ro_other = repo.create_repair_order(
            cur,
            RO(
                ro_number=RO_OTHER_MONTH, vehicle_id=vehicle_col.id, customer_id=customer.id,
                site_id=site.id, category=JobCategory.COLLISION,
                gross_revenue=Decimal("9999.00"),
            ),
            ACTOR,
        )
        cur.execute("UPDATE collision.job SET closed_at = %s WHERE id = %s", (f"{OTHER_MONTH}-10T12:00:00Z", ro_other.id))

    return person_id, customer.id, site.id, vehicle_col.id, vehicle_pdr.id, ro_col.id, ro_pdr.id, ro_other.id


def cleanup(env_var, person_id, customer_id, site_id, vehicle_col_id, vehicle_pdr_id, job_ids):
    with db_cursor(env_var, autocommit=False) as cur:
        for job_id in job_ids:
            cur.execute("DELETE FROM collision.cost_entry WHERE job_id = %s", (job_id,))
            cur.execute("DELETE FROM collision.job_event WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM collision.job WHERE id = ANY(%s)", (job_ids,))
        cur.execute("DELETE FROM collision.vehicle WHERE id IN (%s, %s)", (vehicle_col_id, vehicle_pdr_id))
        cur.execute("DELETE FROM collision.customer WHERE id = %s", (customer_id,))
        cur.execute("DELETE FROM platform.person WHERE id = %s", (person_id,))
        cur.execute(
            "DELETE FROM collision.site WHERE id = %s "
            "AND NOT EXISTS (SELECT 1 FROM collision.job WHERE site_id = collision.site.id)",
            (site_id,),
        )


def verify_clean(env_var, person_id, site_id, job_ids):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM collision.job WHERE id = ANY(%s)", (job_ids,))
        n_jobs = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM platform.person WHERE id = %s", (person_id,))
        n_person = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM collision.site WHERE id = %s", (site_id,))
        n_site = cur.fetchone()["n"]
    check("cleanup confirmed: 0 job rows remaining", n_jobs == 0, n_jobs)
    check("cleanup confirmed: 0 person rows remaining", n_person == 0, n_person)
    check("cleanup confirmed: 0 site rows remaining", n_site == 0, n_site)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    person_id = customer_id = site_id = vehicle_col_id = vehicle_pdr_id = None
    ro_col_id = ro_pdr_id = ro_other_id = None
    try:
        (person_id, customer_id, site_id, vehicle_col_id, vehicle_pdr_id,
         ro_col_id, ro_pdr_id, ro_other_id) = setup_fixtures(env_var)

        # 1. Real settlement for MONTH -- both fixture jobs included,
        #    the other-month job excluded, real math applied.
        r1 = requests.get(f"{base_url}/settlements/pdr-crew", params={"site_id": site_id, "month": MONTH}, timeout=10)
        check("GET /settlements/pdr-crew status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("month echoed back", body1.get("month") == MONTH, body1)
        check("site echoed back", body1.get("site") == SITE_NAME, body1)
        check("status is draft_held_for_review", body1.get("status") == "draft_held_for_review", body1)

        cats = {c["category"]: c for c in body1.get("categories", [])}
        collision_cat = cats.get("collision", {})
        pdr_cat = cats.get("pdr", {})

        check(
            "collision category includes only the collision-month RO (not the other-month RO)",
            collision_cat.get("ro_numbers") == [RO_COLLISION], collision_cat,
        )
        # net_profit = 1000 - (200 labor + 100 parts + 100 rent) = 600
        # 70/30 split -> cc=420.00, pdr=180.00
        check("collision net_profit == 600.00", Decimal(collision_cat.get("net_profit", "0")) == Decimal("600.00"), collision_cat)
        check("collision cc_share == 420.00", Decimal(collision_cat.get("cc_share_amount", "0")) == Decimal("420.00"), collision_cat)
        check("collision pdr_share == 180.00", Decimal(collision_cat.get("pdr_share_amount", "0")) == Decimal("180.00"), collision_cat)

        check("pdr category includes the pdr RO", pdr_cat.get("ro_numbers") == [RO_PDR], pdr_cat)
        # net_profit = 500 - 50 = 450; 5/95 split -> cc=22.50, pdr=427.50
        check("pdr net_profit == 450.00", Decimal(pdr_cat.get("net_profit", "0")) == Decimal("450.00"), pdr_cat)
        check("pdr cc_share == 22.50", Decimal(pdr_cat.get("cc_share_amount", "0")) == Decimal("22.50"), pdr_cat)
        check("pdr pdr_share == 427.50", Decimal(pdr_cat.get("pdr_share_amount", "0")) == Decimal("427.50"), pdr_cat)

        expected_total = Decimal("180.00") + Decimal("427.50")
        check("total_owed_to_pdr sums both categories", Decimal(body1.get("total_owed_to_pdr", "0")) == expected_total, body1)
        check("statement_text is draft language", "DRAFT" in body1.get("statement_text", ""), body1.get("statement_text"))
        check("statement_text mentions both RO numbers", RO_COLLISION in body1["statement_text"] and RO_PDR in body1["statement_text"], body1["statement_text"])
        check("statement_text does NOT mention the other-month RO", RO_OTHER_MONTH not in body1["statement_text"], body1["statement_text"])

        # 2. A month with no closed jobs -> 200 with all-zero categories,
        #    not a 404 (site is real, just nothing to settle that month).
        r2 = requests.get(f"{base_url}/settlements/pdr-crew", params={"site_id": site_id, "month": "2020-01"}, timeout=10)
        check("GET /settlements/pdr-crew empty-month status 200", r2.status_code == 200, (r2.status_code, r2.text))
        body2 = r2.json() if r2.status_code == 200 else {}
        check("empty-month total_owed_to_pdr == 0", Decimal(body2.get("total_owed_to_pdr", "-1")) == Decimal("0"), body2)

        # 3. Unknown site_id -> real 404, not a 500.
        r3 = requests.get(f"{base_url}/settlements/pdr-crew", params={"site_id": 999999999, "month": MONTH}, timeout=10)
        check("GET /settlements/pdr-crew unknown site -> 404", r3.status_code == 404, (r3.status_code, r3.text))

        # 4. Malformed month -> real 400, not a 500.
        r4 = requests.get(f"{base_url}/settlements/pdr-crew", params={"site_id": site_id, "month": "not-a-month"}, timeout=10)
        check("GET /settlements/pdr-crew bad month -> 400", r4.status_code == 400, (r4.status_code, r4.text))
    finally:
        if person_id is not None:
            job_ids = [j for j in (ro_col_id, ro_pdr_id, ro_other_id) if j is not None]
            cleanup(env_var, person_id, customer_id, site_id, vehicle_col_id, vehicle_pdr_id, job_ids)
            verify_clean(env_var, person_id, site_id, job_ids)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed (19/19)")


if __name__ == "__main__":
    main()
