"""Real HTTP smoke test for the SitesAdminPage frontend consumer of
PATCH /sites/{id}/active -- exercises the exact same route the new
web/src/pages/SitesAdminPage.tsx calls, against real staging Postgres
via a real running uvicorn on :8010. Throwaway verification script,
not part of the committed test suite (mirrors the other
scripts/_smoke_http_*.py convention in this repo).
"""
import json
import os
import urllib.request
import urllib.error

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]
BASE = "http://127.0.0.1:8010"
SITE_NAME = "CronVerify Sites Page Fixture"
ACTOR = "cron_verify_sites_page"

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("SELECT id FROM collision.site WHERE name = %s", (SITE_NAME,))
row = cur.fetchone()
if row:
    print("existing fixture found, deleting first:", dict(row))
    cur.execute("DELETE FROM collision.site WHERE id = %s", (row["id"],))

cur.execute(
    "INSERT INTO collision.site (name, address, created_by) VALUES (%s, %s, %s) RETURNING *",
    (SITE_NAME, "999 Cron Test Ave", ACTOR),
)
site = cur.fetchone()
site_id = site["id"]
print("created fixture site:", dict(site))


def http_get(path):
    with urllib.request.urlopen(f"{BASE}{path}") as resp:
        return resp.status, json.loads(resp.read())


def http_patch(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="PATCH", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


checks = []


def check(name, cond, extra=None):
    checks.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), name, "" if extra is None else extra)


status, body = http_get("/sites?active_only=false")
found = [s for s in body if s["id"] == site_id]
check("fixture appears in GET /sites", len(found) == 1, found)
check("fixture starts active=true", bool(found) and found[0]["active"] is True)

status, body = http_get(f"/sites/{site_id}")
check("GET /sites/{id} 200", status == 200, body)
check("GET /sites/{id} matches name", body["name"] == SITE_NAME, body)

status, body = http_patch(f"/sites/{site_id}/active", {"active": False, "actor": ACTOR})
check("PATCH deactivate 200", status == 200, body)
check("PATCH deactivate returns active=false", body["active"] is False, body)

status, body = http_get("/sites?active_only=true")
check("active_only=true excludes deactivated fixture", all(s["id"] != site_id for s in body))

status, body = http_get("/sites?active_only=false")
found2 = [s for s in body if s["id"] == site_id]
check("active_only=false still includes deactivated fixture", len(found2) == 1 and found2[0]["active"] is False)

status, body = http_patch(f"/sites/{site_id}/active", {"active": True, "actor": ACTOR})
check("PATCH reactivate 200", status == 200, body)
check("PATCH reactivate returns active=true", body["active"] is True, body)

try:
    http_patch("/sites/999999999/active", {"active": True, "actor": ACTOR})
    check("unknown site id -> 404", False, "did not raise")
except urllib.error.HTTPError as e:
    check("unknown site id -> 404", e.code == 404, e.code)

n_pass = sum(1 for _, ok in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")

cur.execute("SELECT count(*) AS n FROM collision.job WHERE site_id = %s", (site_id,))
job_refs = cur.fetchone()["n"]
print("job rows referencing fixture site:", job_refs)
if job_refs == 0:
    cur.execute("DELETE FROM collision.site WHERE id = %s", (site_id,))
    print("deleted fixture site")
cur.execute("SELECT count(*) AS n FROM collision.site WHERE name = %s", (SITE_NAME,))
print("remaining rows with fixture name:", cur.fetchone()["n"])

cur.close()
conn.close()

if n_pass != len(checks):
    raise SystemExit(1)
