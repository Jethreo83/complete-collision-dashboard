"""Database connection helper for the Complete Collision app layer.

Same discipline as scripts/run_sql.py: the connection string is read from
an environment variable NAME passed in by the caller, never a literal
value baked into code, so it never lands in shell history / source
control / process listings.

IMPORTANT — role/grant gap, flagged rather than silently worked around:
migrations/001_collision_customer.sql deliberately does NOT grant
collision_app INSERT on platform.person ("collision_app may not write new
person rows directly — creation goes through the identity service's
match-before-create flow, same rule as vls_app and elektrica_app"). No
identity-service API is known to this codebase (out of scope per this
bot's standing VLS-contact boundary, and never described to it for
Elektrica either). This means: whatever DB role the connection string
in COLLISION_DB_URL authenticates as determines whether
repository.create_customer_for_new_person() can actually succeed.
  - Connecting as `collision_app`: INSERT into platform.person will be
    rejected by Postgres (no grant) — this is the intended production
    posture until an identity-service integration exists.
  - Connecting as `neondb_owner` (or another privileged role): INSERT
    will succeed, which is fine for admin scripts / CSV backfills run by
    a human with elevated access, but is NOT how the eventual live
    backend should authenticate day to day.
This module does not choose a role for you — it is the caller's
responsibility to pass a connection string appropriate to what they're
doing. See README's "Open questions" section for this gap.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras


def get_connection(env_var_name: str):
    """Open a new connection using the connection string held in the
    named environment variable. Raises a clear error if unset rather than
    silently trying a default (there is no safe default — the whole point
    is the caller must know which branch/role they're targeting)."""
    conn_string = os.environ.get(env_var_name)
    if not conn_string:
        raise RuntimeError(
            f"Environment variable {env_var_name!r} is not set. Refusing to "
            "guess a default connection — pass the env var name that holds "
            "the Neon connection string for the branch/role you intend to "
            "use (see WORKLOG.md for the branch-name-vs-branch-id neonctl "
            "pitfall before generating a new one)."
        )
    return psycopg2.connect(conn_string)


@contextmanager
def cursor(env_var_name: str, autocommit: bool = False):
    """Context manager yielding a RealDictCursor; commits on clean exit,
    rolls back on exception. autocommit=False by default so multi-step
    repository functions (e.g. get-or-create) are transactional."""
    conn = get_connection(env_var_name)
    conn.autocommit = autocommit
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()
