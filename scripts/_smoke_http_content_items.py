"""Real HTTP-level smoke test for the NEW collision.content_item routes
(POST /content-items, GET /content-items/{id}, GET /content-items,
GET /jobs/{ro_number}/content-items, PATCH /content-items/{id}/tags),
added this cron cycle to close the gap where migrations/005 went to
production on 2026-09-04 with zero app-layer readers/writers.

Exercises against a real uvicorn process + real Postgres (staging OR
production -- collision.content_item is live in BOTH per migrations/005's
promotion), not TestClient mocks (test_api.py already covers the mocked
happy/error paths this session added) -- this catches the real SQL
(to_tsvector search, ro_number join, JSONB round-trip) that mocks can't.

Same cleanup discipline as every other smoke script in this directory:
test data created and deleted by explicit, narrowly-targeted match on a
unique marker filename, never a blanket delete, independently
re-verified by a follow-up query after cleanup.

Usage:
  1. Start uvicorn manually first:
       COLLISION_DB_ENV_VAR=<your env var> uvicorn app.api:app --port 8010
  2. Run: python scripts/_smoke_http_content_items.py <ENV_VAR_NAME> [--base-url http://127.0.0.1:8010]
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor as db_cursor

FILENAME = "SMOKE_content_item_test_0001.jpg"
ACTOR = "_smoke_http_content_items"

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} -- {detail}")
        FAILED.append(name)


def cleanup(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("DELETE FROM collision.content_item WHERE filename = %s", (FILENAME,))


def verify_clean(env_var):
    with db_cursor(env_var, autocommit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM collision.content_item WHERE filename = %s", (FILENAME,))
        n = cur.fetchone()["n"]
    check("cleanup confirmed: 0 content_item rows", n == 0, n)


def main():
    args = sys.argv[1:]
    base_url = "http://127.0.0.1:8010"
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1]
        args = args[:i] + args[i + 2:]
    env_var = args[0]

    content_item_id = None
    try:
        # 1. POST create -- dashboard-native upload path.
        r1 = requests.post(
            f"{base_url}/content-items",
            json={
                "filename": FILENAME, "actor": ACTOR, "description": "smoke test red sedan photo",
                "ro_number": "RO-DOES-NOT-EXIST-9999", "uploader": ACTOR, "type": "photo",
            },
            timeout=10,
        )
        check("POST create status 200", r1.status_code == 200, (r1.status_code, r1.text))
        body1 = r1.json() if r1.status_code == 200 else {}
        content_item_id = body1.get("id")
        check("POST create returns filename", body1.get("filename") == FILENAME, body1)
        check("POST create defaults derived_tags_source=unset", body1.get("derived_tags_source") == "unset", body1)
        check("POST create allows orphan ro_number (no hard FK)", body1.get("ro_number") == "RO-DOES-NOT-EXIST-9999", body1)

        # 2. POST create with empty filename -- should 400 (real
        # ContentItem.__post_init__ ValueError -> HTTP 400, not a
        # silently-accepted row).
        r2 = requests.post(f"{base_url}/content-items", json={"filename": "", "actor": ACTOR}, timeout=10)
        check("POST create empty filename returns 400", r2.status_code == 400, (r2.status_code, r2.text))

        # 3. GET by id: found.
        r3 = requests.get(f"{base_url}/content-items/{content_item_id}", timeout=10)
        check("GET by id found status 200", r3.status_code == 200, (r3.status_code, r3.text))

        # 4. GET by id: not found.
        r4 = requests.get(f"{base_url}/content-items/999999999", timeout=10)
        check("GET by id not-found returns 404", r4.status_code == 404, (r4.status_code, r4.text))

        # 5. GET search by query -- real to_tsvector match on description.
        r5 = requests.get(f"{base_url}/content-items", params={"q": "sedan"}, timeout=10)
        check("GET search status 200", r5.status_code == 200, (r5.status_code, r5.text))
        body5 = r5.json() if r5.status_code == 200 else []
        check("GET search finds the fixture row", any(i.get("id") == content_item_id for i in body5), body5)

        # 6. GET by orphaned ro_number -- should return the row (job doesn't
        # exist in collision.job, but the direct content-items filter is
        # not job-scoped so this exercises the plain filename fixture
        # differently: use the /jobs/{ro}/content-items route instead,
        # which DOES require the job to exist -- expect 404 there.
        r6 = requests.get(f"{base_url}/jobs/RO-DOES-NOT-EXIST-9999/content-items", timeout=10)
        check(
            "GET job content-items for nonexistent job returns 404",
            r6.status_code == 404, (r6.status_code, r6.text),
        )

        # 7. PATCH tags -- real UPDATE + JSONB round-trip.
        r7 = requests.patch(
            f"{base_url}/content-items/{content_item_id}/tags",
            json={"derived_tags": ["red", "sedan", "front-bumper"], "derived_tags_source": "ai", "actor": ACTOR},
            timeout=10,
        )
        check("PATCH tags status 200", r7.status_code == 200, (r7.status_code, r7.text))
        body7 = r7.json() if r7.status_code == 200 else {}
        check("PATCH tags persisted list", body7.get("derived_tags") == ["red", "sedan", "front-bumper"], body7)
        check("PATCH tags persisted source", body7.get("derived_tags_source") == "ai", body7)

        # 8. PATCH tags with a bad source value -- 400.
        r8 = requests.patch(
            f"{base_url}/content-items/{content_item_id}/tags",
            json={"derived_tags": ["x"], "derived_tags_source": "not_a_real_value", "actor": ACTOR},
            timeout=10,
        )
        check("PATCH tags bad source returns 400", r8.status_code == 400, (r8.status_code, r8.text))

        # 9. PATCH tags on a nonexistent id -- 404.
        r9 = requests.patch(
            f"{base_url}/content-items/999999999/tags",
            json={"derived_tags": ["x"], "derived_tags_source": "human", "actor": ACTOR},
            timeout=10,
        )
        check("PATCH tags nonexistent id returns 404", r9.status_code == 404, (r9.status_code, r9.text))

        # 10. GET by id again -- confirm PATCH really persisted (not just
        # the response body reflecting the request).
        r10 = requests.get(f"{base_url}/content-items/{content_item_id}", timeout=10)
        body10 = r10.json() if r10.status_code == 200 else {}
        check(
            "GET by id after PATCH shows persisted tags",
            body10.get("derived_tags") == ["red", "sedan", "front-bumper"], body10,
        )
    finally:
        cleanup(env_var)
        verify_clean(env_var)

    if FAILED:
        print(f"\nFAILURES: {FAILED}")
        sys.exit(1)
    else:
        print("\nAll checks passed")


if __name__ == "__main__":
    main()
