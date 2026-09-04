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
    CostCategory, CostEntry, JobCategory, JobEvent, JobStatus, RepairOrder,
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


if __name__ == "__main__":
    tests = [
        test_health, test_get_job_found, test_get_job_not_found, test_get_job_events,
        test_transition_job_success, test_transition_job_illegal_returns_400,
        test_transition_job_bad_status_value_returns_400, test_get_job_costs,
        test_add_job_cost, test_add_job_cost_bad_category_returns_400,
        test_add_job_cost_negative_amount_returns_400, test_recalculate_job_costs,
        test_job_not_found_on_costs_endpoint,
    ]
    for t in tests:
        t()
    total = len(tests)
    passed = total - len(FAILED)
    print(f"\n{passed}/{total} tests passed")
    if FAILED:
        raise SystemExit(1)
