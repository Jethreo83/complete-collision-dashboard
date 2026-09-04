"""Tests for app/models.py — pure logic, no DB dependency.
Run with: python test_models.py
"""
from decimal import Decimal

from app.models import (
    CostCategory,
    CostEntry,
    Estimate,
    EstimateSource,
    JobCategory,
    JobStatus,
    RepairOrder,
    validate_transition,
)


def test_repair_order_net_profit_collision_nets_labor_and_rent():
    ro = RepairOrder(
        ro_number="RO-1", vehicle_id=1, customer_id=1, site_id=1,
        category=JobCategory.COLLISION,
        gross_revenue=Decimal("10000"), direct_ro_costs=Decimal("2000"),
        labor_cost=Decimal("1500"), rent_utility_share=Decimal("500"),
    )
    assert ro.net_profit() == Decimal("6000")


def test_repair_order_net_profit_pdr_ignores_labor_and_rent():
    ro = RepairOrder(
        ro_number="RO-2", vehicle_id=1, customer_id=1, site_id=1,
        category=JobCategory.PDR,
        gross_revenue=Decimal("3000"), direct_ro_costs=Decimal("500"),
        labor_cost=Decimal("9999"), rent_utility_share=Decimal("9999"),
    )
    assert ro.net_profit() == Decimal("2500")


def test_validate_transition_allows_forward():
    validate_transition(JobStatus.UNDECIDED, JobStatus.CAME_IN)
    validate_transition(JobStatus.CAME_IN, JobStatus.ESTIMATE)
    validate_transition(JobStatus.UNDECIDED, JobStatus.MARKETING)  # skip-ahead allowed


def test_validate_transition_rejects_backward():
    try:
        validate_transition(JobStatus.PAINT, JobStatus.ESTIMATE)
        assert False, "expected ValueError for backward transition"
    except ValueError:
        pass


def test_validate_transition_rejects_noop():
    try:
        validate_transition(JobStatus.ESTIMATE, JobStatus.ESTIMATE)
        assert False, "expected ValueError for same-status no-op"
    except ValueError:
        pass


def test_estimate_manual_requires_confirmed_content():
    try:
        Estimate(
            job_id=1, version=1, source=EstimateSource.MANUAL,
            draft_content={"foo": "bar"}, confirmed_content=None,
        )
        assert False, "expected ValueError: manual estimate must be confirmed at creation"
    except ValueError:
        pass


def test_estimate_manual_with_confirmed_content_ok():
    import datetime
    e = Estimate(
        job_id=1, version=1, source=EstimateSource.MANUAL,
        draft_content={"foo": "bar"}, confirmed_content={"foo": "bar"},
        confirmed_by="jed", confirmed_at=datetime.datetime.now(),
    )
    assert e.confirmed_content == {"foo": "bar"}


def test_estimate_partial_confirmation_missing_confirmed_at_rejected():
    try:
        Estimate(
            job_id=1, version=1, source=EstimateSource.MANUAL,
            draft_content={"foo": "bar"}, confirmed_content={"foo": "bar"},
            confirmed_by="jed", confirmed_at=None,
        )
        assert False, "expected ValueError: confirmed_at missing while content/by are set"
    except ValueError:
        pass


def test_estimate_confirmation_all_or_nothing():
    try:
        Estimate(
            job_id=1, version=1, source=EstimateSource.AI_PROPOSED,
            draft_content={"foo": "bar"}, confirmed_content={"foo": "bar"},
            confirmed_by=None, confirmed_at=None,
        )
        assert False, "expected ValueError: partial confirmation state"
    except ValueError:
        pass


def test_estimate_ai_proposed_can_be_unconfirmed():
    e = Estimate(
        job_id=1, version=1, source=EstimateSource.AI_PROPOSED,
        draft_content={"foo": "bar"},
    )
    assert e.confirmed_content is None


def test_cost_entry_category_enum_values_match_migration_006():
    expected = {"parts", "labor", "paint_materials", "sublet", "rental_reimbursement", "other"}
    assert {c.value for c in CostCategory} == expected


def _run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"PASS: {t.__name__}")
    print(f"\n{passed}/{len(tests)} tests passed")


if __name__ == "__main__":
    _run_all()
