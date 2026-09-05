"""Tests for app/api.py — no DB dependency. Every repository call is
mocked via unittest.mock.patch on app.repository's functions (imported
into app.api as `repo`), and the get_cursor dependency is overridden to
yield a harmless sentinel so no real connection is ever attempted. This
mirrors test_models.py's "no DB dependency" discipline for the HTTP
layer.

Run: python test_api.py
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app, get_cursor
from app.models import (
    CostCategory, CostEntry, Estimate, EstimateSource, JobCategory,
    JobEvent, JobStatus, RepairOrder, StaffRole, StaffUser,
)

FAILED = []


def _override_cursor():
    yield object()  # never touched — every repo.* call in these tests is mocked


app.dependency_overrides[get_cursor] = _override_cursor
client = TestClient(app)


def _sample_ro(**overrides) -> RepairOrder:
    defaults = dict(
        id=1, ro_number="RO-10001", vehicle_id=1, customer_id=1, site_id=1,
        category=JobCategory.COLLISION, status=JobStatus.ESTIMATE,
        claim_number="CLM-1", insurer="Acme Ins", adjuster_name="Pat Adjuster",
        posture="paying",
        gross_revenue=Decimal("5000.00"), direct_ro_costs=Decimal("1200.00"),
        labor_cost=Decimal("800.00"), rent_utility_share=Decimal("200.00"),
    )
    defaults.update(overrides)
    return RepairOrder(**defaults)


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


def test_health():
    r = client.get("/health")
    check("test_health", r.status_code == 200 and r.json() == {"status": "ok"})


def test_get_job_found():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()):
        r = client.get("/jobs/RO-10001")
    check("test_get_job_found_status", r.status_code == 200, r.text)
    body = r.json()
    check("test_get_job_found_ro_number", body["ro_number"] == "RO-10001")
    # net_profit for COLLISION nets labor + rent_utility_share too:
    # 5000 - (1200 + 800 + 200) = 2800.00
    check("test_get_job_found_net_profit", body["net_profit"] == "2800.00", body["net_profit"])


def test_get_job_not_found():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None):
        r = client.get("/jobs/RO-NOPE")
    check("test_get_job_not_found", r.status_code == 404)


def _sample_customer(**overrides):
    from app.models import Customer
    defaults = dict(id=1, person_id=42, source="walk_in")
    defaults.update(overrides)
    return Customer(**defaults)


def _sample_vehicle(**overrides):
    from app.models import Vehicle
    defaults = dict(id=1, customer_id=1, vin="1HGCM82633A123456", make="Honda", model="Accord", year=2019)
    defaults.update(overrides)
    return Vehicle(**defaults)


def _sample_site(**overrides):
    from app.models import Site
    defaults = dict(id=1, name="South")
    defaults.update(overrides)
    return Site(**defaults)


_CREATE_JOB_BODY = {
    "person_id": 42, "site_name": "South", "ro_number": "RO-99999",
    "category": "collision", "actor": "jed",
}


def test_create_job_success():
    created = _sample_ro(id=1, ro_number="RO-99999")
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.api.repo.get_person_by_id", return_value={"id": 42}), \
         patch("app.api.repo.create_customer_for_existing_person", return_value=_sample_customer()), \
         patch("app.api.repo.get_or_create_vehicle", return_value=_sample_vehicle()), \
         patch("app.api.repo.get_or_create_site", return_value=_sample_site()), \
         patch("app.api.repo.create_repair_order", return_value=created) as mock_create:
        r = client.post("/jobs", json=_CREATE_JOB_BODY)
    check("test_create_job_success_status", r.status_code == 200, r.text)
    check("test_create_job_success_body", r.json()["ro_number"] == "RO-99999")
    args, kwargs = mock_create.call_args
    ro_arg = args[1] if len(args) > 1 else kwargs.get("ro")
    check("test_create_job_success_category_passed", ro_arg.category == JobCategory.COLLISION)


def test_create_job_duplicate_ro_number_returns_400():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro(ro_number="RO-99999")):
        r = client.post("/jobs", json=_CREATE_JOB_BODY)
    check("test_create_job_duplicate_ro_number_returns_400", r.status_code == 400, r.text)


def test_create_job_bad_category_returns_400():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None):
        r = client.post("/jobs", json={**_CREATE_JOB_BODY, "category": "not_a_category"})
    check("test_create_job_bad_category_returns_400", r.status_code == 400, r.text)


def test_create_job_bad_status_returns_400():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None):
        r = client.post("/jobs", json={**_CREATE_JOB_BODY, "status": "not_a_real_status"})
    check("test_create_job_bad_status_returns_400", r.status_code == 400, r.text)


def test_create_job_nonexistent_person_id_returns_400():
    """Real bug found via HTTP smoke test against staging (2026-09-07):
    a person_id that doesn't reference an existing platform.person row
    used to fall through to an unhandled FK violation (raw 500), not a
    clean 400. Fixed by checking repo.get_person_by_id() before
    attempting any write; this test guards the regression."""
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.api.repo.get_person_by_id", return_value=None):
        r = client.post("/jobs", json={**_CREATE_JOB_BODY, "person_id": 999999999})
    check("test_create_job_nonexistent_person_id_returns_400", r.status_code == 400, r.text)


def test_create_job_repo_value_error_returns_400():
    """e.g. customer_source is invalid (create_customer_for_existing_person
    raises ValueError for a genuinely bad value, not silently accepted)."""
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.api.repo.get_person_by_id", return_value={"id": 42}), \
         patch("app.api.repo.create_customer_for_existing_person", side_effect=ValueError("Unknown customer source")):
        r = client.post("/jobs", json=_CREATE_JOB_BODY)
    check("test_create_job_repo_value_error_returns_400", r.status_code == 400, r.text)


def test_get_job_events():
    events = [
        JobEvent(id=1, job_id=1, to_status=JobStatus.CAME_IN, from_status=None, created_by="jed"),
        JobEvent(id=2, job_id=1, to_status=JobStatus.ESTIMATE, from_status=JobStatus.CAME_IN, created_by="jed"),
    ]
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.list_job_events", return_value=events):
        r = client.get("/jobs/RO-10001/events")
    check("test_get_job_events_status", r.status_code == 200, r.text)
    body = r.json()
    check("test_get_job_events_count", len(body) == 2)
    check("test_get_job_events_order", body[0]["to_status"] == "came_in" and body[1]["to_status"] == "estimate")


def test_transition_job_success():
    updated = _sample_ro(status=JobStatus.TEARDOWN)
    with patch("app.api.repo.transition_job_status", return_value=updated) as mock_transition:
        r = client.post(
            "/jobs/RO-10001/transition",
            json={"target_status": "teardown", "actor": "jed", "note": "moving along"},
        )
    check("test_transition_job_success_status", r.status_code == 200, r.text)
    check("test_transition_job_success_body", r.json()["status"] == "teardown")
    args, kwargs = mock_transition.call_args
    actor_passed = "jed" in args or kwargs.get("actor") == "jed"
    check("test_transition_job_success_actor_passed", actor_passed, f"args={args} kwargs={kwargs}")


def test_transition_job_illegal_returns_400():
    with patch("app.api.repo.transition_job_status", side_effect=ValueError("Cannot move job status backward")):
        r = client.post(
            "/jobs/RO-10001/transition",
            json={"target_status": "undecided", "actor": "jed"},
        )
    check("test_transition_job_illegal_returns_400", r.status_code == 400, r.text)


def test_transition_job_bad_status_value_returns_400():
    r = client.post(
        "/jobs/RO-10001/transition",
        json={"target_status": "not_a_real_status", "actor": "jed"},
    )
    check("test_transition_job_bad_status_value_returns_400", r.status_code == 400, r.text)


def test_patch_job_intake_partial_update_only_passes_supplied_fields():
    """exclude_unset is the core behavior under test: a field absent from
    the JSON body must arrive at repo.update_job_intake_fields() as the
    repo._UNSET sentinel (not None, not omitted), while a field that IS
    supplied (even if its value happens to equal the old value) must
    arrive as a real value."""
    import app.repository as repo_module
    updated = _sample_ro(insurer="New Insurer Co")
    with patch("app.api.repo.update_job_intake_fields", return_value=updated) as mock_update:
        r = client.patch(
            "/jobs/RO-10001",
            json={"insurer": "New Insurer Co", "actor": "jed"},
        )
    check("test_patch_job_intake_partial_update_status", r.status_code == 200, r.text)
    check("test_patch_job_intake_partial_update_body", r.json()["insurer"] == "New Insurer Co")
    args, kwargs = mock_update.call_args
    check(
        "test_patch_job_intake_partial_update_only_insurer_set",
        kwargs.get("insurer") == "New Insurer Co"
        and kwargs.get("claim_number") is repo_module._UNSET
        and kwargs.get("adjuster_name") is repo_module._UNSET
        and kwargs.get("posture") is repo_module._UNSET,
        f"kwargs={kwargs}",
    )


def test_patch_job_intake_explicit_null_clears_field():
    """A field explicitly sent as JSON null (not merely absent) must pass
    through as a real None, distinct from the _UNSET sentinel used for
    absent fields -- this is the whole reason the route uses
    exclude_unset instead of the schema's own defaults."""
    import app.repository as repo_module
    updated = _sample_ro(adjuster_name=None)
    with patch("app.api.repo.update_job_intake_fields", return_value=updated) as mock_update:
        r = client.patch(
            "/jobs/RO-10001",
            json={"adjuster_name": None, "actor": "jed"},
        )
    check("test_patch_job_intake_explicit_null_status", r.status_code == 200, r.text)
    check("test_patch_job_intake_explicit_null_body", r.json()["adjuster_name"] is None)
    args, kwargs = mock_update.call_args
    check(
        "test_patch_job_intake_explicit_null_kwargs",
        kwargs.get("adjuster_name") is None and kwargs.get("insurer") is repo_module._UNSET,
        f"kwargs={kwargs}",
    )


