"""Complete Collision Dashboard — core domain models.

Phase 1, per docs/ADR-001-complete-collision.md and
docs/COMPLETE_COLLISION_HANDOFF_2026-09-03.md §2.1-2.3.

These are plain dataclasses mirroring the `collision` Postgres schema
(migrations/001-006). They have NO CCC ONE dependency of any kind — every
field here is either Complete Collision's own record or a manually-typed
copy of something a human read off a CCC ONE screen (ADR-001 §1: no API,
no automated read/write against CCC ONE, no bots entering data).

Field names deliberately match the SQL columns 1:1 so repository.py's
row <-> object mapping stays trivial and the shapes never silently drift
apart from the schema that is the actual source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums — kept in exact sync with the Postgres enum types they mirror.
# ---------------------------------------------------------------------------

class JobCategory(str, Enum):
    """Matches collision.job_category (migrations/002) and
    pdr_settlement.py's ROCategory — same three values, deliberately."""
    COLLISION = "collision"
    PDR = "pdr"
    HAIL = "hail"


class JobStatus(str, Enum):
    """Matches collision.job_status (migrations/002) — the handoff §2.2
    state machine. Order matters: this is the expected forward sequence,
    though the DB does not yet enforce it (see migrations/002's
    SIMPLIFICATION note — no valid_next_states() trigger ported yet)."""
    UNDECIDED = "undecided"
    CAME_IN = "came_in"
    ESTIMATE = "estimate"
    TEARDOWN = "teardown"
    WAITING_ON_PARTS = "waiting_on_parts"
    BODYWORK = "bodywork"
    PAINT = "paint"
    DETAIL = "detail"
    DELIVERED = "delivered"
    CLOSED_OUT = "closed_out"
    MARKETING = "marketing"


# The forward sequence, used by application-layer transition validation
# (validate_transition() below) until/unless a DB-level trigger is built.
JOB_STATUS_SEQUENCE = [
    JobStatus.UNDECIDED,
    JobStatus.CAME_IN,
    JobStatus.ESTIMATE,
    JobStatus.TEARDOWN,
    JobStatus.WAITING_ON_PARTS,
    JobStatus.BODYWORK,
    JobStatus.PAINT,
    JobStatus.DETAIL,
    JobStatus.DELIVERED,
    JobStatus.CLOSED_OUT,
    JobStatus.MARKETING,
]


class EstimateSource(str, Enum):
    """Matches collision.estimate_source (migrations/003). Phase 1 only
    ever writes 'manual' — the other two values exist so the shape is
    right for Phase 2/3, per handoff §2.3, but nothing in this codebase
    constructs an Estimate with source != MANUAL yet."""
    MANUAL = "manual"
    CCC_ONE_WEBHOOK = "ccc_one_webhook"
    AI_PROPOSED = "ai_proposed"


class StaffRole(str, Enum):
    """Matches collision.staff_role (migrations/004). Permission
    enforcement is explicitly NOT wired yet — see migrations/004's header
    and README's 'Not yet built' section. This enum exists so the shape
    is right; nothing in this codebase branches behavior on role today."""
    OWNER = "owner"
    MANAGER = "manager"
    RECEPTIONIST = "receptionist"


class CostCategory(str, Enum):
    """Matches collision.cost_category (migrations/006). This is this
    bot's own reasonable body-shop cost taxonomy, NOT sourced from a
    Complete Collision document — flagged in migrations/006's header as
    an assumption for Jed to correct if his real categories differ."""
    PARTS = "parts"
    LABOR = "labor"
    PAINT_MATERIALS = "paint_materials"
    SUBLET = "sublet"
    RENTAL_REIMBURSEMENT = "rental_reimbursement"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

@dataclass
class Site:
    """Mirrors collision.site (migrations/006). No real site name is
    known to this codebase — created on demand by whatever name a human
    enters via CSV import or the dashboard UI (find-or-create by name),
    never guessed or pre-populated. See ADR-001 §4."""
    name: str
    address: Optional[str] = None
    active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


@dataclass
class Customer:
    """Mirrors collision.customer (migrations/001). person_id points at
    the shared platform.person table (cross-business identity, shared
    with VLS/Elektrica per Jed's explicit Neon-project confirmation) —
    this dataclass does NOT model platform.person itself, only the
    collision-specific customer row. In application code, person-level
    fields (name, email, phone) are looked up/created via the identity
    service, not duplicated here.
    """
    person_id: int
    source: str = "walk_in"  # 'walk_in' | 'insurer_referred' | 'elektrica_rental' | 'other'
    elektrica_renter_ref: Optional[int] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


VALID_CUSTOMER_SOURCES = {"walk_in", "insurer_referred", "elektrica_rental", "other"}


@dataclass
class Vehicle:
    """Mirrors collision.vehicle (migrations/002). vin is nullable —
    intake may not always have it captured yet, matching the DB column."""
    customer_id: int
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


