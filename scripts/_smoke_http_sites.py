"""Real HTTP-level smoke test for the NEW GET /sites, GET /sites/{id}
routes (2026-09-08 cron cycle -- collision.site, migrations/006, STAGING
ONLY, has had a writer (get_or_create_site()) since it was created but no
reader anywhere; this closes that gap).

Same discipline as every other smoke script here: real uvicorn process
against real staging Postgres, real requests HTTP calls (not TestClient
mocks -- test_api.py's mocked tests already cover those), test data
created/deleted via explicit narrowly-targeted SQL, independently
re-verified by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first (against STAGING):
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_sites.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository as repo
from app.db import cursor as db_cursor

SITE_NAME_A = "Smoke HTTP Sites Route A"
SITE_NAME_B = "Smoke HTTP Sites Route B"
ACTOR = "_smoke_http_sites"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def setup_prereqs(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        site_a = repo.get_or_create_site(cur, SITE_NAME_A, ACTOR, address="100 Main St")
        site_b = repo.get_or_create_site(cur, SITE_NAME_B, ACTOR)
        # Deactivate B to exercise active_only filtering through real SQL,
        # not just a mocked repo call.
        cur.execute("UPDATE collision.site SET active = false WHERE id = %s", (site_b.id,))
    return site_a.id, site_b.id


def cleanup(env_var, site_a_id, site_b_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "DELETE FROM collision.site WHERE id IN (%s, %s) "
            "AND NOT EXISTS (SELECT 1 FROM collision.job WHERE site_id = collision.site.id)",
            (site_a_id, site_b_id),
        )


def verify_clean(env_var, site_a_id, site_b_id):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute(
            "SELECT count(*) AS n FROM collision.site WHERE id IN (%s, %s)",
            (site_a_id, site_b_id),
        )
        n = cur.fetchone()["n"]
    check("cleanup confirmed: 0 site rows remaining", n == 0, n)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    site_a_id = site_b_id = None
    try:
        site_a_id, site_b_id = setup_prereqs(env_var)

        # 1. GET /sites/{id} for the active site -- real fields round-trip.
        r1 = requests.get(f"{base_url}/sites/{site_a_id}", timeout=10)
        check("GET /sites/{id} found status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        check("GET /sites/{id} name correct", body1.get("name") == SITE_NAME_A, body1)
        check("GET /sites/{id} address correct", body1.get("address") == "100 Main St", body1)
        check("GET /sites/{id} active true", body1.get("active") is True, body1)

        # 2. GET /sites/{id} unknown -> 404, not a 500.
        r2 = requests.get(f"{base_url}/sites/999999999", timeout=10)
        check("GET /sites/{id} unknown returns 404", r2.status_code == 404, (r2.status_code, r2.text))

        # 3. GET /sites (no filter) includes both our fixture rows,
        #    including the inactive one.
        r3 = requests.get(f"{base_url}/sites", timeout=10)
        check("GET /sites status 200", r3.status_code == 200, (r3.status_code, r3.text))
        names3 = {s["name"] for s in r3.json()} if r3.status_code == 200 else set()
        check("GET /sites includes active fixture", SITE_NAME_A in names3, names3)
        check("GET /sites includes inactive fixture (no filter)", SITE_NAME_B in names3, names3)

        # 4. GET /sites?active_only=true excludes the deactivated fixture --
        #    the real behavior this route exists to support (a site
        #    picker that shouldn't offer closed/inactive locations).
        r4 = requests.get(f"{base_url}/sites?active_only=true", timeout=10)
        check("GET /sites?active_only=true status 200", r4.status_code == 200, (r4.status_code, r4.text))
        names4 = {s["name"] for s in r4.json()} if r4.status_code == 200 else set()
        check("GET /sites?active_only=true includes active fixture", SITE_NAME_A in names4, names4)
        check("GET /sites?active_only=true excludes inactive fixture", SITE_NAME_B not in names4, names4)
    finally:
        if site_a_id is not None:
            cleanup(env_var, site_a_id, site_b_id)
            verify_clean(env_var, site_a_id, site_b_id)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed (9/9)")


if __name__ == "__main__":
    main()