def test_patch_job_intake_job_not_found_returns_404():
    with patch("app.api.repo.update_job_intake_fields", side_effect=ValueError("No job with ro_number='RO-NOPE'")):
        r = client.patch(
            "/jobs/RO-NOPE",
            json={"claim_number": "CLM-9", "actor": "jed"},
        )
    check("test_patch_job_intake_job_not_found_returns_404", r.status_code == 404, r.text)


def test_get_job_costs():
    entries = [
        CostEntry(id=1, job_id=1, category=CostCategory.PARTS, amount=Decimal("410.50"),
                  description="bumper", source="csv_import", source_file="cost_entries.csv"),
    ]
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.list_cost_entries", return_value=entries):
        r = client.get("/jobs/RO-10001/costs")
    check("test_get_job_costs_status", r.status_code == 200, r.text)
    check("test_get_job_costs_amount", r.json()[0]["amount"] == "410.50")


def test_add_job_cost():
    created = CostEntry(id=5, job_id=1, category=CostCategory.LABOR, amount=Decimal("100.00"),
                         description="extra labor", source="manual")
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.add_cost_entry", return_value=created):
        r = client.post(
            "/jobs/RO-10001/costs",
            json={"category": "labor", "amount": "100.00", "actor": "jed", "description": "extra labor"},
        )
    check("test_add_job_cost_status", r.status_code == 200, r.text)
    check("test_add_job_cost_category", r.json()["category"] == "labor")


