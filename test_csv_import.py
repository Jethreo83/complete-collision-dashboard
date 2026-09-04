"""Tests for app/csv_import.py — a REAL, previously-untested gap found
this cron cycle (2026-09-06): the module implementing ADR-001 §1's actual
v1 answer for CCC ONE-adjacent data entry (manual/CSV only) had zero test
coverage anywhere in the repo (confirmed by `search_files` for
test_csv_import* before writing this file — nothing existed).

No DB dependency, same discipline as test_models.py/test_api.py:
  - `cur.execute(...)`/`cur.fetchone()` calls this module makes directly
    (the platform.person email lookups) are served by a small FakeCursor
    that inspects the bound parameter rather than the SQL text, so it
    doesn't break if the query is reformatted.
  - Every app.repository.* call is patched via unittest.mock, exactly
    like test_api.py patches app.api.repo.*.
  - Real temporary CSV files are written to disk and read by the actual
    `_read_rows()`/`csv.DictReader` code path — not hand-built dicts
    bypassing the CSV parsing this module exists to do.

Run: python test_csv_import.py
"""
from __future__ import annotations

import atexit
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app import csv_import as ci
from app.models import CostCategory, CostEntry, JobCategory, JobStatus

FAILED = []
_TEMP_CSV_PATHS: list[str] = []


def _cleanup_temp_csvs():
    """write_csv() creates real temp files via tempfile.mkstemp() so this
    module exercises the actual csv.DictReader code path (not hand-built
    dicts) -- mkstemp does not auto-delete, so clean them up on interpreter
    exit rather than leaving scratch files behind in the OS temp dir."""
    for p in _TEMP_CSV_PATHS:
        try:
            os.remove(p)
        except OSError:
            pass


atexit.register(_cleanup_temp_csvs)


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILED.append(name)


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

class FakeCursor:
    """Serves the module's direct `SELECT id FROM platform.person WHERE
    email_normalized = %s` calls. `people` maps normalized email -> id.
    Any other cur.execute() call in this module doesn't exist (all other
    reads/writes go through app.repository, which is mocked separately),
    so this fake only needs to handle the one query shape."""

    def __init__(self, people: dict):
        self.people = people
        self._last_result = None

    def execute(self, sql, params=None):
        params = params or ()
        if len(params) == 1:
            email = params[0]
            person_id = self.people.get(email)
            self._last_result = {"id": person_id} if person_id is not None else None
        else:
            self._last_result = None

    def fetchone(self):
        return self._last_result


