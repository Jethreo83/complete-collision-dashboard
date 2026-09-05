"""Phase 1 HTTP API — thin FastAPI wrapper over app/repository.py.

Scope discipline, same as every other file in this repo:
  - No CCC ONE contact of any kind. Every endpoint here reads/writes only
    Complete Collision's own `collision` schema via the repository layer
    that already enforces Phase 1's manual/CSV-only rule.
  - No authentication/session/role enforcement yet. `collision.
    staff_user_capability()` (migrations/007) is the real permission gate
    once a caller identity exists to check it against -- there is no
    session/auth mechanism in this codebase yet to supply that identity,
    so wiring a route-guard now would be guessing at unbuilt
    architecture, not enforcing a real decision (same reasoning as
    migrations/007's own header). Every route here is currently
    unauthenticated by design, matching the "not yet built" item in
    README.md, and is NOT wired to any process that exposes it
    externally -- this module is CLI/local-server only until Jed
    approves an actual deploy.
  - Connection string comes from the environment variable named by
    COLLISION_DB_ENV_VAR (default "DATABASE_URL"), read once at request
    time via app.db.cursor() -- never hardcoded, matching app/db.py's own
    discipline.

Run locally (never exposed): `uvicorn app.api:app --reload --port 8000`.
Nothing in this repo starts that process automatically; it must be run by
a human on demand until a real deploy decision is made.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import csv_import
from app import db
from app import repository as repo
from app import settlement as settlement_mod
from app.normalize import normalize_email, normalize_phone
from app.models import (
    ContentItem, CostCategory, DerivedTagsSource, JobCategory, JobStatus,
    PaymentSource, RepairOrder, StaffRole,
)

app = FastAPI(
    title="Complete Collision Dashboard API (Phase 1, internal/local only)",
    version="0.1.0",
)


def get_db_env_var() -> str:
    return os.environ.get("COLLISION_DB_ENV_VAR", "DATABASE_URL")


def get_cursor():
    """FastAPI dependency yielding a transactional cursor, exactly like
    app/db.cursor()'s context manager. Overridden in tests so no test run
    ever needs a real database connection."""
    env_var = get_db_env_var()
    with db.cursor(env_var) as cur:
        yield cur


def get_privileged_cursor():
    """FastAPI dependency for the one route that needs a connection whose
    LOGIN role itself is allowed to call platform.match_or_create_person()
    -- currently only POST /customers/intake (see
    app.repository.match_or_create_and_link_customer()'s docstring).
    Modeled directly on Elektrica's get_privileged_cursor() (same repo
    family, same underlying grant gap, confirmed independently against
    real staging Postgres for Collision this cycle: platform_identity_service
    has EXECUTE on platform.match_or_create_person(), collision_app has
    zero pg_auth_members rows granting it that role or a direct grant).

    Same env var as get_cursor() (COLLISION_DB_ENV_VAR) but never sets a
    role -- connects as whatever LOGIN role the connection string
    authenticates as (neondb_owner-class in every environment this repo
    has run in so far), the same "admin-script escape hatch" pattern
    app/db.py's own module docstring documents for person-row creation.
    This module has no notion of "SET ROLE collision_app on every other
    route" today (app/db.cursor() takes no set_role param, unlike
    Elektrica's), so this is currently identical to get_cursor() in
    practice -- kept as its own named dependency anyway so the intent
    (this route needs elevated access) is documented at the call site,
    not just in a comment, and so it does not silently break if/when
    get_cursor() ever does start pinning a lower-privileged role."""
    env_var = get_db_env_var()
    with db.cursor(env_var) as cur:
        yield cur


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RepairOrderOut(BaseModel):
    id: int
    ro_number: str
    vehicle_id: int
    customer_id: int
    site_id: int
    category: str
    status: str
    claim_number: Optional[str] = None
    insurer: Optional[str] = None
    adjuster_name: Optional[str] = None
    posture: Optional[str] = None
    gross_revenue: Decimal
    direct_ro_costs: Decimal
    labor_cost: Decimal
    rent_utility_share: Decimal
    net_profit: Decimal


class JobEventOut(BaseModel):
    id: int
    job_id: int
    from_status: Optional[str] = None
    to_status: str
    created_by: Optional[str] = None
    note: Optional[str] = None


class TransitionRequest(BaseModel):
    target_status: str
    actor: str
    note: Optional[str] = None


class JobIntakeUpdateRequest(BaseModel):
    """PATCH body for update_job_intake_fields() (2026-09-06 WORKLOG
    "Next up" item #1). All fields optional -- a field simply absent from
    the JSON body means "leave unchanged"; a field explicitly present with
    a JSON `null` means "clear it to NULL". FastAPI/pydantic distinguish
    those two cases via `.dict(exclude_unset=True)` in the route below, not
    via this schema's defaults alone -- see the route for how the
    exclude_unset dict is translated into repo._UNSET sentinels."""
    claim_number: Optional[str] = None
    insurer: Optional[str] = None
    adjuster_name: Optional[str] = None
    posture: Optional[str] = None
    actor: str


class CostEntryOut(BaseModel):
    id: int
    job_id: int
    category: str
    description: Optional[str] = None
    amount: Decimal
    incurred_at: Optional[date] = None
    source: str
    source_file: Optional[str] = None


class CostEntryIn(BaseModel):
    category: str
    amount: Decimal
    actor: str
    description: Optional[str] = None
    incurred_at: Optional[date] = None
    source: str = "manual"
    source_file: Optional[str] = None


class RecalculateRequest(BaseModel):
    actor: str


class ImportReportOut(BaseModel):
    """Mirrors app.csv_import.ImportReport (dataclass -> pydantic, plus a
    computed `ok` bool since ImportReport.ok() is a method, not a field)."""
    file: str
    dry_run: bool
    total_rows: int
    created: int
    updated: int
    skipped: int
    errors: list[str]
    ok: bool


class EstimateOut(BaseModel):
    id: int
    job_id: int
    version: int
    source: str
    draft_content: Optional[dict] = None
    confirmed_content: Optional[dict] = None
    confirmed_by: Optional[str] = None


class PaymentOut(BaseModel):
    """Mirrors collision.payment (migrations/011, STAGING ONLY -- not yet
    promoted to production; see migrations/011 header and WORKLOG.md
    2026-09-04 for the payment_source enum question awaiting Jed's
    confirmation). These routes work against whatever DB the connection
    string points at -- if run against production before promotion, the
    underlying SQL will fail with a real "relation does not exist"
    error (no silent fallback), which is the correct behavior rather
    than this app layer trying to guess/gate environments itself."""
    id: int
    job_id: int
    source: str
    external_transaction_id: Optional[str] = None
    amount: Decimal
    received_at: str
    accounting_sync_ref: Optional[str] = None


class PaymentCreateRequest(BaseModel):
    source: str
    amount: Decimal
    actor: str
    external_transaction_id: Optional[str] = None
    received_at: Optional[str] = None  # ISO 8601; None lets the DB default to now()
    accounting_sync_ref: Optional[str] = None


class JobPaymentSummaryOut(BaseModel):
    job_id: int
    ro_number: str
    total_collected: Decimal
    payment_count: int
    last_payment_at: Optional[str] = None


class CustomerOut(BaseModel):
    """Mirrors collision.customer (migrations/001). Closes a real gap:
    repo.get_customer_by_person_id()/get_vehicles_by_customer()/
    get_vehicle_by_vin() have existed since migration 001's app layer but
    were never wired to an HTTP route -- every existing route that reads
    a customer/vehicle does so only as a side effect of a job lookup
    (RepairOrderOut exposes bare customer_id/vehicle_id ints, no way to
    look the entity itself up directly). This is a read-only lookup
    route; customer/vehicle creation stays inside POST /jobs and
    csv_import.py's find-or-create paths, unchanged."""
    id: int
    person_id: int
    source: str
    elektrica_renter_ref: Optional[int] = None


class CustomerIntakeRequest(BaseModel):
    """Body for POST /customers/intake -- the real identity-resolution
    intake path via app.repository.match_or_create_and_link_customer(),
    closing the gap create_person_and_customer()'s docstring has flagged
    since migration 001. Only first_name/last_name/actor are required --
    date_of_birth/email/phone are all optional inputs to the SAME
    underlying platform.match_or_create_person() call (a walk-in intake
    may legitimately supply only some of them), but supplying NEITHER
    email NOR phone NOR (last_name+date_of_birth) means the match
    function has nothing to match on and will always create a new
    person -- that is the function's own documented behavior, not a bug
    introduced by this route. email/phone are normalized here
    (app.normalize) before the repository call, same convention as
    Elektrica's POST /renters/intake."""
    first_name: str
    last_name: str
    actor: str
    date_of_birth: Optional[date] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: str = "walk_in"


class CustomerIntakeOut(BaseModel):
    match_status: str  # 'attached' | 'queued' | 'created'
    person_id: int
    queue_id: Optional[int] = None
    customer: Optional[CustomerOut] = None


class VehicleOut(BaseModel):
    id: int
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    customer_id: int


class SiteOut(BaseModel):
    """Mirrors collision.site (migrations/006, STAGING ONLY -- not yet
    promoted to production, same posture as migration 011; see README's
    'Open questions'/migration 006 header for the pending cost-category
    review, which is a separate question from this table's own shape).
    Closes a real gap: collision.site has had a writer
    (get_or_create_site(), used by POST /jobs and the CSV importers) since
    migration 006, but no reader anywhere in the app layer -- no way to
    list sites or look one up by id, which any dashboard site-picker/
    filter UI needs (GET /jobs already supports filtering by site_id but
    nothing could tell a caller what site_ids exist)."""
    id: int
    name: str
    address: Optional[str] = None
    active: bool


class ContentItemOut(BaseModel):
    """Mirrors collision.content_item (migrations/005, production).
    All manifest fields optional except filename -- see
    app.models.ContentItem's docstring for why (real content_manifest.json
    import still blocked on export access to "the mini")."""
    id: int
    filename: str
    source_manifest_id: Optional[str] = None
    import_source_file: Optional[str] = None
    business: Optional[str] = None
    collection: Optional[str] = None
    description: Optional[str] = None
    drive_id: Optional[str] = None
    mime: Optional[str] = None
    proxy_url: Optional[str] = None
    ro_number: Optional[str] = None
    service: Optional[str] = None
    size: Optional[int] = None
    smr: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    thumbnail: Optional[str] = None
    type: Optional[str] = None
    uploaded_at: Optional[str] = None
    uploader: Optional[str] = None
    url: Optional[str] = None
    video_type: Optional[str] = None
    web_view_link: Optional[str] = None
    derived_tags: list = []
    derived_tags_source: str


class ContentItemCreateRequest(BaseModel):
    """Dashboard-native upload metadata (Phase 1 path -- no actual file
    bytes handled here; url/proxy_url/drive_id are wherever the caller
    already stored the file, same as every other manually-entered field
    in this codebase). filename is the only required field, matching
    collision.content_item's own NOT NULL constraint."""
    filename: str
    actor: str
    business: Optional[str] = None
    collection: Optional[str] = None
    description: Optional[str] = None
    drive_id: Optional[str] = None
    mime: Optional[str] = None
    proxy_url: Optional[str] = None
    ro_number: Optional[str] = None
    service: Optional[str] = None
    size: Optional[int] = None
    smr: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    thumbnail: Optional[str] = None
    type: Optional[str] = None
    uploaded_at: Optional[str] = None  # ISO 8601; None lets the DB default to now()
    uploader: Optional[str] = None
    url: Optional[str] = None
    video_type: Optional[str] = None
    web_view_link: Optional[str] = None


class ContentItemTagsUpdateRequest(BaseModel):
    derived_tags: list
    derived_tags_source: str  # 'ai' | 'human'
    actor: str


class StaffUserOut(BaseModel):
    id: int
    person_id: int
    role: str
    google_email: str
    active: bool
    provisioned_by_staff_user_id: Optional[int] = None


class StaffProvisionRequest(BaseModel):
    """Provisions a staff_user for an ALREADY-EXISTING platform.person.
    Matches app.repository.provision_staff_user_for_existing_person()'s
    scope exactly -- this route deliberately does NOT expose
    provision_new_staff_user() (creating a brand-new platform.person row),
    since that requires a privileged (non-collision_app) DB connection per
    app/db.py's documented role gap. Creating new person rows stays an
    admin-script operation until an identity-service integration exists."""
    person_id: int
    role: str
    google_email: str
    actor: str
    provisioned_by_staff_user_id: Optional[int] = None


class StaffActiveRequest(BaseModel):
    active: bool
    actor: str


class SiteActiveRequest(BaseModel):
    """Body for PATCH /sites/{id} -- same shape as StaffActiveRequest
    (activate/deactivate + actor), closing the WORKLOG-tracked gap: "no
    PATCH /sites/{id} (e.g. to deactivate a site from the dashboard)"."""
    active: bool
    actor: str


class EstimateCreateRequest(BaseModel):
    """Phase 1 manual-entry only, same rule as every other write path in
    this repo -- content is whatever CCC ONE PDF/printout data was typed
    in by staff, stored as-is (jsonb). Matches
    app.repository.create_manual_estimate()'s scope exactly: always
    source=MANUAL, always confirmed at creation (no separate draft/review
    step exists yet in Phase 1 -- see Estimate.__post_init__'s CHECK
    mirror for why confirmed_content can't be added later without also
    supplying confirmed_by/confirmed_at)."""
    content: dict
    actor: str


class JobIntakeCreateRequest(BaseModel):
    """POST /jobs body — the actual RO intake path (handoff §2.1-2.3:
    "customer signs JotForm -> imported as a job (RO)"). Closes a real
    gap: every existing route in this file operates on a job that
    already exists (GET/PATCH/transition/costs/estimates), but nothing
    HTTP-reachable could create the first row. csv_import.py is the
    other intake path (bulk); this is the single-record path for the
    dashboard UI / a human typing in one new RO.

    Deliberately does NOT create a brand-new platform.person — same
    privileged-connection gap as provision_new_staff_user() (see that
    route's comment above) and app.repository.create_person_and_customer()'s
    own docstring. person_id must reference an ALREADY-EXISTING
    platform.person row (looked up by an identity-service call this
    codebase doesn't have yet, or an admin script run under a
    privileged connection). Customer/vehicle/site are found-or-created
    on top of that per repository.py's existing idempotent helpers.
    """
    person_id: int
    customer_source: str = "walk_in"
    elektrica_renter_ref: Optional[int] = None

    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None

    site_name: str
    site_address: Optional[str] = None

    ro_number: str
    category: str
    status: str = "undecided"
    claim_number: Optional[str] = None
    insurer: Optional[str] = None
    adjuster_name: Optional[str] = None
    posture: Optional[str] = None
    gross_revenue: Decimal = Decimal("0")
    rent_utility_share: Decimal = Decimal("0")

    actor: str


def _ro_to_out(ro) -> RepairOrderOut:
    return RepairOrderOut(
        id=ro.id, ro_number=ro.ro_number, vehicle_id=ro.vehicle_id,
        customer_id=ro.customer_id, site_id=ro.site_id,
        category=ro.category.value, status=ro.status.value,
        claim_number=ro.claim_number, insurer=ro.insurer,
        adjuster_name=ro.adjuster_name, posture=ro.posture,
        gross_revenue=ro.gross_revenue, direct_ro_costs=ro.direct_ro_costs,
        labor_cost=ro.labor_cost, rent_utility_share=ro.rent_utility_share,
        net_profit=ro.net_profit(),
    )


def _event_to_out(e) -> JobEventOut:
    return JobEventOut(
        id=e.id, job_id=e.job_id,
        from_status=e.from_status.value if e.from_status else None,
        to_status=e.to_status.value, created_by=e.created_by, note=e.note,
    )


def _cost_to_out(c) -> CostEntryOut:
    return CostEntryOut(
        id=c.id, job_id=c.job_id, category=c.category.value,
        description=c.description, amount=c.amount, incurred_at=c.incurred_at,
        source=c.source, source_file=c.source_file,
    )


def _estimate_to_out(e) -> EstimateOut:
    return EstimateOut(
        id=e.id, job_id=e.job_id, version=e.version, source=e.source.value,
        draft_content=e.draft_content, confirmed_content=e.confirmed_content,
        confirmed_by=e.confirmed_by,
    )


def _staff_to_out(s) -> StaffUserOut:
    return StaffUserOut(
        id=s.id, person_id=s.person_id, role=s.role.value,
        google_email=s.google_email, active=s.active,
        provisioned_by_staff_user_id=s.provisioned_by_staff_user_id,
    )


def _payment_to_out(p) -> PaymentOut:
    return PaymentOut(
        id=p.id, job_id=p.job_id, source=p.source.value,
        external_transaction_id=p.external_transaction_id, amount=p.amount,
        received_at=p.received_at.isoformat() if p.received_at else None,
        accounting_sync_ref=p.accounting_sync_ref,
    )


def _customer_to_out(c) -> CustomerOut:
    return CustomerOut(
        id=c.id, person_id=c.person_id, source=c.source,
        elektrica_renter_ref=c.elektrica_renter_ref,
    )


def _vehicle_to_out(v) -> VehicleOut:
    return VehicleOut(
        id=v.id, vin=v.vin, make=v.make, model=v.model, year=v.year,
        customer_id=v.customer_id,
    )


def _site_to_out(s) -> SiteOut:
    return SiteOut(id=s.id, name=s.name, address=s.address, active=s.active)


def _content_item_to_out(ci) -> ContentItemOut:
    return ContentItemOut(
        id=ci.id, filename=ci.filename, source_manifest_id=ci.source_manifest_id,
        import_source_file=ci.import_source_file, business=ci.business,
        collection=ci.collection, description=ci.description, drive_id=ci.drive_id,
        mime=ci.mime, proxy_url=ci.proxy_url, ro_number=ci.ro_number,
        service=ci.service, size=ci.size, smr=ci.smr, source=ci.source,
        stage=ci.stage, status=ci.status, thumbnail=ci.thumbnail, type=ci.type,
        uploaded_at=ci.uploaded_at.isoformat() if ci.uploaded_at else None,
        uploader=ci.uploader, url=ci.url, video_type=ci.video_type,
        web_view_link=ci.web_view_link, derived_tags=ci.derived_tags,
        derived_tags_source=ci.derived_tags_source.value,
    )


def _report_to_out(r) -> ImportReportOut:
    return ImportReportOut(
        file=r.file, dry_run=r.dry_run, total_rows=r.total_rows,
        created=r.created, updated=r.updated, skipped=r.skipped,
        errors=r.errors, ok=r.ok(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/jobs/{ro_number}", response_model=RepairOrderOut)
def get_job(ro_number: str, cur=Depends(get_cursor)):
    ro = repo.get_repair_order_by_ro_number(cur, ro_number)
    if ro is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return _ro_to_out(ro)


@app.get("/jobs", response_model=list[RepairOrderOut])
def list_jobs(
    status: Optional[str] = None,
    category: Optional[str] = None,
    site_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    cur=Depends(get_cursor),
):
    """Browse/page through jobs -- closes a real gap flagged this cycle:
    every other job route requires already knowing a specific ro_number
    (GET /jobs/{ro_number}), so there was no HTTP-reachable way to list
    jobs at all (e.g. a dashboard's "jobs currently in bodywork" view, or
    "everything at the South site"). Placed as a route ABOVE
    GET /jobs/{ro_number} in this file's declaration order for
    readability only -- FastAPI matches "/jobs" as its own static route
    regardless of declaration order relative to the "/jobs/{ro_number}"
    path-parameter route, so there's no literal-vs-parameter routing
    ambiguity here to worry about.
    """
    status_enum = None
    if status is not None:
        try:
            status_enum = JobStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"status={status!r} must be one of {[s.value for s in JobStatus]}",
            )
    category_enum = None
    if category is not None:
        try:
            category_enum = JobCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"category={category!r} must be one of {[c.value for c in JobCategory]}",
            )
    ros = repo.list_repair_orders(
        cur, status=status_enum, category=category_enum,
        site_id=site_id, customer_id=customer_id, limit=limit, offset=offset,
    )
    return [_ro_to_out(ro) for ro in ros]


@app.post("/jobs", response_model=RepairOrderOut)
def create_job(body: JobIntakeCreateRequest, cur=Depends(get_cursor)):
    """RO intake (see JobIntakeCreateRequest docstring for scope/gap
    notes). Idempotent on ro_number: a duplicate ro_number is a 400, not
    a silent overwrite -- callers that want "find or create" should GET
    first, matching the discipline every other write route in this file
    already follows (no route here ever guesses whether a human meant
    create-new vs update-existing).
    """
    if repo.get_repair_order_by_ro_number(cur, body.ro_number) is not None:
        raise HTTPException(
            status_code=400,
            detail=f"ro_number={body.ro_number!r} already exists -- use PATCH /jobs/{{ro_number}} to edit it.",
        )
    try:
        category = JobCategory(body.category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"category={body.category!r} must be one of {[c.value for c in JobCategory]}",
        )
    try:
        status = JobStatus(body.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"status={body.status!r} must be one of {[s.value for s in JobStatus]}",
        )
    if repo.get_person_by_id(cur, body.person_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"person_id={body.person_id!r} does not reference an existing platform.person row.",
        )
    try:
        customer = repo.create_customer_for_existing_person(
            cur, body.person_id, body.actor,
            source=body.customer_source, elektrica_renter_ref=body.elektrica_renter_ref,
        )
        vehicle = repo.get_or_create_vehicle(
            cur, customer.id, body.actor,
            vin=body.vin, make=body.make, model=body.model, year=body.year,
        )
        site = repo.get_or_create_site(cur, body.site_name, body.actor, address=body.site_address)
        ro = repo.create_repair_order(
            cur,
            RepairOrder(
                ro_number=body.ro_number, vehicle_id=vehicle.id, customer_id=customer.id,
                site_id=site.id, category=category, status=status,
                claim_number=body.claim_number, insurer=body.insurer,
                adjuster_name=body.adjuster_name, posture=body.posture,
                gross_revenue=body.gross_revenue, rent_utility_share=body.rent_utility_share,
            ),
            body.actor,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _ro_to_out(ro)


@app.get("/jobs/{ro_number}/events", response_model=list[JobEventOut])
def get_job_events(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return [_event_to_out(e) for e in repo.list_job_events(cur, ro_number)]


@app.post("/jobs/{ro_number}/transition", response_model=RepairOrderOut)
def transition_job(ro_number: str, body: TransitionRequest, cur=Depends(get_cursor)):
    try:
        target = JobStatus(body.target_status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"target_status={body.target_status!r} must be one of {[s.value for s in JobStatus]}",
        )
    try:
        ro = repo.transition_job_status(cur, ro_number, target, body.actor, note=body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _ro_to_out(ro)


@app.patch("/jobs/{ro_number}", response_model=RepairOrderOut)
def patch_job_intake_fields(ro_number: str, body: JobIntakeUpdateRequest, cur=Depends(get_cursor)):
    """Revise intake-time fields (claim_number/insurer/adjuster_name/
    posture) after creation -- closes the gap flagged in the prior
    cycle's WORKLOG (these were write-once at create_repair_order() time).
    Does not touch status (use POST .../transition) or any cost/revenue
    column (write-once or DB-trigger-derived, see repo.create_repair_order
    and repo.update_job_intake_fields docstrings).

    exclude_unset=True is the whole point of this route: a field simply
    absent from the request body must NOT overwrite existing data with
    NULL, but a field explicitly sent as JSON `null` (e.g.
    {"adjuster_name": null}) must actually clear it -- pydantic's
    exclude_unset distinguishes "not sent" from "sent as null", and that
    distinction is passed straight through as repo._UNSET vs a real None.
    """
    body_fields = body.model_dump(exclude_unset=True, exclude={"actor"})
    kwargs = {
        field: body_fields.get(field, repo._UNSET)
        for field in ("claim_number", "insurer", "adjuster_name", "posture")
    }
    try:
        ro = repo.update_job_intake_fields(cur, ro_number, body.actor, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _ro_to_out(ro)


@app.get("/jobs/{ro_number}/costs", response_model=list[CostEntryOut])
def get_job_costs(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return [_cost_to_out(c) for c in repo.list_cost_entries(cur, ro_number)]


@app.post("/jobs/{ro_number}/costs", response_model=CostEntryOut)
def add_job_cost(ro_number: str, body: CostEntryIn, cur=Depends(get_cursor)):
    ro = repo.get_repair_order_by_ro_number(cur, ro_number)
    if ro is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    try:
        category = CostCategory(body.category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"category={body.category!r} must be one of {[c.value for c in CostCategory]}",
        )
    from app.models import CostEntry as CE
    entry = CE(
        job_id=ro.id, category=category, amount=body.amount,
        description=body.description, incurred_at=body.incurred_at,
        source=body.source, source_file=body.source_file,
    )
    try:
        created = repo.add_cost_entry(cur, entry, body.actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _cost_to_out(created)


@app.post("/jobs/{ro_number}/costs/recalculate", response_model=RepairOrderOut)
def recalculate_job_costs(ro_number: str, body: RecalculateRequest, cur=Depends(get_cursor)):
    """NOTE (migration 010, 2026-09-06): this endpoint is now a no-op
    that just re-reads the job -- there is nothing left to "recalculate"
    on demand. labor_cost/direct_ro_costs are kept correct automatically
    by a DB trigger firing on every collision.cost_entry write, per
    Jed's cost-derivation decision (fully derived, not opt-in
    reconciliation). Kept as a real endpoint rather than deleted outright
    since removing an existing API route is more disruptive than making
    it a harmless read -- any caller hitting it still gets the correct,
    already-current job back. Candidate for actual removal once nothing
    calls it anymore; not done in this session to avoid guessing whether
    something already depends on this route existing.
    """
    ro = repo.get_repair_order_by_ro_number(cur, ro_number)
    if ro is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return _ro_to_out(ro)


# ---------------------------------------------------------------------------
# Estimates (2026-09-06 backlog item #2: get_estimates_for_job()/
# get_latest_estimate_for_job() existed in app/repository.py since the
# earlier cron cycle but had no HTTP route -- closed that gap first.
# POST added this cycle: create_manual_estimate() previously only reachable
# from scripts/tests, now has a real write route. Still Phase 1 manual-only
# -- no CCC ONE contact, content is whatever staff typed in.
# ---------------------------------------------------------------------------

@app.get("/jobs/{ro_number}/estimates", response_model=list[EstimateOut])
def get_job_estimates(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return [_estimate_to_out(e) for e in repo.get_estimates_for_job(cur, ro_number)]


@app.post("/jobs/{ro_number}/estimates", response_model=EstimateOut)
def create_job_estimate(ro_number: str, body: EstimateCreateRequest, cur=Depends(get_cursor)):
    ro = repo.get_repair_order_by_ro_number(cur, ro_number)
    if ro is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    try:
        created = repo.create_manual_estimate(cur, ro.id, body.content, body.actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _estimate_to_out(created)


@app.get("/jobs/{ro_number}/estimates/latest", response_model=EstimateOut)
def get_job_latest_estimate(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    estimate = repo.get_latest_estimate_for_job(cur, ro_number)
    if estimate is None:
        raise HTTPException(status_code=404, detail=f"No estimates for ro_number={ro_number!r}")
    return _estimate_to_out(estimate)


# ---------------------------------------------------------------------------
# Payments (migrations/011, STAGING ONLY -- collision.payment not yet
# promoted to production, see migrations/011's header + WORKLOG.md
# 2026-09-04 for the payment_source enum question awaiting Jed's
# confirmation). App-layer build deliberately sequenced after the
# schema question per this repo's own "schema first, then app layer"
# order (same as every other migration) -- built now because Jed's
# continuous-build instruction says move to the next buildable item
# rather than stall, and this is buildable/testable against staging
# regardless of the still-open enum question (adding/renaming enum
# values later is a low-risk migration per 011's own header, so this
# code isn't wasted if the value set changes).
#
# No PATCH/DELETE route -- collision.payment is append-only at the DB
# level (forbid-mutation trigger); a correction is a new row.
# ---------------------------------------------------------------------------

@app.get("/jobs/{ro_number}/payments", response_model=list[PaymentOut])
def get_job_payments(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return [_payment_to_out(p) for p in repo.list_payments_for_job(cur, ro_number)]


@app.post("/jobs/{ro_number}/payments", response_model=PaymentOut)
def create_job_payment(ro_number: str, body: PaymentCreateRequest, cur=Depends(get_cursor)):
    ro = repo.get_repair_order_by_ro_number(cur, ro_number)
    if ro is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    try:
        source = PaymentSource(body.source)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"source={body.source!r} must be one of {[s.value for s in PaymentSource]}",
        )
    received_at = None
    if body.received_at is not None:
        try:
            received_at = datetime.fromisoformat(body.received_at)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"received_at={body.received_at!r} must be a valid ISO 8601 timestamp",
            )
    from app.models import Payment as PaymentModel
    try:
        payment = PaymentModel(
            job_id=ro.id, source=source, amount=body.amount,
            external_transaction_id=body.external_transaction_id,
            received_at=received_at, accounting_sync_ref=body.accounting_sync_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    created = repo.create_payment(cur, payment, body.actor)
    return _payment_to_out(created)


@app.get("/jobs/{ro_number}/payments/summary", response_model=JobPaymentSummaryOut)
def get_job_payments_summary(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    summary = repo.get_job_payment_summary(cur, ro_number)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No payment summary for ro_number={ro_number!r}")
    return JobPaymentSummaryOut(
        job_id=summary["job_id"], ro_number=summary["ro_number"],
        total_collected=summary["total_collected"], payment_count=summary["payment_count"],
        last_payment_at=summary["last_payment_at"].isoformat() if summary["last_payment_at"] else None,
    )


# ---------------------------------------------------------------------------
# Customer / Vehicle lookup (2026-09-05 cron cycle: closes a real gap --
# repo.get_customer_by_person_id()/get_vehicles_by_customer()/
# get_vehicle_by_vin() existed since migration 001's app layer with no
# HTTP route ever wired to them; every job route only exposes bare
# customer_id/vehicle_id integers, with no way to look the entity itself
# up (e.g. "does this person already have a customer record / what
# vehicles do they have on file" -- a real dashboard need before intake,
# not a guess). Read-only by design: creation stays inside POST /jobs and
# csv_import.py's existing find-or-create paths, unchanged.
# ---------------------------------------------------------------------------

class PersonOut(BaseModel):
    """Thin, read-only mirror of platform.person's own columns -- added
    this cycle to close a real dashboard-UI gap: repo.get_person_by_id()
    only ever selected the bare `id` (enough for POST /jobs's FK-exists
    check), so nothing HTTP-reachable could show a human "is this the
    person you meant" before creating a job against a person_id they
    typed in. Read-only -- does not create/edit platform.person, same
    boundary every other route touching that table already respects
    (see JobIntakeCreateRequest's own docstring for why creating NEW
    person rows stays out of scope for this unauthenticated app layer)."""
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email_normalized: Optional[str] = None
    phone_normalized: Optional[str] = None


@app.get("/persons/{person_id}", response_model=PersonOut)
def get_person(person_id: int, cur=Depends(get_cursor)):
    person = repo.get_person_details_by_id(cur, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail=f"No platform.person with id={person_id!r}")
    return PersonOut(**person)


@app.post("/customers/intake", response_model=CustomerIntakeOut)
def intake_customer(body: CustomerIntakeRequest, cur=Depends(get_privileged_cursor)):
    """The real customer-intake path: closes the gap
    repo.create_person_and_customer()'s docstring has flagged since
    migration 001 ("swap the raw INSERT for platform.match_or_create_person()
    ... not urgent"). Uses get_privileged_cursor(), NOT get_cursor() --
    see that dependency's own docstring: platform.match_or_create_person()
    is callable only by neondb_owner/platform_identity_service, and
    collision_app has no path to either, confirmed by direct query
    against real staging Postgres this cycle (same access gap Elektrica
    already documented and worked around for the identical primitive).

    Normalizes email/phone via app.normalize (lowercase+strip email,
    digits-only phone) before calling
    repo.match_or_create_and_link_customer() -- same reasoning as
    Elektrica's POST /renters/intake: match_or_create_person()'s
    exact-match step does a literal equality comparison against
    already-normalized platform.person rows, so un-normalized input here
    would silently under-match and create a duplicate person.

    Does NOT replace create_person_and_customer() (still used by
    csv_import.py's admin-script path and scripts/_seed_test_people.py)
    -- this is the new preferred path for a real dashboard "new/returning
    customer" intake screen once one exists; swapping the CSV importer
    and provision_new_staff_user() over to the same primitive is a
    separate follow-up, not done in this pass (same "not urgent, next
    time you touch those functions" note the docstring gap has carried
    since 2026-09-06)."""
    email_normalized = normalize_email(body.email)
    phone_normalized = normalize_phone(body.phone)
    result = repo.match_or_create_and_link_customer(
        cur, body.first_name, body.last_name, body.actor,
        date_of_birth=body.date_of_birth,
        email_normalized=email_normalized,
        phone_normalized=phone_normalized,
        source=body.source,
    )
    return CustomerIntakeOut(
        match_status=result.match_status,
        person_id=result.person_id,
        queue_id=result.queue_id,
        customer=_customer_to_out(result.customer) if result.customer else None,
    )




@app.get("/customers/by-person/{person_id}", response_model=CustomerOut)
def get_customer_by_person(person_id: int, cur=Depends(get_cursor)):
    customer = repo.get_customer_by_person_id(cur, person_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"No customer linked to person_id={person_id!r}")
    return _customer_to_out(customer)


@app.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, cur=Depends(get_cursor)):
    """Closes the gap flagged in repo.get_customer_by_id()'s docstring:
    every job response exposes a bare customer_id int, and GET
    /customers/{customer_id}/vehicles already takes this same id as a
    path param, but nothing could look the customer row itself up by it
    (only by person_id, via GET /customers/by-person/{person_id}) --
    this is that direct lookup."""
    customer = repo.get_customer_by_id(cur, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"No customer with id={customer_id!r}")
    return _customer_to_out(customer)


@app.get("/customers/{customer_id}/vehicles", response_model=list[VehicleOut])
def get_customer_vehicles(customer_id: int, cur=Depends(get_cursor)):
    return [_vehicle_to_out(v) for v in repo.get_vehicles_by_customer(cur, customer_id)]


# ---------------------------------------------------------------------------
# Sites (migrations/006, STAGING ONLY -- collision.site not yet promoted
# to production; see README's "Open questions" for the pending migration
# 006 cost-category review, a separate question from this table's shape).
# Site rows are still only CREATED via get_or_create_site()'s
# find-or-create path (POST /jobs, CSV importers) -- no dedicated
# POST /sites here. PATCH /sites/{id}/active below adds the one write
# path this table needed beyond that (soft activate/deactivate, closing
# the WORKLOG-tracked "no PATCH /sites/{id}" gap), same pattern as
# POST /staff/{email}/active -- no hard DELETE, matching the
# append-only/no-hard-delete discipline used elsewhere in this schema.
# ---------------------------------------------------------------------------

@app.get("/sites", response_model=list[SiteOut])
def get_sites(active_only: bool = False, cur=Depends(get_cursor)):
    return [_site_to_out(s) for s in repo.list_sites(cur, active_only=active_only)]


@app.get("/sites/{site_id}", response_model=SiteOut)
def get_site(site_id: int, cur=Depends(get_cursor)):
    site = repo.get_site_by_id(cur, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"No site with id={site_id!r}")
    return _site_to_out(site)


@app.patch("/sites/{site_id}/active", response_model=SiteOut)
def set_site_active_route(site_id: int, body: SiteActiveRequest, cur=Depends(get_cursor)):
    try:
        site = repo.set_site_active(cur, site_id, body.active, body.actor)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _site_to_out(site)


@app.get("/vehicles/by-vin/{vin}", response_model=VehicleOut)
def get_vehicle_by_vin_route(vin: str, cur=Depends(get_cursor)):
    vehicle = repo.get_vehicle_by_vin(cur, vin)
    if vehicle is None:
        raise HTTPException(status_code=404, detail=f"No vehicle with vin={vin!r}")
    return _vehicle_to_out(vehicle)


# ---------------------------------------------------------------------------
# PDR Crew monthly settlement (continuous-build cycle: wires
# pdr_settlement.py's pure-computation calculator -- tested since
# 2026-09-04 (test_pdr_settlement.py, 7/7) but never fed real job data --
# to real collision.job rows via app/settlement.py. ADR-001 §7 flags this
# as a strong v1 candidate specifically because it is NOT blocked by any
# of the CCC ONE / payment_source / cost_category open questions: it
# only reads Complete Collision's own already-entered job cost/revenue
# fields. *** DRAFT-AND-HOLD, same as pdr_settlement.py's own module
# docstring: this computes and returns a draft statement for Jed's
# review. Nothing here sends, emails, or otherwise delivers anything to
# PDR Crew. *** Depends on collision.job.site_id (migrations/006,
# STAGING ONLY as of this writing) -- this route only works against
# staging until Jed promotes 006, same constraint GET /sites and GET
# /jobs?site_id= already carry.
# ---------------------------------------------------------------------------

class CategorySettlementOut(BaseModel):
    category: str
    ro_numbers: list[str]
    gross_revenue: Decimal
    total_costs_netted: Decimal
    net_profit: Decimal
    cc_share_amount: Decimal
    pdr_share_amount: Decimal


class MonthlySettlementOut(BaseModel):
    month: str
    site: str
    status: str
    total_owed_to_pdr: Decimal
    categories: list[CategorySettlementOut]
    statement_text: str


@app.get("/settlements/pdr-crew", response_model=MonthlySettlementOut)
def get_pdr_crew_settlement(site_id: int, month: str, cur=Depends(get_cursor)):
    try:
        settlement, statement_text = settlement_mod.build_monthly_settlement_statement(cur, site_id, month)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("no collision.site"):
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return MonthlySettlementOut(
        month=settlement.month,
        site=settlement.site,
        status=settlement.status,
        total_owed_to_pdr=settlement.total_owed_to_pdr(),
        categories=[
            CategorySettlementOut(
                category=cat.value,
                ro_numbers=c.ro_numbers,
                gross_revenue=c.gross_revenue,
                total_costs_netted=c.total_costs_netted,
                net_profit=c.net_profit,
                cc_share_amount=c.cc_share_amount,
                pdr_share_amount=c.pdr_share_amount,
            )
            for cat, c in settlement.categories.items()
        ],
        statement_text=statement_text,
    )


# ---------------------------------------------------------------------------
# Content library (2026-09-05 cron cycle: closes the "no app layer" gap
# flagged in WORKLOG.md since migrations/005 went to production on
# 2026-09-04 -- collision.content_item existed as a schema-only table
# with zero readers/writers until now. Real content_manifest.json bulk
# import (141 KB, per handoff §3.1) remains blocked on export access to
# "the mini"; these routes only support the dashboard-native upload path
# (a human/UI supplies metadata directly), same discipline as every other
# "don't fabricate the blocked data" decision in this repo. No actual
# file bytes are handled here -- filename/url/proxy_url/drive_id point at
# wherever the caller already stored the file (e.g. Drive), matching how
# every other manually-entered field in this codebase works.
# ---------------------------------------------------------------------------

@app.post("/content-items", response_model=ContentItemOut)
def create_content_item_route(body: ContentItemCreateRequest, cur=Depends(get_cursor)):
    try:
        uploaded_at = datetime.fromisoformat(body.uploaded_at) if body.uploaded_at else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"uploaded_at={body.uploaded_at!r} is not valid ISO 8601")
    try:
        item = ContentItem(
            filename=body.filename, business=body.business, collection=body.collection,
            description=body.description, drive_id=body.drive_id, mime=body.mime,
            proxy_url=body.proxy_url, ro_number=body.ro_number, service=body.service,
            size=body.size, smr=body.smr, source=body.source, stage=body.stage,
            status=body.status, thumbnail=body.thumbnail, type=body.type,
            uploaded_at=uploaded_at, uploader=body.uploader, url=body.url,
            video_type=body.video_type, web_view_link=body.web_view_link,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    created = repo.create_content_item(cur, item, body.actor)
    return _content_item_to_out(created)


@app.get("/content-items/{content_item_id}", response_model=ContentItemOut)
def get_content_item_route(content_item_id: int, cur=Depends(get_cursor)):
    item = repo.get_content_item_by_id(cur, content_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No content_item with id={content_item_id!r}")
    return _content_item_to_out(item)


@app.get("/content-items", response_model=list[ContentItemOut])
def search_content_items_route(
    q: Optional[str] = None, limit: int = 50, offset: int = 0, cur=Depends(get_cursor),
):
    return [_content_item_to_out(i) for i in repo.search_content_items(cur, query=q, limit=limit, offset=offset)]


@app.get("/jobs/{ro_number}/content-items", response_model=list[ContentItemOut])
def get_job_content_items_route(ro_number: str, cur=Depends(get_cursor)):
    if repo.get_repair_order_by_ro_number(cur, ro_number) is None:
        raise HTTPException(status_code=404, detail=f"No job with ro_number={ro_number!r}")
    return [_content_item_to_out(i) for i in repo.list_content_items_for_job(cur, ro_number)]


@app.patch("/content-items/{content_item_id}/tags", response_model=ContentItemOut)
def update_content_item_tags_route(
    content_item_id: int, body: ContentItemTagsUpdateRequest, cur=Depends(get_cursor),
):
    try:
        tags_source = DerivedTagsSource(body.derived_tags_source)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"derived_tags_source={body.derived_tags_source!r} must be one of "
                   f"{[s.value for s in DerivedTagsSource]}",
        )
    try:
        updated = repo.update_content_item_tags(cur, content_item_id, body.derived_tags, tags_source, body.actor)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _content_item_to_out(updated)


# ---------------------------------------------------------------------------
# Staff (2026-09-06 backlog item #1: provision_staff_user_for_existing_person()/
# set_staff_user_active()/get_staff_capability() existed in app/repository.py
# since the earlier cron cycle but had no HTTP route -- closing that gap
# here. Deliberately does NOT expose provision_new_staff_user() (creates a
# NEW platform.person row) -- that requires a privileged, non-collision_app
# connection per app/db.py's documented role gap, and this whole module
# runs unauthenticated with no notion of "who is calling," so exposing an
# operation that can only safely run under an elevated DB role over an
# open HTTP route would be a bigger scope jump than this cycle should make
# unilaterally. Same "don't wire unbuilt architecture" discipline already
# applied elsewhere in this file (no auth route-guards; migrations/007's
# own no-RLS decision).
# ---------------------------------------------------------------------------

@app.post("/staff", response_model=StaffUserOut)
def provision_staff(body: StaffProvisionRequest, cur=Depends(get_cursor)):
    try:
        role = StaffRole(body.role)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"role={body.role!r} must be one of {[r.value for r in StaffRole]}",
        )
    try:
        staff = repo.provision_staff_user_for_existing_person(
            cur, body.person_id, role, body.google_email, body.actor,
            provisioned_by_staff_user_id=body.provisioned_by_staff_user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _staff_to_out(staff)


@app.get("/staff", response_model=list[StaffUserOut])
def list_staff(active_only: bool = False, role: Optional[str] = None, cur=Depends(get_cursor)):
    """Directory/roster listing -- closes a real gap: POST /staff and
    GET /staff/{google_email} have existed since the 2026-09-06 cycle
    but nothing could list the whole roster (same class of gap as
    list_sites()/GET /sites closed for collision.site last cycle).
    Static route, placed above GET /staff/{google_email} for
    readability only -- FastAPI matches "/staff" as its own literal
    route regardless of declaration order relative to the
    "/staff/{google_email}" path-parameter route."""
    role_enum = None
    if role is not None:
        try:
            role_enum = StaffRole(role)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"role={role!r} must be one of {[r.value for r in StaffRole]}",
            )
    return [_staff_to_out(s) for s in repo.list_staff_users(cur, active_only=active_only, role=role_enum)]


@app.get("/staff/{google_email}", response_model=StaffUserOut)
def get_staff(google_email: str, cur=Depends(get_cursor)):
    staff = repo.get_staff_user_by_google_email(cur, google_email)
    if staff is None:
        raise HTTPException(status_code=404, detail=f"No staff_user with google_email={google_email!r}")
    return _staff_to_out(staff)


@app.get("/staff/{google_email}/capability")
def get_staff_capability(google_email: str, cur=Depends(get_cursor)):
    if repo.get_staff_user_by_google_email(cur, google_email) is None:
        raise HTTPException(status_code=404, detail=f"No staff_user with google_email={google_email!r}")
    capability = repo.get_staff_capability(cur, google_email)
    return {"google_email": google_email.strip().lower(), "capability_level": capability}


@app.post("/staff/{google_email}/active", response_model=StaffUserOut)
def set_staff_active(google_email: str, body: StaffActiveRequest, cur=Depends(get_cursor)):
    try:
        staff = repo.set_staff_user_active(cur, google_email, body.active, body.actor)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _staff_to_out(staff)


# ---------------------------------------------------------------------------
# CSV import (2026-09-06 later cron cycle: closes the "No CSV-upload HTTP
# route yet" gap flagged in every prior WORKLOG's "NOT DONE" section --
# importers were CLI-only via scripts/csv_import_cli.py until now).
#
# Thin wrapper only: this route does NOT change app/csv_import.py's
# scope/behavior at all -- same dry_run-by-default, same idempotent-on-
# natural-key semantics, same "never talks to CCC ONE" rule (input here is
# still just a CSV file, now delivered via multipart upload instead of a
# local path arg). commit defaults to False, mirroring csv_import_cli.py's
# --commit flag: a caller must explicitly opt into writing.
#
# The uploaded file is spooled to a real temp file on disk (not read into
# memory as text) because app.csv_import._read_rows() takes a path, and
# every importer already assumes csv.DictReader-over-a-real-file semantics
# (encoding="utf-8-sig" BOM handling, etc.) -- reusing that exact function
# rather than duplicating its parsing logic here. Temp file is always
# cleaned up (finally block), success or failure.
# ---------------------------------------------------------------------------

IMPORTERS = {
    "customers": csv_import.import_customers_csv,
    "vehicles": csv_import.import_vehicles_csv,
    "jobs": csv_import.import_jobs_csv,
    "costs": csv_import.import_cost_entries_csv,
}


@app.post("/import/{kind}", response_model=ImportReportOut)
async def import_csv(
    kind: str,
    file: UploadFile = File(...),
    actor: str = Form(...),
    commit: bool = Form(False),
    cur=Depends(get_cursor),
):
    if kind not in IMPORTERS:
        raise HTTPException(
            status_code=400,
            detail=f"kind={kind!r} must be one of {sorted(IMPORTERS.keys())}",
        )
    importer = IMPORTERS[kind]
    contents = await file.read()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False
        ) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        report = importer(cur, tmp_path, actor, dry_run=not commit)
    finally:
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return _report_to_out(report)