def test_add_job_cost_bad_category_returns_400():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()):
        r = client.post(
            "/jobs/RO-10001/costs",
            json={"category": "not_a_category", "amount": "10.00", "actor": "jed"},
        )
    check("test_add_job_cost_bad_category_returns_400", r.status_code == 400, r.text)


def test_add_job_cost_negative_amount_returns_400():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.add_cost_entry", side_effect=ValueError("cost_entry amount must be >= 0")):
        r = client.post(
            "/jobs/RO-10001/costs",
            json={"category": "parts", "amount": "-5.00", "actor": "jed"},
        )
    check("test_add_job_cost_negative_amount_returns_400", r.status_code == 400, r.text)


def test_recalculate_job_costs():
    """NOTE (migration 010, 2026-09-06): the /costs/recalculate endpoint
    is now a harmless re-read, not an actual recalculation -- labor_cost/
    direct_ro_costs are kept correct automatically by a DB trigger on
    collision.cost_entry writes. The endpoint no longer calls
    repo.recalculate_costs_from_entries() at all, so mocking that
    function to return a different value than get_repair_order_by_ro_number
    (as this test previously did) tests behavior that no longer exists.
    Fixed to assert what the endpoint actually does now: return whatever
    get_repair_order_by_ro_number() returns, unchanged."""
    ro_with_current_derived_costs = _sample_ro(labor_cost=Decimal("455.00"), direct_ro_costs=Decimal("410.50"))
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=ro_with_current_derived_costs):
        r = client.post("/jobs/RO-10001/costs/recalculate", json={"actor": "jed"})
    check("test_recalculate_job_costs_status", r.status_code == 200, r.text)
    check("test_recalculate_job_costs_labor", r.json()["labor_cost"] == "455.00")


def test_job_not_found_on_costs_endpoint():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None):
        r = client.get("/jobs/RO-NOPE/costs")
    check("test_job_not_found_on_costs_endpoint", r.status_code == 404)