def write_csv(rows: list[dict], headers: list[str]) -> str:
    """Writes a real CSV to a temp file and returns its path — exercises
    the real csv.DictReader path in ci._read_rows(), not a bypass."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    _TEMP_CSV_PATHS.append(path)
    import csv
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# ImportReport
# ---------------------------------------------------------------------------

def test_import_report_ok_true_when_no_errors():
    r = ci.ImportReport(file="x.csv", dry_run=True, total_rows=2, created=2)
    check("test_import_report_ok_true_when_no_errors", r.ok())


def test_import_report_ok_false_with_errors():
    r = ci.ImportReport(file="x.csv", dry_run=True, total_rows=1, errors=["row 2: bad"])
    check("test_import_report_ok_false_with_errors", not r.ok())


def test_import_report_summary_includes_error_lines():
    r = ci.ImportReport(file="x.csv", dry_run=False, total_rows=1, errors=["row 2: bad thing"])
    s = r.summary()
    check(
        "test_import_report_summary_includes_error_lines",
        "row 2: bad thing" in s and "COMMITTED" in s,
        s,
    )


# ---------------------------------------------------------------------------
# Helper parsers (_clean/_parse_decimal/_parse_int/_parse_date)
# ---------------------------------------------------------------------------

def test_clean_strips_and_nones_blank():
    check("test_clean_strips_whitespace", ci._clean("  foo  ") == "foo")
    check("test_clean_blank_to_none", ci._clean("   ") is None)
    check("test_clean_none_stays_none", ci._clean(None) is None)


def test_parse_decimal_default_and_value():
    check("test_parse_decimal_blank_defaults_to_zero", ci._parse_decimal("", "amount") == Decimal("0"))
    check("test_parse_decimal_parses_value", ci._parse_decimal("42.50", "amount") == Decimal("42.50"))


def test_parse_decimal_invalid_raises():
    try:
        ci._parse_decimal("not-a-number", "amount")
        check("test_parse_decimal_invalid_raises", False, "did not raise")
    except ValueError as e:
        check("test_parse_decimal_invalid_raises", "amount" in str(e))


def test_parse_int_blank_is_none_and_parses_value():
    check("test_parse_int_blank_is_none", ci._parse_int("", "year") is None)
    check("test_parse_int_parses_value", ci._parse_int("2020", "year") == 2020)


def test_parse_int_invalid_raises():
    try:
        ci._parse_int("abc", "year")
        check("test_parse_int_invalid_raises", False, "did not raise")
    except ValueError:
        check("test_parse_int_invalid_raises", True)


def test_parse_date_blank_none_and_parses_value():
    check("test_parse_date_blank_is_none", ci._parse_date("", "incurred_at") is None)
    check(
        "test_parse_date_parses_value",
        ci._parse_date("2026-01-15", "incurred_at") == date(2026, 1, 15),
    )


def test_parse_date_invalid_raises():
    try:
        ci._parse_date("01/15/2026", "incurred_at")
        check("test_parse_date_invalid_raises", False, "did not raise")
    except ValueError:
        check("test_parse_date_invalid_raises", True)


# ---------------------------------------------------------------------------
# import_customers_csv
# ---------------------------------------------------------------------------

def test_import_customers_dry_run_reports_created_without_writing():
    path = write_csv(
        [{"first_name": "A", "last_name": "B", "email": "a@x.com", "phone": "", "source": ""}],
        ["first_name", "last_name", "email", "phone", "source"],
    )
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_customer_by_person_id", return_value=None), \
         patch("app.csv_import.repo.create_customer_for_existing_person") as mock_create:
        report = ci.import_customers_csv(cur, path, "jed", dry_run=True)
    check("test_import_customers_dry_run_created_count", report.created == 1, report.summary())
    check("test_import_customers_dry_run_no_errors", report.ok(), report.summary())
    check("test_import_customers_dry_run_never_writes", mock_create.call_count == 0)


def test_import_customers_commit_calls_create_with_source():
    path = write_csv(
        [{"first_name": "A", "last_name": "B", "email": "A@X.com", "phone": "", "source": "insurer_referred"}],
        ["first_name", "last_name", "email", "phone", "source"],
    )
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_customer_by_person_id", return_value=None), \
         patch("app.csv_import.repo.create_customer_for_existing_person") as mock_create:
        report = ci.import_customers_csv(cur, path, "jed", dry_run=False)
    check("test_import_customers_commit_created_count", report.created == 1, report.summary())
    args, kwargs = mock_create.call_args
    check(
        "test_import_customers_commit_email_lowercased_for_lookup_and_source_passed",
        args[1] == 5 and (kwargs.get("source") == "insurer_referred" or "insurer_referred" in args),
        f"args={args} kwargs={kwargs}",
    )


def test_import_customers_missing_email_is_error_row():
    path = write_csv(
        [{"first_name": "A", "last_name": "B", "email": "", "phone": "", "source": ""}],
        ["first_name", "last_name", "email", "phone", "source"],
    )
    cur = FakeCursor({})
    report = ci.import_customers_csv(cur, path, "jed", dry_run=True)
    check("test_import_customers_missing_email_is_error", len(report.errors) == 1, report.summary())
    check("test_import_customers_missing_email_row_number", "row 2" in report.errors[0], report.errors)


def test_import_customers_person_not_found_is_error_row():
    path = write_csv(
        [{"first_name": "A", "last_name": "B", "email": "nobody@x.com", "phone": "", "source": ""}],
        ["first_name", "last_name", "email", "phone", "source"],
    )
    cur = FakeCursor({})  # no matching person
    report = ci.import_customers_csv(cur, path, "jed", dry_run=True)
    check("test_import_customers_person_not_found_is_error", len(report.errors) == 1, report.summary())
    check(
        "test_import_customers_person_not_found_message_is_clear",
        "no platform.person found" in report.errors[0],
        report.errors,
    )


def test_import_customers_existing_customer_is_skipped_not_created():
    path = write_csv(
        [{"first_name": "A", "last_name": "B", "email": "a@x.com", "phone": "", "source": ""}],
        ["first_name", "last_name", "email", "phone", "source"],
    )
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_customer_by_person_id", return_value=object()), \
         patch("app.csv_import.repo.create_customer_for_existing_person") as mock_create:
        report = ci.import_customers_csv(cur, path, "jed", dry_run=False)
    check("test_import_customers_existing_customer_skipped", report.skipped == 1 and report.created == 0)
    check("test_import_customers_existing_customer_never_double_creates", mock_create.call_count == 0)


# ---------------------------------------------------------------------------
# import_vehicles_csv
# ---------------------------------------------------------------------------

@dataclass
class _FakeCustomer:
    id: int


def test_import_vehicles_happy_path_commits():
    path = write_csv(
        [{"customer_email": "a@x.com", "vin": "VIN1", "make": "Toyota", "model": "Camry", "year": "2020"}],
        ["customer_email", "vin", "make", "model", "year"],
    )
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=None), \
         patch("app.csv_import.repo.get_or_create_vehicle") as mock_create:
        report = ci.import_vehicles_csv(cur, path, "jed", dry_run=False)
    check("test_import_vehicles_happy_path_created", report.created == 1, report.summary())
    args, kwargs = mock_create.call_args
    check(
        "test_import_vehicles_happy_path_passes_customer_id_and_vin",
        args[1] == 9 and kwargs.get("vin") == "VIN1",
        f"args={args} kwargs={kwargs}",
    )


def test_import_vehicles_no_customer_row_is_error():
    path = write_csv(
        [{"customer_email": "a@x.com", "vin": "VIN1", "make": "", "model": "", "year": ""}],
        ["customer_email", "vin", "make", "model", "year"],
    )
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_customer_by_person_id", return_value=None):
        report = ci.import_vehicles_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_vehicles_no_customer_row_is_error",
        len(report.errors) == 1 and "no collision.customer" in report.errors[0],
        report.summary(),
    )


def test_import_vehicles_existing_vin_is_skipped():
    path = write_csv(
        [{"customer_email": "a@x.com", "vin": "VIN1", "make": "", "model": "", "year": ""}],
        ["customer_email", "vin", "make", "model", "year"],
    )
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=object()), \
         patch("app.csv_import.repo.get_or_create_vehicle") as mock_create:
        report = ci.import_vehicles_csv(cur, path, "jed", dry_run=False)
    check("test_import_vehicles_existing_vin_skipped", report.skipped == 1 and report.created == 0)
    check("test_import_vehicles_existing_vin_never_creates", mock_create.call_count == 0)


# ---------------------------------------------------------------------------
# import_jobs_csv
# ---------------------------------------------------------------------------

@dataclass
class _FakeVehicle:
    id: int
    vin: str = None


@dataclass
class _FakeRO:
    id: int


def _jobs_row(**overrides) -> dict:
    row = dict(
        ro_number="RO-9001", customer_email="a@x.com", vin="VIN1", site="Main St",
        category="collision", status="", claim_number="", insurer="", adjuster_name="",
        posture="", gross_revenue="1000", direct_ro_costs="0", labor_cost="0",
        rent_utility_share="0",
    )
    row.update(overrides)
    return row


JOBS_HEADERS = [
    "ro_number", "customer_email", "vin", "site", "category", "status",
    "claim_number", "insurer", "adjuster_name", "posture", "gross_revenue",
    "direct_ro_costs", "labor_cost", "rent_utility_share",
]


def test_import_jobs_existing_ro_is_skipped():
    path = write_csv([_jobs_row()], JOBS_HEADERS)
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=object()):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check("test_import_jobs_existing_ro_is_skipped", report.skipped == 1 and report.created == 0)


def test_import_jobs_unknown_person_is_error():
    path = write_csv([_jobs_row()], JOBS_HEADERS)
    cur = FakeCursor({})  # no matching person
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_jobs_unknown_person_is_error",
        len(report.errors) == 1 and "no platform.person found" in report.errors[0],
        report.summary(),
    )


def test_import_jobs_vin_not_on_file_is_error():
    path = write_csv([_jobs_row()], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=None):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_jobs_vin_not_on_file_is_error",
        len(report.errors) == 1 and "import vehicles.csv first" in report.errors[0],
        report.summary(),
    )


def test_import_jobs_no_vin_zero_vehicles_is_error():
    path = write_csv([_jobs_row(vin="")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicles_by_customer", return_value=[]):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_jobs_no_vin_zero_vehicles_is_error",
        len(report.errors) == 1 and "no vehicle on file" in report.errors[0],
        report.summary(),
    )


def test_import_jobs_no_vin_multiple_vehicles_is_ambiguous_error():
    path = write_csv([_jobs_row(vin="")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicles_by_customer", return_value=[_FakeVehicle(id=1), _FakeVehicle(id=2)]):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_jobs_no_vin_multiple_vehicles_is_ambiguous_error",
        len(report.errors) == 1 and "ambiguous" in report.errors[0],
        report.summary(),
    )


def test_import_jobs_no_vin_single_vehicle_disambiguates_and_commits():
    path = write_csv([_jobs_row(vin="")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    fake_ro = _FakeRO(id=42)
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicles_by_customer", return_value=[_FakeVehicle(id=7)]), \
         patch("app.csv_import.repo.get_or_create_site") as mock_site, \
         patch("app.csv_import.repo.create_repair_order", return_value=fake_ro) as mock_create_ro, \
         patch("app.csv_import.repo.add_cost_entry") as mock_add_cost:
        mock_site.return_value.id = 3
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=False)
    check("test_import_jobs_no_vin_single_vehicle_created", report.created == 1, report.summary())
    ro_arg = mock_create_ro.call_args[0][1]
    check("test_import_jobs_no_vin_single_vehicle_used_that_vehicle", ro_arg.vehicle_id == 7)
    check("test_import_jobs_no_vin_single_vehicle_no_cost_entries", mock_add_cost.call_count == 0)


def test_import_jobs_bad_category_is_error():
    path = write_csv([_jobs_row(category="not-a-category")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=_FakeVehicle(id=7)):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_jobs_bad_category_is_error",
        len(report.errors) == 1 and "category" in report.errors[0],
        report.summary(),
    )


def test_import_jobs_bad_status_is_error():
    path = write_csv([_jobs_row(status="not-a-status")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=_FakeVehicle(id=7)):
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_jobs_bad_status_is_error",
        len(report.errors) == 1 and "status" in report.errors[0],
        report.summary(),
    )


def test_import_jobs_blank_status_defaults_to_undecided():
    path = write_csv([_jobs_row(status="")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    fake_ro = _FakeRO(id=42)
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=_FakeVehicle(id=7)), \
         patch("app.csv_import.repo.get_or_create_site") as mock_site, \
         patch("app.csv_import.repo.create_repair_order", return_value=fake_ro) as mock_create_ro:
        mock_site.return_value.id = 3
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=False)
    ro_arg = mock_create_ro.call_args[0][1]
    check(
        "test_import_jobs_blank_status_defaults_to_undecided",
        ro_arg.status == JobStatus.UNDECIDED,
        ro_arg.status,
    )
    check("test_import_jobs_blank_status_created", report.created == 1)


def test_import_jobs_migration_010_compat_converts_flat_costs_to_cost_entries():
    """The real compatibility path documented in the module's own
    docstring: a jobs.csv row with non-zero labor_cost/direct_ro_costs
    (the old flat-total format, from before migration 010 made those
    columns DB-derived) must NOT silently drop the value — it must be
    converted into equivalent collision.cost_entry rows instead."""
    path = write_csv([_jobs_row(labor_cost="150.00", direct_ro_costs="75.50")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    fake_ro = _FakeRO(id=42)
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=_FakeVehicle(id=7)), \
         patch("app.csv_import.repo.get_or_create_site") as mock_site, \
         patch("app.csv_import.repo.create_repair_order", return_value=fake_ro), \
         patch("app.csv_import.repo.add_cost_entry") as mock_add_cost:
        mock_site.return_value.id = 3
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=False)
    check("test_import_jobs_migration_010_compat_created", report.created == 1, report.summary())
    check("test_import_jobs_migration_010_compat_two_cost_entries", mock_add_cost.call_count == 2, mock_add_cost.call_args_list)
    entries = [call_args[0][1] for call_args in mock_add_cost.call_args_list]
    categories = {e.category for e in entries}
    amounts = {e.category: e.amount for e in entries}
    check(
        "test_import_jobs_migration_010_compat_labor_category_and_amount",
        CostCategory.LABOR in categories and amounts[CostCategory.LABOR] == Decimal("150.00"),
        entries,
    )
    check(
        "test_import_jobs_migration_010_compat_other_category_and_amount",
        CostCategory.OTHER in categories and amounts[CostCategory.OTHER] == Decimal("75.50"),
        entries,
    )
    check(
        "test_import_jobs_migration_010_compat_all_sourced_as_csv_import",
        all(e.source == "csv_import" and e.source_file == os.path.basename(path) for e in entries),
        entries,
    )


def test_import_jobs_zero_flat_costs_do_not_create_cost_entries():
    path = write_csv([_jobs_row(labor_cost="0", direct_ro_costs="0")], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    fake_ro = _FakeRO(id=42)
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=_FakeVehicle(id=7)), \
         patch("app.csv_import.repo.get_or_create_site") as mock_site, \
         patch("app.csv_import.repo.create_repair_order", return_value=fake_ro), \
         patch("app.csv_import.repo.add_cost_entry") as mock_add_cost:
        mock_site.return_value.id = 3
        ci.import_jobs_csv(cur, path, "jed", dry_run=False)
    check("test_import_jobs_zero_flat_costs_do_not_create_cost_entries", mock_add_cost.call_count == 0)


def test_import_jobs_dry_run_never_calls_create_repair_order():
    path = write_csv([_jobs_row()], JOBS_HEADERS)
    cur = FakeCursor({"a@x.com": 5})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None), \
         patch("app.csv_import.repo.get_customer_by_person_id", return_value=_FakeCustomer(id=9)), \
         patch("app.csv_import.repo.get_vehicle_by_vin", return_value=_FakeVehicle(id=7)), \
         patch("app.csv_import.repo.create_repair_order") as mock_create_ro:
        report = ci.import_jobs_csv(cur, path, "jed", dry_run=True)
    check("test_import_jobs_dry_run_reports_created", report.created == 1, report.summary())
    check("test_import_jobs_dry_run_never_calls_create_repair_order", mock_create_ro.call_count == 0)


# ---------------------------------------------------------------------------
# import_cost_entries_csv
# ---------------------------------------------------------------------------

COST_HEADERS = ["ro_number", "category", "description", "amount", "incurred_at"]


def test_import_cost_entries_happy_path_commits_with_provenance():
    path = write_csv(
        [{"ro_number": "RO-9001", "category": "parts", "description": "bumper", "amount": "250.00", "incurred_at": "2026-02-01"}],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=_FakeRO(id=42)), \
         patch("app.csv_import.repo.add_cost_entry") as mock_add:
        report = ci.import_cost_entries_csv(cur, path, "jed", dry_run=False)
    check("test_import_cost_entries_happy_path_created", report.created == 1, report.summary())
    entry = mock_add.call_args[0][1]
    check(
        "test_import_cost_entries_happy_path_fields",
        entry.job_id == 42 and entry.category == CostCategory.PARTS
        and entry.amount == Decimal("250.00") and entry.source == "csv_import"
        and entry.source_file == os.path.basename(path),
        entry,
    )


def test_import_cost_entries_unknown_ro_is_error():
    path = write_csv(
        [{"ro_number": "RO-NOPE", "category": "parts", "description": "", "amount": "10", "incurred_at": ""}],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=None):
        report = ci.import_cost_entries_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_cost_entries_unknown_ro_is_error",
        len(report.errors) == 1 and "import jobs.csv first" in report.errors[0],
        report.summary(),
    )


def test_import_cost_entries_bad_category_is_error():
    path = write_csv(
        [{"ro_number": "RO-9001", "category": "bogus", "description": "", "amount": "10", "incurred_at": ""}],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=_FakeRO(id=42)):
        report = ci.import_cost_entries_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_cost_entries_bad_category_is_error",
        len(report.errors) == 1 and "category" in report.errors[0],
        report.summary(),
    )


def test_import_cost_entries_negative_amount_is_error():
    path = write_csv(
        [{"ro_number": "RO-9001", "category": "parts", "description": "", "amount": "-5", "incurred_at": ""}],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=_FakeRO(id=42)):
        report = ci.import_cost_entries_csv(cur, path, "jed", dry_run=True)
    check(
        "test_import_cost_entries_negative_amount_is_error",
        len(report.errors) == 1 and ">= 0" in report.errors[0],
        report.summary(),
    )


def test_import_cost_entries_blank_incurred_at_defaults_to_today():
    path = write_csv(
        [{"ro_number": "RO-9001", "category": "parts", "description": "", "amount": "10", "incurred_at": ""}],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=_FakeRO(id=42)), \
         patch("app.csv_import.repo.add_cost_entry") as mock_add:
        ci.import_cost_entries_csv(cur, path, "jed", dry_run=False)
    entry = mock_add.call_args[0][1]
    check("test_import_cost_entries_blank_incurred_at_defaults_to_today", entry.incurred_at == date.today(), entry.incurred_at)


def test_import_cost_entries_dry_run_never_writes():
    path = write_csv(
        [{"ro_number": "RO-9001", "category": "parts", "description": "", "amount": "10", "incurred_at": ""}],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=_FakeRO(id=42)), \
         patch("app.csv_import.repo.add_cost_entry") as mock_add:
        report = ci.import_cost_entries_csv(cur, path, "jed", dry_run=True)
    check("test_import_cost_entries_dry_run_reports_created", report.created == 1)
    check("test_import_cost_entries_dry_run_never_writes", mock_add.call_count == 0)


# ---------------------------------------------------------------------------
# Multi-row: errors in one row don't abort the whole file
# ---------------------------------------------------------------------------

def test_import_cost_entries_one_bad_row_does_not_abort_the_rest():
    path = write_csv(
        [
            {"ro_number": "RO-9001", "category": "parts", "description": "", "amount": "10", "incurred_at": ""},
            {"ro_number": "RO-9001", "category": "bogus-category", "description": "", "amount": "10", "incurred_at": ""},
            {"ro_number": "RO-9001", "category": "labor", "description": "", "amount": "20", "incurred_at": ""},
        ],
        COST_HEADERS,
    )
    cur = FakeCursor({})
    with patch("app.csv_import.repo.get_repair_order_by_ro_number", return_value=_FakeRO(id=42)), \
         patch("app.csv_import.repo.add_cost_entry") as mock_add:
        report = ci.import_cost_entries_csv(cur, path, "jed", dry_run=False)
    check("test_import_cost_entries_partial_failure_total_rows", report.total_rows == 3)
    check("test_import_cost_entries_partial_failure_created_count", report.created == 2, report.summary())
    check("test_import_cost_entries_partial_failure_error_count", len(report.errors) == 1, report.summary())
    check("test_import_cost_entries_partial_failure_still_writes_good_rows", mock_add.call_count == 2)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_") and callable(obj)]
    for t in tests:
        t()
    total = len(tests)
    print(f"\n{total - len(FAILED)}/{total} passed")
    if FAILED:
        print("FAILED:", FAILED)
        raise SystemExit(1)
