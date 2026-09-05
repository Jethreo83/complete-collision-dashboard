"""Tests for app/settlement.py -- no DB dependency, mirrors test_api.py's
mocking discipline (patches app.repository functions app.settlement calls
via `repo`). Run with: python -m pytest test_settlement.py
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models import JobCategory, RepairOrder, Site
from app.settlement import build_monthly_settlement, build_monthly_settlement_statement


def _sample_site(**overrides):
    defaults = dict(id=1, name="South")
    defaults.update(overrides)
    return Site(**defaults)


def _sample_job(**overrides):
    defaults = dict(
        id=1, ro_number="RO-1", vehicle_id=1, customer_id=1, site_id=1,
        category=JobCategory.COLLISION,
        gross_revenue=Decimal("1000.00"), direct_ro_costs=Decimal("100.00"),
        labor_cost=Decimal("200.00"), rent_utility_share=Decimal("100.00"),
    )
    defaults.update(overrides)
    return RepairOrder(**defaults)


def test_build_monthly_settlement_success():
    job = _sample_job()
    with patch("app.settlement.repo.get_site_by_id", return_value=_sample_site()), \
         patch("app.settlement.repo.get_jobs_closed_in_month", return_value=[job]) as m:
        settlement = build_monthly_settlement(object(), 1, "2026-08")
    assert settlement.month == "2026-08"
    assert settlement.site == "South"
    from pdr_settlement import ROCategory
    collision = settlement.categories[ROCategory.COLLISION]
    assert collision.ro_numbers == ["RO-1"]
    # net_profit = 1000 - (100 + 200 + 100) = 600; 70/30 split -> 420/180
    assert collision.net_profit == Decimal("600.00")
    assert collision.cc_share_amount == Decimal("420.00")
    assert collision.pdr_share_amount == Decimal("180.00")
    m.assert_called_once_with(m.call_args.args[0], 1, "2026-08")


def test_build_monthly_settlement_unknown_site_raises():
    with patch("app.settlement.repo.get_site_by_id", return_value=None):
        with pytest.raises(ValueError, match="no collision.site"):
            build_monthly_settlement(object(), 999, "2026-08")


def test_build_monthly_settlement_bad_month_format_raises():
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_monthly_settlement(object(), 1, "2026/08")


def test_build_monthly_settlement_bad_month_out_of_range_raises():
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_monthly_settlement(object(), 1, "2026-13")


def test_build_monthly_settlement_no_jobs_returns_zeroed_categories():
    with patch("app.settlement.repo.get_site_by_id", return_value=_sample_site()), \
         patch("app.settlement.repo.get_jobs_closed_in_month", return_value=[]):
        settlement = build_monthly_settlement(object(), 1, "2026-08")
    assert settlement.total_owed_to_pdr() == Decimal("0")
    for cat_settlement in settlement.categories.values():
        assert cat_settlement.ro_numbers == []


def test_build_monthly_settlement_pdr_category_nets_direct_costs_only():
    job = _sample_job(category=JobCategory.PDR, labor_cost=Decimal("999.00"))
    with patch("app.settlement.repo.get_site_by_id", return_value=_sample_site()), \
         patch("app.settlement.repo.get_jobs_closed_in_month", return_value=[job]):
        settlement = build_monthly_settlement(object(), 1, "2026-08")
    from pdr_settlement import ROCategory
    pdr = settlement.categories[ROCategory.PDR]
    # PDR nets direct_ro_costs only, ignoring labor_cost/rent_utility_share
    assert pdr.net_profit == Decimal("900.00")  # 1000 - 100, labor_cost 999 ignored
    assert pdr.cc_share_amount == Decimal("45.00")  # 5%
    assert pdr.pdr_share_amount == Decimal("855.00")  # 95%


def test_build_monthly_settlement_statement_returns_text():
    job = _sample_job()
    with patch("app.settlement.repo.get_site_by_id", return_value=_sample_site()), \
         patch("app.settlement.repo.get_jobs_closed_in_month", return_value=[job]):
        settlement, text = build_monthly_settlement_statement(object(), 1, "2026-08")
    assert "DRAFT" in text
    assert settlement.status == "draft_held_for_review"
    assert "RO-1" in text


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
