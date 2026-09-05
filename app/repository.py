"""Repository layer — maps app.models dataclasses to/from the `collision`
Postgres schema (migrations/001-006). All SQL lives here, parametrized
(never string-interpolated), so app code above this layer never writes
raw SQL.

Every write function takes an explicit `actor` string for created_by /
updated_by (matches every table's NOT NULL created_by column) — no
"system" default is silently assumed, since these columns exist
specifically to answer "which staff member/process did this" per the
audit-trail discipline used throughout this schema (append-only
job_event/estimate/cost_entry tables).

See app/db.py's module docstring for the unresolved platform.person
INSERT-grant/identity-service gap that affects create_customer_for_new_person().
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from app.models import (
    ContentItem,
    CostCategory,
    CostEntry,
    Customer,
    DerivedTagsSource,
    Estimate,
    EstimateSource,
    JobCategory,
    JobEvent,
    JobStatus,
    Payment,
    PaymentSource,
    RepairOrder,
    Site,
    StaffUser,
    StaffRole,
    Vehicle,
    VALID_COST_ENTRY_SOURCES,
    VALID_CUSTOMER_SOURCES,
    validate_transition,
)


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------

def get_or_create_site(cur, name: str, actor: str, address: Optional[str] = None) -> Site:
    """Find-or-create by name — no guessed site names are ever inserted
    ahead of a human providing one (ADR-001 §4 / migrations/006 header)."""
    cur.execute("SELECT * FROM collision.site WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return _site_from_row(row)
    cur.execute(
        """
        INSERT INTO collision.site (name, address, created_by)
        VALUES (%s, %s, %s)
        RETURNING *
        """,
        (name, address, actor),
    )
    return _site_from_row(cur.fetchone())


def _site_from_row(row) -> Site:
    return Site(
        id=row["id"], name=row["name"], address=row["address"],
        active=row["active"], created_at=row["created_at"], created_by=row["created_by"],
    )


def get_site_by_id(cur, site_id: int) -> Optional[Site]:
    """Read-only lookup by id. Closes a real gap: collision.site
    (migrations/006, staging only) has had a writer (get_or_create_site())
    since it was created, but no reader anywhere -- nothing HTTP-reachable
    could list sites or look one up directly, which any future site-picker/
    filter UI (dashboard job list already supports filtering jobs by
    site_id via list_repair_orders()) needs. Read-only; site rows are still
    only created via get_or_create_site()'s find-or-create path."""
    cur.execute("SELECT * FROM collision.site WHERE id = %s", (site_id,))
    row = cur.fetchone()
    return _site_from_row(row) if row else None


def list_sites(cur, active_only: bool = False) -> list[Site]:
    """List all sites, ordered by name. active_only=True filters out
    sites soft-deactivated via collision.site.active (no DELETE path for
    sites exists anywhere in this codebase, matching the append-only/
    no-hard-delete discipline used elsewhere in this schema)."""
    if active_only:
        cur.execute("SELECT * FROM collision.site WHERE active = true ORDER BY name")
    else:
        cur.execute("SELECT * FROM collision.site ORDER BY name")
    return [_site_from_row(row) for row in cur.fetchall()]


