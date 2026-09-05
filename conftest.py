"""Test-collection-time setup, applies to test_api.py (and any other test
module that imports app.api).

Sets COLLISION_DISABLE_AUTH=1 before app/api.py's module import so the
global SSO-JWT auth middleware (see app/api.py's enforce_staff_auth())
skips verification for TestClient requests, which predate that layer and
exercise routes via app.dependency_overrides[get_cursor]/
[get_privileged_cursor] with no Authorization header. Mirrors Elektrica's
identical conftest.py/ELEKTRICA_DISABLE_AUTH pattern exactly. Never set
outside this test process.
"""
import os

os.environ.setdefault("COLLISION_DISABLE_AUTH", "1")
