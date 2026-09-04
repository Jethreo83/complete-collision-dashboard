"""Manual/CSV data entry workflows — the ONLY way CCC ONE-adjacent data
enters this system in Phase 1 (ADR-001 §1: no API/EMS/Secure Share/DMS
Interface integration; a human reads CCC ONE and either types into the
dashboard directly, or exports a CSV they built by hand/from a
spreadsheet and imports it here).

Every import function in this module:
  - Takes a `dry_run` flag (default True) — reports what WOULD happen
    without writing anything, so a human can review before committing.
  - Is idempotent on natural keys (ro_number, vin, site name) — re-running
    the same CSV twice updates/skips rather than duplicating.
  - Records provenance: cost entries imported this way get
    source='csv_import' and source_file=<the CSV's filename>, per
    migrations/006's cost_entry.source_file column.
  - Never talks to CCC ONE in any way — input is a CSV file path on disk,
    nothing else.
  - Returns a structured report (ImportReport) instead of just printing,
    so a caller (CLI, future admin UI) can decide how to surface errors.

CSV formats (headers are required, order doesn't matter):

  customers.csv:
    first_name, last_name, email, phone, source
      source one of: walk_in, insurer_referred, elektrica_rental, other
      (defaults to walk_in if blank)

  vehicles.csv:
    customer_email, vin, make, model, year
      customer_email must match a row already imported/existing (looked
      up by email against platform.person via collision.customer)

  jobs.csv (the RO tracker):
    ro_number, customer_email, vin, site, category, status,
    claim_number, insurer, adjuster_name, posture,
    gross_revenue, direct_ro_costs, labor_cost, rent_utility_share
      category one of: collision, pdr, hail
      status one of the 11 job_status values (defaults to 'undecided')
      site is a free-text name — created on demand via get_or_create_site

  cost_entries.csv:
    ro_number, category, description, amount, incurred_at
      category one of: parts, labor, paint_materials, sublet,
      rental_reimbursement, other
      incurred_at as YYYY-MM-DD, defaults to today if blank

This module deliberately does NOT create brand-new platform.person rows
(see app/repository.py's create_person_and_customer() docstring — that
requires a privileged, non-collision_app connection and is a known open
architecture gap). customers.csv import will look up an existing person
by email; if none is found, it is reported as an error row, not silently
created under an elevated role. Run create_person_and_customer()
explicitly first (as an admin script) if genuinely onboarding brand-new
customers via CSV — see scripts/csv_import_cli.py for that workflow.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from app.models import CostCategory, CostEntry, JobCategory, JobStatus
from app import repository as repo


@dataclass
class ImportReport:
    file: str
    dry_run: bool
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"Import report for {self.file} ({'DRY RUN — nothing written' if self.dry_run else 'COMMITTED'})",
            f"  total rows:  {self.total_rows}",
            f"  created:     {self.created}",
            f"  updated:     {self.updated}",
            f"  skipped:     {self.skipped}",
            f"  errors:      {len(self.errors)}",
        ]
        for e in self.errors:
            lines.append(f"    - {e}")
        return "\n".join(lines)


def _read_rows(csv_path: str) -> list[dict]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def _parse_decimal(v: Optional[str], field_name: str, default: str = "0") -> Decimal:
    v = _clean(v)
    if v is None:
        v = default
    try:
        return Decimal(v)
    except InvalidOperation:
        raise ValueError(f"{field_name}={v!r} is not a valid decimal number")


def _parse_int(v: Optional[str], field_name: str) -> Optional[int]:
    v = _clean(v)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"{field_name}={v!r} is not a valid integer")


def _parse_date(v: Optional[str], field_name: str) -> Optional[date]:
    v = _clean(v)
    if v is None:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{field_name}={v!r} is not YYYY-MM-DD")


# ---------------------------------------------------------------------------
# customers.csv — link EXISTING platform.person rows only (see module
# docstring). Looks up by normalized email.
# ---------------------------------------------------------------------------

def import_customers_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)

    for i, row in enumerate(rows, start=2):  # start=2: header is row 1
        try:
            email = _clean(row.get("email"))
            if not email:
                raise ValueError("email is required to link to an existing platform.person")
            source = _clean(row.get("source")) or "walk_in"

            cur.execute(
                "SELECT id FROM platform.person WHERE email_normalized = %s",
                (email.lower(),),
            )
            person_row = cur.fetchone()
            if not person_row:
                raise ValueError(
                    f"no platform.person found with email={email!r} — this import "
                    "only links EXISTING people (see module docstring); create the "
                    "person first via an admin script with a privileged connection"
                )
            person_id = person_row["id"]

            existing = repo.get_customer_by_person_id(cur, person_id)
            if existing:
                report.skipped += 1
                continue

            if not dry_run:
                repo.create_customer_for_existing_person(cur, person_id, actor, source=source)
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report


# ---------------------------------------------------------------------------
# vehicles.csv
# ---------------------------------------------------------------------------

def import_vehicles_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)

    for i, row in enumerate(rows, start=2):
        try:
            email = _clean(row.get("customer_email"))
            if not email:
                raise ValueError("customer_email is required")
            vin = _clean(row.get("vin"))
            make = _clean(row.get("make"))
            model = _clean(row.get("model"))
            year = _parse_int(row.get("year"), "year")

            cur.execute(
                "SELECT id FROM platform.person WHERE email_normalized = %s",
                (email.lower(),),
            )
            person_row = cur.fetchone()
            if not person_row:
                raise ValueError(f"no platform.person found with email={email!r}")
            customer = repo.get_customer_by_person_id(cur, person_row["id"])
            if not customer:
                raise ValueError(
                    f"person with email={email!r} exists but has no collision.customer "
                    "row yet — import customers.csv first"
                )

            if vin:
                existing = repo.get_vehicle_by_vin(cur, vin)
                if existing:
                    report.skipped += 1
                    continue

            if not dry_run:
                repo.get_or_create_vehicle(
                    cur, customer.id, actor, vin=vin, make=make, model=model, year=year,
                )
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report


# ---------------------------------------------------------------------------
# jobs.csv — the RO tracker
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {c.value for c in JobCategory}
VALID_STATUSES = {s.value for s in JobStatus}


def import_jobs_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)

    for i, row in enumerate(rows, start=2):
        try:
            ro_number = _clean(row.get("ro_number"))
            if not ro_number:
                raise ValueError("ro_number is required")

            existing = repo.get_repair_order_by_ro_number(cur, ro_number)
            if existing:
                report.skipped += 1
                continue

            email = _clean(row.get("customer_email"))
            if not email:
                raise ValueError("customer_email is required")
            cur.execute(
                "SELECT id FROM platform.person WHERE email_normalized = %s",
                (email.lower(),),
            )
            person_row = cur.fetchone()
            if not person_row:
                raise ValueError(f"no platform.person found with email={email!r}")
            customer = repo.get_customer_by_person_id(cur, person_row["id"])
            if not customer:
                raise ValueError(f"person with email={email!r} has no collision.customer row yet")

            vin = _clean(row.get("vin"))
            if vin:
                vehicle = repo.get_vehicle_by_vin(cur, vin)
                if not vehicle:
                    raise ValueError(f"no vehicle found with vin={vin!r} — import vehicles.csv first")
            else:
                # No VIN given for this RO — matches collision.vehicle.vin's
                # nullable design ("intake may not always have VIN captured
                # yet", migrations/002). Fall back to matching by customer:
                # only safe when the customer has exactly one vehicle on
                # file, otherwise this is genuinely ambiguous and must be
                # disambiguated by a human rather than guessed.
                customer_vehicles = repo.get_vehicles_by_customer(cur, customer.id)
                if len(customer_vehicles) == 0:
                    raise ValueError(
                        f"no vin given and customer {email!r} has no vehicle on file — "
                        "import vehicles.csv first"
                    )
                if len(customer_vehicles) > 1:
                    raise ValueError(
                        f"no vin given and customer {email!r} has {len(customer_vehicles)} "
                        "vehicles on file — ambiguous, specify vin explicitly"
                    )
                vehicle = customer_vehicles[0]

            site_name = _clean(row.get("site"))
            if not site_name:
                raise ValueError("site is required")

            category = _clean(row.get("category"))
            if category not in VALID_CATEGORIES:
                raise ValueError(f"category={category!r} must be one of {VALID_CATEGORIES}")

            status = _clean(row.get("status")) or "undecided"
            if status not in VALID_STATUSES:
                raise ValueError(f"status={status!r} must be one of {VALID_STATUSES}")

            if not dry_run:
                site = repo.get_or_create_site(cur, site_name, actor)
                from app.models import RepairOrder as RO
                ro = RO(
                    ro_number=ro_number, vehicle_id=vehicle.id, customer_id=customer.id,
                    site_id=site.id, category=JobCategory(category), status=JobStatus(status),
                    claim_number=_clean(row.get("claim_number")),
                    insurer=_clean(row.get("insurer")),
                    adjuster_name=_clean(row.get("adjuster_name")),
                    posture=_clean(row.get("posture")),
                    gross_revenue=_parse_decimal(row.get("gross_revenue"), "gross_revenue"),
                    direct_ro_costs=_parse_decimal(row.get("direct_ro_costs"), "direct_ro_costs"),
                    labor_cost=_parse_decimal(row.get("labor_cost"), "labor_cost"),
                    rent_utility_share=_parse_decimal(row.get("rent_utility_share"), "rent_utility_share"),
                )
                repo.create_repair_order(cur, ro, actor)
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report


# ---------------------------------------------------------------------------
# cost_entries.csv — itemized ledger
# ---------------------------------------------------------------------------

VALID_COST_CATEGORIES = {c.value for c in CostCategory}


def import_cost_entries_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)
    source_file = Path(csv_path).name

    for i, row in enumerate(rows, start=2):
        try:
            ro_number = _clean(row.get("ro_number"))
            if not ro_number:
                raise ValueError("ro_number is required")
            job = repo.get_repair_order_by_ro_number(cur, ro_number)
            if not job:
                raise ValueError(f"no job found with ro_number={ro_number!r} — import jobs.csv first")

            category = _clean(row.get("category"))
            if category not in VALID_COST_CATEGORIES:
                raise ValueError(f"category={category!r} must be one of {VALID_COST_CATEGORIES}")

            amount = _parse_decimal(row.get("amount"), "amount")
            if amount < 0:
                raise ValueError(f"amount={amount} must be >= 0")

            incurred_at = _parse_date(row.get("incurred_at"), "incurred_at") or date.today()

            if not dry_run:
                entry = CostEntry(
                    job_id=job.id, category=CostCategory(category),
                    description=_clean(row.get("description")), amount=amount,
                    incurred_at=incurred_at, source="csv_import", source_file=source_file,
                )
                repo.add_cost_entry(cur, entry, actor)
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report