# ---------------------------------------------------------------------------
# Estimates routes (2026-09-06 backlog item #2)
# ---------------------------------------------------------------------------

def _sample_estimate(**overrides) -> Estimate:
    from datetime import datetime
    defaults = dict(
        id=1, job_id=1, version=1, source=EstimateSource.MANUAL,
        draft_content={"total": "5000.00"}, confirmed_content={"total": "5000.00"},
        confirmed_by="jed", confirmed_at=datetime(2026, 9, 6, 12, 0, 0),
    )
    defaults.update(overrides)
    return Estimate(**defaults)


def test_get_job_estimates():
    estimates = [_sample_estimate(id=1, version=1), _sample_estimate(id=2, version=2)]
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.get_estimates_for_job", return_value=estimates):
        r = client.get("/jobs/RO-10001/estimates")
    check("test_get_job_estimates_status", r.status_code == 200, r.text)
    check("test_get_job_estimates_count", len(r.json()) == 2)


def test_get_job_estimates_job_not_found():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None):
        r = client.get("/jobs/RO-NOPE/estimates")
    check("test_get_job_estimates_job_not_found", r.status_code == 404)


def test_get_job_latest_estimate_found():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.get_latest_estimate_for_job", return_value=_sample_estimate(version=3)):
        r = client.get("/jobs/RO-10001/estimates/latest")
    check("test_get_job_latest_estimate_found_status", r.status_code == 200, r.text)
    check("test_get_job_latest_estimate_found_version", r.json()["version"] == 3)


def test_get_job_latest_estimate_none_yet():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.get_latest_estimate_for_job", return_value=None):
        r = client.get("/jobs/RO-10001/estimates/latest")
    check("test_get_job_latest_estimate_none_yet", r.status_code == 404, r.text)


def test_create_job_estimate_success():
    created = _sample_estimate(id=9, version=1, draft_content={"total": "3200.00"},
                                confirmed_content={"total": "3200.00"})
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.create_manual_estimate", return_value=created) as mocked:
        r = client.post(
            "/jobs/RO-10001/estimates",
            json={"content": {"total": "3200.00"}, "actor": "jed"},
        )
    check("test_create_job_estimate_status", r.status_code == 200, r.text)
    check("test_create_job_estimate_version", r.json()["version"] == 1)
    # confirms the route passes ro.id (not the ro_number string) through to
    # the repository layer, matching create_manual_estimate(cur, job_id, ...)
    check("test_create_job_estimate_calls_with_job_id", mocked.call_args[0][1] == _sample_ro().id)


def test_create_job_estimate_job_not_found():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=None):
        r = client.post(
            "/jobs/RO-NOPE/estimates",
            json={"content": {"total": "1.00"}, "actor": "jed"},
        )
    check("test_create_job_estimate_job_not_found", r.status_code == 404, r.text)


def test_create_job_estimate_repo_value_error_returns_400():
    with patch("app.api.repo.get_repair_order_by_ro_number", return_value=_sample_ro()), \
         patch("app.api.repo.create_manual_estimate", side_effect=ValueError("confirmed_content required")):
        r = client.post(
            "/jobs/RO-10001/estimates",
            json={"content": {"total": "1.00"}, "actor": "jed"},
        )
    check("test_create_job_estimate_repo_value_error_returns_400", r.status_code == 400, r.text)


# ---------------------------------------------------------------------------
# Staff routes (2026-09-06 backlog item #1)
# ---------------------------------------------------------------------------

def _sample_staff(**overrides) -> StaffUser:
    defaults = dict(
        id=1, person_id=1, role=StaffRole.MANAGER,
        google_email="jane.doe@completecollisions.com", active=True,
    )
    defaults.update(overrides)
    return StaffUser(**defaults)


def test_provision_staff_success():
    with patch("app.api.repo.provision_staff_user_for_existing_person", return_value=_sample_staff()):
        r = client.post(
            "/staff",
            json={"person_id": 1, "role": "manager", "google_email": "jane.doe@completecollisions.com", "actor": "jed"},
        )
    check("test_provision_staff_success_status", r.status_code == 200, r.text)
    check("test_provision_staff_success_email", r.json()["google_email"] == "jane.doe@completecollisions.com")


def test_provision_staff_bad_role_returns_400():
    r = client.post(
        "/staff",
        json={"person_id": 1, "role": "not_a_role", "google_email": "jane.doe@completecollisions.com", "actor": "jed"},
    )
    check("test_provision_staff_bad_role_returns_400", r.status_code == 400, r.text)