def set_site_active(cur, site_id: int, active: bool, actor: str) -> Site:
    """Flip a site's active flag -- soft activate/deactivate, same pattern
    as set_staff_user_active(). No hard DELETE path for sites, matching
    the append-only/no-hard-delete discipline used elsewhere in this
    schema (WORKLOG's tracked gap: "no PATCH /sites/{id} ... to
    deactivate a site from the dashboard"). collision.site has no
    updated_at/updated_by columns (migrations/006 only defines
    created_at/created_by), so this UPDATE only touches `active` --
    unlike set_staff_user_active() there is no updated_at/updated_by to
    stamp. `actor` is still required for call-site consistency with every
    other write function in this module even though it is not currently
    persisted; if Jed wants an audit trail on site changes, that is a
    migration adding those columns, not a code-only fix."""
    cur.execute(
        """
        UPDATE collision.site
        SET active = %s
        WHERE id = %s
        RETURNING *
        """,
        (active, site_id),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no site with id={site_id!r}")
    return _site_from_row(row)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

def get_person_by_id(cur, person_id: int) -> Optional[dict]:
    """Read-only lookup against the shared platform.person table (no
    collision-specific dataclass for it -- this codebase never owns
    person rows, see create_person_and_customer()'s docstring). Used to
    give a clean 400 ("no such person_id") instead of an unhandled FK
    violation surfacing as a raw 500 when a caller (e.g. POST /jobs)
    passes a person_id that doesn't exist -- found while smoke-testing
    the new POST /jobs route against real staging (2026-09-07 cycle)."""
    cur.execute("SELECT id FROM platform.person WHERE id = %s", (person_id,))
    return cur.fetchone()


def get_customer_by_person_id(cur, person_id: int) -> Optional[Customer]:
    cur.execute("SELECT * FROM collision.customer WHERE person_id = %s", (person_id,))
    row = cur.fetchone()
    return _customer_from_row(row) if row else None


def get_customer_by_id(cur, customer_id: int) -> Optional[Customer]:
    """Read-only lookup by the customer's own id -- closes a real gap:
    every job route (GET /jobs, GET /jobs/{ro_number}) exposes a bare
    customer_id int (RepairOrderOut.customer_id), and GET
    /customers/{customer_id}/vehicles has taken a customer_id path param
    since the prior cycle, but there was no way to look the customer
    entity itself up by that same id -- only by person_id
    (get_customer_by_person_id(), which requires already knowing the
    person_id, not the customer_id a job response actually gives you).
    A dashboard job-detail view showing "customer source: insurer_referred"
    next to a job's bare customer_id has no route to call today without
    this."""
    cur.execute("SELECT * FROM collision.customer WHERE id = %s", (customer_id,))
    row = cur.fetchone()
    return _customer_from_row(row) if row else None


def create_customer_for_existing_person(
    cur, person_id: int, actor: str, source: str = "walk_in",
    elektrica_renter_ref: Optional[int] = None,
) -> Customer:
    """Link an ALREADY-EXISTING platform.person row to Complete Collision
    as a customer. This is the only customer-creation path this module
    fully supports without the platform.person INSERT-grant gap (see
    app/db.py docstring) — the person must already exist (e.g. looked up
    by email/phone against platform.person, or an Elektrica renter's
    person_id from the cross-business link)."""
    if source not in VALID_CUSTOMER_SOURCES:
        raise ValueError(f"Unknown customer source {source!r}, expected one of {VALID_CUSTOMER_SOURCES}")
    existing = get_customer_by_person_id(cur, person_id)
    if existing:
        return existing
    cur.execute(
        """
        INSERT INTO collision.customer (person_id, source, elektrica_renter_ref, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (person_id, source, elektrica_renter_ref, actor),
    )
    return _customer_from_row(cur.fetchone())


def create_person_and_customer(
    cur, first_name: str, last_name: str, actor: str,
    email: Optional[str] = None, phone: Optional[str] = None,
    source: str = "walk_in",
) -> Customer:
    """Create a BRAND NEW platform.person row and link it as a Complete
    Collision customer in one step.

    *** REQUIRES A PRIVILEGED CONNECTION. *** collision_app has no INSERT
    grant on platform.person (migrations/001, by design, mirroring
    vls_app/elektrica_app — new-person creation is supposed to go through
    a shared identity service this codebase has no access to or
    knowledge of). This function will raise psycopg2.errors.
    InsufficientPrivilege if run under the collision_app role, which is
    the CORRECT behavior for an unresolved architecture gap, not a bug to
    route around. It exists so CSV import / admin scripts run by a human
    with a privileged (neondb_owner-class) connection can onboard a truly
    new customer today, while the real fix (calling or replicating the
    identity service's match-before-create flow) is an open question for
    Jed — see README.md "Open questions".

    *** GAP NOW CLOSED, NOT YET WIRED HERE (per hermes, 2026-09-06):
    platform.match_or_create_person() is live (vls-dashboard migration
    008, tag vls-migration-008-person-match) -- exactly the shared
    identity-service primitive this docstring was waiting on. Match
    logic: phone/email first, then name+DOB; exact matches attach,
    close-but-not-exact queues for human review, NULL DOB never matches,
    no match creates new. NEXT TIME THIS FUNCTION IS TOUCHED: swap the
    raw INSERT below for a call to platform.match_or_create_person() via
    platform_identity_service, instead of blindly creating a new person
    row every time. Not done in this pass (flagged "not urgent" by Jed)
    -- see WORKLOG.md's 2026-09-06 entry for the full context. ***
    """
    email_normalized = email.strip().lower() if email else None
    phone_normalized = phone.strip() if phone else None
    cur.execute(
        """
        INSERT INTO platform.person (first_name, last_name, email_normalized, phone_normalized, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (first_name, last_name, email_normalized, phone_normalized, actor),
    )
    person_id = cur.fetchone()["id"]
    return create_customer_for_existing_person(cur, person_id, actor, source=source)


def _customer_from_row(row) -> Customer:
    return Customer(
        id=row["id"], person_id=row["person_id"], source=row["source"],
        elektrica_renter_ref=row["elektrica_renter_ref"],
        created_at=row["created_at"], created_by=row["created_by"],
    )


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------

def get_vehicle_by_vin(cur, vin: str) -> Optional[Vehicle]:
    cur.execute("SELECT * FROM collision.vehicle WHERE vin = %s", (vin,))
    row = cur.fetchone()
    return _vehicle_from_row(row) if row else None


def get_or_create_vehicle(
    cur, customer_id: int, actor: str, vin: Optional[str] = None,
    make: Optional[str] = None, model: Optional[str] = None, year: Optional[int] = None,
) -> Vehicle:
    """Find-or-create by VIN when a VIN is given (vin is UNIQUE in the
    DB); always creates a new row when vin is None, since VIN-less
    vehicles can't be deduplicated safely (matches the DB's nullable,
    unique-when-present vin column)."""
    if vin:
        existing = get_vehicle_by_vin(cur, vin)
        if existing:
            return existing
    cur.execute(
        """
        INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (vin, make, model, year, customer_id, actor),
    )
    return _vehicle_from_row(cur.fetchone())


def get_vehicles_by_customer(cur, customer_id: int) -> list[Vehicle]:
    cur.execute("SELECT * FROM collision.vehicle WHERE customer_id = %s ORDER BY id", (customer_id,))
    return [_vehicle_from_row(r) for r in cur.fetchall()]


def _vehicle_from_row(row) -> Vehicle:
    return Vehicle(
        id=row["id"], vin=row["vin"], make=row["make"], model=row["model"],
        year=row["year"], customer_id=row["customer_id"],
        created_at=row["created_at"], created_by=row["created_by"],
    )


# ---------------------------------------------------------------------------
# RepairOrder (collision.job)
# ---------------------------------------------------------------------------

def create_repair_order(cur, ro: RepairOrder, actor: str) -> RepairOrder:
    """NOTE (migration 010, 2026-09-06): labor_cost/direct_ro_costs are
    deliberately NOT in this INSERT's column list anymore. Per Jed's
    cost-derivation decision, those two columns are now genuinely
    derived from collision.cost_entry by a DB trigger
    (collision.recalculate_job_costs_trigger()), and collision_app has
    no INSERT/UPDATE grant on them at all (column-level REVOKE) --
    attempting to supply them here would fail with
    insufficient_privilege. Any labor_cost/direct_ro_costs values on the
    passed-in `ro` object are silently ignored for this reason; a new
    job always starts at the column DEFAULT (0) until real cost_entry
    rows exist for it.
    """
    cur.execute(
        """
        INSERT INTO collision.job (
            ro_number, vehicle_id, customer_id, site_id, category, status,
            claim_number, insurer, adjuster_name, posture,
            gross_revenue, rent_utility_share,
            created_by, updated_by
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s
        ) RETURNING *
        """,
        (
            ro.ro_number, ro.vehicle_id, ro.customer_id, ro.site_id,
            ro.category.value, ro.status.value,
            ro.claim_number, ro.insurer, ro.adjuster_name, ro.posture,
            ro.gross_revenue, ro.rent_utility_share,
            actor, actor,
        ),
    )
    row = cur.fetchone()
    # First job_event: creation, from_status NULL.
    cur.execute(
        """
        INSERT INTO collision.job_event (job_id, from_status, to_status, created_by, note)
        VALUES (%s, NULL, %s, %s, %s)
        """,
        (row["id"], ro.status.value, actor, "job created"),
    )
    return _repair_order_from_row(row)


def get_repair_order_by_ro_number(cur, ro_number: str) -> Optional[RepairOrder]:
    cur.execute("SELECT * FROM collision.job WHERE ro_number = %s", (ro_number,))
    row = cur.fetchone()
    return _repair_order_from_row(row) if row else None


def list_repair_orders(
    cur,
    status: Optional[JobStatus] = None,
    category: Optional[JobCategory] = None,
    site_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[RepairOrder]:
    """List/browse jobs with optional filters, newest-opened first.

    Closes a real gap: every existing reader in this module requires
    already knowing a specific ro_number (get_repair_order_by_ro_number)
    -- there was no way to browse/page through jobs at all, which any
    dashboard list view or 'jobs currently in bodywork' filter needs.
    Filters are optional and AND-combined; all-None returns everything
    (paginated). limit is capped at 200 server-side so a caller can't
    accidentally request the entire table in one call.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    clauses = []
    params: list = []
    if status is not None:
        clauses.append("status = %s")
        params.append(status.value)
    if category is not None:
        clauses.append("category = %s")
        params.append(category.value)
    if site_id is not None:
        clauses.append("site_id = %s")
        params.append(site_id)
    if customer_id is not None:
        clauses.append("customer_id = %s")
        params.append(customer_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    cur.execute(
        f"""
        SELECT * FROM collision.job
        {where_sql}
        ORDER BY opened_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        params,
    )
    return [_repair_order_from_row(r) for r in cur.fetchall()]


def get_jobs_closed_in_month(cur, site_id: int, month: str) -> list[RepairOrder]:
    """Jobs at site_id with closed_at falling in `month` (YYYY-MM).
    Feeds app/settlement.py's PDR Crew monthly settlement build (ADR-001
    §7) — a job still open (closed_at IS NULL) has no final numbers to
    settle, so it is never included regardless of when it was opened.
    Caller (app/settlement.py) is responsible for validating `month`'s
    format; this function trusts a well-formed 'YYYY-MM' string, same
    division of responsibility as list_repair_orders()'s caller-validated
    enum filters."""
    cur.execute(
        """
        SELECT * FROM collision.job
        WHERE site_id = %s
          AND closed_at IS NOT NULL
          AND to_char(closed_at, 'YYYY-MM') = %s
        ORDER BY closed_at, id
        """,
        (site_id, month),
    )
    return [_repair_order_from_row(r) for r in cur.fetchall()]


def transition_job_status(
    cur, ro_number: str, target: JobStatus, actor: str, note: Optional[str] = None,
) -> RepairOrder:
    """Validate (app-layer, per migrations/002's SIMPLIFICATION note —
    no DB trigger exists yet) then apply a status transition, recording a
    JobEvent. Raises ValueError on an illegal transition before touching
    the DB."""
    current = get_repair_order_by_ro_number(cur, ro_number)
    if current is None:
        raise ValueError(f"No job with ro_number={ro_number!r}")
    validate_transition(current.status, target)
    cur.execute(
        """
        UPDATE collision.job SET status = %s, updated_at = now(), updated_by = %s
        WHERE ro_number = %s
        RETURNING *
        """,
        (target.value, actor, ro_number),
    )
    row = cur.fetchone()
    cur.execute(
        """
        INSERT INTO collision.job_event (job_id, from_status, to_status, created_by, note)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (row["id"], current.status.value, target.value, actor, note),
    )
    return _repair_order_from_row(row)


class _Unset:
    """Sentinel type for update_job_intake_fields() -- see its docstring.
    Defined here (before first use) since Python evaluates default
    argument values at function-definition time, not call time."""
    def __repr__(self):
        return "UNSET"


_UNSET = _Unset()


def update_job_intake_fields(
    cur, ro_number: str, actor: str,
    claim_number=_UNSET, insurer=_UNSET, adjuster_name=_UNSET, posture=_UNSET,
) -> RepairOrder:
    """Revise intake-time fields after creation (flagged as a real gap in
    the 2026-09-06 WORKLOG's "Next up" list -- create_repair_order() made
    these write-once, but Phase 1 CSV/manual entry commonly learns the
    claim number, insurer, adjuster, or posture AFTER the initial RO
    intake row exists, not at creation time).

    Uses a sentinel (`_UNSET`) rather than relying on `None` to mean
    "leave unchanged", because these columns are legitimately nullable --
    a caller must be able to explicitly clear e.g. adjuster_name back to
    NULL (adjuster reassigned, claim dropped) without that being
    indistinguishable from "field not supplied". Only fields explicitly
    passed (not _UNSET) are included in the UPDATE.

    Deliberately does NOT touch status (use transition_job_status(), which
    also validates the state machine and records a job_event) or any of
    the cost/revenue columns (write-once at creation or DB-trigger-derived
    per migration 010 -- see create_repair_order()'s own docstring).
    """
    current = get_repair_order_by_ro_number(cur, ro_number)
    if current is None:
        raise ValueError(f"No job with ro_number={ro_number!r}")

    fields = {
        "claim_number": claim_number, "insurer": insurer,
        "adjuster_name": adjuster_name, "posture": posture,
    }
    to_set = {k: v for k, v in fields.items() if v is not _UNSET}
    if not to_set:
        return current  # nothing to do; not an error -- a no-op PATCH is valid

    set_clause = ", ".join(f"{col} = %s" for col in to_set)
    cur.execute(
        f"""
        UPDATE collision.job SET {set_clause}, updated_at = now(), updated_by = %s
        WHERE ro_number = %s
        RETURNING *
        """,
        (*to_set.values(), actor, ro_number),
    )
    return _repair_order_from_row(cur.fetchone())


def list_job_events(cur, ro_number: str) -> list[JobEvent]:
    cur.execute(
        """
        SELECT je.* FROM collision.job_event je
        JOIN collision.job j ON j.id = je.job_id
        WHERE j.ro_number = %s
        ORDER BY je.occurred_at
        """,
        (ro_number,),
    )
    return [_job_event_from_row(r) for r in cur.fetchall()]


def _repair_order_from_row(row) -> RepairOrder:
    return RepairOrder(
        id=row["id"], ro_number=row["ro_number"], vehicle_id=row["vehicle_id"],
        customer_id=row["customer_id"], site_id=row["site_id"],
        category=JobCategory(row["category"]), status=JobStatus(row["status"]),
        claim_number=row["claim_number"], insurer=row["insurer"],
        adjuster_name=row["adjuster_name"], posture=row["posture"],
        gross_revenue=row["gross_revenue"], direct_ro_costs=row["direct_ro_costs"],
        labor_cost=row["labor_cost"], rent_utility_share=row["rent_utility_share"],
        ccc_one_last_reconciled_at=row["ccc_one_last_reconciled_at"],
        opened_at=row["opened_at"], closed_at=row["closed_at"], collected_at=row["collected_at"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        created_by=row["created_by"], updated_by=row["updated_by"],
    )


def _job_event_from_row(row) -> JobEvent:
    return JobEvent(
        id=row["id"], job_id=row["job_id"],
        from_status=JobStatus(row["from_status"]) if row["from_status"] else None,
        to_status=JobStatus(row["to_status"]), occurred_at=row["occurred_at"],
        created_by=row["created_by"], note=row["note"],
    )


# ---------------------------------------------------------------------------
# CostEntry — itemized ledger
# ---------------------------------------------------------------------------

def add_cost_entry(cur, entry: CostEntry, actor: str) -> CostEntry:
    if entry.source not in VALID_COST_ENTRY_SOURCES:
        raise ValueError(f"Unknown cost entry source {entry.source!r}, expected one of {VALID_COST_ENTRY_SOURCES}")
    if entry.amount < 0:
        raise ValueError("cost_entry amount must be >= 0 (DB CHECK constraint mirrors this)")
    cur.execute(
        """
        INSERT INTO collision.cost_entry (
            job_id, category, description, amount, incurred_at, source, source_file, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            entry.job_id, entry.category.value, entry.description, entry.amount,
            entry.incurred_at or date.today(), entry.source, entry.source_file, actor,
        ),
    )
    return _cost_entry_from_row(cur.fetchone())


def list_cost_entries(cur, ro_number: str) -> list[CostEntry]:
    cur.execute(
        """
        SELECT ce.* FROM collision.cost_entry ce
        JOIN collision.job j ON j.id = ce.job_id
        WHERE j.ro_number = %s
        ORDER BY ce.incurred_at, ce.id
        """,
        (ro_number,),
    )
    return [_cost_entry_from_row(r) for r in cur.fetchall()]


def recalculate_costs_from_entries(cur, ro_number: str, actor: str) -> RepairOrder:
    """SUPERSEDED (migration 010, 2026-09-06). This function's original
    job -- explicit, opt-in reconciliation of collision.job's flat cost
    columns from itemized collision.cost_entry rows -- is now handled
    automatically by a DB trigger (collision.recalculate_job_costs_
    trigger()) firing on every cost_entry write, per Jed's decision that
    labor_cost/direct_ro_costs should be fully derived, not
    separately-entered-then-optionally-reconciled. collision_app also
    no longer has UPDATE/INSERT privilege on those two specific columns
    (migration 010's REVOKE), so the UPDATE below would now fail with
    insufficient_privilege under a real app connection.

    Kept in the codebase (not deleted) as a no-op passthrough rather
    than removed outright, so any existing caller (this session found
    test_api.py and scripts/_smoke_repository.py both called it) gets a
    correct, already-current job back instead of a hard break -- same
    reasoning as api.py's /costs/recalculate route above it. A real
    cleanup pass removing this function AND its two callers is a
    reasonable follow-up, not done here to keep this migration's
    application-layer fix minimal and reviewable.
    """
    return get_repair_order_by_ro_number(cur, ro_number)



def _cost_entry_from_row(row) -> CostEntry:
    return CostEntry(
        id=row["id"], job_id=row["job_id"], category=CostCategory(row["category"]),
        description=row["description"], amount=row["amount"], incurred_at=row["incurred_at"],
        source=row["source"], source_file=row["source_file"],
        created_at=row["created_at"], created_by=row["created_by"],
    )


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------

def create_manual_estimate(cur, job_id: int, content: dict, actor: str) -> Estimate:
    """Phase 1 only writes source=MANUAL, confirmed at creation (per the
    DB's CHECK constraint and Estimate.__post_init__ mirroring it)."""
    cur.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM collision.estimate WHERE job_id = %s",
        (job_id,),
    )
    next_version = cur.fetchone()["next_version"]
    now = datetime.now()
    estimate = Estimate(
        job_id=job_id, version=next_version, source=EstimateSource.MANUAL,
        draft_content=content, confirmed_content=content, confirmed_by=actor, confirmed_at=now,
    )
    cur.execute(
        """
        INSERT INTO collision.estimate (
            job_id, version, source, draft_content, confirmed_content, confirmed_by, confirmed_at, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            job_id, next_version, EstimateSource.MANUAL.value,
            psycopg2_json(content), psycopg2_json(content), actor, now, actor,
        ),
    )
    return _estimate_from_row(cur.fetchone())


def psycopg2_json(d: dict):
    import json
    import psycopg2.extras
    return psycopg2.extras.Json(d) if d is not None else None


def _estimate_from_row(row) -> Estimate:
    return Estimate(
        id=row["id"], job_id=row["job_id"], version=row["version"],
        source=EstimateSource(row["source"]), draft_content=row["draft_content"],
        confirmed_content=row["confirmed_content"], confirmed_by=row["confirmed_by"],
        confirmed_at=row["confirmed_at"], created_at=row["created_at"], created_by=row["created_by"],
    )


def get_estimates_for_job(cur, ro_number: str) -> list[Estimate]:
    """All estimate versions for a job, oldest first -- matches
    collision.estimate's own idx_estimate_job (job_id, version) index
    order. No reader existed for this table before now; app/api.py's
    /jobs/{ro_number} response never included estimate history, so this
    closes a real gap (repository.py had create_manual_estimate() but no
    corresponding list function)."""
    cur.execute(
        """
        SELECT e.* FROM collision.estimate e
        JOIN collision.job j ON j.id = e.job_id
        WHERE j.ro_number = %s
        ORDER BY e.version
        """,
        (ro_number,),
    )
    return [_estimate_from_row(r) for r in cur.fetchall()]


def get_latest_estimate_for_job(cur, ro_number: str) -> Optional[Estimate]:
    estimates = get_estimates_for_job(cur, ro_number)
    return estimates[-1] if estimates else None


# ---------------------------------------------------------------------------
# ContentItem (migrations/005, PRODUCTION since 2026-09-04 -- schema only
# until this cycle; no app layer existed for it before now). See
# app/models.ContentItem's docstring for the two write paths this
# supports (dashboard-native upload vs. a future bulk JSON import from
# content_manifest.json, the latter still blocked on export access to
# "the mini" per every prior WORKLOG entry -- NOT built here).
# ---------------------------------------------------------------------------

_CONTENT_ITEM_COLUMNS = [
    "source_manifest_id", "import_source_file", "business", "collection",
    "description", "drive_id", "filename", "mime", "proxy_url", "ro_number",
    "service", "size", "smr", "source", "stage", "status", "thumbnail",
    "type", "uploaded_at", "uploader", "url", "video_type", "web_view_link",
]


def create_content_item(cur, item: ContentItem, actor: str) -> ContentItem:
    """Dashboard-native content upload (Phase 1 path). Does not touch
    derived_tags/derived_tags_source at creation -- those start at the
    DB's own default ([]/'unset') and are only ever set afterward via
    update_content_item_tags(), so it's always explicit which mechanism
    (ai/human) supplied a given tag set, never silently defaulted."""
    values = [getattr(item, col) for col in _CONTENT_ITEM_COLUMNS]
    placeholders = ", ".join(["%s"] * len(_CONTENT_ITEM_COLUMNS))
    cur.execute(
        f"""
        INSERT INTO collision.content_item (
            {", ".join(_CONTENT_ITEM_COLUMNS)}, created_by, updated_by
        ) VALUES ({placeholders}, %s, %s)
        RETURNING *
        """,
        (*values, actor, actor),
    )
    return _content_item_from_row(cur.fetchone())


def get_content_item_by_id(cur, content_item_id: int) -> Optional[ContentItem]:
    cur.execute("SELECT * FROM collision.content_item WHERE id = %s", (content_item_id,))
    row = cur.fetchone()
    return _content_item_from_row(row) if row else None


def list_content_items_for_job(cur, ro_number: str) -> list[ContentItem]:
    """Handoff §3.1's 'by RO' view -- a tolerant equality join, not a
    hard FK (migrations/005's own header: the real manifest may reference
    ROs that don't exist yet in collision.job)."""
    cur.execute(
        """
        SELECT * FROM collision.content_item
        WHERE ro_number = %s
        ORDER BY uploaded_at NULLS LAST, id
        """,
        (ro_number,),
    )
    return [_content_item_from_row(r) for r in cur.fetchall()]


def search_content_items(
    cur, query: Optional[str] = None, limit: int = 50, offset: int = 0,
) -> list[ContentItem]:
    """Handoff §3.1's 'search across tags/description' need -- uses the
    same to_tsvector(description) expression migrations/005 already
    indexed (idx_content_item_description_fts), plus a plain substring
    check against derived_tags so a tag-only search (no description text)
    still matches, since GIN-over-jsonb doesn't directly support ILIKE."""
    if query:
        cur.execute(
            """
            SELECT * FROM collision.content_item
            WHERE to_tsvector('english', coalesce(description, '')) @@ to_tsquery('english', %s)
               OR derived_tags::text ILIKE %s
            ORDER BY uploaded_at NULLS LAST, id
            LIMIT %s OFFSET %s
            """,
            (query.replace(" ", " & "), f"%{query}%", limit, offset),
        )
    else:
        cur.execute(
            "SELECT * FROM collision.content_item ORDER BY uploaded_at NULLS LAST, id LIMIT %s OFFSET %s",
            (limit, offset),
        )
    return [_content_item_from_row(r) for r in cur.fetchall()]


def update_content_item_tags(
    cur, content_item_id: int, derived_tags: list, derived_tags_source: DerivedTagsSource, actor: str,
) -> ContentItem:
    """The only way derived_tags/derived_tags_source ever change after
    creation -- always records which mechanism (ai/human) supplied the
    tags, per handoff §3.1's 'AI-assisted, human-editable' requirement.
    Full replace, not merge (matches migrations/005's plain JSONB array
    shape -- no per-tag identity to merge against)."""
    cur.execute(
        """
        UPDATE collision.content_item
        SET derived_tags = %s, derived_tags_source = %s, updated_at = now(), updated_by = %s
        WHERE id = %s
        RETURNING *
        """,
        (psycopg2_json(derived_tags), derived_tags_source.value, actor, content_item_id),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no content_item with id={content_item_id!r}")
    return _content_item_from_row(row)


def _content_item_from_row(row) -> ContentItem:
    return ContentItem(
        id=row["id"], source_manifest_id=row["source_manifest_id"],
        import_source_file=row["import_source_file"], business=row["business"],
        collection=row["collection"], description=row["description"],
        drive_id=row["drive_id"], filename=row["filename"], mime=row["mime"],
        proxy_url=row["proxy_url"], ro_number=row["ro_number"], service=row["service"],
        size=row["size"], smr=row["smr"], source=row["source"], stage=row["stage"],
        status=row["status"], thumbnail=row["thumbnail"], type=row["type"],
        uploaded_at=row["uploaded_at"], uploader=row["uploader"], url=row["url"],
        video_type=row["video_type"], web_view_link=row["web_view_link"],
        derived_tags=row["derived_tags"] if row["derived_tags"] is not None else [],
        derived_tags_source=DerivedTagsSource(row["derived_tags_source"]),
        created_at=row["created_at"], created_by=row["created_by"],
        updated_at=row["updated_at"], updated_by=row["updated_by"],
    )


# ---------------------------------------------------------------------------
# Payment (migrations/011, STAGING ONLY -- collision.payment not yet
# promoted to production; see migrations/011's header and
# WORKLOG.md 2026-09-04 for the payment_source enum question still
# awaiting Jed's confirmation).
#
# Append-only per the DB's own forbid-mutation trigger: no update/void
# function exists here on purpose (a correction is a new row -- e.g. a
# negative-amount reversal is NOT supported either, since the DB CHECK
# requires amount > 0; a real reversal design is a genuine open question
# for whenever this gets promoted, not guessed at here).
# ---------------------------------------------------------------------------

def create_payment(cur, payment: Payment, actor: str) -> Payment:
    """Payment.__post_init__ already mirrors the DB's amount>0 and
    authorize_net/external_transaction_id CHECK constraints, so a bad
    call fails fast in Python with a clear ValueError before ever
    reaching the DB -- same belt-and-suspenders pattern as CostEntry/
    StaffUser. Does not verify job_id exists here; the DB's FK
    (collision.payment.job_id REFERENCES collision.job) is the real
    enforcement, and the API layer is responsible for translating that
    into a clean 404 (see app/api.py's POST /jobs/{ro}/payments, same
    pattern as POST /jobs/{ro}/costs and POST /jobs/{ro}/estimates)."""
    cur.execute(
        """
        INSERT INTO collision.payment (
            job_id, source, external_transaction_id, amount, received_at,
            accounting_sync_ref, created_by
        ) VALUES (%s, %s, %s, %s, COALESCE(%s, now()), %s, %s)
        RETURNING *
        """,
        (
            payment.job_id, payment.source.value, payment.external_transaction_id,
            payment.amount, payment.received_at, payment.accounting_sync_ref, actor,
        ),
    )
    return _payment_from_row(cur.fetchone())


def list_payments_for_job(cur, ro_number: str) -> list[Payment]:
    cur.execute(
        """
        SELECT p.* FROM collision.payment p
        JOIN collision.job j ON j.id = p.job_id
        WHERE j.ro_number = %s
        ORDER BY p.received_at, p.id
        """,
        (ro_number,),
    )
    return [_payment_from_row(r) for r in cur.fetchall()]


def get_job_payment_summary(cur, ro_number: str) -> Optional[dict]:
    """Reads collision.job_payment_summary (migrations/011's view) for
    one job by ro_number. Returns a plain dict (not a dataclass -- this
    is a derived/aggregate read, not an entity with its own identity or
    writes, same treatment as any other summary view in this codebase).
    Returns None if the ro_number itself doesn't exist (distinguishes
    "no such job" from "job exists, zero payments," which the view
    itself already handles via its LEFT JOIN -- see migrations/011's
    CHECK 1)."""
    cur.execute(
        """
        SELECT jps.* FROM collision.job_payment_summary jps
        JOIN collision.job j ON j.id = jps.job_id
        WHERE j.ro_number = %s
        """,
        (ro_number,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _payment_from_row(row) -> Payment:
    return Payment(
        id=row["id"], job_id=row["job_id"], source=PaymentSource(row["source"]),
        external_transaction_id=row["external_transaction_id"], amount=row["amount"],
        received_at=row["received_at"], accounting_sync_ref=row["accounting_sync_ref"],
        created_at=row["created_at"], created_by=row["created_by"],
    )


# ---------------------------------------------------------------------------
# StaffUser — provisioning
#
# Closes the real gap flagged 2026-09-06 (Jed's item 3): "staff
# provisioning should also create a platform.person row" -- previously
# no function existed that created both rows together in one
# transaction. collision.staff_user.person_id is NOT NULL REFERENCES
# platform.person(id) at the schema level (migrations/004) already, but
# nothing in app/repository.py exercised the find-or-create-person half
# of that requirement for staff (only create_person_and_customer() did,
# for customers).
#
# Same privileged-connection caveat as create_person_and_customer():
# creating a genuinely NEW platform.person row requires a role with
# INSERT on platform.person, which collision_app does NOT have
# (migrations/001, by design -- identity-service match-before-create
# gap, documented in app/db.py). provision_staff_user_for_existing_person()
# has no such requirement (it only touches collision.staff_user, which
# collision_app can write) -- that's the function a day-to-day backend
# should call once a person already exists; the full
# provision_new_staff_user() convenience wrapper is for an admin script
# run under a privileged connection, exactly like
# create_person_and_customer().
# ---------------------------------------------------------------------------

def get_staff_user_by_google_email(cur, google_email: str) -> Optional[StaffUser]:
    cur.execute(
        "SELECT * FROM collision.staff_user WHERE google_email = %s",
        (google_email.strip().lower(),),
    )
    row = cur.fetchone()
    return _staff_user_from_row(row) if row else None


def list_staff_users(cur, active_only: bool = False, role: Optional[StaffRole] = None) -> list[StaffUser]:
    """List all staff_user rows, ordered by google_email -- closes a real
    gap: POST /staff (provision) and GET /staff/{google_email} (single
    lookup) have existed since the 2026-09-06 cycle, but nothing could
    list the whole roster, which a dashboard "staff directory"/admin
    view needs (the same "writer with no collection reader" gap
    list_sites() closed for collision.site the prior cycle). Optional
    active_only mirrors list_sites()'s own filter; optional role filter
    is new here since staff (unlike sites) has a meaningful role
    dimension to filter a directory view by."""
    clauses = []
    params: list = []
    if active_only:
        clauses.append("active = true")
    if role is not None:
        clauses.append("role = %s")
        params.append(role.value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    cur.execute(f"SELECT * FROM collision.staff_user{where} ORDER BY google_email", params)
    return [_staff_user_from_row(row) for row in cur.fetchall()]


def provision_staff_user_for_existing_person(
    cur, person_id: int, role: StaffRole, google_email: str, actor: str,
    provisioned_by_staff_user_id: Optional[int] = None,
) -> StaffUser:
    """Link an ALREADY-EXISTING platform.person row as a Complete
    Collision staff_user. Runs fine under collision_app (no
    platform.person write involved) -- this is the function a real
    provisioning UI/API should call once the person row already exists
    (e.g. found by email, or created moments earlier by an admin
    script)."""
    existing = get_staff_user_by_google_email(cur, google_email)
    if existing:
        raise ValueError(f"staff_user with google_email={google_email!r} already exists")
    # Constructing StaffUser first runs its own __post_init__ domain
    # validation (app/models.py) before this ever reaches the DB --
    # same "reject bad data in Python before the query" discipline as
    # Estimate.
    staff = StaffUser(
        person_id=person_id, role=role, google_email=google_email,
        provisioned_by_staff_user_id=provisioned_by_staff_user_id,
    )
    cur.execute(
        """
        INSERT INTO collision.staff_user (
            person_id, role, google_email, provisioned_by_staff_user_id,
            created_by, updated_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            staff.person_id, staff.role.value, staff.google_email,
            staff.provisioned_by_staff_user_id, actor, actor,
        ),
    )
    return _staff_user_from_row(cur.fetchone())


def provision_new_staff_user(
    cur, first_name: str, last_name: str, role: StaffRole, google_email: str, actor: str,
    provisioned_by_staff_user_id: Optional[int] = None,
) -> StaffUser:
    """Creates a BRAND NEW platform.person row AND its collision.staff_user
    row in one transaction.

    *** REQUIRES A PRIVILEGED CONNECTION *** -- same platform.person
    INSERT-grant gap as create_person_and_customer() (see that
    function's docstring and app/db.py's module docstring). Raises
    psycopg2.errors.InsufficientPrivilege under collision_app, which is
    correct: a real backend authenticating as collision_app should call
    provision_staff_user_for_existing_person() against a person row an
    admin already created, not this convenience wrapper.

    *** GAP NOW CLOSED, NOT YET WIRED HERE (per hermes, 2026-09-06):
    same platform.match_or_create_person() note as
    create_person_and_customer()'s docstring above -- NEXT TIME THIS
    FUNCTION IS TOUCHED, swap the raw INSERT below for a call to
    platform.match_or_create_person() via platform_identity_service
    instead of blindly creating a new person row every time a staff
    member is provisioned (a real staff member could plausibly already
    exist as a platform.person from being a customer/renter elsewhere in
    the shared schema -- exactly the cross-business case this bot's own
    memory tracks). Not done in this pass; see WORKLOG.md's 2026-09-06
    entry. ***
    """
    email_normalized = google_email.strip().lower()
    cur.execute(
        """
        INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (first_name, last_name, email_normalized, actor),
    )
    person_id = cur.fetchone()["id"]
    return provision_staff_user_for_existing_person(
        cur, person_id, role, google_email, actor,
        provisioned_by_staff_user_id=provisioned_by_staff_user_id,
    )


def set_staff_user_active(cur, google_email: str, active: bool, actor: str) -> StaffUser:
    """Flip a staff member's active flag -- the same lever
    scripts/verify_007.sql's test exercises to prove
    staff_user_capability() genuinely responds to deactivation, now
    exposed as a real repository function rather than only inline test
    SQL."""
    cur.execute(
        """
        UPDATE collision.staff_user
        SET active = %s, updated_at = now(), updated_by = %s
        WHERE google_email = %s
        RETURNING *
        """,
        (active, actor, google_email.strip().lower()),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no staff_user with google_email={google_email!r}")
    return _staff_user_from_row(row)


def get_staff_capability(cur, google_email: str) -> Optional[str]:
    """Calls collision.staff_user_capability() (migrations/007) -- the
    real, callable permission gate. Returns the capability level for an
    active staff member, or None (SQL NULL) for anyone not currently
    active."""
    cur.execute(
        "SELECT collision.staff_user_capability(%s) AS capability_level",
        (google_email.strip().lower(),),
    )
    row = cur.fetchone()
    return row["capability_level"] if row else None


def _staff_user_from_row(row) -> StaffUser:
    return StaffUser(
        id=row["id"], person_id=row["person_id"], role=StaffRole(row["role"]),
        google_email=row["google_email"], active=row["active"],
        provisioned_by_staff_user_id=row["provisioned_by_staff_user_id"],
        created_at=row["created_at"], created_by=row["created_by"],
        updated_at=row["updated_at"], updated_by=row["updated_by"],
    )
