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
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app import db
from app import repository as repo
from app.models import CostCategory, JobStatus, StaffRole

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


class EstimateOut(BaseModel):
    id: int
    job_id: int
    version: int
    source: str
    draft_content: Optional[dict] = None
    confirmed_content: Optional[dict] = None
    confirmed_by: Optional[str] = None


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
