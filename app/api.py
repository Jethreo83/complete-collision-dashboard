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
from app.models import CostCategory, JobStatus

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