def test_provision_staff_duplicate_returns_400():
    with patch("app.api.repo.provision_staff_user_for_existing_person",
               side_effect=ValueError("staff_user with google_email='jane.doe@completecollisions.com' already exists")):
        r = client.post(
            "/staff",
            json={"person_id": 1, "role": "manager", "google_email": "jane.doe@completecollisions.com", "actor": "jed"},
        )
    check("test_provision_staff_duplicate_returns_400", r.status_code == 400, r.text)


def test_get_staff_found():
    with patch("app.api.repo.get_staff_user_by_google_email", return_value=_sample_staff()):
        r = client.get("/staff/jane.doe@completecollisions.com")
    check("test_get_staff_found_status", r.status_code == 200, r.text)


def test_get_staff_not_found():
    with patch("app.api.repo.get_staff_user_by_google_email", return_value=None):
        r = client.get("/staff/nobody@completecollisions.com")
    check("test_get_staff_not_found", r.status_code == 404)


def test_get_staff_capability_active():
    with patch("app.api.repo.get_staff_user_by_google_email", return_value=_sample_staff()), \
         patch("app.api.repo.get_staff_capability", return_value="full"):
        r = client.get("/staff/jane.doe@completecollisions.com/capability")
    check("test_get_staff_capability_active_status", r.status_code == 200, r.text)
    check("test_get_staff_capability_active_value", r.json()["capability_level"] == "full")


def test_get_staff_capability_unknown_email_404():
    with patch("app.api.repo.get_staff_user_by_google_email", return_value=None):
        r = client.get("/staff/nobody@completecollisions.com/capability")
    check("test_get_staff_capability_unknown_email_404", r.status_code == 404)


def test_set_staff_active_deactivate():
    deactivated = _sample_staff(active=False)
    with patch("app.api.repo.set_staff_user_active", return_value=deactivated):
        r = client.post(
            "/staff/jane.doe@completecollisions.com/active",
            json={"active": False, "actor": "jed"},
        )
    check("test_set_staff_active_deactivate_status", r.status_code == 200, r.text)
    check("test_set_staff_active_deactivate_value", r.json()["active"] is False)


def test_set_staff_active_unknown_returns_404():
    with patch("app.api.repo.set_staff_user_active", side_effect=ValueError("no staff_user with google_email='nobody@completecollisions.com'")):
        r = client.post(
            "/staff/nobody@completecollisions.com/active",
            json={"active": True, "actor": "jed"},
        )
    check("test_set_staff_active_unknown_returns_404", r.status_code == 404, r.text)


if __name__ == "__main__":
    tests = [
        test_health, test_get_job_found, test_get_job_not_found,
        test_create_job_success, test_create_job_duplicate_ro_number_returns_400,
        test_create_job_bad_category_returns_400, test_create_job_bad_status_returns_400,
        test_create_job_nonexistent_person_id_returns_400,
        test_create_job_repo_value_error_returns_400,
        test_get_job_events,
        test_transition_job_success, test_transition_job_illegal_returns_400,
        test_transition_job_bad_status_value_returns_400,
        test_patch_job_intake_partial_update_only_passes_supplied_fields,
        test_patch_job_intake_explicit_null_clears_field,
        test_patch_job_intake_job_not_found_returns_404,
        test_get_job_costs,
        test_add_job_cost, test_add_job_cost_bad_category_returns_400,
        test_add_job_cost_negative_amount_returns_400, test_recalculate_job_costs,
        test_job_not_found_on_costs_endpoint,
        test_get_job_estimates, test_get_job_estimates_job_not_found,
        test_get_job_latest_estimate_found, test_get_job_latest_estimate_none_yet,
        test_create_job_estimate_success, test_create_job_estimate_job_not_found,
        test_create_job_estimate_repo_value_error_returns_400,
        test_provision_staff_success, test_provision_staff_bad_role_returns_400,
        test_provision_staff_duplicate_returns_400,
        test_get_staff_found, test_get_staff_not_found,
        test_get_staff_capability_active, test_get_staff_capability_unknown_email_404,
        test_set_staff_active_deactivate, test_set_staff_active_unknown_returns_404,
    ]
    for t in tests:
        t()
    total = len(tests)
    passed = total - len(FAILED)
    print(f"\n{passed}/{total} tests passed")
    if FAILED:
        raise SystemExit(1)
