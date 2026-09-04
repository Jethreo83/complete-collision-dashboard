"""
PDR Crew monthly settlement calculator.

Implements the profit-split formula from the (draft, unsigned) Operating
Agreement — Complete Collision and PDR Crew (Rev 70-30 v4) — per
docs/ADR-001-complete-collision.md §7 and §5 build-order item 5.

Three RO categories, three different splits, net of different cost sets:

  Collision : 70% Complete Collision / 30% PDR Crew
              net of: direct RO costs, labor costs, rent + utilities
  PDR       : 5% Complete Collision / 95% PDR Crew
              net of: direct RO costs only
  Hail      : 40% Complete Collision / 60% PDR Crew
              net of: direct RO costs only

This module is pure computation — no CCC ONE integration, no database. It
takes already-entered RO records (manually keyed per ADR-001 Phase 1 — no
automated CCC ONE read) and produces a monthly itemized statement per the
agreement's "due within 10 days of month-end" requirement.

*** DRAFT-AND-HOLD: this computes a statement that is owed to a third
party (PDR Crew). Per SOUL.md standing rule, any generated statement is
draft-and-hold for Jed's review before it is sent to PDR Crew — this
module produces the draft only, it does not send anything. ***

*** The underlying Operating Agreement is itself still in draft/unsigned
(bracketed terms) per ADR-001 §7 open question #5 — Jed has not yet said
whether to build against current draft terms or wait for signature. This
module implements the draft terms as-is so the math can be validated now;

*** SHARED CONVENTIONS NOTE (per docs/SHARED_CONVENTIONS_NOTE.md,
convention #2 -- one shared document generator for the whole system):
this module is pure computation, NOT document rendering, so it does not
violate the "no project builds its own document generator" rule --
confirmed directly with Jed/hermes 2026-09-04. format_statement()'s
plain-text output below is a draft-review artifact for Jed, not a
rendered PDF. The shared generator now has a real home (2026-09-05,
built+verified by elektrica-dashboard, live on staging):
platform.document_template / platform.document / platform.outbound_log.
If/when a real PDF settlement statement is needed, THAT step must call
those platform tables -- do not add PDF rendering or a parallel
document/template pipeline to this module.
If Jed decides to wait [on the PDR Crew agreement signature], this
computation stays unused until he says otherwise. ***
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


class ROCategory(str, Enum):
    COLLISION = "collision"
    PDR = "pdr"
    HAIL = "hail"


# (cc_share, pdr_share) — must sum to 1 for each category.
SPLITS: dict[ROCategory, tuple[Decimal, Decimal]] = {
    ROCategory.COLLISION: (Decimal("0.70"), Decimal("0.30")),
    ROCategory.PDR: (Decimal("0.05"), Decimal("0.95")),
    ROCategory.HAIL: (Decimal("0.40"), Decimal("0.60")),
}

for _cat, (_cc, _pdr) in SPLITS.items():
    assert _cc + _pdr == Decimal("1"), f"{_cat} split does not sum to 1"


@dataclass(frozen=True)
class RepairOrder:
    """A single RO's inputs to the settlement calc.

    labor_cost and rent_utility_share only apply to Collision-category ROs
    per the agreement (§ split table above) — non-zero values on a
    PDR/Hail RO are accepted but ignored in net-profit math, since the
    agreement only nets those costs against Collision work. That's a
    deliberate modeling choice callers should be aware of, not a bug.
    """

    ro_number: str
    category: ROCategory
    site: str
    gross_revenue: Decimal
    direct_ro_costs: Decimal
    labor_cost: Decimal = Decimal("0")
    rent_utility_share: Decimal = Decimal("0")

    def net_profit(self) -> Decimal:
        costs = self.direct_ro_costs
        if self.category is ROCategory.COLLISION:
            costs += self.labor_cost + self.rent_utility_share
        return self.gross_revenue - costs


@dataclass
class CategorySettlement:
    category: ROCategory
    ro_numbers: list[str] = field(default_factory=list)
    gross_revenue: Decimal = Decimal("0")
    total_costs_netted: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")
    cc_share_amount: Decimal = Decimal("0")
    pdr_share_amount: Decimal = Decimal("0")


@dataclass
class MonthlySettlement:
    month: str  # "YYYY-MM"
    site: str
    categories: dict[ROCategory, CategorySettlement]
    status: str = "draft_held_for_review"  # never auto-sent, see module docstring

    def total_owed_to_pdr(self) -> Decimal:
        return sum((c.pdr_share_amount for c in self.categories.values()), Decimal("0"))


def _round_cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_monthly_settlement(
    month: str,
    site: str,
    repair_orders: list[RepairOrder],
) -> MonthlySettlement:
    """Compute the itemized monthly settlement for one site.

    Raises ValueError if any RO's site doesn't match, or month is missing
    ROs are simply omitted from that category's aggregate — this function
    does no CCC ONE lookups and trusts its caller-supplied list.
    """
    categories: dict[ROCategory, CategorySettlement] = {
        cat: CategorySettlement(category=cat) for cat in ROCategory
    }

    for ro in repair_orders:
        if ro.site != site:
            raise ValueError(
                f"RO {ro.ro_number} has site={ro.site!r}, expected {site!r} "
                "— pass a pre-filtered list per site."
            )
        c = categories[ro.category]
        c.ro_numbers.append(ro.ro_number)
        c.gross_revenue += ro.gross_revenue
        netted_costs = ro.direct_ro_costs
        if ro.category is ROCategory.COLLISION:
            netted_costs += ro.labor_cost + ro.rent_utility_share
        c.total_costs_netted += netted_costs
        c.net_profit += ro.net_profit()

    for cat, c in categories.items():
        cc_pct, pdr_pct = SPLITS[cat]
        c.cc_share_amount = _round_cents(c.net_profit * cc_pct)
        c.pdr_share_amount = _round_cents(c.net_profit * pdr_pct)
        # Reconciliation: rounding both shares independently can leave a
        # penny of drift on a net-profit total that isn't itself a whole
        # cent split evenly — assign any residual to the CC share (the
        # smaller line item in the PDR/Hail categories, and PDR Crew is
        # the party being paid out, so undershooting their share by a
        # stray cent from double-rounding is the wrong direction of error
        # to risk). Collision's CC share is already the majority share, so
        # this convention doesn't materially favor Complete Collision.
        drift = c.net_profit - (c.cc_share_amount + c.pdr_share_amount)
        if drift != 0:
            c.cc_share_amount += drift

    return MonthlySettlement(month=month, site=site, categories=categories)


def format_statement(settlement: MonthlySettlement) -> str:
    """Render a plain-text itemized statement per ADR-001 §7 requirement:
    itemized by RO, category, and site. This is the draft artifact that
    gets held for Jed's review — nothing here sends or emails it."""
    lines = [
        f"PDR Crew Monthly Settlement Statement (DRAFT — HELD FOR REVIEW)",
        f"Month: {settlement.month}   Site: {settlement.site}",
        f"Status: {settlement.status}",
        "",
    ]
    for cat in ROCategory:
        c = settlement.categories[cat]
        cc_pct, pdr_pct = SPLITS[cat]
        lines.append(f"-- {cat.value.upper()} ({int(cc_pct*100)}/{int(pdr_pct*100)} CC/PDR) --")
        if not c.ro_numbers:
            lines.append("  (no ROs this month)")
        else:
            lines.append(f"  ROs: {', '.join(c.ro_numbers)}")
            lines.append(f"  Gross revenue:      ${c.gross_revenue:,.2f}")
            lines.append(f"  Costs netted out:   ${c.total_costs_netted:,.2f}")
            lines.append(f"  Net profit:         ${c.net_profit:,.2f}")
            lines.append(f"  Complete Collision: ${c.cc_share_amount:,.2f}")
            lines.append(f"  PDR Crew:           ${c.pdr_share_amount:,.2f}")
        lines.append("")
    lines.append(f"TOTAL OWED TO PDR CREW: ${settlement.total_owed_to_pdr():,.2f}")
    lines.append(
        "Per Operating Agreement (draft, unsigned): statement due to PDR "
        "Crew within 10 days of month-end; payment due within 15 days of "
        "the statement."
    )
    return "\n".join(lines)
