"""Wires pdr_settlement.py's pure-computation calculator to real Complete
Collision job data in the `collision` schema — closing a real gap: since
2026-09-04, pdr_settlement.py (the PDR Crew monthly settlement formula)
has existed, been tested (test_pdr_settlement.py, 7/7), and even had an
example script (example_statement.py) — but every one of those built its
input RepairOrder list from hand-typed dataclass literals. Nothing in the
app layer ever pulled real collision.job rows into it. ADR-001 §7 flags
this exact feature ("PDR Crew monthly settlement automation") as a
strong v1 candidate specifically because it is NOT blocked by the CCC ONE
license question (§1) or any of the open questions in §6 — it operates
only on Complete Collision's own already-entered job data.

Still governed by pdr_settlement.py's own draft-and-hold rule inherited
via MonthlySettlement.status ('draft_held_for_review') — this module
computes a draft. It does not send, email, or otherwise deliver anything
to PDR Crew. See app/api.py's GET /settlements/pdr-crew route docstring
for the same rule at the HTTP layer.

ASSUMPTION FLAGGED FOR JED (same discipline as migrations/006's
cost_category and migrations/011's payment_source): "monthly settlement"
here means every job whose `closed_at` timestamp falls within the given
calendar month, for the given site — i.e. jobs finished (closed) that
month, not jobs opened that month or jobs with any activity that month.
This reading matches the Operating Agreement's "due within 10 days of
month-end" framing (you settle completed work), but ADR-001 never pinned
down the exact cutover rule against source documents. If Jed's actual
practice differs (e.g. settle by `collected_at`/payment date instead, or
by `opened_at`), this is a one-function change (get_jobs_for_settlement's
WHERE clause), not a schema change.

Depends on collision.job.site_id (migrations/006) — STAGING ONLY as of
this writing (see README.md's migration 006 status). Same constraint as
GET /sites / GET /jobs?site_id= — this whole feature only works against
staging (or a future production once 006 is promoted with Jed's
sign-off), not current production.
"""
from __future__ import annotations

import re
from typing import Optional

from app import repository as repo
from app.models import JobCategory
from pdr_settlement import MonthlySettlement, ROCategory
from pdr_settlement import RepairOrder as SettlementRepairOrder
from pdr_settlement import compute_monthly_settlement, format_statement

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(month: str) -> None:
    if not MONTH_RE.match(month):
        raise ValueError(f"month={month!r} must be in YYYY-MM format")


def build_monthly_settlement(cur, site_id: int, month: str) -> MonthlySettlement:
    """Fetch real job data for site_id/month and run it through
    pdr_settlement.compute_monthly_settlement(). Raises ValueError if
    site_id doesn't resolve to a real collision.site row (same "clean
    404, not a raw DB error" discipline as every other repo function
    this app layer calls with a caller-supplied id) -- app/api.py's route
    is responsible for translating that into an HTTP 404.
    """
    _validate_month(month)
    site = repo.get_site_by_id(cur, site_id)
    if site is None:
        raise ValueError(f"no collision.site with id={site_id!r}")

    jobs = repo.get_jobs_closed_in_month(cur, site_id, month)
    settlement_ros = [
        SettlementRepairOrder(
            ro_number=job.ro_number,
            category=ROCategory(job.category.value),  # JobCategory/ROCategory share values
            site=site.name,
            gross_revenue=job.gross_revenue,
            direct_ro_costs=job.direct_ro_costs,
            labor_cost=job.labor_cost,
            rent_utility_share=job.rent_utility_share,
        )
        for job in jobs
    ]
    return compute_monthly_settlement(month, site.name, settlement_ros)


def build_monthly_settlement_statement(cur, site_id: int, month: str) -> tuple[MonthlySettlement, str]:
    """Convenience wrapper returning both the structured settlement and
    the plain-text draft statement (format_statement()) -- what
    app/api.py's route actually returns to a caller."""
    settlement = build_monthly_settlement(cur, site_id, month)
    return settlement, format_statement(settlement)
