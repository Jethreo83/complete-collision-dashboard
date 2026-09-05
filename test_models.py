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
    JOB_STATUS_SEQUENCE,
    Payment,
    PaymentSource,
    RepairOrder,
    StaffRole,
    StaffUser,
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


def test_payment_accepts_valid_check():
    p = Payment(job_id=1, source=PaymentSource.CHECK, amount=Decimal("250.00"))
    assert p.amount == Decimal("250.00")
    assert p.external_transaction_id is None


def test_payment_rejects_nonpositive_amount():
    try:
        Payment(job_id=1, source=PaymentSource.MANUAL, amount=Decimal("0"))
        assert False, "expected ValueError for amount <= 0"
    except ValueError:
        pass
    try:
        Payment(job_id=1, source=PaymentSource.MANUAL, amount=Decimal("-5"))
        assert False, "expected ValueError for negative amount"
    except ValueError:
        pass


def test_payment_authorize_net_requires_external_transaction_id():
    try:
        Payment(job_id=1, source=PaymentSource.AUTHORIZE_NET, amount=Decimal("100"))
        assert False, "expected ValueError for missing external_transaction_id"
    except ValueError:
        pass
    # Same call, with the id set, succeeds:
    p = Payment(
        job_id=1, source=PaymentSource.AUTHORIZE_NET, amount=Decimal("100"),
        external_transaction_id="txn_123",
    )
    assert p.external_transaction_id == "txn_123"


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


def test_job_status_sequence_matches_migration_008_array_literal():
    """migrations/008_collision_job_valid_transitions.sql's
    job_status_rank() function hardcodes this exact same order as a SQL
    array literal, deliberately NOT derived from this Python list (a
    migration can't import Python at apply time). The migration's own
    header flags this as a coupling that must be kept in sync by hand if
    either side changes. This test is the guardrail: if someone reorders
    JOB_STATUS_SEQUENCE without updating the SQL array (or vice versa),
    this test won't catch the SQL side directly, but it locks the Python
    side down so a silent, accidental reorder here is caught immediately
    -- pairing with scripts/verify_008.sql's own checks (which prove the
    SQL side's actual behavior) is what covers both halves of the
    coupling."""
    expected = [
        JobStatus.UNDECIDED, JobStatus.CAME_IN, JobStatus.ESTIMATE,
        JobStatus.TEARDOWN, JobStatus.WAITING_ON_PARTS, JobStatus.BODYWORK,
        JobStatus.PAINT, JobStatus.DETAIL, JobStatus.DELIVERED,
        JobStatus.CLOSED_OUT, JobStatus.MARKETING,
    ]
    assert JOB_STATUS_SEQUENCE == expected


def test_staff_user_rejects_wrong_domain():
    try:
        StaffUser(person_id=1, role=StaffRole.OWNER, google_email="jed@gmail.com")
        assert False, "expected ValueError: wrong Google Workspace domain"
    except ValueError:
        pass


def test_staff_user_rejects_lookalike_domain():
    """Same 'reject lookalike, don't just substring-match' discipline as
    migrations/009_collision_staff_domain_constraint.sql's own verify
    script (verify_009.sql) is described as testing on the SQL side --
    mirrored here in Python."""
    try:
        StaffUser(person_id=1, role=StaffRole.OWNER, google_email="jed@notcompletecollisions.com")
        assert False, "expected ValueError: lookalike domain must not pass"
    except ValueError:
        pass


def test_staff_user_accepts_correct_domain_and_normalizes_case():
    staff = StaffUser(person_id=1, role=StaffRole.MANAGER, google_email="Jed@CompleteCollisions.com")
    assert staff.google_email == "jed@completecollisions.com"


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