@dataclass
class RepairOrder:
    """Mirrors collision.job (migrations/002, /006). Named RepairOrder in
    this module (matching pdr_settlement.py's dataclass name and the
    shop's own "RO" terminology) even though the DB table is `job` — kept
    consistent with the handoff's own language ("RO tracker spine").

    Cost fields here are the four flat aggregate columns that
    pdr_settlement.py's compute_monthly_settlement() reads directly by
    field name. They are NOT automatically derived from CostEntry rows in
    this module — see recalculate_costs_from_entries() in repository.py
    for the explicit, opt-in reconciliation step (migrations/006 header
    explains why this isn't an automatic trigger).
    """
    ro_number: str
    vehicle_id: int
    customer_id: int
    site_id: int
    category: JobCategory
    status: JobStatus = JobStatus.UNDECIDED

    claim_number: Optional[str] = None
    insurer: Optional[str] = None
    adjuster_name: Optional[str] = None
    posture: Optional[str] = None  # 'paying' | 'fighting', free text per handoff §2.3

    gross_revenue: Decimal = Decimal("0")
    direct_ro_costs: Decimal = Decimal("0")
    labor_cost: Decimal = Decimal("0")
    rent_utility_share: Decimal = Decimal("0")

    ccc_one_last_reconciled_at: Optional[datetime] = None

    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None

    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    def net_profit(self) -> Decimal:
        """Same formula as pdr_settlement.RepairOrder.net_profit() —
        Collision-category ROs net labor + rent/utilities in addition to
        direct RO costs; PDR/Hail net direct RO costs only."""
        costs = self.direct_ro_costs
        if self.category is JobCategory.COLLISION:
            costs += self.labor_cost + self.rent_utility_share
        return self.gross_revenue - costs


@dataclass
class JobEvent:
    """Mirrors collision.job_event (migrations/002) — append-only status
    transition log."""
    job_id: int
    to_status: JobStatus
    from_status: Optional[JobStatus] = None
    occurred_at: Optional[datetime] = None
    created_by: Optional[str] = None
    note: Optional[str] = None
    id: Optional[int] = None


@dataclass
class CostEntry:
    """Mirrors collision.cost_entry (migrations/006) — itemized cost
    ledger, one row per line item. Additive to (not a replacement for)
    RepairOrder's four flat cost columns; see repository.py's
    recalculate_costs_from_entries()."""
    job_id: int
    category: CostCategory
    amount: Decimal
    description: Optional[str] = None
    incurred_at: Optional[date] = None
    source: str = "manual"  # 'manual' | 'csv_import' — never a CCC ONE automated source
    source_file: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


VALID_COST_ENTRY_SOURCES = {"manual", "csv_import"}


@dataclass
class Estimate:
    """Mirrors collision.estimate (migrations/003). Phase 1 only
    constructs these with source=MANUAL and confirmed_content set at
    creation (per the DB's own CHECK constraint requiring this)."""
    job_id: int
    version: int
    source: EstimateSource
    draft_content: dict
    confirmed_content: Optional[dict] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None

    def __post_init__(self):
        if self.source == EstimateSource.MANUAL and self.confirmed_content is None:
            raise ValueError(
                "Manual estimates must have confirmed_content set at creation "
                "(collision.estimate's estimate_manual_confirmed_at_creation "
                "CHECK constraint mirrors this at the DB level)."
            )
        has_any = any([self.confirmed_content, self.confirmed_by, self.confirmed_at])
        has_all = all([self.confirmed_content, self.confirmed_by, self.confirmed_at])
        if has_any and not has_all:
            raise ValueError(
                "confirmed_content/confirmed_by/confirmed_at must be set together "
                "or not at all (estimate_confirmation_all_or_nothing CHECK)."
            )


def validate_transition(current: JobStatus, target: JobStatus) -> None:
    """Application-layer state-machine guard, per migrations/002's
    SIMPLIFICATION note: the DB does not enforce valid transitions yet (no
    valid_next_states() trigger ported from VLS), so this is the only
    enforcement that exists today. Raises ValueError on an illegal jump.

    Allows moving forward by any number of steps (e.g. skipping a stage
    that genuinely doesn't apply to a given RO) but never backward, and
    never to the same status (that's a no-op, not a transition — callers
    should not create a JobEvent for it).
    """
    if current == target:
        raise ValueError(f"{target} is not a transition — job is already {current}.")
    cur_idx = JOB_STATUS_SEQUENCE.index(current)
    tgt_idx = JOB_STATUS_SEQUENCE.index(target)
    if tgt_idx < cur_idx:
        raise ValueError(
            f"Cannot move job status backward: {current.value} -> {target.value}. "
            "If this is a genuine correction (e.g. data entry mistake), it should "
            "be handled explicitly, not silently allowed as a normal transition."
        )
